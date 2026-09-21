"""Write or verify the Phase 03C Stage 1a scenario-invariant manifest.

``--write`` runs the per-instance invariant suite over seeds 1..1000 (all 16
families x 2 configurations, zero model calls) and writes the manifest.
``--check`` recomputes the suite and exits non-zero on any manifest drift or
on any quarantined instance: the contract requires zero oracle/verifier
disagreement over at least 1,000 seeds, so a quarantined row is a finding.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from pathlib import Path

from proxyloop_evaluation.phase03c_scenarios import (
    DEFAULT_INVARIANT_SEEDS,
    INVARIANT_MANIFEST_PATH,
    check_invariant_manifest,
    write_invariant_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    path = ROOT / INVARIANT_MANIFEST_PATH
    started = time.perf_counter()
    if args.write:
        report = write_invariant_manifest(path, DEFAULT_INVARIANT_SEEDS)
        elapsed = time.perf_counter() - started
        print(f"wrote {path.relative_to(ROOT)} in {elapsed:.1f}s")
        print(
            f"seeds {report.seed_first}..{report.seed_last}: "
            f"{report.total_instances} instances, {report.accepted_count} accepted, "
            f"{report.quarantined_count} quarantined"
        )
        for scenario_id, reasons in report.quarantined:
            print(f"quarantined {scenario_id}: {', '.join(reasons)}")
        return 1 if report.quarantined else 0
    problems = check_invariant_manifest(path, DEFAULT_INVARIANT_SEEDS)
    elapsed = time.perf_counter() - started
    if problems:
        for problem in problems:
            print(problem)
        return 1
    print(f"phase03c scenario invariants are consistent ({elapsed:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
