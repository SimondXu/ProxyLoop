"""The implementer SubagentStop soft done-gate: block once while the task worktree
is dirty or has no commit ahead of origin/main; never loop, never block elsewhere."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.harness.hooks_layout import Layout, git

HOOK = "done_gate.py"
REASON = "commit your work, or state explicitly in your report why you are returning"


def stop(
    layout: Layout,
    cwd: Path | str,
    active: bool = False,
    extra: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    body: dict[str, Any] = {
        "hook_event_name": "SubagentStop",
        "agent_type": "implementer",
        "agent_id": "agent-i",
        "stop_hook_active": active,
        "cwd": str(cwd),
        **(extra or {}),
    }
    out = layout.run(HOOK, body)
    return json.loads(out) if out else None


def commit(layout: Layout) -> None:
    (layout.wt / "a.txt").write_text("a\n")
    git(layout.wt, "add", "a.txt")
    git(layout.wt, "commit", "-q", "-m", "T1: a")


def assert_blocks(result: dict[str, Any] | None) -> None:
    assert result is not None
    assert result["decision"] == "block"
    assert REASON in result["reason"]


def test_no_commit_ahead_blocks(fresh_layout: Layout) -> None:
    assert_blocks(stop(fresh_layout, fresh_layout.wt))


def test_dirty_worktree_blocks_even_with_a_commit(fresh_layout: Layout) -> None:
    commit(fresh_layout)
    (fresh_layout.wt / "b.txt").write_text("b\n")
    assert_blocks(stop(fresh_layout, fresh_layout.wt))
    (fresh_layout.wt / "b.txt").unlink()
    (fresh_layout.wt / "a.txt").write_text("changed\n")
    assert_blocks(stop(fresh_layout, fresh_layout.wt / "sub-dir-that-is-missing"))


def test_clean_with_a_commit_allows(fresh_layout: Layout) -> None:
    commit(fresh_layout)
    assert stop(fresh_layout, fresh_layout.wt) is None


def test_stop_hook_active_never_loops(fresh_layout: Layout) -> None:
    (fresh_layout.wt / "b.txt").write_text("b\n")
    assert stop(fresh_layout, fresh_layout.wt, active=True) is None


def test_cwd_outside_a_task_worktree_never_blocks(fresh_layout: Layout) -> None:
    (fresh_layout.wt / "b.txt").write_text("b\n")
    assert stop(fresh_layout, fresh_layout.shared) is None
    assert stop(fresh_layout, "/") is None


def test_worktree_named_in_the_transcript_is_used_when_cwd_is_shared(
    fresh_layout: Layout, tmp_path: Path
) -> None:
    # Subagent cwd resets to the shared checkout; the packet names the worktree.
    transcript = tmp_path / "agent.jsonl"
    line = {"message": {"content": f"WORKTREE path: {fresh_layout.wt}\n"}}
    transcript.write_text(json.dumps(line) + "\n")
    extra = {"agent_transcript_path": str(transcript)}
    assert_blocks(stop(fresh_layout, fresh_layout.shared, extra=extra))
    commit(fresh_layout)
    assert stop(fresh_layout, fresh_layout.shared, extra=extra) is None


def test_two_worktrees_in_the_transcript_is_ambiguous_and_allows(
    fresh_layout: Layout, tmp_path: Path
) -> None:
    made = fresh_layout.new_worktree("T2", "**")
    assert made.returncode == 0, made.stderr
    transcript = tmp_path / "agent.jsonl"
    text = f"{fresh_layout.wt}/x and {fresh_layout.plwt / 'T2'}/y"
    transcript.write_text(json.dumps({"m": text}) + "\n")
    extra = {"agent_transcript_path": str(transcript)}
    assert stop(fresh_layout, fresh_layout.shared, extra=extra) is None


@pytest.mark.parametrize(
    "who",
    [
        {"agent_type": "reviewer", "agent_id": "a"},
        {"agent_type": "implementer", "agent_id": ""},
        {"agent_type": "", "agent_id": "a"},
    ],
)
def test_other_agents_and_top_level_never_block(
    fresh_layout: Layout, who: dict[str, str]
) -> None:
    (fresh_layout.wt / "b.txt").write_text("b\n")
    body = {
        "hook_event_name": "SubagentStop",
        "stop_hook_active": False,
        "cwd": str(fresh_layout.wt),
        **who,
    }
    assert fresh_layout.run(HOOK, body) == ""


@pytest.mark.parametrize("raw", ["", "not json", "[]", "{}"])
def test_unparseable_hook_json_is_allowed(fresh_layout: Layout, raw: str) -> None:
    assert fresh_layout.run(HOOK, None, raw=raw) == ""
