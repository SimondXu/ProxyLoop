"""PreToolUse(Bash) hook: deny recursive deletes of data/, external/, a checkout root
or the v0 archive, and any `git clean -d/-x/-X/-f`. Stdlib only; allows on bad input."""

import fnmatch
import json
import os
import re
import shlex
import sys
from pathlib import Path

ARCHIVE = Path.home() / "Desktop" / "proxyloop-v0-archive"
PROTECTED_DIRS = ("data", "external")
ROOT_LITERALS = {".", "./", "*", "./*"}
WRAPPERS = {"sudo", "command", "exec", "nohup", "time", "env", "xargs"}
REASON = (
    "Blocked by .claude/hooks/block_destructive.py: recursive delete or git clean on "
    "data/, external/, a repo root or the v0 archive. Do not delete: remove tracked "
    "files with `git rm`, move untracked files to ~/Desktop/proxyloop-v0-archive/, "
    "and tell the user what you moved."
)


def hits(part: str) -> bool:
    return any(fnmatch.fnmatch(name, part) for name in PROTECTED_DIRS)


def protected(target: str, cwd: str) -> bool:
    t = os.path.expandvars(os.path.expanduser(target))
    if t in ROOT_LITERALS:
        return True
    if not os.path.isabs(t):
        if hits(t.removeprefix("./").split("/", 1)[0]):
            return True
        t = os.path.join(cwd, t)
    p = Path(os.path.normpath(t))
    if p == ARCHIVE or ARCHIVE in p.parents:
        return True
    return any(
        (a / ".git").exists() and (a == p or hits(p.relative_to(a).parts[0]))
        for a in (p, *p.parents)
    )


def targets(words: list[str]) -> list[str] | None:
    """The paths a segment would delete recursively, or None if it deletes nothing."""
    while words and (words[0] in WRAPPERS or ("=" in words[0] and words[0][0] != "-")):
        wrapper = words.pop(0) in WRAPPERS
        while wrapper and words and words[0].startswith("-"):
            words.pop(0)
    if words[:2] == ["uv", "run"]:
        words = words[2:]
    if not words:
        return None
    cmd, args = os.path.basename(words[0]), words[1:]
    if cmd == "rm":
        end = args.index("--") if "--" in args else len(args)
        flags = [a for a in args[:end] if a[:1] == "-"]
        recursive = "--recursive" in flags or any(
            f[1] != "-" and set(f) & {"r", "R"} for f in flags if len(f) > 1
        )
        return [a for a in args if a not in flags and a != "--"] if recursive else None
    if cmd == "find":
        execs_rm = any(
            a in ("-exec", "-execdir") and args[i + 1 : i + 2] == ["rm"]
            for i, a in enumerate(args)
        )
        end = next((i for i, a in enumerate(args) if a[:1] in "-(!"), len(args))
        return (args[:end] or ["."]) if "-delete" in args or execs_rm else None
    if cmd.startswith("python") and "-c" in args[:-1]:
        code = args[args.index("-c") + 1]
        return re.findall(r"""['"]([^'"]*)['"]""", code) if "rmtree" in code else None
    if cmd in ("bash", "sh", "zsh") and "-c" in args[:-1]:
        return split_segments(args[args.index("-c") + 1]) or None
    if cmd == "git":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
        rest = args[i + 1 :] if args[i : i + 1] == ["clean"] else []
        short = "".join(a[1:] for a in rest if a[:1] == "-" and a[:2] != "--")
        if "--force" in rest or set(short) & set("dxXf"):
            return ["."]  # "." is a root literal: every destructive git clean is denied
    return None


def split_segments(command: str) -> list[str]:
    flat = command.replace("\\\n", " ").replace("\n", ";")
    lexer = shlex.shlex(flat, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    found: list[str] = []
    segment: list[str] = []
    for word in [*lexer, ";"]:
        if all(c in "();<>|&" for c in word):
            found += targets(segment) or []
            segment = []
        else:
            segment.append(word)
    return found


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
        command = payload["tool_input"]["command"]
        cwd = str(payload.get("cwd") or os.getcwd())
        found = split_segments(command) if isinstance(command, str) else []
    except Exception:  # malformed hook input never blocks unrelated work
        return
    if any(protected(t, cwd) for t in found):
        out = {"hookEventName": "PreToolUse", "permissionDecision": "deny"}
        out["permissionDecisionReason"] = REASON
        print(json.dumps({"hookSpecificOutput": out}))


if __name__ == "__main__":
    os.environ.setdefault("CLAUDE_PROJECT_DIR", str(Path(__file__).resolve().parents[2]))
    main()
