"""The web never carries prompt text (AGENTS rule 4, I3): no distinctive line
of a Fast profile appears anywhere under ``apps/web``. Prompts reach the viewer
only as ``prompts.jsonl`` content, verbatim."""

from __future__ import annotations

import re
from pathlib import Path

from proxyloop.contract.protocol import PROFILES

WEB = Path(__file__).parents[2] / "apps" / "web"
SKIP = {"node_modules", "dist", "test-results", "playwright-report"}
MIN_LEN = 10


def prompt_lines() -> set[str]:
    """Every system line and sentence, header, trigger and move of every profile."""

    lines = set[str]()
    for p in PROFILES.values():
        pieces = [*p.system.splitlines(), p.closing, *p.moves.values()]
        pieces += [h for h, _ in p.sections]
        for template in p.triggers.values():
            pieces += re.split(r"\{\w+\}", template)
        for piece in pieces:
            lines.add(piece.strip())
            lines.update(s.strip() for s in re.split(r"(?<=[.:;])\s", piece))
    return {line for line in lines if len(line) >= MIN_LEN}


def leaks(root: Path, lines: set[str]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or SKIP & set(path.relative_to(root).parts):
            continue
        try:
            text = path.read_text("utf-8")
        except UnicodeDecodeError:
            continue  # binary (an icon); prompt text is text
        found += [(str(path.relative_to(root)), s) for s in lines if s in text]
    return found


def test_the_extraction_finds_the_profiles_prompt_lines() -> None:
    lines = prompt_lines()
    assert len(lines) > 40
    assert "Respond now per the output format." in lines
    assert "CASE AGENT GUIDANCE" in lines


def test_a_planted_prompt_line_is_caught(tmp_path: Path) -> None:
    lines = prompt_lines()
    (tmp_path / "App.tsx").write_text('const s = "Speak first, directives after.";')
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("CASE AGENT GUIDANCE")
    assert leaks(tmp_path, lines) == [("App.tsx", "Speak first, directives after.")]


def test_the_web_carries_no_prompt_text() -> None:
    assert WEB.is_dir()
    assert leaks(WEB, prompt_lines()) == []
