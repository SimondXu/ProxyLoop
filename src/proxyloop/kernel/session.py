"""``run_session``, the only execution path (I1); ``llm.call`` only from the record
sinks; ``LLMUnavailable`` ends it (I8). It wires agent code to ``env`` (with the
channels and the sim approver in ``fence``). ``Kernel.bb`` is the board at the
bus clock's now: Guard's "now" is ``bb.t_ms``, so no rule runs on a stale clock."""

from __future__ import annotations

import asyncio
import functools
import json
import secrets
import subprocess
from collections import Counter
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from proxyloop.contract import CONTRACT_VERSION, llm
from proxyloop.contract import bundle as b
from proxyloop.contract.base import Lane, sha256_text
from proxyloop.contract.config import (
    AblationId,
    SessionConfig,
    SlowViewMode,
    config_hash,
)
from proxyloop.contract.events import ApprovalPost, Approver, Event, Stream, event_id
from proxyloop.contract.protocol import ChatTokenizer, fingerprint
from proxyloop.contract.state import Blackboard
from proxyloop.contract.views import Trigger
from proxyloop.core.bus import Bus, Subscriber
from proxyloop.core.clock import Clock, WallClock
from proxyloop.env.tasks.loader import instance_hash
from proxyloop.env.tasks.schema import Task
from proxyloop.env.world import World, WorldError
from proxyloop.evidence.reality import role_refs
from proxyloop.kernel.calls import DISCLOSURE as DISCLOSURE
from proxyloop.kernel.calls import Calls
from proxyloop.kernel.channels import (
    Channel,
    HumanChannel,
    Incoming,
    make_channels,
    read_stdin,
)
from proxyloop.kernel.channels import ChannelSpec as ChannelSpec
from proxyloop.kernel.channels import SimRepChannel as SimRepChannel
from proxyloop.kernel.channels import SimUserChannel as SimUserChannel
from proxyloop.kernel.fence import Authority
from proxyloop.kernel.lanes import PROFILE, FastLane, load_tokenizer, p3
from proxyloop.kernel.speaker import Sleep, Speaker
from proxyloop.kernel.wake import Wakes
from proxyloop.kernel.watchdog import Abort, SessionEnd, watchdog
from proxyloop.llm.factory import LiveModeError, make_client
from proxyloop.llm.http import HTTPAdapter, RecordSink
from proxyloop.llm.spend import RunawaySpend, SpendLedger
from proxyloop.llm.vllm import VLLMClient
from proxyloop.models.repair import TeacherRepair
from proxyloop.slow import prompt
from proxyloop.slow.loop import SlowLoop

PROJECTED = (900_000, 400)  # tokens, calls per episode (guard at 3x): provisional until
# the root re-derives both from smoke #2 bundles and TeamRouter prices (S1-SYS-29)
ClientFactory = Callable[[llm.LLMRole, llm.ModelRef, RecordSink], llm.LLMClient]
PromptKind = Literal["view", "prompt", "messages", "response"]
P3 = Literal["pass", "fail", "not_applicable"]
REAL = llm.AdapterKind.REAL_HTTP
_ACTOR = {"fast_user": "fast.user", "fast_cp": "fast.cp", "slow": "slow"}
_ERRORS: dict[type[Exception], str] = {  # in priority: budget before the world
    **{llm.LLMUnavailable: "llm_unavailable", RunawaySpend: "budget"},
    **{WorldError: "world_error"},
}
_AFTER_DEATH = ("llm.call", "spend.charged", "session.ended")
# The TaskGroup aborts only in the ending task's done callback, so every task
# already ready runs one more step: after the end none may start new work. A
# call in flight still records (llm.call, spend.charged); world calls go on.
_NEW_WORK = ("slow.step.started", "fast.request")
_REPAIR = {AblationId.TEACHER_REPAIR_CP, AblationId.TEACHER_REPAIR_USER}


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    path: Path
    reason: str  # the session.ended reason


class _Loud:  # The session dies the moment one of its endpoints does
    def __init__(self, client: llm.LLMClient, die: Callable[[], None]) -> None:
        self.inner, self._die, self.ref = client, die, client.ref

    async def stream_text(
        self, request: llm.TextRequest
    ) -> AsyncIterator[str | llm.LLMCallRecord]:
        try:
            async for item in self.inner.stream_text(request):
                yield item
        except llm.LLMUnavailable:
            self._die()
            raise

    async def chat_tools(self, request: llm.ToolRequest) -> llm.ToolResponse:
        try:
            return await self.inner.chat_tools(request)
        except llm.LLMUnavailable:
            self._die()
            raise


class _WorldSink:
    def __init__(self, k: Kernel) -> None:
        self._k = k

    def emit(self, type_: str, actor: str, payload: Any, causes: Sequence[str]) -> str:
        return self._k.emit(type_, actor, payload, causes, "world").event_id

    def store(self, kind: Literal["messages", "response"], content: str) -> None:
        self._k.store(kind, content)


def _roles(specs: Mapping[str, ChannelSpec]) -> list[llm.LLMRole]:
    rep = specs.get("cp") == "sim"
    used: dict[llm.LLMRole, bool] = {"slow": "cp_agent" not in specs}
    used |= {"fast_user": "user" in specs}
    used |= {"simuser": specs.get("user") == "sim", "fast_cp": "cp_agent" not in specs}
    used |= {"ear": rep, "mouth": rep}
    return [role for role, yes in used.items() if yes]


def _outcome(
    group: BaseExceptionGroup[BaseException],
) -> tuple[str, BaseException | None]:  # the reason, and an error to re-raise
    leaves = group.exceptions  # tasks raise plain exceptions: the group is flat
    for kind, reason in _ERRORS.items():
        if found := [e for e in leaves if isinstance(e, kind)]:
            return reason, found[0]
    if aborted := [e for e in leaves if isinstance(e, Abort)]:
        return aborted[0].reason, aborted[0]
    if others := [e for e in leaves if not isinstance(e, SessionEnd)]:
        return "error", others[0]
    return cast(SessionEnd, leaves[0]).reason, None


def _reason(err: Exception) -> str:  # the end a task's error makes, as _outcome
    if isinstance(err, SessionEnd | Abort):
        return err.reason
    return next((r for kind, r in _ERRORS.items() if isinstance(err, kind)), "error")


def _world_error(err: BaseException | None) -> dict[str, str] | None:
    """A ``WorldError``'s type and authored message (rule 15): the world writes
    ``<what>: <how>``, and only what follows (an ``Invalid``'s reason, which
    may quote model output) is dropped: at most two ``": "`` parts are kept."""
    if not isinstance(err, WorldError):
        return None
    authored = ": ".join(str(err).split(": ")[:2])
    return {"type": type(err).__name__, "message": authored}


def slow_fp(mode: SlowViewMode, kind: Literal["info_only", "full"]) -> str:
    """``session.started.slow_fp``: the sha256 of ``prompt.fp_inputs`` as
    canonical JSON (ADR-0018 V6): runs with different Slow harnesses differ."""
    return sha256_text(json.dumps(prompt.fp_inputs(mode, kind), sort_keys=True))


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def _files(attest: dict[str, Any] | None) -> dict[str, str] | None:
    if attest is None:  # /pl/attest as file -> sha256: shards, tokenizer, adapters
        return None
    slots = {f"adapters/{s}": f for s, f in attest.get("adapters", {}).items()}
    groups = {"shards": attest["shards"], "tokenizer": attest["tokenizer"]} | slots
    return {f"{g}/{n}": v for g, files in groups.items() for n, v in files.items()}


@functools.cache  # once per process: a web server starts many runs
def _git_sha() -> str:
    git = ["git", "rev-parse", "HEAD"]
    done = subprocess.run(
        git, cwd=Path(__file__).parent, capture_output=True, text=True
    )
    return done.stdout.strip() or "unknown"


class Kernel:
    def __init__(
        self,
        cfg: SessionConfig,
        task: Task,
        specs: Mapping[str, ChannelSpec],
        runs_dir: Path,
        clock: Clock,
        sleep: Sleep,
        clients: ClientFactory | None,
        tok: ChatTokenizer | None,
        run_id: str | None = None,
    ) -> None:
        modes = (SlowViewMode.TRANSCRIPT, SlowViewMode.RELAY_ONLY)  # ADR-0016
        if set(cfg.ablations) - _REPAIR or cfg.slow_view not in modes:
            raise ValueError("ablations other than R's arrive with S3-SYS-01")
        if "cp" not in specs or specs.get("cp_agent", "human") == "sim":
            raise ValueError("a session needs a cp partner; a cp_agent is a person")
        self.cfg, self.task, self.clock, self.sleep = cfg, task, clock, sleep
        self.counts: Counter[str] = Counter()
        self.prompts: dict[str, b.PromptRecord] = {}
        self._causes: dict[str, str] = {}  # call_id -> the event it answers
        self._calls: dict[str, str] = {}  # call_id -> its last llm.call event
        self._dead, self._utt, self._tg = False, 0, asyncio.TaskGroup()
        self._ended = False
        self._ending: str | None = None  # the first SessionEnd's reason
        self.p3: P3 = "not_applicable"
        self.attest: dict[str, Any] | None = None
        refs, make, roles = role_refs(cfg), clients or self._make, _roles(specs)
        roles.extend(("teacher",) if cfg.teacher is not None else ())
        if cfg.live and (bad := [r for r in roles if refs[r].kind is not REAL]):
            raise LiveModeError(f"live mode refuses {bad}: not real_http")
        self.clients: dict[llm.LLMRole, _Loud] = {}
        for role in roles:  # before anything is written: startup refusals
            world = role in ("ear", "mouth", "simuser")  # the teacher answers as Fast
            client = make(
                role, refs[role], self._world_record if world else self._record
            )
            if cfg.live and client.ref.kind is not REAL:
                raise LiveModeError(f"live mode refuses {client.ref.kind} for {role}")
            if client.ref != refs[role]:
                raise ValueError(f"the {role} client is not the cfg's model")
            self.clients[role] = _Loud(client, self._die)
        refs_now = [c.ref for c in self.clients.values()]  # the factor, at the start
        self.ledger = SpendLedger(*PROJECTED, refs=refs_now)
        fast = [self.clients.get(r) for r in ("fast_user", "fast_cp")]
        vllm = any(c is not None and c.ref.endpoint == "vllm" for c in fast)
        self.tok = tok if tok is not None or not vllm else load_tokenizer()
        self.run_id = run_id or new_run_id()
        self.path = runs_dir / self.run_id
        self.path.mkdir(parents=True)
        self.bus = Bus(self.path / b.EVENTS, self.run_id, clock)
        self.bus.subscribe(self._on_event)
        self.authority = Authority(self)
        teacher = self.clients.get("teacher")  # condition R: evaluation, 0 resamples
        self.teacher = TeacherRepair(teacher, 0) if teacher is not None else None
        self.world = World(_WorldSink(self))
        self.channels = make_channels(cfg, task, specs, self.clients, self.world)
        both: tuple[Lane, ...] = ("user", "cp")
        lanes: list[Lane] = [x for x in both if x in self.channels]
        self.speakers = {lane: Speaker(self, lane) for lane in lanes}
        fast_lanes: list[Lane] = [x for x in lanes if f"fast_{x}" in self.clients]
        self.lanes = {lane: FastLane(self, lane) for lane in fast_lanes}
        keys = frozenset(task.disclosure.shareable)
        slow = self.clients.get("slow")  # none in rep-chat
        self.slow = slow and SlowLoop(self, slow, task.slow_brief, keys)
        self.closed = False  # the cp call
        self.calls = Calls(self, self._ingress)  # when it opens (ADR-0012)
        self.bus.subscribe(self.calls.on_event)
        self.bus.subscribe(Wakes(self).on_event)  # Slow's wakes and its one timer

    def _make(self, role: str, ref: llm.ModelRef, sink: RecordSink) -> llm.LLMClient:
        clock, live = self.clock.monotonic_ms, self.cfg.live
        return make_client(ref, live=live, clock=clock, on_record=sink)

    @property
    def bb(self) -> Blackboard:  # at the bus clock's now
        bb = self.bus.bb
        return bb.model_copy(update={"t_ms": max(bb.t_ms, self.now())})

    def now(self) -> int:
        return self.clock.monotonic_ms()

    def emit(
        self,
        type_: str,
        actor: str,
        payload: Mapping[str, object],
        causes: Sequence[str] = (),
        stream: Stream = "agent",
    ) -> Event:
        if self._ending is not None and type_ in _NEW_WORK:
            raise SessionEnd(self._ending)  # this task ends with the session
        if self._dead and type_ not in _AFTER_DEATH:
            raise RuntimeError(f"no {type_} after an endpoint died")
        return self.bus.emit(type_, actor, stream, payload, causes)

    def next_event_id(self) -> str:
        return event_id(self.run_id, self.bus.bb.seq + 1)

    def store(self, kind: PromptKind, content: str) -> str:
        sha = sha256_text(content)
        record = b.PromptRecord(sha=sha, kind=kind, content=content)
        self.prompts.setdefault(sha, record)
        return sha

    def spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = self._tg.create_task(self._task(coro))
        task.add_done_callback(lambda _: coro.close())  # if cancelled before it ran

    async def _task(self, coro: Coroutine[Any, Any, None]) -> None:
        try:
            await coro
        except Exception as err:  # any end, loud too: gated before the next task
            self.end(_reason(err))
            raise

    def expect(self, call_id: str, cause: str) -> None:
        self._causes[call_id] = cause

    def call_event(self, call_id: str) -> str:
        return self._calls[call_id]

    def _record(self, r: llm.LLMCallRecord) -> None:
        call, cause = r.model_dump(mode="json"), [self._causes[r.call_id]]
        self._calls[r.call_id] = self.emit(
            "llm.call", _ACTOR[r.role], call, cause
        ).event_id
        self._charge(r, self._calls[r.call_id])

    def _world_record(self, r: llm.LLMCallRecord) -> None:
        self.world.record(r)
        self._charge(r, self.world.calls([r.call_id])[-1])

    def _charge(self, r: llm.LLMCallRecord, cause: str) -> None:
        runaway: RunawaySpend | None = None
        try:
            charge = self.ledger.charge(r)
        except RunawaySpend as err:
            charge, runaway = err.charge, err
            self.end("budget")  # before anything else runs: no new Fast or Slow call
        self.emit(
            "spend.charged", "kernel", charge.model_dump(mode="json"), [cause], "ops"
        )
        if runaway is not None:
            raise runaway

    def _die(self) -> None:
        self._dead = True

    def end(self, reason: str) -> SessionEnd:
        """The session ends: the first reason stands, and no new work starts."""
        self._ending = self._ending or reason
        return SessionEnd(self._ending)

    @property
    def ended(self) -> bool:  # session.ended is written
        return self._ended

    def post_approval(self, post: ApprovalPost, by: Approver = "ui") -> None:
        """The approvals ingress (§9.6): enqueued, decided in the kernel's loop."""
        if self._ended:
            raise RuntimeError("the session has ended")
        self.authority.post(post, by)

    def _on_event(self, e: Event) -> None:
        self.authority.on_event(e)  # first: a user.msg raises its fence at once
        p, user, cp = e.payload, self.lanes.get("user"), self.lanes.get("cp")
        if e.type == "speak.verbatim" and p["kind"] in ("accept", "decline"):
            self.spawn(self.speakers[cast(Lane, p["lane"])].verbatim(e))
        elif e.type == "user.msg" and user is not None:
            user.trigger(Trigger(kind="user_msg"), e.event_id)
        elif e.type == "utt.final" and p["speaker"] == "partner" and cp:
            cp.trigger(
                Trigger(kind="rep_spoke"), e.event_id
            ) if not self.closed else None
        elif e.type == "s2f.msg" and p["type"] in ("ASK_USER", "TELL_USER") and user:
            user.trigger(Trigger(kind="slow_msg", msg_id=str(p["msg_id"])), e.event_id)
        elif e.type == "s2f.msg" and p["type"] == "GUIDE" and cp and not self.closed:
            cp.trigger(Trigger(kind="guidance"), e.event_id)
        elif e.type == "s2f.msg" and p["type"] == "APPROVAL_NOTICE" and user:
            notice = (str(p["msg_id"]),)  # acknowledged by the turn that voices it
            user.trigger(Trigger(kind="approval_card"), e.event_id, notice)

    def finish(self, outcome: str) -> None:
        async def drain() -> None:  # up to 30 s for FastU to voice Slow's messages
            for _ in range(60):
                if "user" not in self.lanes or not self.bb.s2f_pending.get("user"):
                    break
                await self.sleep(0.5)
            raise self.end(outcome)

        self.spawn(drain())

    async def run(self) -> RunResult:
        models = {
            r: {"ref": c.ref.model_dump(mode="json")} for r, c in self.clients.items()
        }
        started: dict[str, Any] = {
            "cfg_hash": config_hash(self.cfg),
            "task_ref": self.task.ref,
            "instance_hash": instance_hash(self.task),
            "split": "train",  # piloted families are train-only (I9)
            "renderer_fp": {p: fingerprint(p) for p in PROFILE.values()},
            "contract_version": CONTRACT_VERSION,
            "git_sha": _git_sha(),
        }
        dead: Exception | None = None
        try:
            self.p3, self.attest = await self._p3()
        except Exception as err:  # vLLM cannot answer P3: the endpoint is dead
            self.p3, self.attest, dead = "fail", None, err
        head = started | {"models": models, "attest": self.attest, "parity": self.p3}
        head["slow_view"] = self.cfg.slow_view.value  # extra keys (S1-SYS-43)
        if self.slow is not None:  # rep-chat has no Slow
            head["slow_fp"] = slow_fp(self.cfg.slow_view, self.task.mode)
        led = self.ledger  # the S0 runaway guard in force (an extra key, §4.2)
        head["runaway"] = {"factor": led.factor, "tokens": led.limit_tokens}
        head["runaway"] |= {"unpriced_calls": led.limit_unpriced_calls}
        head["runaway"] |= {"cap_micro_usd": led.limit_micro_usd}
        root = self.emit("session.started", "kernel", head, (), "ops").event_id
        self.authority.root = root
        if self.p3 == "fail":  # refuse to start (§12)
            self._close("p3_failed" if dead is None else "llm_unavailable", started)
            raise dead or RuntimeError("P3: vLLM /tokenize != the pinned tokenizer")
        reason, error = "error", None
        try:
            async with self._tg:
                self._open(root)
        except BaseExceptionGroup as group:
            reason, error = _outcome(group)
        except asyncio.CancelledError:
            self._close("stopped", started)
            raise
        self._close(reason, started, _world_error(error))
        if error is not None:
            raise error
        return RunResult(self.run_id, self.path, reason)

    async def _p3(self) -> tuple[P3, Any]:  # and /pl/attest (§12, §13)
        passed: list[bool] = []
        attest: dict[str, Any] | None = None
        for lane, fast in self.lanes.items():
            if isinstance(vllm := fast.client.inner, VLLMClient) and self.tok:
                kind = "session_start" if lane == "user" else "call_connected"
                passed.append(await p3(vllm, fast.view(Trigger(kind=kind)), self.tok))
                attest = attest or await vllm.attest()
        return (
            "pass" if all(passed) else "fail"
        ) if passed else "not_applicable", attest

    def _open(self, root: str) -> None:  # the user lane; the cp call: ``calls``
        if "user" in self.channels:
            opened = self.emit("chan.opened", "kernel", {"lane": "user"}, [root])
            user = self.channels["user"]
            self.spawn(self._ingress("user", user, opened.event_id))
            self.spawn(user.send(None, "", opened.event_id, self.now()))
        if "user" in self.lanes:
            self.spawn(self.lanes["user"].run())
        if self.slow:
            self.spawn(self.slow.run())
        self.spawn(self.authority.run())  # the approvals queue
        self.spawn(watchdog(self))
        self.calls.start(root)
        if humans := {
            k: c for k, c in self.channels.items() if isinstance(c, HumanChannel)
        }:
            read_stdin(humans)

    async def _ingress(self, key: str, channel: Channel, opened: str) -> None:
        while True:  # partner turns become user.msg / utt.final
            inc = await channel.incoming.get()
            if key != "user" and self.closed and inc.end != "quit":
                continue  # the call is over: nothing more on its lane
            if key == "cp_agent":
                await self.calls.disclosed.wait()
            if (wait := inc.due_ms - self.now()) > 0:
                await self.sleep(wait / 1000)
            if key == "cp" and inc.lines:  # cuts the line; lands before a verbatim
                async with self.speakers["cp"].partner_turn():
                    last, closing = self._turn(key, inc, opened)
            else:
                last, closing = self._turn(key, inc, opened)
            if inc.delivered is not None:
                inc.delivered.set()
            channel.floor(True, self.now())
            if inc.end in ("quit", "hangup"):
                hung_up = inc.end == "hangup" and key == "cp"
                if hung_up and last != opened:  # §9.5 ABANDONED, caused by the
                    self.authority.move("hang_up", last)  # turn's own event (I2)
                raise self.end("abandoned" if hung_up else "stopped")
            if closing:
                self.emit("chan.closed", "kernel", {"lane": "cp"}, [last])
                if self.slow is None:  # rep-chat: nothing left to judge the case
                    end = self.end("stopped")
                    await asyncio.sleep(0)  # the person still reads the last line
                    raise end

    def _turn(self, key: str, inc: Incoming, opened: str) -> tuple[str, bool]:
        last, first = opened, [c for _, c in inc.lines if c][:1]
        closing = inc.end == "closed" and key == "cp" and not self.closed
        self.closed |= closing  # before its lines: they trigger no FastC
        if inc.strike:
            struck = {"lane": "cp", "kind": inc.strike_kind}
            last = self.emit("chan.strike", "kernel", struck, first).event_id
        for text, cause in inc.lines:
            last = self._line(key, text, [cause] if cause else [])
        return last, closing

    def _line(self, key: str, text: str, causes: list[str]) -> str:
        if key == "user":
            return self.emit("user.msg", "kernel", {"text": text}, causes).event_id
        self._utt += 1
        utt_id = f"{key}-{self._utt}"
        said = {
            "speaker": "agent" if key == "cp_agent" else "partner",
            "utt_id": utt_id,
        }
        ev = self.emit(
            "utt.final", "kernel", said | {"lane": "cp", "text": text}, causes
        )
        other = self.channels.get("cp" if key == "cp_agent" else "cp_agent")
        if other is not None:  # rep-chat: a person speaks for the agent
            self.spawn(other.send(text, utt_id, ev.event_id, self.now()))
        return ev.event_id

    def _close(
        self,
        reason: str,
        started: dict[str, Any],
        world_error: dict[str, str] | None = None,
    ) -> None:
        ended: dict[str, object] = {"reason": reason, "counts": dict(self.counts)}
        ended["spend"] = self.ledger.totals()  # extra keys: S1-CON-03 types them
        if world_error is not None:
            ended["world_error"] = world_error
        self.emit("session.ended", "kernel", ended, (), "ops")
        self._ended = True
        self.bus.close()
        prompts = "".join(f"{r.model_dump_json()}\n" for r in self.prompts.values())
        (self.path / b.PROMPTS).write_text(prompts, "utf-8")
        manifest = b.Manifest(
            run_id=self.run_id,
            cfg=self.cfg,
            fingerprints=started.pop("renderer_fp"),
            models={r: b.RoleModel(ref=c.ref) for r, c in self.clients.items()},
            p3=self.p3,
            attestation=_files(self.attest),
            reality={r: c.ref.kind for r, c in self.clients.items()},
            spend=self.ledger.spend,
            **started,
        )
        (self.path / b.MANIFEST).write_text(manifest.model_dump_json(indent=2), "utf-8")

    async def aclose(self) -> None:
        for client in self.clients.values():
            if isinstance(client.inner, HTTPAdapter):
                await client.inner.aclose()


async def run_session(
    cfg: SessionConfig,
    task: Task,
    channels: Mapping[str, ChannelSpec] | None = None,
    *,
    runs_dir: Path = Path("runs"),
    clock: Clock | None = None,
    sleep: Sleep | None = None,
    clients: ClientFactory | None = None,
    tokenizer: ChatTokenizer | None = None,
    observers: Sequence[Subscriber] = (),
    run_id: str | None = None,
    opened: Callable[[Kernel], None] | None = None,
) -> RunResult:
    """``channels``: ``user``/``cp`` (and for rep-chat ``cp_agent``, a person for
    the agent) -> ``"sim"``/``"human"``/a ``Channel``. ``observers`` are isolated
    bus subscribers (an exporter): their errors are logged, never fatal (§11).
    ``run_id`` (unset: a new one) and ``opened`` (gets the kernel before it runs)
    serve a web case (``kernel.web``). The other keywords are test seams."""
    sims: dict[str, ChannelSpec] = {"user": "sim", "cp": "sim"}
    specs, clock = sims if channels is None else channels, clock or WallClock()
    sleep = sleep or asyncio.sleep
    k = Kernel(cfg, task, specs, runs_dir, clock, sleep, clients, tokenizer, run_id)
    for observer in observers:
        k.bus.subscribe(observer, isolated=True)
    if opened is not None:
        opened(k)
    try:
        return await k.run()
    finally:
        k.bus.close()  # idempotent; else open if cancelled in P3, before seq 0
        await k.aclose()
