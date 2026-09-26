# v0 worktree inventory (S0-ROOT-01, 2026-09-26)

Taken before cleanup, with `main` at `514fe31` (= tag `v0-legacy`). `git worktree list | wc -l` = 22.

`main..branch` counts the branch's own commits; they are non-zero because every PR was squash-merged. "Merged" is from the PR state, and "PR head = HEAD" confirms that nothing was committed after the merge. "Unpushed" is `git log origin/<branch>..HEAD`. No worktree held unique work, so all were removed.

| Worktree | Branch | HEAD | `git log main..<branch> --oneline \| wc -l` | Merged (PR) | PR head = HEAD | Unpushed | Dirty | Removed |
|---|---|---|---|---|---|---|---|---|
| `.` (main checkout) | main | 514fe31 | 0 | — | — | 0 | 0 | kept |
| `impl-pr14` | `feat/pr14-judge-seam` | ae11a04 | 16 | #102 merged | yes | 0 | 0 | yes |
| `agent-a1267e7378c699fa4` | `feat/pr9a-fast-backend-seam` | ed36854 | 7 | #97 merged | yes | 0 | 0 | yes |
| `agent-a19503a38242ee3d4` | `fix/r17-r5-channel-redrive` | 123954c | 7 | #92 merged | yes | 0 | 0 | yes |
| `agent-a20261934d6661034` | `feat/pr12-stateless-intake` | 2f1226d | 11 | #101 merged | yes | 0 | 0 | yes |
| `agent-a24eb6a53c854d222` | `docs/pr17-phase07-reports` | bef24ae | 14 | #106 merged | yes | 0 | 0 | yes |
| `agent-a31ad4d9d7b8f6c5e` | `fix/pr5-ops-tests` | 4d7ac3c | 6 | #93 merged | yes | 0 | 0 | yes |
| `agent-a5a8cced7893036f4` | `feat/pr10-agent-status-bar` | abb0438 | 7 | #96 merged | yes | 0 | 0 | yes |
| `agent-a688d638fdaa9ebfa` | `fix/r16-expiry-classifier` | 7f0232b | 4 | #87 merged | yes | 0 | 0 | yes |
| `agent-a7c57a1497ad5ce02` | `fix/r12-model-trace-log` | 28cba4b | 8 | #91 merged | yes | 0 | 0 | yes |
| `agent-a802225b339cae3c3` | `fix/r18-callback-evidence-pairing` | 4265cd6 | 10 | #88 merged | yes | 0 | 0 | yes |
| `agent-a858a8e4becb31aef` | `feat/pr16-phase07-contract` | 8b8e206 | 11 | #105 merged | yes | 0 | 0 | yes |
| `agent-a9217dd8373dec494` | `fix/r6-injectable-offer-ttl` | 8cf88b2 | 5 | #104 merged | yes | 0 | 0 | yes |
| `agent-a961ff41a6989f92a` | `fix/b2-8-threadpool-runtime-calls` | 6f20484 | 5 | #89 merged | yes | 0 | 0 | yes |
| `agent-aac8bb47949094b20` | `feat/pr13-slow-drives-intent` | 1819542 | 8 | #99 merged | yes | 0 | 0 | yes |
| `agent-abfd91dd5b07215e6` | `feat/pr8b-web-assistant-lines` | b244a11 | 5 | #95 merged | yes | 0 | 0 | yes |
| `agent-ad13868a2b6ef13a5` | `fix/gate-honesty-r15-g1` | f40e6b6 | 8 | #90 merged | yes | 0 | 0 | yes |
| `agent-ad3ab2dfc3a96ae37` | `feat/pr11-fast-under-temporal` | 946b684 | 4 | #98 merged | yes | 0 | 0 | yes |
| `agent-adaba0832e42a60df` | `fix/followup-web-restore-flaky` | 773322d | 3 | #103 merged | yes | 0 | 0 | yes |
| `agent-aec35921d3b098e50` | `feat/pr8a-fast-dialogue` | e552bf3 | 9 | #94 merged | yes | 0 | 0 | yes |
| `agent-af6be891d62f80fe5` | `feat/pr9b-local-fast-gateway` | 70f5ee8 | 25 | #100 merged | yes | 0 | 0 | yes |
| `phase-03c-parallel` | (detached) | ebb9635 | 0 | ancestor of main | — | — | 0 | yes |

Git-ignored v0 artefacts found in two worktrees (not in the main checkout) were moved, not deleted, to `~/Desktop/proxyloop-v0-archive/`: the Phase 03C MLX adapter (`data/experiments/phase-03c/training/cloud-run-01/train/mlx/`, 333 MB) and the local-parity runs (`data/experiments/phase-03c/local-parity/runs/`, 768 KB). They are not part of the tag.
