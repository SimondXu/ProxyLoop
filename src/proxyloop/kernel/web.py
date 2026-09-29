"""The live web case (S1-SYS-05): ``serve.cases.Starter`` and ``Case`` over
``run_session`` (I1). serve calls them and never imports the kernel.

A case is one run. Its case_id is its run_id: an S1 convention of this module
and the docs, never a stored key. The browser user is the user lane's
``HumanWebChannel``; the rep is the SimRep or, with ``rep="human"``, the cp
lane's ``HumanWebChannel`` (the /rep page). The run is written to
``<runs>/live/<run_id>/<run_id>``. Only ``real_http`` models are offered or
started (I8); a dead endpoint ends the session (``LLMUnavailable``), never the
start. Only the piloted, train-only families are offered or resolved (I9):
any other task_ref is ``unknown_task`` and no file of it is opened (AGENTS
rule 11).

``python -m proxyloop.kernel.web [--port N] [--web-dir PATH]`` serves
``serve.api.create_app`` with this Starter on 127.0.0.1 (``make demo``). It
reads the ``PL_<ENDPOINT>_*`` variables of the endpoints a start uses (as
``make smoke-live`` does) and never prints them.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

import uvicorn

from proxyloop.cli import FAST, build_parser, live_config
from proxyloop.contract.config import SessionConfig
from proxyloop.contract.events import ApprovalPost, Event
from proxyloop.contract.llm import AdapterKind, Endpoint, LLMUnavailable
from proxyloop.contract.protocol import ChatTokenizer
from proxyloop.contract.state import Blackboard
from proxyloop.core.clock import Clock
from proxyloop.env.tasks.loader import load_task, resolve, task_ref_of
from proxyloop.env.tasks.refs import parse_task_ref
from proxyloop.env.tasks.schema import Limits, Task
from proxyloop.kernel.channels import ChannelSpec, HumanWebChannel
from proxyloop.kernel.lanes import load_tokenizer
from proxyloop.kernel.session import (
    ClientFactory,
    Kernel,
    RunResult,
    new_run_id,
    run_session,
)
from proxyloop.kernel.speaker import Sleep
from proxyloop.kernel.watchdog import Abort
from proxyloop.llm.http import EndpointEnv, LLMConfigError
from proxyloop.serve.api import HOST, create_app
from proxyloop.serve.bundles import default_roots
from proxyloop.serve.cases import (
    LaneKey,
    ModelOption,
    NotOpen,
    RoleCard,
    RoleFact,
    RoleLimits,
    RoleStop,
    StartRefused,
)

REAL = AdapterKind.REAL_HTTP
# The piloted families, train-only (I9; S1-ROOT-01's pilot lock lists them).
TRAINING = (
    "cp-direct-discount",
    "cp-hidden-fee-readback",
    "x-out-of-envelope-approval",
    "x-user-mind-change",
)
LUNA, SLOW = "openai/gpt-6-luna", "google/gemini-3.8-flash"
_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Offer:
    """A catalogue entry. Only a ``real_http`` one is offered (I8)."""

    lane: LaneKey
    endpoint: Endpoint | None
    model_id: str
    label: str
    default: bool = False
    kind: AdapterKind = REAL

    @property
    def id(self) -> str:  # unique across lanes: the same model serves two
        return f"{self.lane}:{self.endpoint}:{self.model_id}"


def _fast(lane: LaneKey) -> tuple[Offer, ...]:  # the vLLM option needs flag G
    luna = Offer(lane, "openrouter", LUNA, "GPT-6 Luna (OpenRouter)", True)
    return luna, Offer(lane, "vllm", FAST, "Qwen3.5-9B (vLLM)")


CATALOG = (
    *_fast("fast_user"),
    *_fast("fast_cp"),
    Offer("slow", "openrouter", SLOW, "Gemini 3.8 Flash (OpenRouter)", True),
)


@functools.cache
def _tokenizer() -> ChatTokenizer:  # once per process, for a vLLM Fast's P3
    return load_tokenizer()


def _config(family: str, fast: Offer, slow: Offer) -> SessionConfig:
    """The CLI's live config (its reasoning-effort rules) for these models."""
    argv = ["session", "--family", family]
    argv += ["--fast-model", fast.model_id, "--fast-endpoint", str(fast.endpoint)]
    argv += ["--slow-model", slow.model_id, "--slow-endpoint", str(slow.endpoint)]
    return live_config(build_parser().parse_args(argv))


class WebCase:
    """Implements ``serve.cases.Case`` over one running kernel. Every method
    reads the board or queues, on the kernel's loop, without blocking; after
    the session ended each ingress raises (serve: 503), and before the cp call
    opened (``chan.opened{cp}``) a human rep line raises ``NotOpen`` (409)."""

    def __init__(
        self,
        k: Kernel,
        run: asyncio.Task[RunResult],
        user: HumanWebChannel,
        rep: HumanWebChannel | None,
    ) -> None:
        self.run_id = k.run_id
        self._k, self._run, self._user, self._rep = k, run, user, rep

    def blackboard(self) -> Blackboard:
        return self._k.bb

    def post_approval(self, post: ApprovalPost) -> None:
        self._live()
        self._k.post_approval(post, "ui")  # enqueued; the kernel decides

    def user_message(self, text: str) -> None:
        self._live()
        self._user.say(text)

    def rep_utterance(self, text: str) -> None:
        if self._rep is None:
            raise RuntimeError("this case's rep is simulated")
        self._live()
        if self._k.calls.opened is None:  # a line now would land after the call
            raise NotOpen  # opens (serve: 409); no await before the say
        self._rep.say(text)

    def _live(self) -> None:
        if self._run.done() or self._k.ended:  # a line now would be dropped
            raise RuntimeError("the session has ended")


def _ended(run: asyncio.Task[RunResult]) -> None:
    """The server's log, loudly, but no upstream text (AGENTS rule 15): an
    error's type, plus the message only of the kernel's redacted or authored
    ones; no traceback, no chained cause (a raw upstream body)."""
    if run.cancelled():
        _log.info("a live session was cancelled")
    elif (error := run.exception()) is not None:
        told = f": {error}" if isinstance(error, (LLMUnavailable, Abort)) else ""
        _log.error("a live session failed: %s%s", type(error).__name__, told)
    else:
        _log.info("a live session ended: %s", run.result().reason)


class Starter:
    """Implements ``serve.cases.Starter``: one live case at a time (S1). The
    keywords are test seams (as ``run_session``'s)."""

    def __init__(
        self,
        runs: Path = Path("runs"),
        *,
        catalog: Sequence[Offer] = CATALOG,
        clock: Clock | None = None,
        sleep: Sleep | None = None,
        clients: ClientFactory | None = None,
    ) -> None:
        self._runs, self._catalog = runs / "live", {o.id: o for o in catalog}
        self._clock, self._sleep, self._clients = clock, sleep, clients
        self._tasks = tuple(
            task_ref_of(f, load_task(f).version, None, 0) for f in TRAINING
        )
        self._run: asyncio.Task[RunResult] | None = None

    def model_options(self) -> list[ModelOption]:
        return [
            ModelOption(
                id=o.id,
                lane=o.lane,
                label=o.label,
                endpoint=o.endpoint,
                model_id=o.model_id,
                default=o.default,
            )
            for o in self._catalog.values()
            if o.kind is REAL and o.endpoint is not None
        ]

    def task_options(self) -> tuple[str, ...]:
        return self._tasks

    def role_card(self, task_ref: str) -> RoleCard:
        """An allow-list over the resolved instance: what the SimUser and the
        approver see of the principal, plus the company's name. Never the
        counterparty's ladder, persona, patience or ledger, gold, probes,
        briefs or the user spec (I4)."""
        task = self._task(task_ref)  # refuses a non-training ref unopened
        facts, principal = task.profile.facts, task.principal
        identity, shareable = task.counterparty.identity, task.disclosure.shareable
        approval = None
        if principal is not None:
            stated = {b: facts[k] for b, k in principal.envelope.items()}
            limits = principal.limits or Limits.model_validate(stated)
            approval = RoleLimits.model_validate(limits.model_dump())
        stop = None
        if (s := task.stop) is not None:
            hint = s.text_hint.strip()
            stop = RoleStop(trigger=s.trigger, text_hint=hint, change=s.change)
        return RoleCard(
            company=task.counterparty.company,
            persona=task.profile.persona.strip(),
            goal=task.goal(facts).strip(),
            facts=[
                RoleFact(
                    key=k, value=v, identity=k in identity, shareable=k in shareable
                )
                for k, v in facts.items()
            ],
            approval=approval,
            stop=stop,
        )

    async def start_case(
        self,
        task_ref: str,
        models: Mapping[LaneKey, str],
        rep: Literal["sim", "human"] = "sim",
    ) -> WebCase:
        if self._run is not None and not self._run.done():
            raise StartRefused("busy")
        task, chosen = self._task(task_ref), self._chosen(models)
        cfg = _config(task.family, chosen["fast_user"], chosen["slow"])
        cp_cfg = _config(task.family, chosen["fast_cp"], chosen["slow"])
        cfg = cfg.model_copy(update={"fast_cp": cp_cfg.fast_cp})
        _endpoints_set(cfg, rep)
        user = HumanWebChannel()
        human = HumanWebChannel() if rep == "human" else None
        return await self._launch(cfg, task, user, human)

    def _task(self, task_ref: str) -> Task:
        try:
            family = parse_task_ref(task_ref).family
        except ValueError:
            raise StartRefused("unknown_task") from None
        if family not in TRAINING:  # never resolved: no held-out file is opened
            raise StartRefused("unknown_task")
        try:
            return resolve(task_ref)
        except ValueError:
            raise StartRefused("unknown_task") from None

    def _chosen(self, models: Mapping[LaneKey, str]) -> dict[LaneKey, Offer]:
        offers = self._catalog.values()
        chosen: dict[LaneKey, Offer] = {
            o.lane: o for o in offers if o.default and o.kind is REAL
        }
        for lane, option_id in models.items():
            if lane not in get_args(LaneKey):
                raise StartRefused("wrong_lane")
            if (offer := self._catalog.get(option_id)) is None:
                raise StartRefused("unknown_model")
            if offer.lane != lane:
                raise StartRefused("wrong_lane")
            if offer.kind is not REAL:
                raise StartRefused("not_live")
            chosen[lane] = offer
        return chosen

    async def _launch(
        self,
        cfg: SessionConfig,
        task: Task,
        user: HumanWebChannel,
        rep: HumanWebChannel | None,
    ) -> WebCase:
        """Run the session; return once its seq 0 is written. Cancelled before
        that (serve's client left), the run is cancelled too: its bundle ends
        ``stopped`` (or holds no seq 0) and no case is left running."""
        opened: list[Kernel] = []
        ready = asyncio.get_running_loop().create_future()

        def started(e: Event) -> None:  # an isolated bus subscriber
            if e.seq == 0 and not ready.done():  # session.started is written
                ready.set_result(None)

        run_id = new_run_id()
        vllm = "vllm" in (cfg.fast_user.endpoint, cfg.fast_cp.endpoint)
        specs: dict[str, ChannelSpec] = {"user": user, "cp": rep or "sim"}
        session = run_session(
            cfg,
            task,
            specs,
            runs_dir=self._runs / run_id,
            clock=self._clock,
            sleep=self._sleep,
            clients=self._clients,
            tokenizer=_tokenizer() if vllm else None,
            observers=(started,),
            run_id=run_id,
            opened=opened.append,
        )
        self._run = run = asyncio.create_task(session)
        run.add_done_callback(_ended)
        try:
            await asyncio.wait((run, ready), return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            run.cancel()
            await asyncio.gather(run, return_exceptions=True)
            raise
        if not ready.done():  # it ended before seq 0: its error is the start's
            ready.cancel()
            run.result()
            raise RuntimeError("the session ended before session.started")
        return WebCase(opened[0], run, user, rep)


def _endpoints_set(cfg: SessionConfig, rep: str) -> None:
    """Every endpoint the start uses has its variables, else ``unavailable``
    (only the reason: a variable's value is never shown)."""
    refs = [cfg.fast_user, cfg.fast_cp, cfg.slow]
    refs += [cfg.world.ear, cfg.world.mouth] if rep == "sim" else []
    used: set[Endpoint] = {r.endpoint for r in refs if r.endpoint is not None}
    for endpoint in sorted(used):
        try:
            EndpointEnv.load(endpoint)
        except LLMConfigError:
            raise StartRefused("unavailable") from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m proxyloop.kernel.web")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--web-dir", type=Path, metavar="PATH")
    args = parser.parse_args(argv)
    origins = [f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}"]
    roots = default_roots(Path())
    app = create_app(roots, origins, web_dir=args.web_dir, start=Starter())
    uvicorn.run(app, host=HOST, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
