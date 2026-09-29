"""Helpers for the agent-scoped hook tests (S1-ROOT-24).

`layout` builds a throwaway shared checkout `<tmp>/projects/pine` with an
`origin/main` ref, and a task worktree `<tmp>/projects/pl-wt/<ID>` created by
`scripts/root/new_worktree.sh`, exactly as a dispatching session would. Hooks run as
subprocesses with the hook JSON on stdin, as Claude Code invokes them, with
CLAUDE_PROJECT_DIR set to the throwaway shared checkout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude" / "hooks"
NEW_WORKTREE = REPO / "scripts" / "root" / "new_worktree.sh"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    )
    return out.stdout


@dataclass
class Layout:
    shared: Path
    plwt: Path
    wt: Path

    def env(self) -> dict[str, str]:
        return {**os.environ, **GIT_ENV, "CLAUDE_PROJECT_DIR": str(self.shared)}

    def run(self, hook: str, payload: Any, *, raw: str | None = None) -> str:
        """Run a hook; return its stdout (empty means allow)."""
        stdin = raw if raw is not None else json.dumps(payload)
        result = subprocess.run(
            [sys.executable, str(HOOKS / hook)],
            input=stdin,
            capture_output=True,
            text=True,
            env=self.env(),
            check=False,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def new_worktree(self, task: str, *globs: str) -> subprocess.CompletedProcess[str]:
        return self.script(task, f"task/{task.lower()}", *globs)

    def script(
        self, *args: str, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run scripts/root/new_worktree.sh with raw arguments."""
        return subprocess.run(
            ["bash", str(NEW_WORKTREE), *args],
            cwd=cwd or self.shared,
            env=self.env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )


def make_layout(base: Path) -> Layout:
    base = base.resolve()
    shared = base / "projects" / "pine"
    shared.mkdir(parents=True)
    git(shared, "init", "-q", "-b", "main")
    (shared / "README.md").write_text("x\n")
    git(shared, "add", "README.md")
    git(shared, "commit", "-q", "-m", "init")
    git(shared, "update-ref", "refs/remotes/origin/main", "HEAD")
    layout = Layout(
        shared, base / "projects" / "pl-wt", base / "projects" / "pl-wt" / "T1"
    )
    made = layout.new_worktree(
        "T1",
        "src/proxyloop/kernel/**",
        "tests/kernel/**",
        "docs/one.md",
        "**/*.txt",
    )
    assert made.returncode == 0, made.stderr
    return layout
