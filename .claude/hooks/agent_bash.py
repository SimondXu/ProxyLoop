"""PreToolUse(Bash) hook for subagents (S1-ROOT-24). Denies, for every subagent:
- state-changing git (worktree fetch pull checkout switch reset merge rebase commit
  stash clean, `branch -D`) aimed at the shared checkout: through `git -C`, the cwd,
  or a `cd` earlier in the command; and `git worktree` other than `list` anywhere;
- application launches and system installs: `open -a`/`open X.app`, docker, colima,
  `brew install|upgrade|reinstall`, `npm|pnpm install -g`, pip install (not `uv pip`),
  sudo.
A `scout` is also read-only: no output redirection to a file, no rm/mv/cp/tee/touch/
mkdir, and only read-only git.

Top-level sessions are never affected; unparseable hook JSON is allowed (it cannot be
told from a top-level call); a subagent's malformed input or unparseable command is
denied. Heredoc bodies are data, except when a shell reads them as a script.
Stdlib only, Python 3.9+."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from hooklib import (
    SHELLS,
    deny,
    expand,
    inside,
    is_operator,
    load_payload,
    real,
    segments,
    shared_checkout,
    shell_c_arg,
    strip_wrappers,
    subagent,
    tokenize,
)

HOOK = "agent_bash.py"
ASK = "; ask the dispatching session."
SHARED_VERBS = {
    "fetch", "pull", "checkout", "switch", "reset", "merge", "rebase",
    "commit", "stash", "clean",
}  # fmt: skip
GIT_VALUE_OPTS = {"-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
READ_VERBS = {
    "log", "show", "diff", "status", "blame", "annotate", "grep", "ls-files",
    "ls-tree", "ls-remote", "rev-parse", "rev-list", "cat-file", "describe",
    "shortlog", "merge-base", "name-rev", "for-each-ref", "show-ref", "show-branch",
    "range-diff", "whatchanged", "count-objects", "check-ignore", "help", "version",
}  # fmt: skip
BRANCH_LIST = {"--all", "--remotes", "--list", "--show-current", "--verbose"}
SCOUT_WRITERS = {"rm", "mv", "cp", "tee", "touch", "mkdir"}
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(?:'(\w+)'|\"(\w+)\"|\\?(\w+))")
SHELL_FED = re.compile(r"(?:^|[\s;&|(])(?:ba|z)?sh(?:\s+-\w+)*\s*<<")


def split_heredocs(command: str) -> tuple[str, list[str]]:
    """The command without heredoc bodies, and the bodies a shell reads as a script."""
    kept: list[str] = []
    scripts: list[str] = []
    lines = iter(command.split("\n"))
    for line in lines:
        kept.append(line)
        for match in HEREDOC.finditer(line):
            end = next(g for g in match.groups() if g)
            body = []
            for inner in lines:
                if inner.strip() == end:
                    break
                body.append(inner)
            if SHELL_FED.search(line[: match.end()]):
                scripts.append("\n".join(body))
    return "\n".join(kept), scripts


def short_flags(args: list[str]) -> set[str]:
    return {c for a in args if a[:1] == "-" and a[1:2] != "-" for c in a[1:]}


def scout_git_ok(verb: str, rest: list[str]) -> bool:
    if verb in READ_VERBS:
        return True
    if verb == "branch":
        return all(
            a in BRANCH_LIST or (a[:1] == "-" and a[1:2] != "-") for a in rest
        ) and (short_flags(rest) <= {"a", "r", "v", "l"})
    if verb == "tag":
        return rest[:1] in ([], ["-l"], ["--list"])
    if verb == "stash":
        return rest[:1] in (["list"], ["show"])
    if verb == "remote":
        return rest[:1] in ([], ["-v"], ["--verbose"], ["show"], ["get-url"])
    if verb == "config":
        return bool({"--get", "--get-all", "--get-regexp", "--list", "-l"} & set(rest))
    return False


def git_reason(args: list[str], cwd: str, shared: Path, scout: bool) -> str | None:
    target, i = cwd, 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-C" and i + 1 < len(args):
            target = os.path.join(target, expand(args[i + 1]))
        i += 2 if args[i] in GIT_VALUE_OPTS or args[i] == "-C" else 1
    if i >= len(args):
        return None
    verb, rest = args[i], args[i + 1 :]
    if verb == "worktree":  # anywhere: a stray worktree is the 2026-09-28 incident
        ok = rest[:1] == ["list"]
        return None if ok else "subagents never add, move or remove worktrees" + ASK
    if scout and not scout_git_ok(verb, rest):
        return f"a scout is read-only (`git {verb}`)" + ASK
    flags = short_flags(rest)
    force_delete = "D" in flags or (
        ("d" in flags or "--delete" in rest) and ("f" in flags or "--force" in rest)
    )
    if (verb in SHARED_VERBS or (verb == "branch" and force_delete)) and inside(
        real(target), shared
    ):
        return (
            f"subagents never run state-changing git (`git {verb}`) on the shared "
            f"checkout {shared}; use `git -C <your ../pl-wt worktree> ...`" + ASK
        )
    return None


def app_reason(cmd: str, args: list[str]) -> str | None:
    first = next((a for a in args if a[:1] != "-"), "")
    if cmd == "open":
        app = any(a.rstrip("/").endswith(".app") for a in args)
        launch = app or bool(short_flags(args) & {"a", "b"})
    elif cmd == "brew":
        launch = first in ("install", "upgrade", "reinstall")
    elif cmd in ("npm", "pnpm"):
        is_global = bool({"-g", "--global", "--location=global"} & set(args))
        launch = first in ("i", "install", "add") and is_global
    elif cmd.startswith("python"):
        launch = args[:2] == ["-m", "pip"] and "install" in args
    else:
        pip = re.fullmatch(r"pip3?(\.\d+)?", cmd) is not None and "install" in args
        launch = pip or cmd in ("docker", "docker-compose", "colima")
    if launch:
        what = f"`{cmd}`"
        return f"subagents never launch applications or install software ({what})" + ASK
    return None


def writes_file(words: list[str]) -> bool:
    """Output redirection to a file (not /dev/*, not an fd duplication)."""
    for op, target in zip(words, [*words[1:], ""]):
        if not is_operator(op) or ">" not in op:
            continue
        if op.endswith("&"):
            if not re.fullmatch(r"\d+|-", target):
                return True
        elif not target.startswith("/dev/"):
            return True
    return False


def reason_for(command: str, cwd: str, shared: Path, scout: bool) -> str | None:
    text, scripts = split_heredocs(command)
    for script in scripts:
        found = reason_for(script, cwd, shared, scout)
        if found:
            return found
    try:
        words = tokenize(text)
    except ValueError:
        return "the command could not be parsed (unbalanced quotes?); simplify it" + ASK
    if scout and writes_file(words):
        return "a scout is read-only (output redirection to a file)" + ASK
    for segment in segments(words):
        seg = strip_wrappers(segment)
        prefix = segment[: len(segment) - len(seg)]
        if "sudo" in (os.path.basename(w) for w in prefix):
            return "subagents never use sudo" + ASK
        if not seg:
            continue
        cmd, args = os.path.basename(seg[0]), seg[1:]
        found = None
        if cmd == "cd":
            dest = [a for a in args if a[:1] != "-"]
            cwd = os.path.join(cwd, expand(dest[0]) if dest else str(Path.home()))
        elif cmd in SHELLS:
            inner = shell_c_arg(args)
            found = reason_for(inner, cwd, shared, scout) if inner else None
        elif cmd == "git":
            found = git_reason(args, cwd, shared, scout)
        elif scout and cmd in SCOUT_WRITERS:
            found = f"a scout is read-only (`{cmd}`)" + ASK
        else:
            found = app_reason(cmd, args)
        if found:
            return found
    return None


def verdict(payload: dict[str, Any]) -> str | None:
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    cwd = payload.get("cwd")
    if not isinstance(command, str):
        return "malformed hook input (no tool_input.command)" + ASK
    cwd = cwd if isinstance(cwd, str) and cwd else os.getcwd()
    return reason_for(command, cwd, shared_checkout(), subagent(payload) == "scout")


def main() -> None:
    payload = load_payload()
    if payload is None or not subagent(payload):
        return
    reason = verdict(payload)
    if reason is not None:
        deny(HOOK, reason)


if __name__ == "__main__":
    os.environ.setdefault(
        "CLAUDE_PROJECT_DIR", str(Path(__file__).resolve().parents[2])
    )
    main()
