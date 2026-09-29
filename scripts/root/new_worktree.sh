#!/usr/bin/env bash
# Create a task worktree and its owned-paths grant (S1-ROOT-24). Run by the dispatching
# session (main root or lane lead), from the shared checkout or any worktree of it:
#
#   scripts/root/new_worktree.sh <TASK-ID> <branch> <owned-glob>...
#
# Runs `git worktree add ../pl-wt/<TASK-ID> -b <branch> origin/main` next to the shared
# checkout, then writes one repo-relative glob per line (`**` allowed) to
# `$(git -C ../pl-wt/<TASK-ID> rev-parse --git-dir)/pl-owned-paths`, which
# .claude/hooks/owned_paths.py reads. Refuses if the worktree path already exists.
set -euo pipefail

fail() {
  echo "new_worktree.sh: $*" >&2
  exit 1
}

[ "$#" -ge 3 ] || fail "usage: new_worktree.sh <TASK-ID> <branch> <owned-glob>..."
task=$1
branch=$2
shift 2

case "$task" in
  "" | */* | .* | *[!A-Za-z0-9._-]*) fail "bad task id: '$task'" ;;
esac
for glob in "$@"; do
  case "$glob" in
    "" | /* | .. | ../* | */.. | */../* | *$'\n'*) fail "bad owned glob: '$glob'" ;;
  esac
done

common="$(git rev-parse --path-format=absolute --git-common-dir)"
shared="$(dirname "$common")"
wt="$(dirname "$shared")/pl-wt/$task"
[ ! -e "$wt" ] || fail "refusing: $wt exists"

git -C "$shared" worktree add "$wt" -b "$branch" origin/main
gitdir="$(git -C "$wt" rev-parse --absolute-git-dir)"
printf '%s\n' "$@" >"$gitdir/pl-owned-paths"
echo "worktree $wt on $branch; grant $gitdir/pl-owned-paths:"
sed 's/^/  /' "$gitdir/pl-owned-paths"
