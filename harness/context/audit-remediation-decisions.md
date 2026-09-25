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
| 15 | ~~Phase order per audit decision 12: V0 (frontier-only) is the target of Stages 1–3; training stays behind V0's numbers.~~ Superseded by decision 17 (2026-09-24). |

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

## Decisions adopted 2026-09-24 (build to complete)

Recorded 2026-09-24 by the root orchestrator. Decisions 16–18 follow the
user's instruction quoted in 16; 19–21 are root decisions taken under it.
The plan they drive is `harness/context/build-plan-to-complete.md`.

| # | Decision | Reason |
|---|---|---|
| 16 | **Extended authorization** (user, 2026-09-24): "全部按照你的计划去执行 只要完成这个项目全部building就好了 然后每做一步记得更新对应的docs 遇到不确定的问题可以起一个subagent来对话进行分享建议讨论再做决定". The root carries the plan to a complete build, decides open questions after consulting a subagent (`architect` or `reviewer`) and records each decision here; every PR updates the docs it affects. Hard limits unchanged: real credentials, real external channels and Providers (Phase 06B2), deployment or release, hosted spend beyond a recorded budget, force-push, destructive operations. | The user's own words; it widens the 2026-09-22 authorization from the audit backlog to the whole build without lifting any hard limit. |
| 17 | **Decision 15 is superseded.** V0 (hosted frontier in both slots) cannot be measured: the relay keys are exhausted (≈ USD 146 total per `harness/context/phase-03c-stage2-handoff.md` §5; ≈ USD 121.59 for Stages 1b/1c per `harness/context/post-phase-03c-handoff.md` §4; no remaining budget recorded), model mode is direct-only today, and training has already happened (Phase 03C, GO_DISTILLED). All gates run on scripted adapters; Slow stays scripted; the Judge seam is built with a scripted Judge; no further training. The V0, frontier-as-Fast and second-family-Judge rows are recorded as "not measured (budget)". | Decision 15 assumed a hosted budget and an ordering that no longer exist; measuring it would breach the hosted-spend limit in 16. |
| 18 | **After Phase 03C: option A in local-only form, then option C; option B excluded.** The GO_DISTILLED Qwen3-8B LoRA adapter becomes an opt-in local Fast backend behind a gateway, with untuned/scripted rollback, an input-parity renderer, attestation, a pre-registered local parity re-measure, the disclosure gate and a deterministic fallback. It is always labelled "local opt-in candidate", never "promoted" or "production", and carries the four recorded 03C caveats plus E1–E5: (E1) the product never produces the trained observation input; (E2) a different inference stack: training/evaluation ran on vLLM/HF (A100, PEFT LoRA); local serving would be MLX on Apple silicon; parity unmeasured; (E3) no product latency measured; (E4) act agreement has little product consequence today; (E5) nothing about Slow, Judge, multi-turn or outcomes. The root treats decision 16 as the user decision `harness/status.toml` required for local serving; production serving, p95/capacity/OOM and automatic fallback under load remain out of scope. Option C (Phase 07) comes last. Option B (Phase 06B2) is a hard limit and excluded; "complete" means complete within the authorized limits. | Makes the 03C result reachable in the product without claiming promotion, and keeps every external-party step behind the hard limits. |
| 19 | **Contract set 1.2 is narrow and droppable, after Stage 4.** R-11b: ProviderOffer 1.2 declares `applied_changes`; the 1.2 material-terms hash adds the fee breakdown and applied changes; ActionIntent/ApprovalRequest 1.2; verifier outcome `applied_change_not_approved`. B1-9b: 1.2 ProviderOffer requires FEE/TAX ≥ 0 and CREDIT ≤ 0. Every committed simulator, benchmark, ML and 03C producer stays at 1.1 and every committed `*-check` must stay byte-identical. A-3a is replaced by a coordinator validator (build plan PR-13); A-9b is dropped (the r4-frozen `runner_v2` increments `PlanningBasis.revision`). | Closes R-11 and B1-9 without moving frozen evidence; dropping 1.2 leaves nothing half-done. |
| 20 | **Stage 2 feedback is passed outside the contract**: no `SlowWorkRequest.revision_feedback` field. | r4 prompts serialize the typed Slow request, so a new default field risks moving frozen fingerprints. |
| 21 | **PR-15 (narrow contracts 1.2) is dropped.** Decision 19's contract set 1.2 is not built. R-11b (fees, credits and applied changes outside `material_terms_hash`) and B1-9b (no FEE/TAX ≥ 0 or CREDIT ≤ 0 rule at the wire) stay recorded limits; every contract and committed producer stays at 1.1. | YAGNI: decision 19 made it optional and droppable, and no Definition-of-done item in `harness/context/build-plan-to-complete.md` needs it. |
