"""Fail if a README results section contains a digit outside a `gen` block (DOCS §4, S0-ROOT-03).

Results sections are the level-2 section headed "Results" and all its subsections. Content between
`<!-- gen:… -->` and `<!-- /gen -->` is generated and exempt, as are the marker lines themselves and
stage ids such as S2.

    python scripts/lint_readme.py [README.md]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

STAGE_ID = re.compile(r"\bS\d\+?\b")


def violations(text: str) -> list[str]:
    out: list[str] = []
    in_results = in_gen = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            in_results = line[3:].strip().lower().startswith("results")
        if line.strip().startswith("<!-- gen:"):
            in_gen = True
            continue
        if line.strip() == "<!-- /gen -->":
            in_gen = False
            continue
        if in_results and not in_gen and re.search(r"\d", STAGE_ID.sub("", line)):
            out.append(f"README line {n}: digit outside a gen block in a results section: {line.strip()[:100]!r}")
    if in_gen:
        out.append("README: unterminated gen block")
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
