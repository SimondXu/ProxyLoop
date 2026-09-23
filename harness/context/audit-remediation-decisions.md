# Audit remediation: standing authorization and adopted decisions

Recorded 2026-09-22 by the root orchestrator from the user's instruction
(session `phase-03c-parallel`): fix everything the repository audit
(`docs/research/2026-09-21-repository-audit.md`) and the target
architecture proposal (`docs/research/2026-09-21-target-architecture-proposal.md`)
identified, fully autonomously — implementer → independent reviewer →
root review → `make preflight` → PR → CI → squash merge — without a
per-PR go from the user. Merge to `main` is therefore authorized for this
programme; the per-PR stop in `CLAUDE.md` is superseded for it. Still
excluded without a new user decision: real credentials, hosted spend
beyond the recorded relay budget, real external channels, deployment,
force-push, destructive operations on shared history.

## Decisions adopted (audit §8 "Recommended" and proposal §12 bold)

| # | Decision |
|---|---|
| 1 | Same-command retry is the recovery contract; the timer path never fails the run (done: P0-1, P0-3). |
| 2 | The executor owns approval consumption and terms-vs-offer comparison (done: P0-2). |
| 3 | `offer_policy` (shared policy) is the only label authority; the legacy predicate is deleted. |
| 4 | E2E = validity ∧ ¬false_completion ∧ (accept ⇒ state-verified); `reference_match` reported separately; `forged-evidence` and `multi-hazard` leave `SAFETY_FAMILIES` until Stage 4 makes them test what they name. |
| 5 | r1 artifacts are historical/superseded; no "replay" wording. |
| 6 | r5 reworded now (done: P0-4); parity-only rerun only after Stage 2. |
| 7 | Fast dialogue is product behaviour, wired with a per-turn measurement; a Judge pass sits before the deterministic gate, quality-only, never in metrics or authority. |
| 8 | Direct mode routes POSTs through `apply_command` (honours `Idempotency-Key`), in-process expiry timer, documented one-Case limit. |
| 9 | Browser projection is an allow-list. |
| 10 | The 30-minute strategy lifetime is a Slow-refresh trigger, not a session bound; `strategy.expires_at` does not gate execution. |
| 11 | One canonical `schema_version` bump (1.1) covers the planning-basis fingerprint (A-1), `ModelTrace` (A-2), the completion receipt (A-6), the canonical `ExecutionClaim`, and the materiality narrowing (A-10), with regenerated fixtures. |
| 12 | `ModelTrace` is **emitted** with a `role` field, not deleted (proposal §12.2). |
| 13 | Judge uses a second model family when a second credential exists, else the Slow family, recorded in the trace. |
| 14 | Intake is a stateless `POST /intake/proposals`. |
| 15 | Phase order per audit decision 12: V0 (frontier-only) is the target of Stages 1–3; training stays behind V0's numbers. |

## Execution order

1. P0-3b — dedup replay must not roll back `_last_transition` (this file's PR).
2. Group 2 — P0-5 content-free ids + value-level leakage scan; P0-6
   state-based verifier and Case-carried constraints; P0-7 single oracle,
   single `material_terms_hash`, single unsupported-change list; artifact
   regeneration where the artifacts are deterministic; hosted artifacts
   (r1–r5) stay frozen and are relabelled, never rewritten.
3. P1 by stage: B2-3/B2-5 Slow refresh; B1-3 manifest id; A-1/A-2/A-6/A-10
   in the 1.1 bump; projection allow-list; B2-4/E-4 direct mode via
   `apply_command`; E-5/E-6; D2-2/D2-5/D3-4; C-4.
4. P2 hygiene and the architecture-test replacement.
5. Proposal stages (intake, Fast dialogue wiring, Judge, Agent Status Bar
   rendering of `CaseContextSnapshot`) as bounded PRs, each with its own
   spec under `harness/context/`.

Every PR keeps one bounded concern, a spec under `harness/context/`, and a
log under `harness/log/`; anything that needs credentials or hosted spend
is reported instead of run.
