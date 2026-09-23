# Audit remediation: live status and handoff

Single status source for the 2026-09-21 repository audit
(`docs/research/2026-09-21-repository-audit.md`) and the target architecture
proposal (`docs/research/2026-09-21-target-architecture-proposal.md`).
Authorization and adopted decisions: `harness/context/audit-remediation-decisions.md`.
Group 2 design: `harness/context/group2-evaluator-proposal.md`.

**Updated 2026-09-23. `main` @ `059d333`. Everything below is merged to
`main` unless the row says otherwise.**

A new session should read, in order: `harness/status.toml`, this file,
`harness/context/audit-remediation-decisions.md`, then only the spec and
log named by the item it picks up.

## 1. Where the programme stands

| Group | Scope | State |
|---|---|---|
| Audit itself | 10 review lanes, Pine reference, target architecture | done, #37 |
| Group 1 | every Blocking and the Important defects in the runtime, workflow and Web | **done**, #38 #39 #40 #43 #44 #46 |
| Group 2 | simulator / evaluation authority, evaluator evolution, verifier, leakage | **done**, #47 #48 #49 #50 |
| P1 | 11 backlog rows, staged | **not started** (3 rows overtaken by Group 2, see §3) |
| P2 | ~40 hygiene items | partly done through P0-4 (see §4) |
| Proposal stages | intake, Fast dialogue wiring, Judge, Agent Status Bar | **not started** (see §5) |

Every audit finding rated Blocking or Important is closed. What remains is
feature work (P1, the proposal) and hygiene (P2).

`make preflight` on `main`: runtime 686 passed / 42 gated skips, ML 363
passed / 1 skipped, web 51. Real-dependency gates (`postgres-check`,
`phase05a-check`, `phase06b1-check`) were run per change against the
Compose profiles and passed; they are not part of `preflight`.

## 2. Closed items, with the evidence

| Item | Finding | What changed | PR | Log |
|---|---|---|---|---|
| P0-1 | B2-1, C-1, B2-2, C-2 (Blocking) | the execution claim is persisted with a receipt (`command_id`, `before_revision`, `claimed_at`); the same command retried after a lost final write finishes the claim instead of re-executing; `record_channel_delivery` refuses a case with a pending execution | #38 | `fix-runtime-claim-receipt-retry.md` |
| P0-2 | B1-1, B1-2 | the executor keeps a per-approval ledger (`approval_already_consumed`) and compares the intent's material terms against the snapshot offer (`current_offer_terms_mismatch`) | #39 | `fix-executor-approval-ledger.md` |
| P0-3 | C-3 | the expiry timer catches activity failure: retryable exhaustion backs off (15 s doubling to 5 min), a non-retryable category abandons the timer; the workflow run never fails | #40 | `fix-workflow-expiry-failure-boundary.md` |
| P0-3b | reviewer finding on #40 | a replayed older command returned its stored receipt and rolled `_last_transition` back, disarming a pending approval's expiry; only a newer revision is adopted now | #46 | `fix-workflow-dedup-transition-guard.md` |
| P0-8 | E-1, E-2, E-3 | the Web surfaces a non-advancing 409 (category message, stale retry dropped, "Reconnect to continue"), reports poll exhaustion with a reconnect control, and keeps the exact approval retry while `pending_execution` is true | #43 | `fix-web-failure-surfacing.md` |
| P0-4 | §7 doc claims | 13 documents corrected (at-most-once wording, unkeyed SHA-256 fixtures, `Idempotency-Key` scope, ml-evidence ceiling/verifier/r5, 03A1-B erratum, default oracle, test counts, READMEs, Qwen3-8B, Temporal in the MVP list, preflight note) | #44 | `docs-audit-claim-corrections.md` |
| G2a | B1-5/D1-2, B1-4, D1-7 | one offer policy (`proxyloop_contracts.offer_policy`), one `material_terms_hash` / `offer_material_terms`, one supported-change list; the legacy Phase 01B predicate deleted; zero artifact bytes changed | #47 | `fix-one-offer-policy-authority.md` |
| G2b | D2-2, D2-5 (brought forward) | r4's frozen bytes stay provenance; a new `hosted_rescore` gate checks integrity, labels execution-contract drift, and derives a rescored r4 through the current evaluator with a recorded per-condition delta; r1 leaves `make test` for an integrity-only check | #48 | `fix-hosted-evaluator-evolution.md` |
| G2c | D1-3, D1-4, D2-3 | every action is verified against public turn state, not the scenario label; `unexpected_action` retired; `reference_match` separate; `SAFETY_FAMILIES` versioned (V1 pinned). Four r4 rows move; reference-high E2E 1→2 | #49 | `fix-state-based-verifier.md` |
| G2d | D1-1, D3-1, D3-2, D3-4 | public offer/turn/evidence ids are opaque `ep-<hash>` at the source; value-level leakage scans (incl. JSON-in-string) in the benchmark, harness, pipeline and 03C prompt paths; seven deterministic artifacts regenerated (ids/fingerprints only; 4400/4400 prompt fingerprints unchanged) | #50 | `fix-content-free-public-ids.md` |

Independent review found and forced a fix in five of these before merge —
the claim-retry channel guard (#38), the over-broad error gate that trapped
direct-mode users (#43), a contract test pinned to the old wording (#44),
the `deduplicated` rejection that would have stranded a Case (#46), and the
harness `idempotency_key` that still leaked the scenario id (#50). Each is
recorded in its log.

## 3. P1 — next, in stage order

Nothing here is started. Rows are from the audit's §6 P1 table; the "stage"
column is the demo stage in §5 of the audit that depends on it.

| Ids | Work | Files | Stage | Note |
|---|---|---|---|---|
| B2-3, B2-5 | route `slow_refresh` to the Slow path; `strategy.expires_at` does not gate execution (decision 10) | `runtime.py`, `capabilities.py` | 3 | **highest value: today a demo dies 30 minutes after the strategy is written** |
| B1-3 | resolve the capability id through the manifest (`simulator.accept_offer` vs `simulator.accept_fictional_offer`) | `openai_adapter/outputs.py` | 3 | small |
| A-1, A-2, A-6, A-10 | planning-basis fingerprint on the strategy; `ModelTrace` **emitted** with a `role`; completion receipt as a canonical contract; materiality narrowing — all in **one** `schema_version` 1.1 bump with regenerated fixtures (decision 11, proposal §12.2) | `contracts.py`, `router.py`, `coordinator.py`, `domain.py` | 3 | the canonical `ExecutionClaim` joins this bump |
| E-N1, B2-N1 | browser projection allow-list (decision 9) | `app.py`, `runtime-client.ts` | 3 | removes `idempotency_key`/fingerprints from the browser |
| A-11 | capability manifest per snapshot, or no expiry | `runtime.py` | 4 | execution at T+25 h currently fails |
| D1-5, D1-6, D1-8, D1-9 | behavioural provider configurations; real forgery; hazard is not one boolean; N-turn episodes | `scenarios.py`, `multi_turn.py`, `environment.py` | 4 | large; re-adds `forged-evidence`/`multi-hazard` to `SAFETY_FAMILIES` |
| B2-4, E-4, E-11, B2-6 | direct mode routes POSTs through `apply_command` so it honours `Idempotency-Key`; in-process approval expiry; honest placeholder (decision 8) | `app.py`, `runtime.py`, `apps/README.md` | 5 | also unblocks the P0-1 strict `command_id` form and the P0-8 direct-mode dead end |
| E-5, E-6 | `blocked` never re-offers confirm; write the tests two review artifacts claim exist | `conversation-workspace.tsx`, tests | 5 | |
| C-4 | the Update ID must not be the inbox `command_id` when the body changes | `client.py`, `app.py` | 5 | small |
| D2-2 | `validity_smoke --check` replays labels via `replay_v2` | `run_phase_03a1_validity_smoke.py` | before any new eval artifact | partly covered by the G2b rescore; confirm before closing |
| ~~D2-5~~, ~~D3-4~~ | r1 retired from `make test`; readiness compares to the committed manifest | — | — | **done** in G2b / G2d |

## 4. P2 — hygiene

Done through P0-4: G-2 (`contracts/README.md`), F-2 (test counts), F-3
(`tests/README.md`), A-7a (Qwen3-8B), A-7b (Temporal in the MVP list),
A-7c (ADR gate), part of G-1 (the `CLAUDE.md` note on what `preflight`
skips).

Open: G-1's stronger form (`preflight` asserts the gated-skip count or
names the real-dependency gates), G-3, A-3, A-5, A-7d–g, A-9,
B1-6…B1-12, B2-7…B2-9, C-5, C-7, C-8, D1-10…D1-12, D2-6…D2-9, D3-5…D3-9,
E-7…E-10, and replacing the grep-based architecture tests with Router
precedence tests (audit §3, lane A).

Added by this programme, not in the audit:
- `docs/development.md` still describes the `*-check` targets as "replay
  committed reports" and does not list `baselines-historical-check`,
  `hosted-rescore`, `hosted-rescore-check`.
- `tests/contract/test_phase_03a1_hosted_rerun_architecture.py:35` matches
  the old script name by substring; nothing pins
  `hosted-rerun-check: hosted-rescore-check`.
- The legacy `make baselines-check` (r1 replay) fails on the current tree
  by design; a test asserts that. Commented in the `Makefile`.

## 5. Proposal stages — the gap between "audited" and "a Pine-style demo"

These are the changes that make the product demonstrable; none is started.
Each needs its own spec under `harness/context/` before implementation.

1. **Fast dialogue reaches the product** (A-4, B1-3, decision 7). Today the
   runtime accepts only a constant Fast text and no model output reaches a
   user-visible surface; the Web demo is an eight-step wizard that never
   shows model text. Needs a per-turn measurement so the Fast/Slow share is
   a number, not a claim.
2. **Judge pass before the deterministic gate** (decision 7). Quality only,
   never in metrics or authority — a Judge that reaches metrics repeats
   D2-1. Second model family when a second credential exists, recorded in
   the trace.
3. **Stateless intake** `POST /intake/proposals` (proposal §12.5), so the
   Case invariant "goal is consumer-confirmed" stays typed.
4. **Agent Status Bar** = rendering `CaseContextSnapshot` in the Web.
5. Phase order (decision 12) said training waits for V0's numbers. Phase
   03C has since closed at **GO_DISTILLED** (#51, `harness/log/phase-03c-stage2-stage3.md`),
   so re-read that decision against the new evidence before planning V0.

## 6. Known limits carried deliberately

Each is recorded in the log of the change that introduced or found it.

- **Runtime.** The executor ledger is process-local by design; cross-process
  at-most-once rests on the persisted claim and the Provider state machine.
  A `terms_derivation` that raises propagates instead of returning
  `REJECTED` (unreachable through the runtime). `_check_claim_retry` keeps
  the lenient `command_id` form until direct mode carries a command id
  (P1 B2-4). Workflow runs that already FAILED on `main` before #40 are not
  recovered. After continue-as-new the expiry backoff restarts at zero
  (worst case one extra attempt round).
- **Web.** The `case_conflict` copy says "retry if the action is still
  offered" while the action needs a reconnect first; the two new
  `statusMessage` entries have no test in `runtime-client.test.ts`; the
  poll-exhaustion error is not auto-cleared if a later replay reaches a
  receipt; direct mode still cannot recover after a dropped stale retry
  (E-4).
- **Simulator / evaluation.** `_acceptance_state_valid` does not consult
  `clarification_required` / `disclosure_restricted` / `transfer_available`
  and both paths use `offers[0]`; no generator produces a turn that would
  expose either, but a Stage 4 catalogue could. Public ids are content-free
  but **not unlinkable** (unsalted truncated SHA-256, reversible by a
  dictionary over the catalogue). `pins.provider_config_ref` still carries
  the configuration id in the frozen r2 views and the 03C pins; the frozen
  r2 public episodes keep `r2-oracle:<scenario_id>`. The leakage scan's
  label tier cannot apply to a rendered prompt section. The Stage 2 cloud
  bundle's held-out prompt identity is argued from the mechanism, not
  proven locally (its JSONL is git-ignored).
- **Historical artifacts.** r1, the 03B smoke and the Stage 2 bundle report
  `drifted_since_r1` / `drifted_since_03b` / `drifted_since_bundle` against
  the current sources. That is expected and labelled, not a defect: each
  keeps a binding that still fails on tampering (r1 by its own
  fingerprints, the 03B manifest by the fingerprint every `results/arm-*.json`
  recorded, the bundle by its committed `dataset_fingerprint`).

## 7. Working agreement that produced these results

Per bounded change: root freezes a spec under `harness/context/` → an
`implementer` writes the failing regression tests first, then the fix → an
independent `reviewer` (never the writer) reviews the stable diff → root
reviews the complete diff and applies or rejects the findings → `make
preflight` once → commit, PR filling `.github/pull_request_template.md` →
CI → squash merge. One bounded concern per PR; one log per change under
`harness/log/`. The user's standing authorization (2026-09-22) covers the
merge step for this programme; it does not cover credentials, hosted spend,
real channels, deployment, force-push or destructive operations.
