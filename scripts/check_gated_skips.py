#!/usr/bin/env python3
"""Report and pin the runtime tests that skip without real dependencies.

``make unit-test`` writes the runtime pytest JUnit report; ``make preflight``
ends by running this script over it.  A test is gated when pytest skipped it
with a reason naming a ``PROXYLOOP_TEST_*`` variable.  Only the two
variables the gated tests read decide enforcement: with neither set, the
per-file gated-skip counts must equal ``EXPECTED_GATED_SKIPS_PER_FILE``, so a
gated test that newly skips, disappears, or moves fails the gate instead of
passing silently; with both set, no gated test may skip; with exactly one
set, the counts are reported only.
"""

import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / ".gate" / "runtime-junit.xml"
GATE_PREFIX = "PROXYLOOP_TEST_"
DATABASE_VARIABLE = "PROXYLOOP_TEST_DATABASE_URL"
TEMPORAL_VARIABLE = "PROXYLOOP_TEST_TEMPORAL_ADDRESS"
# Change only together with the tests it counts (and docs/development.md).
EXPECTED_GATED_SKIPS_PER_FILE = {
    "tests/integration/test_fast_under_temporal.py": 3,
    "tests/integration/test_phase_04c_persistent_case_store.py": 29,
    "tests/integration/test_phase_05a_case_runtime.py": 2,
    "tests/integration/test_phase_05a_temporal_workflow.py": 24,
    "tests/integration/test_phase_06b1_channel_runtime.py": 4,
    "tests/integration/test_phase_06b1_temporal.py": 4,
}
EXPECTED_GATED_SKIPS = sum(EXPECTED_GATED_SKIPS_PER_FILE.values())
REAL_DEPENDENCY_TARGETS = ("postgres-check", "phase05a-check", "phase06b1-check")


def gated_skips(report: Path) -> Counter[str]:
    """Count gated skips per test file in a pytest JUnit (xunit1) report."""

    counts: Counter[str] = Counter()
    for testcase in ET.parse(report).getroot().iter("testcase"):
        skipped = testcase.find("skipped")
        if skipped is None or GATE_PREFIX not in skipped.get("message", ""):
            continue
        name = testcase.get("file") or testcase.get("classname") or "<unknown>"
        counts[name.removeprefix("../")] += 1
    return counts


def gate_variables_set(environ: dict[str, str]) -> list[str]:
    """The enforcement-deciding variables that are set to a non-empty value."""

    return [
        name for name in (DATABASE_VARIABLE, TEMPORAL_VARIABLE) if environ.get(name)
    ]


def check(report: Path, environ: dict[str, str]) -> tuple[bool, list[str]]:
    """Return whether the gate holds and the lines to print."""

    if not report.is_file():
        return False, [
            f"gated-skip check: no runtime test report at {report}; "
            "run `make unit-test` (or `make preflight`) first"
        ]
    counts = gated_skips(report)
    total = sum(counts.values())
    targets = ", ".join(f"make {target}" for target in REAL_DEPENDENCY_TARGETS)
    lines = [f"Gated tests skipped for a missing {GATE_PREFIX}* variable: {total}"]
    lines += [f"  {name}: {count}" for name, count in sorted(counts.items())]
    lines.append(
        f"Skipped gated tests are covered only by the real-dependency gates: {targets} "
        '(docs/development.md, "Local gate and real-dependency gates").'
    )
    variables = gate_variables_set(environ)
    if len(variables) == 2:
        if total:
            lines.append(
                f"FAIL: {DATABASE_VARIABLE} and {TEMPORAL_VARIABLE} are set, but "
                f"{total} gated test{'s' if total != 1 else ''} skipped."
            )
            return False, lines
        lines.append(
            f"{DATABASE_VARIABLE} and {TEMPORAL_VARIABLE} set: no gated test skipped."
        )
        return True, lines
    if variables:
        lines.append(
            f"Pin not enforced: only {variables[0]} is set, "
            "so gated tests may have run instead of skipping."
        )
        return True, lines
    mismatches = [
        f"  {name}: expected {EXPECTED_GATED_SKIPS_PER_FILE.get(name, 0)}, "
        f"found {counts.get(name, 0)}"
        for name in sorted(set(counts) | set(EXPECTED_GATED_SKIPS_PER_FILE))
        if counts.get(name, 0) != EXPECTED_GATED_SKIPS_PER_FILE.get(name, 0)
    ]
    if mismatches:
        lines.append(
            f"FAIL: expected {EXPECTED_GATED_SKIPS} gated skips, found {total}. "
            f"Per-file differences from the pin:"
        )
        lines += mismatches
        lines.append(
            f"A test newly skips on a missing {GATE_PREFIX}* variable, or a gated "
            "test was removed, added, or moved between files. If intended, update "
            "EXPECTED_GATED_SKIPS_PER_FILE in scripts/check_gated_skips.py and "
            "docs/development.md."
        )
        return False, lines
    lines.append(f"Gated-skip counts match the pinned {EXPECTED_GATED_SKIPS} per file.")
    return True, lines


def main(argv: list[str]) -> int:
    report = Path(argv[1]) if len(argv) > 1 else DEFAULT_REPORT
    ok, lines = check(report, dict(os.environ))
    print("\n".join(lines), file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
