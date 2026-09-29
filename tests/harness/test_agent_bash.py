"""The subagent Bash hook: no state-changing git on the shared checkout, no app
launches or system installs, and a read-only `scout`.

Top-level sessions (no agent_type/agent_id) are never affected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.harness.hooks_layout import Layout

HOOK = "agent_bash.py"
REVIEWER = {"agent_type": "reviewer", "agent_id": "agent-r"}
IMPL = {"agent_type": "implementer", "agent_id": "agent-i"}
SCOUT = {"agent_type": "scout", "agent_id": "agent-s"}
TOP: dict[str, str] = {}


def decide(
    layout: Layout, command: str, who: dict[str, str], cwd: str | None = None
) -> str:
    body: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd if cwd is not None else str(layout.shared),
        **who,
    }
    out = layout.run(HOOK, body)
    if not out:
        return "allow"
    spec = json.loads(out)["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    assert "ask the dispatching session" in spec["permissionDecisionReason"]
    return spec["permissionDecision"]


def sub(layout: Layout, command: str) -> str:
    return (
        command.replace("<SHARED>", str(layout.shared))
        .replace("<WT>", str(layout.wt))
        .replace("<PLWT>", str(layout.plwt))
    )


SHARED_GIT_DENIED = [
    "git -C <SHARED> worktree add ../pl-wt/X -b x origin/main",
    "git -C <SHARED> fetch origin",
    "git pull",  # cwd is the shared checkout
    "git checkout -b foo",
    "git switch main",
    "git reset --hard HEAD~1",
    "git merge origin/main",
    "git rebase origin/main",
    "git commit -m x",
    "git stash",
    "git clean -n",
    "git branch -D task/x",
    "git branch --delete --force task/x",
    "cd <SHARED> && git commit -m x",
    "cd <WT>; cd <SHARED>; git fetch",
    "git -C <WT> -C ../../pine commit -m x",
    "git -c core.pager=cat -C <SHARED>/src commit -m x",
    "bash -c 'git -C <SHARED> fetch'",
    "bash <<'EOF'\ngit -C <SHARED> fetch\nEOF",  # a heredoc a shell runs
    "sh -s <<EOF\necho hi\ngit -C <SHARED> commit -m x\nEOF",
    "echo hi && git --no-pager -C <SHARED> merge x",
    "cd <SHARED>/pl-wt/stray && git commit -m x",  # a stray worktree is inside
    # git worktree mutations are never a subagent's job, wherever they point
    "git -C <WT> worktree add ../elsewhere",
    "git worktree remove <PLWT>/T1",
    "git -C <WT> worktree prune",
]

SHARED_GIT_ALLOWED = [
    "git -C <WT> log --oneline -3",
    "git -C <SHARED> log --oneline -3",
    "git -C <SHARED> status",
    "git -C <SHARED> diff origin/main",
    "git -C <SHARED> worktree list",
    "git -C <SHARED> branch -a",
    "git log",
    "cd <WT> && git commit -m 'S1-X: y'",
    "cd <WT> && git add -A && git commit -m x && git status",
    "git -C <WT> commit -m x",
    "git -C <WT> fetch origin",
    "git -C <WT> branch -d old",
    "cd <WT> && git commit -F - <<'EOF'\nS1-X: fix\n\nIt's done.\nEOF",
    "cd <WT> && git commit -m \"$(cat <<'EOF'\nS1-X: fix\n\nDon't.\nEOF\n)\"",
    "echo 'git -C <SHARED> commit' > /dev/null",
    "grep -rn 'git checkout' <WT>/src",
]

APPS_DENIED = [
    "open -a Docker",
    "open -a 'Visual Studio Code' .",
    "open /Applications/Docker.app",
    "open -na Colima",
    "docker run --rm alpine",
    "docker pull postgres:16",
    "/usr/local/bin/docker ps",
    "colima start",
    "brew install jq",
    "brew upgrade",
    "npm install -g pnpm",
    "npm i -g typescript",
    "npm i --global typescript",
    "pip install requests",
    "pip3 install requests",
    "python3 -m pip install requests",
    "sudo ls",
    "sudo -u root make check",
    "cd <WT> && timeout 60 docker compose up",
    "echo x | xargs docker rm",
    "bash -lc 'brew install jq'",
]

APPS_ALLOWED = [
    "open README.md",
    "brew list",
    "brew info jq",
    "npm install",
    "npm ci",
    "npm i -D vitest",
    "uv pip install requests",
    "uv sync",
    "uv run pytest -q",
    "make check",
    "echo docker",
    "grep -rn docker compose.yaml",
    "ls /Applications",
]


@pytest.mark.parametrize("command", SHARED_GIT_DENIED + APPS_DENIED)
@pytest.mark.parametrize("who", [REVIEWER, IMPL, SCOUT])
def test_subagent_is_denied(layout: Layout, command: str, who: dict[str, str]) -> None:
    assert decide(layout, sub(layout, command), who) == "deny"


@pytest.mark.parametrize("command", SHARED_GIT_DENIED + APPS_DENIED)
def test_top_level_session_is_never_affected(layout: Layout, command: str) -> None:
    assert decide(layout, sub(layout, command), TOP) == "allow"
    agent_flag = {"agent_type": "implementer"}  # `claude --agent`: no agent_id
    assert decide(layout, sub(layout, command), agent_flag) == "allow"


@pytest.mark.parametrize("command", SHARED_GIT_ALLOWED + APPS_ALLOWED)
@pytest.mark.parametrize("who", [REVIEWER, IMPL])
def test_subagent_ordinary_commands_are_allowed(
    layout: Layout, command: str, who: dict[str, str]
) -> None:
    assert decide(layout, sub(layout, command), who) == "allow"


def test_cwd_inside_a_task_worktree_allows_state_changing_git(
    layout: Layout,
) -> None:
    assert decide(layout, "git commit -m x", IMPL, cwd=str(layout.wt)) == "allow"
    assert decide(layout, "git commit -m x", IMPL, cwd=str(layout.shared)) == "deny"
    sub_dir = str(layout.shared / "src")
    assert decide(layout, "git commit -m x", IMPL, cwd=sub_dir) == "deny"
    back = f"cd {layout.shared} && git commit -m x"
    assert decide(layout, back, IMPL, cwd=str(layout.wt)) == "deny"
    assert decide(
        layout, f"git -C {layout.shared} commit", IMPL, cwd=str(layout.wt)
    ) == ("deny")


SCOUT_DENIED = [
    "echo x > f",
    "echo x >> <WT>/notes.md",
    "ls &> out.txt",
    "cat a | tee b",
    "rm a.txt",
    "mv a b",
    "cp a b",
    "git -C <WT> add a",
    "git -C <WT> commit -m x",
    "git -C <WT> push",
    "git -C <WT> branch newbranch",
    "git -C <WT> tag v1",
    "git -C <WT> stash",
    "git -C <WT> restore a",
    "git -C <WT> config user.name x",
    "git -C <WT> frobnicate",  # unknown verbs fail closed for a scout
    "cd <WT> && git apply p.diff",
]

SCOUT_ALLOWED = [
    "git -C <WT> log --oneline",
    "git -C <WT> show HEAD",
    "git -C <WT> diff origin/main",
    "git -C <WT> status",
    "git -C <WT> blame README.md",
    "git -C <WT> branch -a",
    "git -C <WT> branch --show-current",
    "git -C <WT> worktree list",
    "git -C <WT> stash list",
    "git -C <WT> config --get user.name",
    "git -C <WT> remote -v",
    "ls -la <WT> 2>/dev/null",
    "grep -rn foo <WT> 2>&1 | head",
    "cat <WT>/README.md > /dev/null",
    "rg -n 'x' <WT>",
]


@pytest.mark.parametrize("command", SCOUT_DENIED)
def test_scout_writes_are_denied(layout: Layout, command: str) -> None:
    assert decide(layout, sub(layout, command), SCOUT) == "deny"
    # the same command is not a scout rule for other subagents
    if "<WT>" in command and "frobnicate" not in command:
        assert decide(layout, sub(layout, command), REVIEWER) == "allow"


@pytest.mark.parametrize("command", SCOUT_ALLOWED)
def test_scout_reads_are_allowed(layout: Layout, command: str) -> None:
    assert decide(layout, sub(layout, command), SCOUT) == "allow"


@pytest.mark.parametrize(
    "body",
    [
        {**REVIEWER, "tool_name": "Bash"},
        {**REVIEWER, "tool_name": "Bash", "tool_input": {}},
        {**REVIEWER, "tool_name": "Bash", "tool_input": {"command": 5}},
        {**REVIEWER, "tool_name": "Bash", "tool_input": {"command": "echo 'x"}},
    ],
)
def test_malformed_subagent_input_fails_closed(
    layout: Layout, body: dict[str, Any]
) -> None:
    out = json.loads(layout.run(HOOK, body))["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"


@pytest.mark.parametrize("raw", ["", "not json", "[]", "{}"])
def test_unparseable_hook_json_is_allowed(layout: Layout, raw: str) -> None:
    assert layout.run(HOOK, None, raw=raw) == ""


SYSTEM_PYTHON = Path("/usr/bin/python3")


@pytest.mark.skipif(not SYSTEM_PYTHON.exists(), reason="no /usr/bin/python3")
def test_the_hooks_run_under_system_python(layout: Layout) -> None:
    py = str(SYSTEM_PYTHON)
    bash = {
        "tool_name": "Bash",
        "tool_input": {"command": f"git -C {layout.shared} fetch"},
        "cwd": str(layout.shared),
        **REVIEWER,
    }
    assert "deny" in layout.run(HOOK, bash, python=py)
    edit = {"tool_name": "Edit", "tool_input": {"file_path": str(layout.wt / "x")}}
    assert "deny" in layout.run("owned_paths.py", {**edit, **IMPL}, python=py)
    ok = {"tool_name": "Edit", "tool_input": {"file_path": str(layout.wt / "a.txt")}}
    assert layout.run("owned_paths.py", {**ok, **IMPL}, python=py) == ""
    stop = {"stop_hook_active": False, "cwd": str(layout.wt), **IMPL}
    assert '"block"' in layout.run("done_gate.py", stop, python=py)
