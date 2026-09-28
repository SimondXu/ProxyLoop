"""``slow_fp`` (ADR-0018 V6, S1-SYS-43): stable for fixed inputs, across
processes and hash seeds, and it moves when any input does: the mode's system
prompt, the ACT schema, the kind's playbook, the head's fixed wording,
``MAX_TOKENS``, ``WINDOW`` or any byte of a ``slow/`` or ``guard/`` source (on a
tmp copy: repo files are never edited). ``_HEAD`` is pinned to SlowLoop's head."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from tests.slow.test_loop import Idle

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.llm import ToolSpec
from proxyloop.slow import loop, prompt
from proxyloop.slow.prompt import slow_fp
from proxyloop.slow.tools import FORMATS

T, R = SlowViewMode.TRANSCRIPT, SlowViewMode.RELAY_ONLY


def test_the_head_template_is_slow_loops_head(tmp_path: Path) -> None:
    idle = Idle(tmp_path)
    loop, t = idle.slow(["unused"]), idle.k.task
    keys = frozenset(t.disclosure.shareable)
    head = prompt._HEAD.format(  # pyright: ignore[reportPrivateUsage]
        brief=t.slow_brief,
        kind=t.mode,
        keys=", ".join(sorted(keys)),
        public=", ".join(sorted(keys & FORMATS.keys())) or "none",
        playbook=prompt.PLAYBOOK[t.mode],
    )
    assert loop._head == head  # pyright: ignore[reportPrivateUsage]


def test_slow_fp_is_stable_and_splits_modes_and_kinds() -> None:
    assert slow_fp(T, "full") == slow_fp(T, "full")
    fps = {slow_fp(m, k) for m in (T, R) for k in ("full", "info_only")}
    assert len(fps) == 4 and all(len(fp) == 64 for fp in fps)


@pytest.mark.parametrize("mode", [T, R])
def test_slow_fp_moves_with_each_input(
    monkeypatch: pytest.MonkeyPatch, mode: SlowViewMode
) -> None:
    before = slow_fp(mode, "full")
    act = prompt.ACT.parameters | {"required": ["calls"]}
    edits = [
        ("SYSTEM" if mode is R else "_SYSTEM_TRANSCRIPT", "a new system prompt"),
        ("ACT", ToolSpec(name="act", description="x", parameters=act)),
        ("PLAYBOOK", prompt.PLAYBOOK | {"full": "CLOSE PLAYBOOK (edited)"}),
        ("_HEAD", prompt._HEAD + ".\n"),  # pyright: ignore[reportPrivateUsage]
        ("MAX_TOKENS", prompt.MAX_TOKENS + 1),
    ]
    for name, value in edits:
        with monkeypatch.context() as m:
            m.setattr(prompt, name, value)
            assert slow_fp(mode, "full") != before, name
    with monkeypatch.context() as m:
        m.setattr(loop, "WINDOW", loop.WINDOW + 1)
        assert slow_fp(mode, "full") != before, "WINDOW"
    assert slow_fp(mode, "full") == before


def test_slow_fp_is_the_same_across_hash_seeds() -> None:
    code = "from proxyloop.slow.prompt import slow_fp as f, SlowViewMode as M;"
    code += "print(f(M.TRANSCRIPT, 'full'))"
    fps = {
        subprocess.run(
            [sys.executable, "-c", code],
            env=os.environ | {"PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for seed in ("1", "2")
    }
    assert fps == {slow_fp(T, "full")}


@pytest.mark.parametrize("edited", ["guard/verify.py", "slow/state.py"])
def test_slow_fp_moves_with_any_slow_or_guard_source_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, edited: str
) -> None:
    package = Path(prompt.__file__).parent.parent
    skip = shutil.ignore_patterns("__pycache__")
    for d in ("slow", "guard"):
        shutil.copytree(package / d, tmp_path / d, ignore=skip)
    before = slow_fp(T, "full")
    monkeypatch.setattr(prompt, "_PACKAGE", tmp_path)
    assert slow_fp(T, "full") == before  # relative paths: a copy is the same
    with (tmp_path / edited).open("a", encoding="utf-8") as f:
        f.write("# a comment\n")
    assert slow_fp(T, "full") != before


def test_no_sources_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no slow/ or guard/ sources"):
        prompt.sources_sha(tmp_path)
