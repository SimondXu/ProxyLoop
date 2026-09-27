"""``python -m proxyloop.cli session|rep-chat|replay`` (sessions via ``run_session``,
I1). Live runs read ``PL_<ENDPOINT>_{BASE_URL,API_KEY}`` for each endpoint in use
(``VLLM``, ``RELAY``, ``TEAMROUTER``, ``OPENROUTER``). The Fast
and Slow models are chosen by ``ModelRef`` id and endpoint (only ``SessionConfig``
values change); a hosted Fast runs through the chat adapter, with P3
``not_applicable``."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import get_args

from proxyloop.contract.bundle import read_bundle
from proxyloop.contract.config import Sampling, SessionConfig, WorldModels
from proxyloop.contract.llm import (
    AdapterKind,
    Endpoint,
    LLMClient,
    LLMRole,
    ModelRef,
    ReasoningEffort,
)
from proxyloop.core.clock import Clock, WallClock
from proxyloop.env.tasks.loader import load_task, resolve, task_ref_of
from proxyloop.env.tasks.schema import Task
from proxyloop.evidence.check import ENDED_OK, check_path
from proxyloop.kernel.session import ChannelSpec, ClientFactory, run_session
from proxyloop.llm.factory import make_client
from proxyloop.llm.http import RecordSink

REAL = AdapterKind.REAL_HTTP
FAST, FAST_ENDPOINT = "Qwen3.5-9B", "vllm"  # today's defaults
SLOW, SLOW_ENDPOINT = "claude-sonnet-5", "relay"
WORLD = "gemini-3.8-flash"  # ADR-0005
WORLD_ROLES = ("ear", "mouth", "simuser")
WORLD_EFFORT = "low"  # provisional: ADR-0005; S1 probe decides
TEAMROUTER_SLOW_EFFORT = "low"  # provisional until S0-ROOT-12; the user's setting
HOSTED_FAST_EFFORT = "low"  # provisional until S0-ROOT-12; the user's setting
OPENROUTER_FAST_EFFORT = "none"  # user decision 2026-09-27 (S1-SYS-26): Luna
SHOWN = {  # what a person follows in a replay: the payload field per event type
    **{"user.msg": "text", "utt.final": "text", "utt.delivered": "text_heard"},
    **{"f2s.msg": "facts", "s2f.msg": "text", "slow.tool": "result_text"},
    **{"declass.denied": "violations", "session.ended": "reason"},
}


def _ref(endpoint: Endpoint, model_id: str, effort: ReasoningEffort | None) -> ModelRef:
    return ModelRef(
        kind=REAL, endpoint=endpoint, model_id=model_id, reasoning_effort=effort
    )


def live_config(args: argparse.Namespace) -> SessionConfig:
    """The session's models from the options; a vLLM Fast and a relay Slow keep
    the provider's effort, a hosted Fast and a TeamRouter Slow pin it."""

    fast_effort = args.fast_effort
    if args.fast_endpoint != "vllm" and fast_effort is None:
        openrouter = args.fast_endpoint == "openrouter"
        fast_effort = OPENROUTER_FAST_EFFORT if openrouter else HOSTED_FAST_EFFORT
    fast = _ref(args.fast_endpoint, args.fast_model, fast_effort)
    slow_effort = args.slow_effort  # the relay's Slow keeps the provider's default
    if args.slow_endpoint == "teamrouter" and slow_effort is None:
        slow_effort = TEAMROUTER_SLOW_EFFORT
    world = {
        role: _ref(
            "teamrouter", WORLD, getattr(args, f"{role}_effort") or args.world_effort
        )
        for role in WORLD_ROLES
    }
    return SessionConfig(
        fast_user=fast,
        fast_cp=fast,
        slow=_ref(args.slow_endpoint, args.slow_model, slow_effort),
        world=WorldModels(**world),
        fast_sampling=Sampling(temperature=0.3, top_p=0.9, max_tokens=160),  # §6.3
        seed=args.seed,
        live=True,
    )


def redirect_fast_cp(base_url: str, clock: Clock) -> ClientFactory:
    """The dead-endpoint smoke: only ``fast_cp`` goes to ``base_url``."""

    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        url = base_url if role == "fast_cp" else None
        now = clock.monotonic_ms
        return make_client(ref, live=True, clock=now, on_record=sink, base_url=url)

    return make


def replay(run: Path, speed: float) -> int:
    start = time.monotonic()
    for e in read_bundle(run).events:
        if (field := SHOWN.get(e.type)) is None:
            continue
        if speed > 0:
            time.sleep(max(0.0, e.t_ms / 1000 / speed - (time.monotonic() - start)))
        p = e.payload
        shown = p[field] or p.get("text") or p.get("guide") or ""
        print(f"{e.t_ms / 1000:7.1f}s {e.actor:<13} {e.type:<14} {shown}", flush=True)
    report = check_path(run, "offline")
    print("evidence-check offline:", "ok" if report.ok else report.failures)
    return 0 if report.ok else 1


def task_of(args: argparse.Namespace) -> Task:
    """The instance ``--instance`` of ``--family`` in ``--mode`` (unset: the
    family's default mode), resolved from its canonical task_ref."""

    version = load_task(args.family).version
    return resolve(task_ref_of(args.family, version, args.mode, args.instance))


def session(args: argparse.Namespace, channels: dict[str, ChannelSpec]) -> int:
    cfg, clock = live_config(args), WallClock()
    if "human" in channels.values():
        print("Type lines; /quit ends. A rep can /hangup. Two people: u: or r: first.")
    url = args.fast_cp_base_url
    clients = redirect_fast_cp(url, clock) if url else None
    run = run_session(
        cfg,
        task_of(args),
        channels,
        runs_dir=Path(args.runs),
        clock=clock,
        clients=clients,
    )
    result = asyncio.run(run)
    report = check_path(result.path, "claim" if args.claim else "offline")
    print(f"{result.path}: {result.reason}; {report.mode} check:", end=" ")
    print("ok" if report.ok else "\n  " + "\n  ".join(report.failures))
    print(f"reality: {report.reality}")
    return 0 if report.ok and result.reason in ENDED_OK else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proxyloop.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("session", "rep-chat"):
        p = sub.add_parser(name)
        p.add_argument("--family", required=True)
        p.add_argument("--mode", help="a family mode; unset: the family's default")
        p.add_argument("--instance", type=int, default=0, help="0: the file itself")
        efforts, endpoints = get_args(ReasoningEffort), get_args(Endpoint)
        p.add_argument("--world-effort", default=WORLD_EFFORT, choices=efforts)
        for role in WORLD_ROLES:  # per role; unset: --world-effort
            p.add_argument(f"--{role}-effort", choices=efforts)
        p.add_argument("--fast-model", default=FAST, help="a ModelRef model_id")
        p.add_argument("--fast-endpoint", default=FAST_ENDPOINT, choices=endpoints)
        p.add_argument("--fast-effort", choices=efforts, help="hosted Fast only")
        p.add_argument("--slow-model", default=SLOW, help="a ModelRef model_id")
        p.add_argument("--slow-endpoint", default=SLOW_ENDPOINT, choices=endpoints)
        p.add_argument("--slow-effort", choices=efforts, help="unset: see live_config")
        p.add_argument(
            "--fast-cp-base-url", help="dead-endpoint smoke only: fast_cp's server root"
        )
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--runs", default="runs")
        p.add_argument("--claim", action="store_true", help="evidence-check --claim")
        if name == "session":
            p.add_argument("--user", choices=("sim", "human"), default="sim")
            p.add_argument("--rep", choices=("sim", "human"), default="sim")
    p = sub.add_parser("replay")
    p.add_argument("run", help="runs/<run_id>; RUN=<dir> is accepted too")
    p.add_argument("--speed", type=float, default=0, help="0: no pacing; 1: real time")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "replay" and args.fast_endpoint == "vllm" and args.fast_effort:
        parser.error("--fast-effort is for a hosted Fast; a vLLM Fast keeps its own")
    if args.command != "replay" and args.fast_cp_base_url and args.claim:
        parser.error("--fast-cp-base-url is not in the bundle: never with --claim")
    if args.command != "replay" and args.instance < 0:
        parser.error("--instance is a seed >= 0")
    if args.command == "replay":
        return replay(Path(args.run.removeprefix("RUN=")), args.speed)
    if args.command == "rep-chat":
        return session(args, {"cp": "sim", "cp_agent": "human"})
    return session(args, {"user": args.user, "cp": args.rep})


if __name__ == "__main__":
    sys.exit(main())
