"""The owned-paths hook: an implementer edits only its worktree's granted globs.

Top-level sessions (no agent_type/agent_id) and other subagents are never affected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.harness.hooks_layout import REPO, Layout, git, make_layout

HOOK = "owned_paths.py"
IMPL = {"agent_type": "implementer", "agent_id": "agent-1"}


def payload(path: str, tool: str = "Edit", **extra: Any) -> dict[str, Any]:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {key: path},
        "cwd": "/",
        **extra,
    }


def decide(layout: Layout, body: dict[str, Any]) -> tuple[str, str]:
    out = layout.run(HOOK, body)
    if not out:
        return "allow", ""
    spec = json.loads(out)["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    return spec["permissionDecision"], spec["permissionDecisionReason"]


GRANTED = [
    "src/proxyloop/kernel/loop.py",
    "src/proxyloop/kernel/sub/deep/x.py",
    "tests/kernel/test_x.py",
    "docs/one.md",
    "a.txt",
    "deep/er/b.txt",
]
OUTSIDE = [
    "src/proxyloop/slow/x.py",
    "docs/two.md",
    "docs/one.md.bak",
    "tests/kernelx/test.py",
    "PLAN.md",
    ".git",
]


@pytest.mark.parametrize("rel", GRANTED)
@pytest.mark.parametrize("tool", ["Edit", "Write", "NotebookEdit", "MultiEdit"])
def test_implementer_edit_inside_grant_is_allowed(
    layout: Layout, rel: str, tool: str
) -> None:
    assert decide(layout, payload(str(layout.wt / rel), tool, **IMPL))[0] == "allow"


@pytest.mark.parametrize("rel", OUTSIDE)
def test_implementer_edit_outside_grant_is_denied(layout: Layout, rel: str) -> None:
    verdict, reason = decide(layout, payload(str(layout.wt / rel), **IMPL))
    assert verdict == "deny"
    assert "src/proxyloop/kernel/**" in reason  # the globs are named


@pytest.mark.parametrize(
    "rel",
    [
        "src/proxyloop/contract/events.py",
        "tests/contract/test_x.py",
        "tests/golden/ids.txt",
        ".env",
        ".env.local",
        "apps/web/.env.txt",
    ],
)
def test_sensitive_paths_need_an_explicit_grant(tmp_path: Path, rel: str) -> None:
    layout = make_layout(tmp_path)
    made = layout.new_worktree("T2", "**")
    assert made.returncode == 0, made.stderr
    wt2 = layout.plwt / "T2"
    verdict, reason = decide(layout, payload(str(wt2 / rel), **IMPL))
    assert verdict == "deny", rel
    assert "explicit" in reason
    # the broad grant still covers ordinary files
    assert decide(layout, payload(str(wt2 / "src/x.py"), **IMPL))[0] == "allow"


def test_named_contract_and_env_grants_allow(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    made = layout.new_worktree(
        "T3", "src/proxyloop/contract/**", "tests/golden/ids.txt", ".env.example"
    )
    assert made.returncode == 0, made.stderr
    wt3 = layout.plwt / "T3"
    for rel in (
        "src/proxyloop/contract/events.py",
        "tests/golden/ids.txt",
        ".env.example",
    ):
        assert decide(layout, payload(str(wt3 / rel), **IMPL))[0] == "allow", rel
    for rel in ("tests/golden/other.txt", ".env", "tests/contract/t.py"):
        assert decide(layout, payload(str(wt3 / rel), **IMPL))[0] == "deny", rel


def test_shared_checkout_path_is_denied(layout: Layout) -> None:
    for rel in ("src/proxyloop/kernel/loop.py", "README.md", ".claude/x"):
        verdict, reason = decide(layout, payload(str(layout.shared / rel), **IMPL))
        assert verdict == "deny"
        assert "inside the shared checkout" in reason


def test_a_stray_worktree_inside_the_shared_checkout_is_denied(
    layout: Layout,
) -> None:
    stray = layout.shared / "pl-wt" / "T1" / "src/proxyloop/kernel/loop.py"
    assert decide(layout, payload(str(stray), **IMPL))[0] == "deny"


def test_worktree_without_grant_file_is_denied(fresh_layout: Layout) -> None:

    bare = fresh_layout.plwt / "T9"
    git(fresh_layout.shared, "worktree", "add", "-q", str(bare), "-b", "t9")
    verdict, reason = decide(fresh_layout, payload(str(bare / "a.txt"), **IMPL))
    assert verdict == "deny"
    assert "scripts/root/new_worktree.sh" in reason


@pytest.mark.parametrize(
    "path",
    ["/etc/hosts", "PLACEHOLDER_PLWT/not-a-worktree/a.txt", "relative/a.txt"],
)
def test_paths_outside_any_task_worktree_are_denied(layout: Layout, path: str) -> None:
    path = path.replace("PLACEHOLDER_PLWT", str(layout.plwt))
    assert decide(layout, payload(path, **IMPL))[0] == "deny"


def test_scratchpad_writes_are_allowed(layout: Layout, tmp_path: Path) -> None:
    body = payload(str(tmp_path / "notes.txt"), "Write", scratchpad_dir=str(tmp_path))
    assert decide(layout, {**body, **IMPL})[0] == "allow"
    # but not a sibling of the scratchpad
    body = payload(
        str(tmp_path.parent / "x.txt"), "Write", scratchpad_dir=str(tmp_path)
    )
    assert decide(layout, {**body, **IMPL})[0] == "deny"


def test_dotdot_and_symlinks_cannot_escape_the_grant(layout: Layout) -> None:
    sneaky = str(layout.wt / "src/proxyloop/kernel/../../../PLAN.md")
    assert decide(layout, payload(sneaky, **IMPL))[0] == "deny"
    link = layout.wt / "src/proxyloop/kernel/link"
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.exists():
        link.symlink_to(layout.shared)
    assert decide(layout, payload(str(link / "README.md"), **IMPL))[0] == "deny"


@pytest.mark.parametrize(
    "who",
    [
        {},  # top-level session
        {"agent_type": "", "agent_id": ""},
        {"agent_type": "implementer"},  # `claude --agent implementer`: no agent_id
        {"agent_type": "reviewer", "agent_id": "a"},
    ],
)
def test_non_implementer_calls_are_never_affected(
    layout: Layout, who: dict[str, str]
) -> None:
    for path in (str(layout.shared / "README.md"), "/etc/hosts"):
        assert decide(layout, payload(path, **who))[0] == "allow"


@pytest.mark.parametrize(
    "body",
    [
        {**IMPL, "tool_name": "Edit"},
        {**IMPL, "tool_name": "Edit", "tool_input": {}},
        {**IMPL, "tool_name": "Edit", "tool_input": {"file_path": 5}},
        {**IMPL, "tool_name": "Edit", "tool_input": "x"},
    ],
)
def test_malformed_implementer_input_fails_closed(
    layout: Layout, body: dict[str, Any]
) -> None:
    verdict, reason = decide(layout, body)
    assert verdict == "deny"
    assert "malformed" in reason


@pytest.mark.parametrize("raw", ["", "not json", "[]", "{}"])
def test_unparseable_hook_json_is_allowed(layout: Layout, raw: str) -> None:
    # without a parseable agent_type the call cannot be told from a top-level one
    assert layout.run(HOOK, None, raw=raw) == ""


def test_settings_register_the_agent_hooks() -> None:
    settings = json.loads((REPO / ".claude" / "settings.json").read_text())
    hooks = settings["hooks"]
    registered = {
        (event, entry["matcher"], Path(h["command"].split('"')[1]).name)
        for event, entries in hooks.items()
        for entry in entries
        for h in entry["hooks"]
    }
    assert registered == {
        ("PreToolUse", "Bash", "block_destructive.py"),
        ("PreToolUse", "Bash", "agent_bash.py"),
        ("PreToolUse", "Edit|Write|NotebookEdit|MultiEdit", "owned_paths.py"),
    }
