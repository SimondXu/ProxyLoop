"""``slow_fp`` (ADR-0018 V6, S1-SYS-43): stable for fixed inputs, and it moves
when any of the mode's system prompt, the ACT schema, the kind's playbook or
the head's fixed wording does. ``_HEAD`` is pinned to SlowLoop's real head."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.slow.test_loop import Idle

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.llm import ToolSpec
from proxyloop.slow import prompt
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
    ]
    for name, value in edits:
        with monkeypatch.context() as m:
            m.setattr(prompt, name, value)
            assert slow_fp(mode, "full") != before, name
    assert slow_fp(mode, "full") == before
