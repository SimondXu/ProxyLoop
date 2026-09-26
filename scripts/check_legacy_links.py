"""Check a document's `v0-legacy:<path>` references (S0-ROOT-03).

1. Every `v0-legacy:<path>` names a file or directory that exists at the tag.
2. Every paragraph or list item that contains a number also cites at least one `v0-legacy:` path.
   Ignored as numbers: text inside backticks, headings, ISO dates, the tag commit, and stage,
   invariant and version ids (S0, I10, v0, v3, 03C, ...).

    python scripts/check_legacy_links.py docs/v0-retrospective.md
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TAG = "v0-legacy"
REF = re.compile(r"v0-legacy:([A-Za-z0-9_./\-]+[A-Za-z0-9_/\-])")
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")
EXEMPT = [re.compile(p) for p in (r"`[^`]*`", r"\bS\d-(?:CON|SYS|MOD|ROOT)-\d{2}\b", r"\b\d{4}-\d{2}-\d{2}\b", r"§\d+(?:\.\d+)*", r"\b(?:S|I|v|P|E|Q)\d+\b",
                                  r"\b\d{2}[A-Z]\d?\b", r"\b(?:ADR|PR)-?\d+\b", r"\[[^\]]*\]\([^)]*\)")]


def exists_at_tag(path: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{TAG}:{path.rstrip('/')}"],
                          capture_output=True).returncode == 0


def blocks(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    start, buf = 0, []
    for i, line in enumerate(text.splitlines(), 1):
        new_item = line.lstrip().startswith(("- ", "* ", "| ")) or re.match(r"\s*\d+\. ", line)
        if not line.strip() or new_item:
            if buf:
                out.append((start, "\n".join(buf)))
            buf, start = ([line], i) if line.strip() else ([], 0)
        else:
            if not buf:
                start = i
            buf.append(line)
    if buf:
        out.append((start, "\n".join(buf)))
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    text = Path(argv[1]).read_text()
    errors: list[str] = []
    if subprocess.run(["git", "rev-parse", "-q", "--verify", f"{TAG}^{{commit}}"], capture_output=True).returncode:
        errors.append(f"tag {TAG} not found")
    refs = sorted(set(REF.findall(text)))
    errors += [f"missing at {TAG}: {r}" for r in refs if not exists_at_tag(r)]
    for line_no, block in blocks(text):
        if block.lstrip().startswith("#"):
            continue
        stripped = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", block)
        for pat in EXEMPT:
            stripped = pat.sub(" ", stripped)
        if NUMBER.search(stripped) and "v0-legacy:" not in block:
            errors.append(f"line {line_no}: number without a v0-legacy: citation: {block.strip()[:100]!r}")
    for e in errors:
        print(e)
    print(f"{len(refs)} v0-legacy references checked; {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
