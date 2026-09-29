"""PreToolUse(Edit|Write|NotebookEdit|MultiEdit) hook (S1-ROOT-24): an `implementer`
subagent edits only its own ../pl-wt/<ID> worktree, and there only the globs its
dispatcher granted with scripts/root/new_worktree.sh (the grant file
`<worktree git dir>/pl-owned-paths`). The contract, golden and `.env*` paths need a
glob that names them explicitly; a broad `**` does not reach them. Writes into the
session's scratchpad are allowed.

Top-level sessions and other subagents are never affected; unparseable hook JSON is
allowed (it cannot be told from a top-level call); malformed input from an
implementer is denied. Stdlib only, Python 3.9+."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from hooklib import (
    deny,
    grant_globs,
    inside,
    load_payload,
    real,
    shared_checkout,
    subagent,
    task_worktree,
)

HOOK = "owned_paths.py"
# repo-relative roots that only an explicit grant opens
SENSITIVE_ROOTS = ("src/proxyloop/contract/", "tests/contract/", "tests/golden/")


def glob_regex(glob: str) -> re.Pattern[str]:
    """`**` crosses directories (`**/` also matches none), `*` and `?` do not."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        else:
            out.append({"*": "[^/]*", "?": "[^/]"}.get(glob[i], re.escape(glob[i])))
            i += 1
    return re.compile("".join(out) + r"\Z")


def literal_prefix(glob: str) -> str:
    return re.split(r"[*?]", glob, maxsplit=1)[0]


def is_env(part: str) -> bool:
    return part.startswith(".env")


def explicit(glob: str, rel: str) -> bool:
    """Does `glob` name every sensitive area `rel` lies in, not just cover it?"""
    for root in SENSITIVE_ROOTS:
        if rel.startswith(root) and not literal_prefix(glob).startswith(root):
            return False
    if any(is_env(p) for p in rel.split("/")):
        return is_env(glob.rsplit("/", 1)[-1])
    return True


def sensitive(rel: str) -> bool:
    return rel.startswith(SENSITIVE_ROOTS) or any(is_env(p) for p in rel.split("/"))


def verdict(payload: dict[str, Any]) -> str | None:
    """The deny reason for an implementer edit, or None to allow."""
    tool_input = payload.get("tool_input")
    path = None
    if isinstance(tool_input, dict):
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(path, str) or not os.path.isabs(path):
        return (
            "malformed hook input (no absolute tool_input.file_path/notebook_path); "
            "implementer edits are denied until the path is known."
        )
    target = real(path)
    scratch = payload.get("scratchpad_dir")
    if isinstance(scratch, str) and scratch and inside(target, real(scratch)):
        return None
    shared = shared_checkout()
    if inside(target, shared):
        return (
            f"{target} is inside the shared checkout {shared}; implementers work "
            "only in their ../pl-wt worktree."
        )
    worktree = task_worktree(target, shared)
    if worktree is None:
        return (
            f"{target} is outside every task worktree ({shared.parent}/pl-wt/<ID>); "
            "implementers work only in their ../pl-wt worktree."
        )
    globs = grant_globs(worktree)
    if globs is None:
        return (
            f"{worktree} has no owned-paths grant; ask the dispatcher to create the "
            "worktree with scripts/root/new_worktree.sh <ID> <branch> <owned globs...>."
        )
    rel = target.relative_to(worktree).as_posix()
    matching = [g for g in globs if glob_regex(g).match(rel)]
    if not matching:
        return (
            f"{rel} is outside this task's owned paths ({', '.join(globs)}); "
            "stop and ask the dispatcher for the path."
        )
    if sensitive(rel) and not any(explicit(g, rel) for g in matching):
        return (
            f"{rel} is a contract, golden or .env path, and no grant names it "
            f"explicitly ({', '.join(matching)} is too broad); stop and ask the "
            "dispatcher."
        )
    return None


def main() -> None:
    payload = load_payload()
    if payload is None or subagent(payload) != "implementer":
        return
    reason = verdict(payload)
    if reason is not None:
        deny(HOOK, reason)


if __name__ == "__main__":
    os.environ.setdefault(
        "CLAUDE_PROJECT_DIR", str(Path(__file__).resolve().parents[2])
    )
    main()
