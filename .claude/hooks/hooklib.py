"""Shared helpers for the .claude/hooks scripts: shell-word splitting, hook payloads and
the checkout layout (the shared checkout and its ../pl-wt/<ID> task worktrees).
Stdlib only, Python 3.9+."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "{", "!"}
# wrapper -> its flags that take a value; timeout also takes a duration
WRAPPERS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"},
    "nice": {"-n"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "xargs": {"-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a"},
    "env": {"-u", "-C", "-S"},
    "exec": {"-a"},
    **{w: set() for w in ("command", "nohup", "time")},
}
SHELLS = {"bash", "sh", "zsh"}


# --- shell words ----------------------------------------------------------------


def expand(word: str) -> str:
    return os.path.expandvars(os.path.expanduser(word))


def strip_wrappers(words: list[str]) -> list[str]:
    while words:
        w = words[0]
        if w in KEYWORDS or re.match(r"[A-Za-z_]\w*=", w):
            words = words[1:]
        elif w in WRAPPERS:
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in WRAPPERS[w] else words[1:]
            words = words[1:] if w == "timeout" else words
        else:
            break
    return words[2:] if words[:2] == ["uv", "run"] else words


def is_operator(word: str) -> bool:
    return all(c in "();<>|&" for c in word)


def tokenize(command: str) -> list[str]:
    """Shell words and operators; raises ValueError on text shlex cannot parse."""
    flat = command.replace("\\\n", " ").replace("\n", ";")
    lexer = shlex.shlex(flat, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""  # a `#` must never hide the lines after it
    return list(lexer)


def segments(words: list[str]) -> Iterator[list[str]]:
    """The simple commands between operators, unstripped (may be empty)."""
    segment: list[str] = []
    for word in [*words, ";"]:
        if is_operator(word):
            yield segment
            segment = []
        else:
            segment.append(word)


def shell_c_arg(args: list[str]) -> str | None:
    """The command string of `bash -c '<cmd>'` (None if absent)."""
    c = next((i for i, a in enumerate(args) if re.fullmatch(r"-\w*c\w*", a)), -1)
    return args[c + 1] if 0 <= c < len(args) - 1 else None


# --- hook payloads --------------------------------------------------------------


def load_payload() -> dict[str, Any] | None:
    """The hook JSON on stdin, or None if it is not a JSON object."""
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def subagent(payload: dict[str, Any]) -> str:
    """The subagent's type, or "" for a top-level session. Claude Code sets agent_id
    only inside a subagent; agent_type alone also comes from `claude --agent`."""
    kind, ident = payload.get("agent_type"), payload.get("agent_id")
    if isinstance(kind, str) and kind and isinstance(ident, str) and ident:
        return kind
    return ""


def deny(hook: str, reason: str) -> None:
    out = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"Blocked by .claude/hooks/{hook}: {reason}",
    }
    print(json.dumps({"hookSpecificOutput": out}))


# --- checkout layout ------------------------------------------------------------


def real(path: str | Path) -> Path:
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def git_dir(root: Path) -> Path | None:
    """The git dir of a checkout root: `.git` itself, or where a `.git` file points."""
    dot = root / ".git"
    if dot.is_dir():
        return dot
    try:
        text = dot.read_text().strip()
    except OSError:
        return None
    return (
        real(root / text[len("gitdir:") :].strip())
        if text.startswith("gitdir:")
        else None
    )


def shared_checkout() -> Path:
    """The main checkout of the repository holding $CLAUDE_PROJECT_DIR."""
    start = real(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).parents[2])
    for root in (start, *start.parents):
        gd = git_dir(root)
        if gd is None:
            continue
        common = gd / "commondir"
        if common.is_file():
            return real(gd / common.read_text().strip()).parent
        return root
    return start


def task_worktree(path: Path, shared: Path) -> Path | None:
    """The `<shared>/../pl-wt/<ID>` worktree holding `path` (None if not in one)."""
    plwt = shared.parent / "pl-wt"
    if not inside(path, plwt) or path == plwt:
        return None
    root = plwt / path.relative_to(plwt).parts[0]
    return root if git_dir(root) is not None else None


def grant_globs(worktree: Path) -> list[str] | None:
    """The grant written by scripts/root/new_worktree.sh (None if there is none)."""
    gd = git_dir(worktree)
    try:
        text = (gd / "pl-owned-paths").read_text() if gd else None
    except OSError:
        return None
    if text is None:
        return None
    lines = (line.strip() for line in text.splitlines())
    return [line.removeprefix("./") for line in lines if line and line[0] != "#"]
