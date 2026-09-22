#!/usr/bin/env python3
"""Check r4 integrity and contract state; write or verify the rescored r4."""

from __future__ import annotations

import argparse
from pathlib import Path

from proxyloop_evaluation.hosted_rerun import _fresh_fixtures, load_report_r4
from proxyloop_evaluation.hosted_rescore import (
    R4_RESCORED_REPORT_PATH,
    check_r4_integrity,
    check_rescored_artifact,
    derive_rescored_r4,
    execution_contract_state,
    write_rescored_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _print_contract_state() -> None:
    state = execution_contract_state(ROOT)
    print(
        f"Phase 03A1-R execution contract: {state['state']} "
        f"(r4 {state['r4_fingerprint']}, current {state['current_fingerprint']})."
    )
    drifted = state["drifted_paths"]
    if isinstance(drifted, tuple) and drifted:
        print("Drifted since r4:", *drifted, sep="\n- ")
    if state["pins_stale"]:
        print("Per-file execution contract pins are stale; drifted paths unknown.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()

    passed, failures = check_r4_integrity(ROOT)
    if not passed:
        print("Phase 03A1-R r4 integrity check failed:", *failures, sep="\n- ")
        return 1
    print("Phase 03A1-R r4 artifact integrity is valid.")
    _print_contract_state()

    if args.write:
        report = write_rescored_report(
            ROOT, derive_rescored_r4(load_report_r4(ROOT), fixtures=_fresh_fixtures())
        )
        print(f"Wrote {R4_RESCORED_REPORT_PATH} ({report.rescored.evaluator_version}).")
        for condition, episode_ids in report.rows_changed_vs_r4.items():
            print(f"- {condition}: rows_changed_vs_r4={len(episode_ids)}")
        return 0

    passed, failures = check_rescored_artifact(ROOT)
    if not passed:
        print("Phase 03A1-R rescored artifact check failed:", *failures, sep="\n- ")
        return 1
    print("Phase 03A1-R rescored artifact equals the current-evaluator derivation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
