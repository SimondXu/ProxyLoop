"""The web never carries prompt text (AGENTS rule 4, I3): no distinctive line
of a Fast profile, of Slow's prompt or of a world model's prompt (#131 D7)
appears anywhere under ``apps/web``. Prompts reach the viewer only as
``prompts.jsonl`` content, verbatim."""

from __future__ import annotations

import re
from pathlib import Path

from proxyloop.contract.protocol import PROFILES
from proxyloop.env.counterparty import ear, mouth
from proxyloop.env.user import simuser
from proxyloop.slow import prompt as slow

WEB = Path(__file__).parents[2] / "apps" / "web"
SKIP = {"node_modules", "dist", "test-results", "playwright-report"}
MIN_LEN = 10
MIN_WORDS = (
    3  # Slow's and the world's prompts name tools and acts ("smalltalk;"): not prose
)
# Their system prompts (templates: split at each {placeholder}) and Slow's tool text.
OTHERS = (slow.SYSTEM, slow.ACT.description, mouth.SYSTEM, ear.SYSTEM, simuser.SYSTEM)


def _sentences(piece: str) -> set[str]:
    return {piece.strip()} | {s.strip() for s in re.split(r"(?<=[.:;])\s", piece)}


def prompt_lines() -> set[str]:
    """Every system line and sentence, header, trigger and move of every profile."""

    lines = set[str]()
    for p in PROFILES.values():
        pieces = [*p.system.splitlines(), p.closing, *p.moves.values()]
        pieces += [h for h, _ in p.sections]
        for template in p.triggers.values():
            pieces += re.split(r"\{\w+\}", template)
        for piece in pieces:
            lines |= _sentences(piece)
    lines = {line for line in lines if len(line) >= MIN_LEN}
    for text in OTHERS:
        for piece in re.split(r"\{\w+\}|\n", text):
            lines |= {s for s in _sentences(piece) if len(s.split()) >= MIN_WORDS}
    return lines


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
    assert "Tool results come back as text; a refusal says why." in lines  # Slow
    assert "Output only the line." in lines  # the Mouth
    assert "Never invent facts." in lines  # the sim user
    assert "smalltalk;" not in lines  # an act name, too short to be prompt prose


def test_a_planted_prompt_line_is_caught(tmp_path: Path) -> None:
    lines = prompt_lines()
    (tmp_path / "App.tsx").write_text('const s = "Speak first, directives after.";')
    (tmp_path / "Slow.tsx").write_text("<p>You never hear either conversation.</p>")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("CASE AGENT GUIDANCE")
    assert leaks(tmp_path, lines) == [
        ("App.tsx", "Speak first, directives after."),
        ("Slow.tsx", "You never hear either conversation."),
    ]


def test_the_web_carries_no_prompt_text() -> None:
    assert WEB.is_dir()
    assert leaks(WEB, prompt_lines()) == []
