"""Write or verify the Phase 03C Stage 0 offline artifacts.

``--write`` regenerates the two parser errata from the frozen Phase 03B raw
outputs (zero model calls).  ``--check`` verifies the committed errata are
reproducible and that any committed Stage 0 smoke results are self-consistent.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from proxyloop_evaluation.phase03c_experiment import (
    ROOT,
    check_parser_errata,
    check_smoke_results,
    write_parser_errata,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        for path in write_parser_errata(ROOT):
            print(f"wrote {path.relative_to(ROOT)}")
        return 0
    problems = (*check_parser_errata(ROOT), *check_smoke_results(ROOT))
    if problems:
        for problem in problems:
            print(problem)
        return 1
    print("phase03c errata and smoke results are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
