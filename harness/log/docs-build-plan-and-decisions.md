# Docs log: build plan to complete and decisions 16–20

Branch `docs/build-plan-and-decisions` from `main` @ `d23aff9` (#80),
2026-09-24. Docs only; no code, contract or artifact changes.

## What changed

- `harness/context/audit-remediation-decisions.md`: decisions 16–20 appended
  (16 the user's extended authorization, quoted; 17 decision 15 superseded —
  no V0, scripted gates, no further training; 18 Phase 03C option A in
  local-only form, then C, B excluded; 19 narrow, droppable contract set 1.2;
  20 Stage 2 feedback outside the contract). Decision 15 is struck through
  and points at 17.
- `harness/context/build-plan-to-complete.md` (new): Wave 0 and PR-1..PR-17
  in Waves 1–6, serialization rules, "do not do", blocked-by-hard-limits,
  definition of done.
- `harness/context/audit-remediation-status.md` §0: resume order points at
  the build plan and decisions 16–20; the "ask the user about decision 15"
  step is gone (superseded by 17); the gate-hygiene paragraph is kept.
- `harness/status.toml`: still `idle`; `updated_at` and the boundaries
  summary mention decisions 16–18; the promotion line in `inactive` now
  names production serving and notes that local opt-in serving is
  authorized by decision 18.

Root corrections applied in a second commit: the architect's wave grouping
and per-PR dependencies; both relay figures kept with their sources; the
E2 wording; the status file's header (`main` @ `d23aff9`, the merge point)
and §5 item 5 now point at decisions 17–18.

## Relay spend, two records

≈ USD 146 total per `harness/context/phase-03c-stage2-handoff.md` §5;
≈ USD 121.59 for Stages 1b/1c per `harness/context/post-phase-03c-handoff.md`
§4. Decision 17 says "≈ USD 146 total" citing the former; PR-17 carries both.

## Checks

- Passed: `make preflight-fast` (the layout validator accepts the edited
  `harness/status.toml`), `make harness-check`, `git diff --check`,
  `pytest tests/contract` 106 passed (after `pnpm install --frozen-lockfile`
  in the fresh worktree; before it, the two generated-contract tests failed
  on the missing `tsc`, as documented).
- Not run: `make preflight` and the DB gates (docs-only change).
