"""``run_session``, the only execution path (I1); ``llm.call`` only from the record
sinks; ``LLMUnavailable`` ends it (I8). The one module wiring agent code to ``env``."""

from __future__ import annotations

import asyncio
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
from proxyloop.contract.config import SessionConfig, SlowViewMode, config_hash
from proxyloop.contract.events import Event, Stream, event_id
from proxyloop.contract.protocol import ChatTokenizer, fingerprint
from proxyloop.contract.state import Blackboard, CaseStatus
from proxyloop.contract.views import Trigger
from proxyloop.core.bus import Bus
from proxyloop.core.clock import Clock, WallClock
from proxyloop.env.counterparty.simrep import RepTurn, SimRep
from proxyloop.env.tasks.loader import instance_hash
from proxyloop.env.tasks.schema import Task
from proxyloop.env.user.simuser import SimUser
from proxyloop.env.world import World, WorldError
from proxyloop.evidence.reality import role_refs
from proxyloop.kernel.channels import Channel, End, HumanChannel, Incoming, read_stdin
from proxyloop.kernel.lanes import PROFILE, FastLane, load_tokenizer, p3
from proxyloop.kernel.speaker import Sleep, Speaker
from proxyloop.kernel.watchdog import SessionEnd, watchdog
from proxyloop.llm.factory import LiveModeError, make_client
from proxyloop.llm.http import HTTPAdapter, RecordSink
from proxyloop.llm.spend import RunawaySpend, SpendLedger
from proxyloop.llm.vllm import VLLMClient
from proxyloop.slow.loop import SlowLoop

# Guard-authored and fixed (I11, C14): the first thing the rep hears.
DISCLOSURE = "Hello, this is an AI assistant calling on behalf of the account holder."
PROJECTED = (500_000, 200)  # [E] micro-USD and calls per S0 episode; guard at 10x
ChannelSpec = Literal["sim", "human"] | Channel
ClientFactory = Callable[[llm.LLMRole, llm.ModelRef, RecordSink], llm.LLMClient]
PromptKind = Literal["view", "prompt", "messages", "response"]
P3 = Literal["pass", "fail", "not_applicable"]
REAL = llm.AdapterKind.REAL_HTTP
_ACTOR = {"fast_user": "fast.user", "fast_cp": "fast.cp", "slow": "slow"}
_ERRORS: dict[type[Exception], str] = {
    **{llm.LLMUnavailable: "llm_unavailable", WorldError: "world_error"},
    **{RunawaySpend: "budget"},
}
_AFTER_DEATH = ("llm.call", "spend.charged", "session.ended")


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


class SimUserChannel(Channel):  # replies delay_s after each message
    def __init__(self, user: SimUser) -> None:
        super().__init__()
        self._user, self._lock = user, asyncio.Lock()

    async def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> None:
        async with self._lock:  # one reply at a time, in message order
            reply = await self._user.on_agent_message(text, cause)
        due = 0 if text is None else t_ms + round(1000 * reply.delay_s)
        self.incoming.put_nowait(Incoming(((reply.text, reply.event_id),), due))


class SimRepChannel(Channel):  # hears text_heard; ticks on a free floor
    def __init__(self, rep: SimRep) -> None:
        super().__init__()
        self._rep, self._turns = rep, 0

    @property
    def busy(self) -> bool:
        return self._turns > 0

    async def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> None:
        if text is not None:
            await self._run(self._rep.on_agent_utterance(utt_id, text, cause, t_ms))

    async def tick(self, t_ms: int) -> None:
        await self._run(self._rep.tick(t_ms))

    def floor(self, free: bool, t_ms: int) -> None:
        self._rep.floor(free, t_ms)

    async def _run(self, turn: Coroutine[Any, Any, RepTurn]) -> None:
        self._turns += 1
        try:
            done = await turn
        finally:
            self._turns -= 1
        end: End = ("hangup" if done.strike else "closed") if done.ended else ""
        if done.lines or end or done.strike:
            lines = tuple((text, ev) for text, ev in done.lines)
            self.incoming.put_nowait(Incoming(lines, strike=done.strike, end=end))


class _WorldSink:
    def __init__(self, k: Kernel) -> None:
        self._k = k

    def emit(self, type_: str, actor: str, payload: Any, causes: Sequence[str]) -> str:
        return self._k.emit(type_, actor, payload, causes, "world").event_id

    def store(self, kind: Literal["messages", "response"], content: str) -> None:
        self._k.store(kind, content)


def _roles(specs: Mapping[str, ChannelSpec]) -> list[llm.LLMRole]:
    rep = specs.get("cp") == "sim"
    used: dict[llm.LLMRole, bool] = {"slow": True, "fast_user": "user" in specs}
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
    if others := [e for e in leaves if not isinstance(e, SessionEnd)]:
        return "error", others[0]
    return cast(SessionEnd, leaves[0]).reason, None


def _files(attest: dict[str, Any] | None) -> dict[str, str] | None:
    if attest is None:  # /pl/attest as file -> sha256: shards, tokenizer, adapters
        return None
    slots = {f"adapters/{s}": f for s, f in attest.get("adapters", {}).items()}
    groups = {"shards": attest["shards"], "tokenizer": attest["tokenizer"]} | slots
    return {f"{g}/{n}": v for g, files in groups.items() for n, v in files.items()}


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
    ) -> None:
        if cfg.ablations or cfg.slow_view is not SlowViewMode.RELAY_ONLY:
            raise ValueError("ablations arrive with S3-SYS-01")
        if "cp" not in specs or specs.get("cp_agent", "human") == "sim":
            raise ValueError("a session needs a cp partner; a cp_agent is a person")
        self.cfg, self.task, self.clock, self.sleep = cfg, task, clock, sleep
        self.counts: Counter[str] = Counter()
        self.prompts: dict[str, b.PromptRecord] = {}
        self.ledger = SpendLedger(*PROJECTED)
        self._causes: dict[str, str] = {}  # call_id -> the event it answers
        self._calls: dict[str, str] = {}  # call_id -> its last llm.call event
        self._dead, self._utt, self._tg = False, 0, asyncio.TaskGroup()
        self.p3: P3 = "not_applicable"
        self.attest: dict[str, Any] | None = None
        refs, make, roles = role_refs(cfg), clients or self._make, _roles(specs)
        if cfg.live and (bad := [r for r in roles if refs[r].kind is not REAL]):
            raise LiveModeError(f"live mode refuses {bad}: not real_http")
        self.clients: dict[llm.LLMRole, _Loud] = {}
        for role in roles:  # before anything is written: startup refusals
            world = role in ("ear", "mouth", "simuser")
            client = make(
                role, refs[role], self._world_record if world else self._record
            )
            if cfg.live and client.ref.kind is not REAL:
                raise LiveModeError(f"live mode refuses {client.ref.kind} for {role}")
            if client.ref != refs[role]:
                raise ValueError(f"the {role} client is not the cfg's model")
            self.clients[role] = _Loud(client, self._die)
        fast = [self.clients.get(r) for r in ("fast_user", "fast_cp")]
        vllm = any(c is not None and c.ref.endpoint == "vllm" for c in fast)
        self.tok = tok if tok is not None or not vllm else load_tokenizer()
        self.run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
        self.path = runs_dir / self.run_id
        self.path.mkdir(parents=True)
        self.bus = Bus(self.path / b.EVENTS, self.run_id, clock)
        self.bus.subscribe(self._on_event)
        self.world = World(_WorldSink(self))
        self.channels = {key: self._channel(key, spec) for key, spec in specs.items()}
        both: tuple[Lane, ...] = ("user", "cp")
        lanes: list[Lane] = [x for x in both if x in self.channels]
        self.speakers = {lane: Speaker(self, lane) for lane in lanes}
        fast_lanes: list[Lane] = [x for x in lanes if f"fast_{x}" in self.clients]
        self.lanes = {lane: FastLane(self, lane) for lane in fast_lanes}
        keys = frozenset(task.disclosure.shareable)
        self.slow = SlowLoop(self, self.clients["slow"], task.slow_brief, keys)

    def _make(self, role: str, ref: llm.ModelRef, sink: RecordSink) -> llm.LLMClient:
        clock, live = self.clock.monotonic_ms, self.cfg.live
        return make_client(ref, live=live, clock=clock, on_record=sink)

    def _channel(self, key: str, spec: ChannelSpec) -> Channel:
        if spec == "human":
            return HumanChannel({"user": "ASSISTANT", "cp": "AGENT"}.get(key, "REP"))
        if spec != "sim":
            return spec
        if key == "user":
            simuser = self.clients["simuser"]
            return SimUserChannel(
                SimUser(self.task, simuser, self.world, self.cfg.seed)
            )
        ear, mouth = self.clients["ear"], self.clients["mouth"]
        return SimRepChannel(SimRep(self.task, ear, mouth, self.world))

    @property
    def bb(self) -> Blackboard:
        return self.bus.bb

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
        self._tg.create_task(coro)

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
        self.emit(
            "spend.charged", "kernel", charge.model_dump(mode="json"), [cause], "ops"
        )
        if runaway is not None:
            raise runaway

    def _die(self) -> None:
        self._dead = True

    def _on_event(self, e: Event) -> None:
        p, user, cp = e.payload, self.lanes.get("user"), self.lanes.get("cp")
        if e.type == "user.msg" and user is not None:
            user.trigger(Trigger(kind="user_msg"), e.event_id)
        elif e.type == "utt.final" and p["speaker"] == "partner" and cp is not None:
            cp.trigger(Trigger(kind="rep_spoke"), e.event_id)
        elif e.type == "s2f.msg" and p["type"] in ("ASK_USER", "TELL_USER") and user:
            user.trigger(Trigger(kind="slow_msg", msg_id=str(p["msg_id"])), e.event_id)
        elif e.type == "s2f.msg" and p["type"] == "GUIDE" and cp is not None:
            cp.trigger(Trigger(kind="guidance"), e.event_id)
        elif e.type == "f2s.msg":
            self.slow.wake("relay")

    def finish(self, outcome: str) -> None:
        async def drain() -> None:  # up to 30 s for FastU to voice Slow's messages
            for _ in range(60):
                if "user" not in self.lanes or not self.bb.s2f_pending.get("user"):
                    break
                await self.sleep(0.5)
            raise SessionEnd(outcome)

        self.spawn(drain())

    def wake_slow(self, reason: str, after_s: float) -> None:
        async def later() -> None:
            await self.sleep(after_s)
            self.slow.wake(reason)

        self.spawn(later())

    async def run(self) -> RunResult:
        models = {
            r: {"ref": c.ref.model_dump(mode="json")} for r, c in self.clients.items()
        }
        started: dict[str, Any] = {
            "cfg_hash": config_hash(self.cfg),
            "task_ref": f"{self.task.family}@{self.task.version}",
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
        root = self.emit("session.started", "kernel", head, (), "ops").event_id
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
        self._close(reason, started)
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

    def _open(self, root: str) -> None:
        lanes = self.speakers
        opened = {
            x: self.emit("chan.opened", "kernel", {"lane": x}, [root]) for x in lanes
        }
        cp = opened["cp"].event_id
        status = {"previous": CaseStatus.INTAKE, "status": CaseStatus.IN_CALL}
        self.emit("status.changed", "guard", status, [cp])
        self.spawn(self._disclose(cp))
        for key, channel in self.channels.items():
            self.spawn(self._ingress(key, channel, cp))
        if "user" in opened:
            user = self.channels["user"]
            self.spawn(user.send(None, "", opened["user"].event_id, self.now()))
        if "user" in self.lanes:
            self.spawn(self.lanes["user"].run())
        self.spawn(self.slow.run())
        self.spawn(watchdog(self))
        if humans := {
            k: c for k, c in self.channels.items() if isinstance(c, HumanChannel)
        }:
            read_stdin(humans)

    async def _disclose(self, opened: str) -> None:  # first cp agent line (I11)
        line = {"lane": "cp", "kind": "disclosure", "text": DISCLOSURE}
        said = self.emit("speak.verbatim", "guard", line, [opened]).event_id
        released = self.emit("speak.released", "kernel", {"lane": "cp"}, [said])
        await self.speakers["cp"].speak([("disclosure", DISCLOSURE, released.event_id)])
        if "cp" in self.lanes:
            self.spawn(self.lanes["cp"].run())

    async def _ingress(self, key: str, channel: Channel, opened: str) -> None:
        while True:  # partner turns become user.msg / utt.final
            inc = await channel.incoming.get()
            if (wait := inc.due_ms - self.now()) > 0:
                await self.sleep(wait / 1000)
            if key == "cp" and inc.lines:
                await self.speakers["cp"].barge_in()
            last, first = opened, [c for _, c in inc.lines if c][:1]
            if inc.strike:
                last = self.emit(
                    "chan.strike", "kernel", {"lane": "cp"}, first
                ).event_id
            for text, cause in inc.lines:
                last = self._line(key, text, [cause] if cause else [])
            channel.floor(True, self.now())
            if inc.end in ("quit", "hangup"):
                hung_up = inc.end == "hangup" and key == "cp"
                raise SessionEnd("abandoned" if hung_up else "stopped")
            if inc.end == "closed":
                self.emit("chan.closed", "kernel", {"lane": "cp"}, [last])
                self.slow.wake("call_closed")

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

    def _close(self, reason: str, started: dict[str, Any]) -> None:
        ended = {"reason": reason, "counts": dict(self.counts)}
        self.emit("session.ended", "kernel", ended, (), "ops")
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
) -> RunResult:
    """``channels``: ``user``/``cp`` (and for rep-chat ``cp_agent``, a person for
    the agent) -> ``"sim"``/``"human"``/a ``Channel``. Keywords are test seams."""
    sims: dict[str, ChannelSpec] = {"user": "sim", "cp": "sim"}
    specs, clock = sims if channels is None else channels, clock or WallClock()
    k = Kernel(
        cfg, task, specs, runs_dir, clock, sleep or asyncio.sleep, clients, tokenizer
    )
    try:
        return await k.run()
    finally:
        await k.aclose()
