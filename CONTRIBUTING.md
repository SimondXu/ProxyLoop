# Contributing to ProxyLoop

The rules for every contributor, human or agent, are in `AGENTS.md`; product intent and invariants are
in `NORTH_STAR.md`; tasks, lanes and owned paths are in `PLAN.md`. This file is only the short version.

## One task, one branch, one pull request
- Every change is a `PLAN.md` task with an id such as `S0-SYS-03`.
- Work on the branch `task/<task-id>` (lowercase), in its own worktree created from `origin/main`:
  `git worktree add ../pl-wt/<TASK-ID> -b task/<task-id> origin/main`.
- Commit messages start with `<TASK-ID>: `.
- The pull request title is `<TASK-ID>: <title>`; CI rejects any other title.
- One task is one pull request. Keep it inside the task's owned paths and size (S, M or L in `PLAN.md`).
- `main` is the last integrated state: never commit on it, force-push or rewrite its history.
- Pull requests are squash-merged by the root after CI, the fresh-context review and the reality rule pass.

## Before you open a pull request
- Run `make check` (lint, type check, tests, import contracts, docs check) and make it green.
- Paste the real output tails in the pull request; never claim a check you did not run.
- Fill in `.github/pull_request_template.md`. The pull request description is the log.

## Never commit
- `.env`, keys, relay URLs or any other secret; never copy `.env` into a worktree.
- Consumer PII, model weights, adapters, local datasets or recordings.
- Third-party code: fetch the pinned sources with `scripts/sys/fetch_external.sh` (see `third_party/README.md`).
