#!/usr/bin/env python3
"""Report and pin the runtime tests that skip without real dependencies.

``make unit-test`` writes the runtime pytest JUnit report; ``make preflight``
ends by running this script over it.  A test is gated when pytest skipped it
with a reason naming a ``PROXYLOOP_TEST_*`` variable.  With every such
variable unset, the gated-skip count must equal ``EXPECTED_GATED_SKIPS``, so
a test that newly skips on a missing variable, or a gated test that
disappears, fails the gate instead of passing silently.
"""

import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / ".gate" / "runtime-junit.xml"
GATE_PREFIX = "PROXYLOOP_TEST_"
# Change only together with the tests it counts (and docs/development.md).
EXPECTED_GATED_SKIPS = 51
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
    return sorted(
        key for key, value in environ.items() if key.startswith(GATE_PREFIX) and value
    )


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
    if variables:
        lines.append(
            f"Pin of {EXPECTED_GATED_SKIPS} not enforced: {', '.join(variables)} "
            "set, so gated tests may have run instead of skipping."
        )
        return True, lines
    if total != EXPECTED_GATED_SKIPS:
        lines.append(
            f"FAIL: expected {EXPECTED_GATED_SKIPS} gated skips, found {total}. "
            f"A test newly skips on a missing {GATE_PREFIX}* variable, or a gated "
            "test was removed or renamed. If intended, update EXPECTED_GATED_SKIPS "
            "in scripts/check_gated_skips.py and docs/development.md."
        )
        return False, lines
    lines.append(f"Gated-skip count matches the pinned {EXPECTED_GATED_SKIPS}.")
    return True, lines


def main(argv: list[str]) -> int:
    report = Path(argv[1]) if len(argv) > 1 else DEFAULT_REPORT
    ok, lines = check(report, dict(os.environ))
    print("\n".join(lines), file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
