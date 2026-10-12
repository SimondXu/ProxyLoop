# Implementer brief (the session sends this to one `implementer`)

Before sending: the worktree exists (`scripts/root/new_worktree.sh <ID> task/<id> <owned globs…>`), the owned paths cover every file the task must touch, and no two lines contradict each other. Pass `model: opus` for Tier C work. Put every grant in the first brief; a grant sent later by message gets blocked.

```text
BRIEF — <ID>: <title>
Worktree: ../pl-wt/<ID>   branch task/<id>   from origin/main@<sha>
Goal: <one or two sentences; the trajectory step it unblocks and the run id that shows the block, if on the session path>
Owned paths: <globs>
Read first: <≤ 5 files>
Acceptance: <observable criteria; which test proves each; model-touching ones are "needs live run: <command>">
Check: make check-fast 2>&1 | tail -40   (full make check if concurrency/fences or serial tests)
Do not touch: <frozen interfaces and paths outside the grant>
Size: S ≤ 300 / M ≤ 700 changed lines excluding tests
```
