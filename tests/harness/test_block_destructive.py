"""The PreToolUse Bash hook denies destructive deletes and allows everything else.

The hook runs as a subprocess with the hook JSON on stdin, exactly as Claude Code
invokes it. No destructive command is ever executed here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude" / "hooks" / "block_destructive.py"


def run_hook(
    stdin: str, scratch: Path, python: str = sys.executable
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(REPO), "SCRATCH": str(scratch)}
    return subprocess.run(
        [python, str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=10,
    )


def decision(command: str, scratch: Path, python: str = sys.executable) -> str:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(REPO),
    }
    result = run_hook(json.dumps(payload), scratch, python)
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return "allow"
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert "proxyloop-v0-archive" in out["permissionDecisionReason"]
    return out["permissionDecision"]


BLOCKED = [
    "rm -rf data/",
    "rm -rf ./external/pine-ai-tasks",
    "rm -r data",
    "cd x && rm -rf data",
    "git clean -fdx",
    "git clean -X",
    "rm -rf ~/Desktop/proxyloop-v0-archive/x",
    "rm -rf .",
    "find external -delete",
    # beyond the packet's samples
    "rm -fr external",
    "rm --recursive ./data/raw",
    "rm -R -f data*",
    "rm -rf *",
    "rm -rf $CLAUDE_PROJECT_DIR",
    'rm -rf "$CLAUDE_PROJECT_DIR/data"',
    f"rm -rf {REPO}",
    f"rm -rf {REPO}/external/pine-ai-tasks/repos",
    "echo hi; rm -rf external",
    "ls\nrm -rf data",
    "sudo rm -rf data",
    "bash -c 'rm -rf data'",
    "find . -name '*.json' -delete",
    "find data -exec rm {} +",
    "python3 -c \"import shutil; shutil.rmtree('data')\"",
    "uv run python -c \"import shutil; shutil.rmtree('external/x')\"",
    "git clean -f",
    "git -C sub clean -d -n",
    "git clean --force",
    # review of #114: comments must not hide later lines
    "# clean up\nrm -rf data",
    "echo ok # note\nrm -rf external",
    # the running cwd follows cd
    "cd data && rm -rf raw",
    "cd external && rm -rf pine-ai-tasks",
    f"cd {REPO}/external; rm -rf pine-ai-tasks",
    f"cd .. && rm -rf {REPO.name}",
    # the project dir, the archive and every ancestor of either
    "rm -rf ..",
    "rm -rf ~",
    "rm -rf /",
    "rm -rf ~/Desktop",
    "rm -rf ~/Desktop/proxyloop-v0-archive",
    f"rm -rf {REPO.parent}",
    f"rm -rf {REPO.parent.parent}",
    "rm -rf $CLAUDE_PROJECT_DIR/..",
    # unparseable command text falls back to a raw scan
    "cat <<EOF\ndon't\nEOF\nrm -rf data",
    "rm -rf 'data",
    "echo it's; git clean -fd",
    # keywords and wrappers before the command word
    "for d in a b; do rm -rf data; done",
    "if true; then rm -rf data; fi",
    "if false; then :; else rm -rf external; fi",
    "{ rm -rf data; }",
    "! rm -rf data",
    "timeout 10 rm -rf data",
    "timeout -s KILL 5 rm -rf external",
    "nice -n 5 rm -rf data",
    "sudo -u root rm -rf data",
    "bash -lc 'rm -rf data'",
    "sh -ec 'cd external && rm -rf x'",
]

ALLOWED = [
    "git rm -r runtime/",
    "git rm -r -q tests/contract",
    "rm -r /tmp/abc",
    "rm -r $SCRATCH/x",
    "ls data",
    "make check",
    "rm file.txt",
    # beyond the packet's samples
    "rm data/one.json",
    "rm -rf /tmp/pl-scratch/data",
    "d=$(mktemp -d) && rm -rf $d",
    "git clean -n",
    "git commit -m 'git clean -fdx'",
    "find data -name '*.json'",
    "python3 -c \"import shutil; shutil.rmtree('/tmp/x')\"",
    "uv run pytest tests/harness -q",
    # review of #114
    "rm -rf .pytest_cache",
    "rm -rf node_modules",
    "rm -rf .venv",
    "rm -rf runs/old",
    "git worktree remove ../pl-wt/S0-ROOT-07",
    "git commit -m \"$(cat <<'EOF'\nS0-ROOT-07: fix\n\nDon't delete data.\nEOF\n)\"",
    "git commit -F - <<'EOF'\nS0-ROOT-07: fix\n\nIt's done.\nEOF",
    "echo '# not a comment' && ls",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_destructive_command_is_denied(command: str, tmp_path: Path) -> None:
    assert decision(command, tmp_path) == "deny"


@pytest.mark.parametrize("command", ALLOWED)
def test_ordinary_command_is_allowed(command: str, tmp_path: Path) -> None:
    assert decision(command, tmp_path) == "allow"


@pytest.mark.parametrize(
    "stdin",
    [
        "",
        "not json",
        "[]",
        "{}",
        '{"tool_input": {}}',
        '{"tool_input": {"command": 5}}',
    ],
)
def test_malformed_input_is_allowed(stdin: str, tmp_path: Path) -> None:
    result = run_hook(stdin, tmp_path)
    assert result.returncode == 0
    assert result.stdout == ""


SYSTEM_PYTHON = Path("/usr/bin/python3")


@pytest.mark.skipif(not SYSTEM_PYTHON.exists(), reason="no /usr/bin/python3")
@pytest.mark.parametrize(
    ("command", "expected"), [("rm -rf data", "deny"), ("ls", "allow")]
)
def test_hook_runs_under_system_python(
    command: str, expected: str, tmp_path: Path
) -> None:
    assert decision(command, tmp_path, str(SYSTEM_PYTHON)) == expected
