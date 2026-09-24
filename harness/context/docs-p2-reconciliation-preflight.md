# Docs: P2 reconciliation batch (A-7d, A-7e, A-7g, G-1, check-target docs)

Bounded P2 hygiene change from `harness/context/audit-remediation-status.md`
§4. Branch `docs/p2-reconciliation` from `origin/main` @ `5bedcce`.

## Items

- **A-7d** (`harness/code_review/repo-audit-A.md` §A-7d): revision
  vocabulary. `docs/architecture.md` uses `version`/`case_version`/
  `fact_ledger_version` and "optimistic versions" where the contracts use
  `revision`, `case_revision`, `fact_ledger_revision`. Follow `CONTEXT.md`
  (Entity Revision vs Contract Schema Version).
- **A-7e** (§A-7e): `docs/architecture.md` says `Case` has an owner; the
  contract has `consumer_id` and no owner field.
- **A-7g** (§A-7g): `docs/architecture.md` implies 13 contracts; the
  registry `CANONICAL_MODELS` holds more and a test freezes the set.
- **G-1 stronger form** (`repo-audit-G.md` §G-1): document exactly what
  `make preflight` runs, which DB/Temporal tests it skips, the
  real-dependency gates and their variables, and the serial-run rule. No
  Makefile behaviour change.
- **Programme addition**: `docs/development.md` says every `*-check` target
  "replays committed reports"; correct per target and list
  `baselines-historical-check`, `hosted-rescore`, `hosted-rescore-check`,
  `negotiation-check`, `phase03c-rescore-check`.
- **Programme addition**:
  `tests/contract/test_phase_03a1_hosted_rerun_architecture.py` matches the
  old script name by substring; pin `hosted-rerun-check: hosted-rescore-check`
  exactly.

## Out of scope

- A-7f (verifier outcomes `continue`/`needs_user`): needs a code or wording
  decision.
- `AGENTS.md` semantics, the Makefile, any code under `runtime/` or `ml/`.
- Describing the `phase03c-*` checks other than `phase03c-rescore-check`, and
  `hosted-rerun-source-check`.

## Acceptance

1. Every changed doc statement is checked against code, the Makefile, CI, or
   a command run, and the check is cited in
   `harness/log/docs-p2-reconciliation.md`.
2. The hosted-rerun test fails if `hosted-rerun-check` stops depending on
   `hosted-rescore-check`, if that target's recipe changes, or if
   `hosted-rerun-check` leaves the `test:` prerequisites.
3. `make lint` and `make preflight-fast` pass; the touched test passes.
