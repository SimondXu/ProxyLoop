# Repository audit — execution log

Contract: `harness/build/repo-audit.md`. Worktree
`.claude/worktrees/phase-03c-parallel`, branch `worktree-phase-03c-parallel`,
base `main` at `aaae134`. Read-only audit; no product code, tests, artifacts,
or `harness/status.toml` changed.

## Baseline (2026-09-21, observed in the audit worktree)

Fresh dependency install (`uv sync` runtime + ml, `pnpm install
--frozen-lockfile`), then:

| Check | Result |
|---|---|
| `make preflight` | passed, 72 s wall |
| runtime pytest | 291 passed, 33 skipped (all `PROXYLOOP_TEST_DATABASE_URL is required`) |
| ml pytest | 220 passed |
| web vitest | 47 passed (2 files); eslint, tsc, `next build` passed |
| ruff format/check, mypy (57 runtime + 35 ml files) | passed |
| contracts `--check`, TypeScript `tsc --noEmit` | passed |
| artifact drift checks 01b / 02 / 03a1 ×5 / 03b ×2 / 03c | passed |
| `validate_layout.py`, `uv lock --check` ×2, pnpm frozen offline, compileall, `docker compose config` | passed |
| `make postgres-check` (Compose `postgres-test`, tmpfs) | 24 passed |
| `make phase04d-check` / `phase04d-profile-check` | 16 passed / profile emitted |
| `make phase05a-check` (Postgres + Temporal 1.28.1) | 24 passed, 27.9 s |
| `make phase06b1-check` | 31 passed |

Compose services were started for the real-dependency gates
(`postgres`, `postgres-test`, `temporal`) and removed afterwards; no other
Compose project or container was running before or after.

The baseline is the documented state. Lanes compare against this, not
against the docs.

## Batch timeline

- Batch 1 started 2026-09-21: A (architect/Fable), B1 and B2
  (reviewer/Opus), G (explorer/Sonnet), plus the baseline run above.
- G returned (136 s, ~82K tokens): 3 Minor, 3 Note; recorded in
  `harness/code_review/repo-audit-G.md`.
- F (explorer/Sonnet) started early to use a free slot; returned (215 s,
  ~79K tokens): 1 Important, 2 Minor, 1 rejected; partial coverage noted;
  `repo-audit-F.md`.
- A returned (875 s, ~206K tokens): 2 Important, 5 Minor, 4 Note;
  `repo-audit-A.md` (written by the architect agent directly).
- D1 (reviewer/Opus) started while B1/B2 still running (3 Opus in flight).
- B1 returned (1001 s, ~234K tokens): 5 Important, 7 Minor, 11 Notes;
  root re-ran four repro scripts; `repo-audit-B1.md`. Root also ran a
  32-scenario legacy-vs-shared oracle comparison (0 disagreements), so
  B1-5 stays Important and the committed ceiling labels stand.
- B2 returned (1104 s, ~272K tokens): **1 Blocking (B2-1)**, 3 Important,
  5 Minor, 8 Notes; root re-ran three repro scripts; `repo-audit-B2.md`.
- Batch 2: C and E (reviewer/Opus) started; D1 still running.
- D1 returned (737 s, ~200K tokens): reported 1 Blocking + 7 Important;
  root re-ran `leak.py`, read the committed episodes artifact and the r2
  view builders, and downgraded D1-1 to Important (model views are
  UUID-mapped; oracle ignores ids); `repo-audit-D1.md`.
- Batch 3: D2 (reviewer/Opus) started (C, E, D2 in flight); D3 waits.
- C returned (1032 s, ~306K tokens): **1 Blocking (C-1 = B2-1 on the real
  worker)**, 3 Important, 4 Minor; root brought Compose up and re-ran
  `c2` and `c3` (identical output), tore it down; `repo-audit-C.md`.
- E returned (1068 s, ~230K tokens): 6 Important, 5 Minor; root read the
  three cited component ranges; `repo-audit-E.md`. §5 "agent or form"
  trace recorded for the synthesis.
- D3 (reviewer/Opus) started (D2, D3 in flight). A separate research agent
  (Sonnet, web only) was started at the user's request to inventory Pine
  AI's public architecture and the `19PINE-AI/TalkAct` repository for the
  synthesis; it is not an audit lane and touches no repository file.
  Its two passes are recorded in `harness/context/pine-ai-reference.md`.
- D2 returned (1002 s, ~382K tokens): reported 5 Important, 4 Minor, 4
  Notes; root read the r5 prompt builder and re-ran `q1_leak.py`, raised
  D2-1 to **Blocking (evidence claim)**; `repo-audit-D2.md`.
- D3 returned (1041 s, ~261K tokens): 3 Important, 6 Minor, 9 Notes; root
  read the committed readiness packet and re-ran two probes;
  `repo-audit-D3.md`. All ten lanes complete.
- Synthesis: `architect` (Fable, high) started on the confirmed findings,
  the Pine reference card, and the user's question ("what is wrong, what
  must change, what is the path to a runnable Pine-style demo"). First
  attempt failed on an API session limit (HTTP 429, Fable); the retry
  completed (503 s, ~165K tokens) and wrote
  `docs/research/2026-09-21-repository-audit.md` (420 lines). Root read the
  verdict, §8 decisions, and grepped for content the user did not author.
- The research agent ran a third pass verifying the user's own Pine
  sources; results appended to `harness/context/pine-ai-reference.md`.
- Next: a second `architect` run for a detailed target-architecture
  proposal (`docs/research/2026-09-21-target-architecture-proposal.md`),
  requested by the user; not part of the audit contract's outputs.
  Completed (694 s, ~275K tokens); 600 lines. Root read §12 and grepped
  for content the user did not author. It disagrees with audit decision
  11 on `ModelTrace` (emit, not delete) and says so in §12 Q2.

## Gate

Audit complete. All outputs are untracked files on branch
`worktree-phase-03c-parallel`; nothing is committed, no product code, test,
artifact, or `harness/status.toml` changed. Committing the audit, opening a
PR, and every remediation item are new user decisions (audit §8; proposal
§12).

## Finding verification

Per-finding verdicts live at the end of each `repo-audit-<lane>.md`.
Summary so far:

| Lane | Blocking | Important | Minor | Note | Rejected |
|---|---|---|---|---|---|
| G | 0 | 0 | 3 (G-1..3) | 3 | 0 |
| F | 0 | 1 (F-1) | 2 (F-2, F-3) | 2 | 1 (F-4) |
| A | 0 | 2 (A-1, A-2) | 5 (A-3..7) | 4 (A-8..11) | 0 |
| B1 | 0 (B1-1 Blocking once a non-simulator capability exists) | 5 (B1-1..5) | 7 (B1-6..12) | 11 | 0 |
| B2 | 1 (B2-1) | 3 (B2-2..4) | 5 (B2-5..9) | 8 | 0 |
| D1 | 0 (D1-1 downgraded; Blocking for Stage 1b/1c data generation) | 8 (D1-1..8) | 4 (D1-9..12) | 2 | 0 |
| C | 1 (C-1, same defect as B2-1) | 3 (C-2, C-3, C-6) | 4 (C-4, C-5, C-7, C-8) | 8 | 0 |
| E | 0 | 6 (E-1..6) | 5 (E-7..11) | 7 | 0 |
| D2 | 1 (D2-1, raised by root) | 4 (D2-2..5) | 4 (D2-6..9) | 4 | 0 |
| D3 | 0 (D3-2 Blocking for Stage 1b/1c if 03B example views are reused) | 3 (D3-1..3) | 6 (D3-4..9) | 9 | 0 |
| **Total** | **3 distinct** (B2-1/C-1 runtime recovery; D2-1/D3-3 r5 evidence; plus conditional D1-1/D3-2 for data generation) | **38** | **40** | — | **1** |

## Not audited

See `repo-audit.md` "Explicitly not audited".

## User decisions recorded (2026-09-21)

- Audit artifacts to be committed as one docs PR (`docs/repo-audit`).
- Audit decision **#1: recovery contract = same-command retry** (the
  retry the Web and Temporal already send re-drives `_execute_claim`
  regardless of `expected_revision`; the timer path never fails the run).
- Remediation starts with **Group 1** (runtime side), one bounded change
  at a time, regression test first: P0-1 claim receipt and retry (B2-1 /
  C-1, B2-2 / C-2), P0-2 executor approval ledger and terms derivation
  (B1-1, B1-2), P0-3 timer-path failure boundary (C-3), P0-8 Web failure
  surfacing (E-1, E-2, E-3). Group 2 (simulator / evaluation) waits for
  the Stage 1a session or its merge. P0-4 doc corrections are a separate
  small PR.
