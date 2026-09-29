"""SubagentStop hook, matcher `implementer` (S1-ROOT-24): a soft done-gate. While the
implementer's task worktree has uncommitted changes, or no commit ahead of
origin/main, block the stop once and ask it to commit or say why it returns without
a commit. With stop_hook_active set it always allows, so it never loops.

The worktree is the ../pl-wt/<ID> worktree holding the hook's cwd; a subagent's cwd
is usually reset to the shared checkout, so failing that it is the one ../pl-wt
worktree the subagent's transcript names (its packet's WORKTREE path). No worktree,
or more than one named: allow. Top-level sessions and other agents are never
affected. Stdlib only, Python 3.9+."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from hooklib import load_payload, real, shared_checkout, subagent, task_worktree

REASON = (
    "commit your work, or state explicitly in your report why you are returning "
    "without a commit (escalation)"
)


def from_transcript(payload: dict[str, Any], shared: Path) -> Path | None:
    path = payload.get("agent_transcript_path")
    if not isinstance(path, str) or not path:
        return None
    try:
        text = real(path).read_text(errors="replace")
    except OSError:
        return None
    plwt = shared.parent / "pl-wt"
    names = set(re.findall(re.escape(str(plwt)) + r"/([A-Za-z0-9._-]+)", text))
    found = {w for w in (task_worktree(plwt / n, shared) for n in names) if w}
    return found.pop() if len(found) == 1 else None


def git(worktree: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    return out.stdout.strip()


def problems(worktree: Path) -> list[str]:
    try:
        dirty = git(worktree, "status", "--porcelain")
        ahead = git(worktree, "rev-list", "--count", "origin/main..HEAD")
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"git could not inspect the worktree: {exc}"]
    found = ["uncommitted changes"] if dirty else []
    return found + (["no commit ahead of origin/main"] if ahead == "0" else [])


def main() -> None:
    payload = load_payload()
    if payload is None or subagent(payload) != "implementer":
        return
    if payload.get("stop_hook_active"):
        return
    shared = shared_checkout()
    cwd = payload.get("cwd")
    worktree = (
        task_worktree(real(cwd), shared) if isinstance(cwd, str) and cwd else None
    )
    worktree = worktree or from_transcript(payload, shared)
    if worktree is None:
        return
    found = problems(worktree)
    if found:
        reason = f"{REASON}. Found in {worktree}: {'; '.join(found)}."
        print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    os.environ.setdefault(
        "CLAUDE_PROJECT_DIR", str(Path(__file__).resolve().parents[2])
    )
    main()
