"""Check a document's `v0-legacy:<path>` references (S0-ROOT-03).

1. Every `v0-legacy:<path>` names a file or directory that exists at the tag.
2. Every block that contains a number also cites at least one `v0-legacy:<path>`
   that is a FILE at the tag. A block is a paragraph, a list item, a table row or
   a heading; fenced code is split the same way. Code spans, link text and headings
   are checked like prose. A number is any token that starts with a digit (or a dot
   and a digit) not preceded by a letter or digit: 58, 0.983, .95, 1,200, 24GB, 10k,
   1e5. Exempt: ISO dates, a prefix of the tag's commit sha, task ids (S0-ROOT-03),
   v0 phase ids (03C, 03A1) and section signs (§2). Letter-prefixed ids (S0, I10,
   v3, A1) are not numbers.

    python scripts/check_legacy_links.py docs/v0-retrospective.md
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TAG = "v0-legacy"
REF = re.compile(r"v0-legacy:([A-Za-z0-9_./\-]+[A-Za-z0-9_/\-])")
NUMBER = re.compile(r"(?<![\w.])\.?\d[\w.,]*")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
FENCE = re.compile(r"^\s{0,3}(```|~~~)")
ITEM = re.compile(r"^\s*(?:[-*+]\s|\|\s|\d+\.\s)")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
MARKER = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
EXEMPT = [
    re.compile(p)
    for p in (
        r"\bS\d-(?:CON|SYS|MOD|ROOT)-\d{2}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"§\d+(?:\.\d+)*",
        r"\b0\d[A-Z]\d?\b",
    )
]


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def object_type(path: str) -> str:
    """Return 'blob', 'tree' or '' for a path at the tag."""
    result = git("cat-file", "-t", f"{TAG}:{path.rstrip('/')}")
    return result.stdout.strip() if result.returncode == 0 else ""


def blocks(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    start = 0
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append((start, "\n".join(buf)))
        buf.clear()

    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip() or FENCE.match(line):
            flush()
        elif HEADING.match(line):
            flush()
            out.append((i, line))
        elif ITEM.match(line) or not buf:
            flush()
            start = i
            buf.append(line)
        else:
            buf.append(line)
    flush()
    return out


def uncited_numbers(block: str, tag_sha: str, types: dict[str, str]) -> list[str]:
    if any(types.get(ref) == "blob" for ref in REF.findall(block)):
        return []
    text = LINK_TARGET.sub("]", REF.sub(" ", MARKER.sub("", block, count=1)))
    text = SHA.sub(lambda m: " " if tag_sha.startswith(m.group()) else m.group(), text)
    for pat in EXEMPT:
        text = pat.sub(" ", text)
    return NUMBER.findall(text)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    text = Path(argv[1]).read_text()
    errors: list[str] = []
    tag_sha = git("rev-parse", "-q", "--verify", f"{TAG}^{{commit}}").stdout.strip()
    if not tag_sha:
        errors.append(f"tag {TAG} not found")
    refs = sorted(set(REF.findall(text)))
    types = {ref: object_type(ref) for ref in refs}
    errors += [f"missing at {TAG}: {ref}" for ref in refs if not types[ref]]
    for line_no, block in blocks(text):
        found = uncited_numbers(block, tag_sha, types)
        if found:
            errors.append(
                f"line {line_no}: number(s) {found[:5]} without a v0-legacy: "
                f"file citation: {block.strip()[:100]!r}"
            )
    for e in errors:
        print(e)
    print(f"{len(refs)} v0-legacy references checked; {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
