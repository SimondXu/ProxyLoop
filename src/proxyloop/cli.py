"""``python -m proxyloop.cli``: ``session``, ``rep-chat`` and the terminal ``replay``.

``session`` and ``rep-chat`` both call ``run_session`` (I1); rep-chat is a
session in which the person at the terminal speaks for the agent on the call
(``cp_agent``) against the simulated rep. ``replay`` only reads a bundle. Live
runs read ``PL_{VLLM,RELAY,TEAMROUTER}_{BASE_URL,API_KEY}`` from the shell.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import get_args

from proxyloop.contract.bundle import read_bundle
from proxyloop.contract.config import Sampling, SessionConfig, WorldModels
from proxyloop.contract.llm import AdapterKind, ModelRef, ReasoningEffort
from proxyloop.env.tasks.loader import load_task
from proxyloop.evidence.check import ENDED_OK, check_path
from proxyloop.kernel.session import ChannelSpec, run_session

REAL = AdapterKind.REAL_HTTP
SONNET = ModelRef(kind=REAL, endpoint="relay", model_id="claude-sonnet-5")
WORLD = "gemini-3.8-flash"  # ADR-0005
# What a person follows in a replay: the payload field shown per event type.
SHOWN = {
    **{"user.msg": "text", "utt.final": "text", "utt.delivered": "text_heard"},
    **{"f2s.msg": "facts", "s2f.msg": "text", "slow.tool": "result_text"},
    **{"declass.denied": "violations", "session.ended": "reason"},
}


def live_config(
    fast_model: str, world_effort: ReasoningEffort, seed: int
) -> SessionConfig:
    fast = ModelRef(kind=REAL, endpoint="vllm", model_id=fast_model)
    world = ModelRef(
        kind=REAL, endpoint="teamrouter", model_id=WORLD, reasoning_effort=world_effort
    )
    return SessionConfig(
        fast_user=fast,
        fast_cp=fast,
        slow=SONNET,
        world=WorldModels(ear=world, mouth=world, simuser=world),
        fast_sampling=Sampling(temperature=0.3, top_p=0.9, max_tokens=160),  # §6.3
        seed=seed,
        live=True,
    )


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


def session(args: argparse.Namespace, channels: dict[str, ChannelSpec]) -> int:
    cfg = live_config(args.fast_model, args.world_effort, args.seed)
    if "human" in channels.values():
        print("Type lines; /quit ends. A rep can /hangup. Two people: u: or r: first.")
    run = run_session(cfg, load_task(args.family), channels, runs_dir=Path(args.runs))
    result = asyncio.run(run)
    report = check_path(result.path, "claim" if args.claim else "offline")
    print(f"{result.path}: {result.reason}; {report.mode} check:", end=" ")
    print("ok" if report.ok else "\n  " + "\n  ".join(report.failures))
    print(f"reality: {report.reality}")
    return 0 if report.ok and result.reason in ENDED_OK else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="proxyloop.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("session", "rep-chat"):
        p = sub.add_parser(name)
        p.add_argument("--family", required=True)
        efforts = get_args(ReasoningEffort)
        p.add_argument("--world-effort", required=True, choices=efforts)
        p.add_argument("--fast-model", default="Qwen3.5-9B")
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--runs", default="runs")
        p.add_argument("--claim", action="store_true", help="evidence-check --claim")
        if name == "session":
            p.add_argument("--user", choices=("sim", "human"), default="sim")
            p.add_argument("--rep", choices=("sim", "human"), default="sim")
    p = sub.add_parser("replay")
    p.add_argument("run", help="runs/<run_id>; RUN=<dir> is accepted too")
    p.add_argument("--speed", type=float, default=0, help="0: no pacing; 1: real time")
    args = parser.parse_args(argv)
    if args.command == "replay":
        return replay(Path(args.run.removeprefix("RUN=")), args.speed)
    if args.command == "rep-chat":
        return session(args, {"cp": "sim", "cp_agent": "human"})
    return session(args, {"user": args.user, "cp": args.rep})


if __name__ == "__main__":
    sys.exit(main())
