"""scripts/root/merge_gate.sh against fake `gh`, a recording `git` and a stub `make`.

Every test builds a throwaway repository in tmp_path: a bare "origin" (the GitHub
side, with refs/pull/<n>/head) and a clone the script runs in. The fake `gh` answers
from a JSON state file (its --jq filters run through the real jq) and simulates a
squash merge and update-branch on the bare origin. The fake `git` records its argv and
executes the real git. No real PR, remote or network is touched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "root" / "merge_gate.sh"
REAL_GIT = shutil.which("git")
JQ = shutil.which("jq")
BASH = shutil.which("bash")
REQUIRED = ("check", "task-id", "web", "shellcheck")

pytestmark = pytest.mark.skipif(
    REAL_GIT is None or JQ is None or BASH is None,
    reason="needs git, jq and bash on PATH",
)

FAKE_GH = r"""
import json, os, subprocess, sys
d = os.environ["FAKE_DIR"]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(["gh", *sys.argv[1:]]) + "\n")
state_path = os.path.join(d, "gh_state.json")
with open(state_path) as f:
    state = json.load(f)
args = sys.argv[1:]

def opt(name):
    return args[args.index(name) + 1] if name in args else None

if args[0] == "run":
    if state.get("runs") is None:
        sys.exit("gh run list unavailable")
    assert args[1] == "list" and opt("--workflow") == "ci.yml", args
    assert opt("--event") == "push" and "--branch" not in args, args
    runs = [r for r in state["runs"] if r["headSha"] == opt("--commit")]
    out = subprocess.run([state["jq"], "-r", opt("--jq")],
                         input=json.dumps(runs[: int(opt("--limit"))]),
                         capture_output=True, text=True, check=True).stdout
    sys.stdout.write(out)
    sys.exit(0)
assert args[0] == "pr", args
verb, n = args[1], args[2]
pr = state["prs"][n]

def g(*a):
    return subprocess.run([state["git"], "-C", state["origin"], *a], check=True,
                          capture_output=True, text=True).stdout.strip()

if verb == "view":
    data = {k: pr.get(k) for k in opt("--json").split(",")}
    out = subprocess.run([state["jq"], "-r", opt("--jq")], input=json.dumps(data),
                         capture_output=True, text=True, check=True).stdout
    sys.stdout.write(out)
    sys.exit(0)
if verb == "merge":
    if {"--admin", "--auto", "--delete-branch", "-d"} & set(args):
        sys.exit("forbidden flag")
    if opt("--match-head-commit") != pr["headRefOid"]:
        sys.exit("head moved")
    if not pr.get("merge_noop"):
        tree = g("merge-tree", "--write-tree", "refs/heads/main", pr["headRefOid"])
        oid = g("commit-tree", tree, "-p", "refs/heads/main", "-m", "squash #" + n)
        g("update-ref", "refs/heads/main", oid)
        pr["state"], pr["mergeCommit"] = "MERGED", {"oid": oid}
elif verb == "update-branch":
    head = pr["headRefOid"]
    tree = g("merge-tree", "--write-tree", head, "refs/heads/main")
    oid = g("commit-tree", tree, "-p", head, "-p", "refs/heads/main", "-m", "update")
    g("update-ref", "refs/pull/" + n + "/head", oid)
    pr["headRefOid"], pr["statusCheckRollup"] = oid, []
with open(state_path, "w") as f:
    json.dump(state, f)
"""

FAKE_GIT = r"""
import json, os, sys
with open(os.path.join(os.environ["FAKE_DIR"], "calls.jsonl"), "a") as f:
    f.write(json.dumps(["git", *sys.argv[1:]]) + "\n")
real = os.environ["REAL_GIT"]
os.execv(real, [real, *sys.argv[1:]])
"""

FAKE_MAKE = r"""
import json, os, sys
d = os.environ["FAKE_DIR"]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    hf = "HF_HUB_OFFLINE=" + os.environ.get("HF_HUB_OFFLINE", "")
    f.write(json.dumps(["make", *sys.argv[1:], hf]) + "\n")
print("stub make", *sys.argv[1:])
with open(os.path.join(d, "gh_state.json")) as f:
    sys.exit(json.load(f).get("make_exit", {}).get(sys.argv[1], 0))
"""


def rollup(**verdicts: str) -> list[dict[str, Any]]:
    """GREEN for every required context, overridden per context by name."""
    out: list[dict[str, Any]] = []
    for name in REQUIRED:
        v = verdicts.get(name.replace("-", "_"), "SUCCESS")
        if v == "MISSING":
            continue
        if v == "IN_PROGRESS":
            out.append({"__typename": "CheckRun", "name": name, "status": v})
        elif v == "STATUS_FAILURE":
            out.append(
                {"__typename": "StatusContext", "context": name, "state": "FAILURE"}
            )
        else:
            out.append(
                {
                    "__typename": "CheckRun",
                    "name": name,
                    "status": "COMPLETED",
                    "conclusion": v,
                }
            )
    return out


class Gate:
    def __init__(self, tmp: Path) -> None:
        assert REAL_GIT and JQ
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.origin = tmp / "origin.git"
        self.work = tmp / "work"
        for name, body in (("gh", FAKE_GH), ("git", FAKE_GIT), ("make", FAKE_MAKE)):
            path = self.bin / name
            path.write_text(f"#!{sys.executable}\n{body}")
            path.chmod(0o755)
        self.env = {
            **{
                k: v
                for k, v in os.environ.items()
                if not k.startswith(("MAKE", "GIT_"))
            },
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DIR": str(tmp),
            "REAL_GIT": REAL_GIT,
            "MAKE": str(self.bin / "make"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
        self.state: dict[str, Any] = {
            "git": REAL_GIT,
            "jq": JQ,
            "origin": str(self.origin),
            "prs": {},
        }
        self.git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=tmp)
        self.git("init", "-q", "-b", "main", str(self.work), cwd=tmp)
        self.git("remote", "add", "origin", str(self.origin))
        self.base = self.commit(
            None,
            {
                "a.txt": "a\n",
                "b.txt": "b\n",
                "apps/web/x.ts": "x\n",
                ".gitignore": "*.log\n",
            },
        )
        self.git("push", "-q", "origin", f"{self.base}:refs/heads/main")
        self.git("fetch", "-q", "origin")
        self.save()

    def git(self, *args: str, cwd: Path | None = None) -> str:
        assert REAL_GIT
        out = subprocess.run(
            [REAL_GIT, *args],
            cwd=cwd or self.work,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()

    def commit(self, parent: str | None, files: dict[str, str]) -> str:
        if parent:
            self.git("checkout", "-q", "--detach", parent)
        for rel, text in files.items():
            (self.work / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.work / rel).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c")
        return self.git("rev-parse", "HEAD")

    def main_sha(self) -> str:
        return self.git("--git-dir", str(self.origin), "rev-parse", "refs/heads/main")

    def advance_main(self, files: dict[str, str]) -> str:
        sha = self.commit(self.main_sha(), files)
        self.git("push", "-q", "origin", f"{sha}:refs/heads/main")
        return sha

    def add_pr(
        self,
        n: int,
        files: dict[str, str],
        parent: str | None = None,
        checks: list[dict[str, Any]] | None = None,
        **extra: Any,
    ) -> str:
        sha = self.commit(parent or self.main_sha(), files)
        self.git("push", "-q", "origin", f"{sha}:refs/pull/{n}/head")
        self.state["prs"][str(n)] = {
            "headRefOid": sha,
            "state": "OPEN",
            "baseRefName": "main",
            "statusCheckRollup": rollup() if checks is None else checks,
            "mergeCommit": None,
            **extra,
        }
        self.save()
        return sha

    def save(self) -> None:
        (self.tmp / "gh_state.json").write_text(json.dumps(self.state))
        (self.tmp / "calls.jsonl").write_text("")

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        assert BASH
        return subprocess.run(
            [BASH, str(SCRIPT), *args],
            cwd=self.work,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def calls(self) -> list[list[str]]:
        text = (self.tmp / "calls.jsonl").read_text()
        return [json.loads(line) for line in text.splitlines()]

    def mutating(self) -> list[list[str]]:
        bad_git = {"merge", "worktree", "push", "commit", "update-ref", "pull", "reset"}
        return [
            c
            for c in self.calls()
            if (c[0] == "gh" and c[1:3] in (["pr", "merge"], ["pr", "update-branch"]))
            or (c[0] == "git" and bad_git & set(c))
            or c[0] == "make"
        ]


def last(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout.strip().splitlines()[-1]


@pytest.fixture
def gate(tmp_path: Path) -> Gate:
    return Gate(tmp_path)


# --- check -------------------------------------------------------------------------


def test_check_green_and_contained_is_ready(gate: Gate) -> None:
    head = gate.add_pr(7, {"a.txt": "pr\n"})
    r = gate.run("check", "7")
    assert r.returncode == 0, r.stderr
    base = gate.main_sha()
    assert r.stdout.strip() == (
        f"PR 7 head={head[:7]} base={base[:7]} checks=GREEN main=CONTAINED ready=yes"
        " main_ci=unknown"
    )
    assert gate.mutating() == []


def test_check_missing_or_running_context_is_pending(gate: Gate) -> None:
    gate.add_pr(7, {"a.txt": "pr\n"}, checks=rollup(web="MISSING", check="IN_PROGRESS"))
    r = gate.run("check", "7")
    assert r.returncode == 0, r.stderr
    assert "checks=PENDING main=CONTAINED ready=no" in last(r)


def test_check_failed_names_every_failed_context(gate: Gate) -> None:
    checks = rollup(shellcheck="FAILURE", task_id="STATUS_FAILURE", web="IN_PROGRESS")
    gate.add_pr(7, {"a.txt": "pr\n"}, checks=checks)
    r = gate.run("check", "7")
    assert "checks=FAILED:task-id,shellcheck " in last(r)
    assert " ready=no main_ci=" in last(r)


def test_check_disjoint_when_main_moved_on_other_files(gate: Gate) -> None:
    gate.add_pr(7, {"a.txt": "pr\n"})
    gate.advance_main({"b.txt": "main\n"})
    r = gate.run("check", "7")
    assert "checks=GREEN main=DISJOINT ready=no" in last(r)


def test_check_overlap_names_the_shared_paths(gate: Gate) -> None:
    gate.add_pr(7, {"a.txt": "pr\n", "apps/web/x.ts": "pr\n", "c.txt": "c\n"})
    gate.advance_main({"a.txt": "main\n", "apps/web/x.ts": "main\n", "b.txt": "m\n"})
    r = gate.run("check", "7")
    assert "main=OVERLAP:a.txt,apps/web/x.ts ready=no" in last(r)


MAIN_URL = "https://github.com/o/r/actions/runs/1"


def main_ci_run(
    status: str, conclusion: str | None, sha: str = "TIP"
) -> list[dict[str, Any]]:
    """One ci.yml push run; sha "TIP" means origin/main's current tip."""
    return [
        {"status": status, "conclusion": conclusion, "url": MAIN_URL, "headSha": sha}
    ]


def set_runs(gate: Gate, runs: list[dict[str, Any]] | None) -> None:
    tip = gate.main_sha()
    gate.state["runs"] = (
        None
        if runs is None
        else [{**r, "headSha": r["headSha"].replace("TIP", tip)} for r in runs]
    )
    gate.save()


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        (main_ci_run("completed", "success"), "success"),
        (main_ci_run("in_progress", ""), "pending"),
        (main_ci_run("completed", "cancelled"), "unknown"),
        ([], "pending"),  # no run for the tip yet
        (None, "unknown"),  # gh run list itself fails
    ],
    ids=["success", "pending", "cancelled", "no-run-for-tip", "gh-fails"],
)
def test_check_reports_main_ci_without_a_warning(
    gate: Gate, runs: list[dict[str, Any]] | None, expected: str
) -> None:
    gate.add_pr(7, {"a.txt": "pr\n"})
    set_runs(gate, runs)
    r = gate.run("check", "7")
    assert r.returncode == 0, r.stderr
    assert last(r).endswith(f"ready=yes main_ci={expected}")
    assert "WARNING" not in r.stdout


def test_check_warns_when_main_ci_is_red_but_stays_ready(gate: Gate) -> None:
    gate.add_pr(7, {"a.txt": "pr\n"})
    set_runs(gate, main_ci_run("completed", "failure"))
    r = gate.run("check", "7")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert lines[-2] == f"WARNING: main's full check is red ({MAIN_URL})"
    assert lines[-1].endswith("ready=yes main_ci=failure")
    assert gate.mutating() == []


def test_check_ignores_a_stale_failed_run_for_an_older_sha(gate: Gate) -> None:
    stale = main_ci_run("completed", "failure", sha=gate.base)
    gate.advance_main({"b.txt": "main\n"})
    gate.add_pr(7, {"a.txt": "pr\n"})
    # A stale red run for an older sha, and nothing for the tip yet.
    set_runs(gate, stale)
    r = gate.run("check", "7")
    assert r.returncode == 0, r.stderr
    assert "WARNING" not in r.stdout
    assert last(r).endswith("main_ci=pending")
    # The tip's own green run wins over the older red one, whatever the order.
    set_runs(gate, main_ci_run("completed", "success") + stale)
    r = gate.run("check", "7")
    assert "WARNING" not in r.stdout
    assert last(r).endswith("main_ci=success")
    # The tip's own red run warns.
    set_runs(
        gate,
        main_ci_run("completed", "failure")
        + main_ci_run("completed", "success", gate.base),
    )
    r = gate.run("check", "7")
    assert "WARNING: main's full check is red" in r.stdout
    assert last(r).endswith("main_ci=failure")
    call = next(c for c in gate.calls() if c[:2] == ["gh", "run"])
    assert call[call.index("--commit") + 1] == gate.main_sha()


# --- merge -------------------------------------------------------------------------


def test_merge_squashes_on_the_exact_head_and_confirms_merged(gate: Gate) -> None:
    head = gate.add_pr(7, {"a.txt": "pr\n"})
    r = gate.run("merge", "7")
    assert r.returncode == 0, r.stdout + r.stderr
    assert last(r) == f"MERGED 7 -> {gate.main_sha()[:7]}"
    assert "pull --ff-only" in r.stdout  # the shared checkout is never pulled
    merges = [c for c in gate.calls() if c[:3] == ["gh", "pr", "merge"]]
    assert merges == [
        ["gh", "pr", "merge", "7", "--squash", "--match-head-commit", head]
    ]
    assert not any(c[0] == "git" and "pull" in c for c in gate.calls())


@pytest.mark.parametrize(
    "checks",
    [rollup(web="MISSING"), rollup(check="FAILURE")],
    ids=["pending", "failed"],
)
def test_merge_refuses_when_checks_are_not_green(
    gate: Gate, checks: list[dict[str, Any]]
) -> None:
    gate.add_pr(7, {"a.txt": "pr\n"}, checks=checks)
    r = gate.run("merge", "7")
    assert r.returncode == 1
    assert last(r).startswith("MERGE REFUSED 7: checks=")
    assert gate.mutating() == []


def test_merge_refuses_overlap(gate: Gate) -> None:
    gate.add_pr(7, {"a.txt": "pr\n"})
    gate.advance_main({"a.txt": "main\n"})
    r = gate.run("merge", "7", "--allow-disjoint")
    assert r.returncode == 1
    assert last(r).startswith("MERGE REFUSED 7: main=OVERLAP:a.txt")
    assert gate.mutating() == []


def test_merge_refuses_disjoint_without_the_flag_and_merges_with_it(gate: Gate) -> None:
    head = gate.add_pr(7, {"a.txt": "pr\n"})
    gate.advance_main({"b.txt": "main\n"})
    r = gate.run("merge", "7")
    assert r.returncode == 1
    assert "DISJOINT" in last(r) and last(r).startswith("MERGE REFUSED 7:")
    assert gate.mutating() == []

    r = gate.run("merge", "7", "--allow-disjoint")
    assert r.returncode == 0, r.stdout + r.stderr
    assert last(r) == f"MERGED 7 -> {gate.main_sha()[:7]}"
    assert [
        "gh",
        "pr",
        "merge",
        "7",
        "--squash",
        "--match-head-commit",
        head,
    ] in gate.calls()


def test_merge_fails_when_the_pr_is_not_merged_afterwards(gate: Gate) -> None:
    gate.add_pr(7, {"a.txt": "pr\n"}, merge_noop=True)
    r = gate.run("merge", "7")
    assert r.returncode == 1
    assert last(r) == "MERGE FAILED 7: PR 7 is OPEN after gh pr merge, not MERGED"


# --- update ------------------------------------------------------------------------


def test_update_prints_the_new_head(gate: Gate) -> None:
    old = gate.add_pr(7, {"a.txt": "pr\n"})
    gate.advance_main({"b.txt": "main\n"})
    r = gate.run("update", "7")
    assert r.returncode == 0, r.stderr
    new = json.loads((gate.tmp / "gh_state.json").read_text())["prs"]["7"]["headRefOid"]
    assert new != old
    assert last(r).startswith(f"UPDATED 7 head={new} (was {old[:7]})")
    assert ["gh", "pr", "update-branch", "7"] in gate.calls()


# --- batch -------------------------------------------------------------------------


def test_batch_tests_the_merged_tree_then_merges_each_head(gate: Gate) -> None:
    h1 = gate.add_pr(1, {"a.txt": "one\n"})
    h2 = gate.add_pr(2, {"apps/web/x.ts": "two\n"}, parent=gate.base)
    r = gate.run("batch", "1", "2")
    assert r.returncode == 0, r.stdout + r.stderr
    tree = gate.git(
        "--git-dir", str(gate.origin), "rev-parse", "refs/heads/main^{tree}"
    )
    assert last(r).startswith(f"BATCH OK tree={tree[:7]} merged=1->")
    assert last(r).endswith("worktree=removed")
    makes = [c for c in gate.calls() if c[0] == "make"]
    assert makes == [
        ["make", "check", "HF_HUB_OFFLINE=1"],
        ["make", "web-test", "HF_HUB_OFFLINE=1"],
    ]
    lines = r.stdout.splitlines()
    assert any(ln.startswith("make check: PASS (log: ") for ln in lines)
    assert "stub make" not in r.stdout  # make output goes to the log only
    merges = [c for c in gate.calls() if c[:3] == ["gh", "pr", "merge"]]
    assert [m[3] for m in merges] == ["1", "2"]
    assert [m[-1] for m in merges] == [h1, h2]
    assert not list((gate.tmp / "pl-wt").glob("ROOT-BATCH-*"))
    remove = [c for c in gate.calls() if c[:3] == ["git", "worktree", "remove"]]
    assert remove and "--force" not in remove[0]


def test_batch_without_web_paths_skips_web_test(gate: Gate) -> None:
    gate.add_pr(1, {"a.txt": "one\n"})
    gate.add_pr(2, {"b.txt": "two\n"}, parent=gate.base)
    r = gate.run("batch", "1", "2")
    assert r.returncode == 0, r.stdout + r.stderr
    assert [c[1] for c in gate.calls() if c[0] == "make"] == ["check"]


def test_batch_refuses_overlapping_file_sets(gate: Gate) -> None:
    gate.add_pr(1, {"a.txt": "one\n"})
    gate.add_pr(2, {"a.txt": "two\n", "b.txt": "two\n"}, parent=gate.base)
    r = gate.run("batch", "1", "2")
    assert r.returncode == 1
    assert "overlaps an earlier PR in the batch on: a.txt" in last(r)
    assert gate.mutating() == []


def test_batch_refuses_a_pr_that_is_not_green(gate: Gate) -> None:
    gate.add_pr(1, {"a.txt": "one\n"})
    gate.add_pr(2, {"b.txt": "two\n"}, parent=gate.base, checks=rollup(web="MISSING"))
    r = gate.run("batch", "1", "2")
    assert r.returncode == 1
    assert "PR 2 checks=PENDING" in last(r)
    assert gate.mutating() == []


def test_batch_conflict_aborts_and_removes_the_worktree(gate: Gate) -> None:
    gate.add_pr(1, {"a.txt": "one\n"})
    gate.advance_main({"a.txt": "main\n"})
    r = gate.run("batch", "1")
    assert r.returncode == 1
    assert "PR 1 does not merge cleanly" in last(r)
    assert "merged=none; not merged=1; worktree=removed" in last(r)
    assert not any(c[:3] == ["gh", "pr", "merge"] for c in gate.calls())
    assert not any(c[0] == "make" for c in gate.calls())
    assert not list((gate.tmp / "pl-wt").glob("ROOT-BATCH-*"))


def test_batch_make_check_failure_merges_nothing_and_keeps_the_worktree(
    gate: Gate,
) -> None:
    gate.add_pr(1, {"a.txt": "one\n"})
    gate.state["make_exit"] = {"check": 2}
    gate.save()
    before = gate.main_sha()
    r = gate.run("batch", "1")
    assert r.returncode == 1
    assert any(ln.startswith("make check: FAIL (log: ") for ln in r.stdout.splitlines())
    assert "make check failed; merged=none; not merged=1; worktree=kept: " in last(r)
    assert not any(c[:3] == ["gh", "pr", "merge"] for c in gate.calls())
    assert gate.main_sha() == before
    kept = list((gate.tmp / "pl-wt").glob("ROOT-BATCH-*"))
    assert len(kept) == 1
    assert "stub make check" in (kept[0] / ".batch-logs" / "make-check.log").read_text()


# --- dry-run -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "args", [("merge", "1"), ("update", "1"), ("batch", "1", "2")], ids=lambda a: a[0]
)
def test_dry_run_changes_nothing(gate: Gate, args: tuple[str, ...]) -> None:
    head = gate.add_pr(1, {"a.txt": "one\n"})
    gate.add_pr(2, {"apps/web/x.ts": "two\n"}, parent=gate.base)
    before = gate.main_sha()
    r = gate.run(*args, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert last(r).startswith(f"DRY-RUN {args[0]} ")
    assert last(r).endswith("nothing changed")
    assert gate.mutating() == []
    assert gate.main_sha() == before
    state = json.loads((gate.tmp / "gh_state.json").read_text())
    assert state["prs"]["1"]["headRefOid"] == head
    assert not (gate.tmp / "pl-wt").exists()
    if args[0] != "update":
        assert f"--match-head-commit {head}" in r.stdout


def test_usage_errors_exit_2(gate: Gate) -> None:
    assert gate.run().returncode == 2
    assert gate.run("check", "abc").returncode == 2
    assert gate.run("update", "1", "--allow-disjoint").returncode == 2
    assert gate.run("merge", "1", "2").returncode == 2
    assert gate.calls() == []
