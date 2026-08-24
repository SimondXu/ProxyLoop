"""Compose or validate committed Phase 03A1 baseline evidence."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from proxyloop_evaluation import (
    check_baseline_artifacts,
    frontier_report,
    qwen_report,
    write_report,
)
from proxyloop_evaluation.openai_frontier import FRONTIER_API_KEY_ENV

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--run-qwen", action="store_true")
    action.add_argument("--run-frontier", action="store_true")
    parser.add_argument("--model-path")
    parser.add_argument("--approve-max-cost-usd", type=float)
    args = parser.parse_args()
    if args.run_qwen or args.run_frontier:
        required = {
            "--model-path": args.model_path,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            parser.error(f"model run requires {', '.join(missing)}")
    if args.run_qwen:
        write_report(
            ROOT,
            qwen_report(
                ROOT,
                model_path=args.model_path,
            ),
        )
        print("Recorded local quantized untuned Qwen baseline evidence.")
        return 0
    if args.run_frontier:
        if not os.environ.get(FRONTIER_API_KEY_ENV):
            parser.error(
                f"--run-frontier requires {FRONTIER_API_KEY_ENV} in the process "
                "environment"
            )
        if args.approve_max_cost_usd is None:
            parser.error("--run-frontier requires --approve-max-cost-usd")
        write_report(
            ROOT,
            frontier_report(
                ROOT,
                model_path=args.model_path,
                approved_max_cost_usd=args.approve_max_cost_usd,
            ),
        )
        print("Recorded hosted frontier baseline evidence within the approved cap.")
        return 0
    ok, errors = check_baseline_artifacts(ROOT)
    if ok:
        print("Phase 03A1 baseline artifacts are valid and truthfully bound.")
        return 0
    for error in errors:
        print(error)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
