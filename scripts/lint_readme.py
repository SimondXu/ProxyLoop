"""Lint the README's generated sections (DOCS §2 and §4, S0-ROOT-03).

1. `gen` markers are whole lines: a start is exactly `<!-- gen:<kind>[=<target>] -->`
   and an end is exactly `<!-- /gen -->`. Marker-like text anywhere else (malformed,
   indented, or sharing a line with other content) is an error, as are a nested
   start, an end without a start, a heading inside an open block and an
   unterminated block.
2. In every section DOCS §2 marks `[gen]` ("Results", "What is real vs simulated",
   "Limitations") and in its subsections, a digit outside a gen block is an error.
   Stage ids such as S2 or S5+ are exempt.

    python scripts/lint_readme.py [README.md]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

START = re.compile(r"^<!-- gen:[a-z_]+(=[^ ]+)? -->$")
END = re.compile(r"^<!-- /gen -->$")
MARKER_LIKE = re.compile(r"<!--\s*/?\s*gen\b", re.IGNORECASE)
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
TOP_LEVEL = re.compile(r"^#{1,2}\s")
GEN_SECTION = re.compile(
    r"^#{2}\s+(\d+\.\s*)?(Results|What is real vs simulated|Limitations)\b",
    re.IGNORECASE,
)
STAGE_ID = re.compile(r"\bS\d\+?\b(?!\.\d)")
SECTION_NUMBER = re.compile(r"^#{2}\s+\d+\.")


def violations(text: str) -> list[str]:
    out: list[str] = []
    in_section = False
    open_at = 0
    for n, line in enumerate(text.splitlines(), 1):
        if START.match(line):
            if open_at:
                out.append(
                    f"README line {n}: gen block opened while the block from line "
                    f"{open_at} is open"
                )
            open_at = n
            continue
        if END.match(line):
            if not open_at:
                out.append(f"README line {n}: gen end without a start")
            open_at = 0
            continue
        if MARKER_LIKE.search(line):
            out.append(
                f"README line {n}: malformed or inline gen marker: "
                f"{line.strip()[:100]!r}"
            )
            continue
        if HEADING.match(line):
            if open_at:
                out.append(
                    f"README line {n}: heading inside the gen block opened at line "
                    f"{open_at}"
                )
            if TOP_LEVEL.match(line):
                in_section = bool(GEN_SECTION.match(line))
        prose = STAGE_ID.sub("", SECTION_NUMBER.sub("##", line))
        if in_section and not open_at and re.search(r"\d", prose):
            out.append(
                f"README line {n}: digit outside a gen block in a generated section: "
                f"{line.strip()[:100]!r}"
            )
    if open_at:
        out.append(f"README line {open_at}: unterminated gen block")
    return out


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "README.md")
    found = violations(path.read_text())
    for v in found:
        print(v)
    print(f"{path}: {len(found)} problem(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
