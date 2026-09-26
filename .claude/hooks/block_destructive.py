"""PreToolUse(Bash) hook: deny recursive deletes of data/, external/, a checkout root,
the project dir, the v0 archive or an ancestor of either, and any destructive
`git clean`. Stdlib only, Python 3.9+; malformed hook JSON is allowed."""

from __future__ import annotations

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
REASON = (
    "Blocked by .claude/hooks/block_destructive.py: recursive delete or git clean on "
    "data/, external/, a repo root or the v0 archive. Do not delete: remove tracked "
    "files with `git rm`, move untracked files to ~/Desktop/proxyloop-v0-archive/, "
    "and tell the user what you moved."
)


def expand(word: str) -> str:
    return os.path.expandvars(os.path.expanduser(word))


def hits(part: str) -> bool:
    return any(fnmatch.fnmatch(name, part) for name in PROTECTED_DIRS)


def protected(target: str, cwd: str) -> bool:
    t = expand(target)
    if t in ROOT_LITERALS:
        return True
    if not os.path.isabs(t):
        if hits((t[2:] if t.startswith("./") else t).split("/", 1)[0]):
            return True
        t = os.path.join(cwd, t)
    p = Path(os.path.normpath(t))
    project = Path(os.path.normpath(expand("$CLAUDE_PROJECT_DIR")))
    if ARCHIVE in p.parents or any(
        p == x or p in x.parents for x in (ARCHIVE, project)
    ):
        return True
    return any(
        (a / ".git").exists() and (a == p or hits(p.relative_to(a).parts[0]))
        for a in (p, *p.parents)
    )


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


def delete_targets(cmd: str, args: list[str]) -> list[str]:
    """The paths a simple command deletes recursively ([] if none)."""
    if cmd == "rm":
        end = args.index("--") if "--" in args else len(args)
        flags = [a for a in args[:end] if a[:1] == "-" and len(a) > 1]
        recursive = "--recursive" in flags or any(
            f[1] != "-" and set(f) & {"r", "R"} for f in flags
        )
        return [a for a in args if a not in flags and a != "--"] if recursive else []
    if cmd == "find":
        execs_rm = any(
            a in ("-exec", "-execdir") and args[i + 1 : i + 2] == ["rm"]
            for i, a in enumerate(args)
        )
        end = next((i for i, a in enumerate(args) if a[:1] in "-(!"), len(args))
        return (args[:end] or ["."]) if "-delete" in args or execs_rm else []
    if cmd.startswith("python") and "-c" in args[:-1]:
        code = args[args.index("-c") + 1]
        return re.findall(r"""['"]([^'"]*)['"]""", code) if "rmtree" in code else []
    return []


def git_clean(args: list[str]) -> bool:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    rest = args[i + 1 :] if args[i : i + 1] == ["clean"] else []
    short = "".join(a[1:] for a in rest if a[:1] == "-" and a[:2] != "--")
    return "--force" in rest or bool(set(short) & set("dxXf"))


def raw_scan(command: str) -> bool:
    """Fallback for text shlex cannot parse: deny anything that looks destructive."""
    for piece in re.split(r"[;&|\n]", command):
        deletes = re.search(
            r"(?<!git )\brm\b.*(?<!\S)(-[A-Za-z]*[rR]|--recursive)", piece
        ) or re.search(r"\bfind\b.*\s-(delete|exec(dir)?\s+rm)\b", piece)
        if deletes and re.search(r"data|external|archive|[.*~/]", piece):
            return True
        if re.search(r"\bgit\b.*\bclean\b.*(?<!\S)(-[A-Za-z]*[dxXf]|--force)", piece):
            return True
    return False


def blocked(command: str, cwd: str) -> bool:
    flat = command.replace("\\\n", " ").replace("\n", ";")
    lexer = shlex.shlex(flat, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""  # a `#` must never hide the lines after it
    try:
        words = list(lexer)
    except ValueError:
        return raw_scan(command)
    segment: list[str] = []
    for word in [*words, ";"]:
        if not all(c in "();<>|&" for c in word):
            segment.append(word)
            continue
        seg, segment = strip_wrappers(segment), []
        if not seg:
            continue
        cmd, args = os.path.basename(seg[0]), seg[1:]
        if cmd == "cd":
            dest = [a for a in args if a[:1] != "-"]
            cwd = os.path.join(cwd, expand(dest[0]) if dest else str(Path.home()))
        elif cmd in SHELLS:
            c = next(
                (i for i, a in enumerate(args) if re.fullmatch(r"-\w*c\w*", a)), -1
            )
            if 0 <= c < len(args) - 1 and blocked(args[c + 1], cwd):
                return True
        elif (cmd == "git" and git_clean(args)) or any(
            protected(t, cwd) for t in delete_targets(cmd, args)
        ):
            return True
    return False


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
        command = payload["tool_input"]["command"]
        cwd = str(payload.get("cwd") or os.getcwd())
    except Exception:  # malformed hook JSON never blocks unrelated work
        return
    if isinstance(command, str) and blocked(command, cwd):
        out = {"hookEventName": "PreToolUse", "permissionDecision": "deny"}
        out["permissionDecisionReason"] = REASON
        print(json.dumps({"hookSpecificOutput": out}))


if __name__ == "__main__":
    os.environ.setdefault(
        "CLAUDE_PROJECT_DIR", str(Path(__file__).resolve().parents[2])
    )
    main()
