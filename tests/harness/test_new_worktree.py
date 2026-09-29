"""scripts/root/new_worktree.sh creates ../pl-wt/<ID> from origin/main and writes the
grant file the owned-paths hook reads."""

from __future__ import annotations

from pathlib import Path

from tests.harness.hooks_layout import Layout, git


def grant(wt: Path) -> Path:
    return Path(git(wt, "rev-parse", "--absolute-git-dir").strip()) / "pl-owned-paths"


def test_creates_the_worktree_branch_and_grant(layout: Layout) -> None:
    assert (layout.wt / ".git").is_file()
    assert git(layout.wt, "rev-parse", "--abbrev-ref", "HEAD").strip() == "task/t1"
    head = git(layout.wt, "rev-parse", "HEAD")
    assert head == git(layout.shared, "rev-parse", "origin/main")
    assert grant(layout.wt).read_text().splitlines() == [
        "src/proxyloop/kernel/**",
        "tests/kernel/**",
        "docs/one.md",
        "**/*.txt",
    ]


def test_refuses_an_existing_worktree(layout: Layout) -> None:
    before = grant(layout.wt).read_text()
    made = layout.new_worktree("T1", "other/**")
    assert made.returncode != 0
    assert "exists" in made.stderr
    assert grant(layout.wt).read_text() == before


def test_works_from_inside_a_task_worktree_too(fresh_layout: Layout) -> None:
    made = fresh_layout.script("T5", "task/t5", "a/**", cwd=fresh_layout.wt)
    assert made.returncode == 0, made.stderr
    assert (fresh_layout.plwt / "T5" / ".git").is_file()
    assert not (fresh_layout.plwt / "pl-wt").exists()


def test_rejects_bad_arguments(fresh_layout: Layout) -> None:
    for args in (
        ("T6", "task/t6"),  # no glob
        ("T6", "task/t6", "/abs/**"),
        ("T6", "task/t6", "../up/**"),
        ("T6", "task/t6", "a/../../b"),
        ("../T6", "task/t6", "a/**"),
        ("T6", "task/t6", ""),
    ):
        made = fresh_layout.script(*args)
        assert made.returncode != 0, args
        assert not (fresh_layout.plwt / "T6").exists(), args
