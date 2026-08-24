#!/usr/bin/env python3
"""Freeze or verify Phase 03A1-E deterministic r2 fixture artifacts.

This command is deliberately offline.  Hosted model execution is owned by a
separate runner and is not reachable through this CLI.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from proxyloop_evaluation.artifacts_v2 import (
    R2_REPORT_PATH,
    R3_REPORT_PATH,
    check_r2_artifacts,
    write_fixtures_v2,
    write_report_v3,
)
from proxyloop_evaluation.fresh_fixtures import build_fresh_phase03a1_bundle
from proxyloop_evaluation.models import EvaluationReportV2
from proxyloop_evaluation.replay_v2 import derive_r3_report_from_r2

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--write-fixtures",
        action="store_true",
        help="write only the deterministic r2 manifest, episodes, and ceiling",
    )
    modes.add_argument(
        "--check",
        action="store_true",
        help="verify deterministic r2 artifacts and an optional report offline",
    )
    modes.add_argument(
        "--write-r3-report",
        action="store_true",
        help="derive a versioned offline correction from immutable r2 evidence",
    )
    args = parser.parse_args()
    if args.write_fixtures:
        write_fixtures_v2(ROOT)
        print("Phase 03A1-E deterministic fixture artifacts written.")
        return 0
    if args.write_r3_report:
        source = EvaluationReportV2.model_validate_json(
            (ROOT / R2_REPORT_PATH).read_text(encoding="utf-8")
        )
        corrected = derive_r3_report_from_r2(
            source,
            fixtures=build_fresh_phase03a1_bundle().fixtures,
        )
        write_report_v3(ROOT, corrected)
        print("Phase 03A1-E r3 offline re-attribution report written (0 dispatches).")
        return 0
    passed, failures = check_r2_artifacts(ROOT)
    if not passed:
        print("Phase 03A1-E artifact check failed:", *failures, sep="\n- ")
        return 1
    report = ROOT / R3_REPORT_PATH
    if report.is_file():
        parsed = EvaluationReportV2.model_validate_json(
            report.read_text(encoding="utf-8")
        )
        report_state = (
            "ready report checked"
            if parsed.phase_completion_ready
            else "terminally blocked report checked"
        )
    else:
        report_state = "r3 correction report not written"
    print(f"Phase 03A1-E deterministic artifacts valid ({report_state}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
