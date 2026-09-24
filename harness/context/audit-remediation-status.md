# Audit remediation: live status and handoff

Single status source for the 2026-09-21 repository audit
(`docs/research/2026-09-21-repository-audit.md`) and the target architecture
proposal (`docs/research/2026-09-21-target-architecture-proposal.md`).
Authorization and adopted decisions: `harness/context/audit-remediation-decisions.md`.
Group 2 design: `harness/context/group2-evaluator-proposal.md`.

**Updated 2026-09-24, end of the third session (#72–#85 merged; build plan and
decisions 16–20 adopted). `main` @ `903a7ba`.
Everything below is merged to `main` unless the row says otherwise.**

A new session should read, in order: `harness/status.toml`, this file
(§0 first), `harness/context/audit-remediation-decisions.md`, then only the
spec and log named by the item it picks up.

## 0. Next session — start here

**Handoff 2026-09-24 (end of the third session).** `main` @ `903a7ba`.
This session merged #72–#85: 1.1 PR4 (P1 closed), R-10, R-1/R-1b, the four
P2 WIP batches, B1-12 + Router precedence tests, API hygiene (R-2, B2-7,
B2-9, G-3), B1-9, R-14, the contract-semantics limits (A-3, A-5, A-9,
R-11a, R-13c), and decisions 16–20 with the build plan.

**The plan of record is `harness/context/build-plan-to-complete.md`**
(PR-1..PR-17 in six waves, dependencies, serialization rules, "do not do"
list, definition of done), governed by decisions 16–20 in
`harness/context/audit-remediation-decisions.md`. Decision 16 is the
user's standing authorization for a complete build: do not stop to ask
for design or routine decisions — consult `architect` (or a reviewer) when
unsure, decide, and record the decision; every PR updates the docs it
affects; merge after CI + independent review. Hard limits still need the
user: real credentials, real external channels/Providers (06B2),
deployment/release, hosted spend beyond a recorded budget (none is
recorded — the relay is exhausted), force-push, destructive operations.

### In flight (pushed, no PR open) — finish these first

| Branch | Plan item | State | Remaining |
|---|---|---|---|
| `fix/r18-callback-evidence-pairing` | PR-4, R-18 | Implemented; merged with `main` @ `e1c8371`; `make test`, `postgres-check` 27, `phase05a-check` 42, `phase06b1-check` 35, `make preflight` all green | independent `reviewer`; merge current `main` (status-file conflict likely); PR; CI; squash merge. Accepted limits are in its log (a consistent forged event+Evidence pair, unchecked `source_ref`/`content_hash`; binding to real deliveries needs a storage change) |
| `fix/r16-expiry-classifier` | PR-2, R-16 | Implemented (outermost-cause classifier, second patch gate `expiry-failure-outermost-cause`, replay fixture recorded on `main`); non-DB checks green; replay test red on `main`, green on the branch | with the DB: red run of the chained non-retryable expiry test against `main`'s `workflow.py`, green run, then `phase05a-check` → `phase06b1-check` → `postgres-check` → `make preflight`; `reviewer`; PR; CI; merge |
| `fix/gate-honesty-r15-g1` | PR-1, R-15 + G-1 strong form | Implemented; commit subject says "(unreviewed WIP)". R-15: the `<= 20` bound was wrong (true invariant 10 ≤ calls ≤ 21; 21 is reachable with one worker) — barrier-based deterministic test, 200/200 passes. G-1: `scripts/check_gated_skips.py` pins 51 gated skips and names the real-dependency gates at the end of `make preflight` | `make preflight`; `reviewer`; open question for the reviewer/root: the pin is not enforced when any `PROXYLOOP_TEST_*` is set (alternative: require 0 gated skips when both are set); PR; CI; merge |
| `fix/b2-8-threadpool-runtime-calls` | PR-6, B2-8 | Implemented: `app.py` runs the direct-mode `apply_command`, `current_result`, the readiness probe, and the mailbox route's storage calls via `run_in_threadpool`; red/green test `tests/integration/test_api_event_loop.py`; `make lint`, `typecheck`, `test`, `preflight` green; `postgres-check` 27, `phase05a-check` 42, `phase06b1-check` 35. Known limits (root decision: accept and document): the direct-mode clock guard is a check-then-act outside the Runtime lane, so a stale guard read can carry an earlier `occurred_at` (same window already exists across uvicorn processes); it fails closed in the `CaseContextSnapshot` timestamp-order validator before any write, and the client gets 500 `internal_error` (an unmapped `pydantic` `ValidationError`); with the scripted adapters the two-event form gets 409 `case_conflict` ("awaiting approval"), a pinned `expected_revision` 409 `stale_cas`. Out of scope: `direct_expiry.py` `_expire` still calls `apply_command` on the loop | `reviewer`; PR; CI; merge. Log `fix-b2-8-threadpool-runtime-calls.md` |

R-19 (`SafeObservationAdapter` raises on negative-fee / duplicate-feature
offers; used by `ml/` and two scripts) is assigned to PR-9, whose parity
renderer uses `agent_core/observation.py`.

### Then

Wave 1 continues with PR-3 (after PR-2), PR-5 (after PR-4), PR-6 (B2-8,
`app.py`), PR-7 (R-12 + R-13b trace log, **architect design first**);
then Waves 2–6 per the plan. Items marked "architect first" get an
`architect` proposal before any `implementer` starts.

### How to run it (harness)

- Root = the main session: decides, reads primary evidence for its
  decisions, reviews final diffs, merges. `implementer` writes code in its
  own worktree (`isolation: worktree`) with a full task packet;
  `reviewer` (read-only) reviews every material PR; `architect` proposes
  for design-first items and uncertain decisions; `explorer` for
  inventories. Resume a subagent with SendMessage for follow-ups instead
  of starting a fresh one. Up to 6 in flight.
- **One DB lane**: the Compose test DB (`localhost:55432/proxyloop_test`,
  Temporal `localhost:7233`) is shared — only one agent at a time runs
  DB/Temporal tests or the gates, `postgres-check` → `phase05a-check` →
  `phase06b1-check`, with the variables on the make command line only.
  Implementers do all non-DB work first and report "ready for DB"; the
  root hands the DB out explicitly.
- **One writer per hot file** (`runtime.py`, `app.py`,
  `conversation-workspace.tsx`, `workflow.py`, `postgres_repository.py`).
- Bring pushed branches up to date with `git merge origin/main`, never
  rebase + force-push. Every PR edits this status file, so merging one PR
  makes the others conflict here: merge them one at a time and resolve by
  keeping both sides (closed rows from both; open lists minus everything
  either side closed). A code auto-merge in `runtime.py` needs `make test`,
  and the DB gates when the combined behaviour is DB-covered.
- Give each subagent its own scratch subdirectory (the scratchpad root is
  shared; agents overwrote each other's files once).
- `gh pr checks --watch` can die on a GitHub TLS timeout; poll
  `gh pr checks <n>` in a loop instead. The ML test R-15 flaked on CI
  twice before PR-1; if it recurs before PR-1 lands, rerun the failed job.
- Fresh worktrees need `pnpm install --frozen-lockfile` before `make test`.

## 1. Where the programme stands

| Group | Scope | State |
|---|---|---|
| Audit itself | 10 review lanes, Pine reference, target architecture | done, #37 |
| Group 1 | every Blocking and the Important defects in the runtime, workflow and Web | **done**, #38 #39 #40 #43 #44 #46 |
| Group 2 | simulator / evaluation authority, evaluator evolution, verifier, leakage | **done**, #47 #48 #49 #50 |
| P1 | 11 backlog rows, staged | **done** (#54–#70, #72, see §3) |
| P2 | ~40 hygiene items + R-1…R-18 found in the P1/P2 runs | first four batches merged (#73 #74 #76 #77), R-10 and R-1/R-1b fixed (#75 #78); the rest open (§4, §4a) |
| Proposal stages | intake, Fast dialogue wiring, Judge, Agent Status Bar | **not started** (see §5) |

Every audit finding rated Blocking or Important is closed. What remains is
feature work (the proposal), hygiene (P2) and the §4a backlog.

Latest recorded gates: #77 and #78 each merged `origin/main` @ `8e1522a`
(#76) and ran `make preflight` exit 0 there, with the real-dependency
gates one at a time — #78 (`fix-r1-retryable-update-continues-as-new.md`):
runtime 1200 passed / 51 skipped, ML 397 / 1 skipped, web 99;
`phase05a-check` 42, `phase06b1-check` 35, `postgres-check` 27. No gate
has been recorded on the combined tip `74e2073` (#77 + #78). Real-dependency
gates are not part of `preflight`; run them serially.

## 2. Closed items, with the evidence

Groups 1 and 2 below; P1 in §3; P2 items and R-items in §4 and §4a.

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

## 3. P1 — closed (second session; 1.1 PR4 in the third)

| Ids | What changed | PR | Log |
|---|---|---|---|
| B1-3 | the Slow compiler resolves `accept_offer` through the manifest's unique ACCEPT_OFFER definition | #54 | `fix-manifest-capability-resolution.md` |
| B2-3, B2-5 | event paths refresh an expired strategy through Slow (the demo no longer dies at T+30 min); strategy expiry does not gate execution | #56 | `fix-slow-refresh-strategy-expiry.md` |
| E-N1, B2-N1 | the browser receives an explicit allow-listed projection | #57 | `fix-browser-projection-allowlist.md` |
| D2-2 | `validity-smoke-check` replays r5 raw outputs through the current evaluator (0 rows move) | #59 | `fix-validity-smoke-replay-check.md` |
| D1-8 (P-B) | versioned oracle precedence, default V1 byte-identical | #60 | `feat-oracle-precedence-v2.md` |
| A-11 (P-A) | the capability manifest lives until `case.goal.deadline` | #61 | `fix-capability-manifest-lifetime.md` |
| C-4 | the Temporal Update ID binds the command id and the request fingerprint; a duplicate mailbox delivery racing the first dispatch is deduplicated | #62 | `fix-update-id-body-binding.md` |
| E-5, E-6 | a blocked response never re-offers an action (blocked is sticky); the recorded-but-missing Web tests exist | #63 | `fix-web-blocked-and-claimed-tests.md` |
| D1-5, D1-8, D1-9 (P-C) | V2 negotiation catalogue + N-turn state machine + state-predicate verifier, alongside a frozen V1 | #64 | `feat-negotiation-v2-catalogue.md` |
| A-1, A-2, A-6, A-10 (PR1) | the 1.1 contract set, per-type versioning, 1.0 byte-identical | #65 | `feat-contracts-1-1.md` |
| B2-4, E-4, E-11, B2-6 | direct mode goes through `apply_command`, expires approvals in-process, reports honestly | #66 | `fix-direct-mode-apply-command.md` |
| D1-6 (P-D) | private confirmation ledger; forged/absent evidence families | #67 | `feat-negotiation-confirmation-ledger.md` |
| A-1, A-10, A-6 (PR2) | the runtime produces 1.1 snapshots; strategies bind to their planning basis; COMPLETE carries a bound receipt | #68 | `feat-runtime-1-1.md` |
| D1 (P-E) | V2 splits, `SAFETY_FAMILIES_V2`, state-derived metrics, committed scripted ceiling (`make negotiation-check`) | #69 | `feat-negotiation-v2-evaluation.md` |
| A-2 (PR3) | the coordinator emits a 1.1 `ModelTrace` per model call | #70 | `feat-model-trace-producer.md` |
| B2-1 (contract half), A-2 (storage) (PR4) | runtime state carries the canonical 1.1 `ExecutionClaim` and persisted `model_traces` (storage envelope v2, v1 upgraded on read). Root decision: the runtime passes only `monotonic=time.perf_counter` to the coordinator, not the runtime clock | #72 | `feat-persisted-claim-and-traces.md` |

Also merged: #55 (the 03C training check visits all committed manifests),
#58 (the `architect` role runs on Opus). Designs with root decisions:
`harness/context/schema-1.1-design.md`, `harness/context/d1-simulator-v2-design.md`.

## 4. P2 — hygiene

Done through P0-4: G-2 (`contracts/README.md`), F-2 (test counts), F-3
(`tests/README.md`), A-7a (Qwen3-8B), A-7b (Temporal in the MVP list),
A-7c (ADR gate), part of G-1 (the `CLAUDE.md` note on what `preflight`
skips).

Closed in the third session:

| Ids | What changed | PR | Log |
|---|---|---|---|
| A-7d, A-7e, A-7g | `docs/architecture.md` uses the revision vocabulary, lists the `Case` fields (no owner field), names `CANONICAL_MODELS` (25 types at 1.1); `CONTEXT.md` wording "Case revision" and "at a specific revision" adopted | #73 | `docs-p2-reconciliation.md` |
| G-1 (documented only) | `AGENTS.md` step 9 pointer, `CLAUDE.md` and `docs/development.md` state what `preflight` skips and that the real-dependency gates run serially. **Not enforced by `make preflight`**: G-1's stronger form stays open | #73 | `docs-p2-reconciliation.md` |
| programme items (not in the audit) | `docs/development.md` describes each `*-check` target, lists `baselines-historical-check`, `hosted-rescore`, `hosted-rescore-check`, and says `baselines-check` fails by design; `test_phase_03a1_hosted_rerun_architecture.py` pins the exact line `hosted-rerun-check: hosted-rescore-check` | #73 | `docs-p2-reconciliation.md` |
| D3-7, D2-6 | pipeline reason codes: `schema_invalid`, `hash_mismatch`, `declared_rejection` (a non-empty `rejection_reasons` is quarantined, no longer accepted), `provenance_mismatch`, `unknown_derivation_parent`, `missing_provenance` for a null `source`; a non-frozen test replays the committed r2 and pins its one r3-corrected mismatch | #74 | `fix-p2-ml-eval-hygiene.md` |
| B1-6, B1-7, B1-8, B1-10, B1-11 | model match is exact or a dated snapshot; SDK `ValidationError` → `invalid_output`; `offer_case_mismatch`; a `commit()` that raised is never re-run (`execution_outcome_unknown`); the credit constant is owned by `offer_policy.py` | #76 | `fix-p2-adapter-domain.md` |
| E-7, E-8, E-9 (= R-3), E-10 | polls never regress an in-flight command; Progress shows only payload-backed steps; `usage.data_megabytes` allow-listed and rendered; strict USD parsing | #77 | `fix-p2-web-hygiene.md` |
| B2-7, B2-9, G-3 | a replayed receipt reports its route and Fast decision only if it produced the current snapshot (otherwise `terminal`/`current`, no `fast`); the dead clock read in the terminal-approval branch is gone; `phase04d-profile-check` compares a committed shape baseline and exact counts and exits 1 with named failures (no bare `assert`) | #82 | `fix-p2-api-hygiene.md` |
| B1-12 | the Router waits on approval state, not an event label: `RouteRequest.trigger_is_approval_decision` removed, a current PENDING approval always routes `WAIT_FOR_APPROVAL`; precedence and reason codes unchanged | #80 | `fix-p2-router-precedence.md` |
| grep-based architecture tests → Router precedence tests (audit §3, lane A) | the grep test over `router.py`/`coordinator.py` is deleted; `test_router_precedence_ladder_matches_the_frozen_table` checks each row of `ROUTER_PRECEDENCE` behaviourally, plus a slow-result planning-basis rejection test; the 03A0 docs-invariant tests are kept | #80 | `fix-p2-router-precedence.md` |
| B1-9 | the Case-vs-offer policy check is total: `case_offer_violations` (telecom domain) turns a contract-valid but out-of-domain input (negative fee sum from a credit line, duplicate goal/offer/applied-change tokens) into `offer_terms_invalid` / `compliance_context_invalid` instead of raising; `verify_completion` and the runtime approval gate both use it (NEEDS_REPLAN / no approval). A non-UTC `evaluated_at` still raises (caller bug). No wire or fee-netting change; non-negative fees at the wire deferred to 1.2 | `fix/b1-9-total-offer-policy` | `fix-b1-9-total-offer-policy.md` |

Recorded as limits by #74 (`fix-p2-ml-eval-hygiene.md`), still open:
deleting the D3-7 `rejection_reasons` field (emitted in the committed
`data/schemas/normalized-trajectory-v1.schema.json`); D3-9, D2-7, D2-8
(frozen modules or committed hosted-report bytes); audit N1, the
`_matches_environment` fallback at `pipeline.py:566`.

Recorded as limits (documentation plus characterization tests, no
behaviour change) in #83
(`docs-contract-semantics-limits.md`): A-3 (the executor is the only
enforcement point for the capability/action join), A-5 (`Evidence.content_hash`
referent table), A-9 (ephemeral values and write-once records keep
`revision=1`). The contract changes the audit proposed for them stay open as
separate decisions.

Open: G-1's stronger form (`preflight` asserts the gated-skip count or
names the real-dependency gates), A-7f,
B2-8 (in flight, PR-6, §0), C-5, C-7, C-8, D1-10…D1-12, D2-7…D2-9, D3-5, D3-6, D3-7 (field
deletion only), D3-8, D3-9.

## 4a. Found during the P1 and P2 runs (R-1 … R-19)

Closed:

| Ids | What changed | PR | Log |
|---|---|---|---|
| R-10 (Important) | fix A: the codec's terminal rule compares the execution source pins with the snapshot pins at the approval-decision cursor and accepts only delivery-callback `provider_event`s after it; a callback on a stored 1.0 COMPLETE Case keeps 1.0 | #75 | `fix-r10-terminal-delivery-callback.md` |
| R-1 (Important), R-1b | option (f): a retry-exhausted Update still fails with `temporal_unavailable` and the run requests Continue-As-New (patch gate `retryable-update-failure-continues-as-new`), so the identical retry reaches the Runtime; the classifier reads `ActivityError.retry_state` (`MAXIMUM_ATTEMPTS_REACHED`, `TIMEOUT`); `_can_continue_as_new()` ends the R-1b busy-loop | #78 | `fix-r1-retryable-update-continues-as-new.md` |
| R-3 (= E-9) | see §4 | #77 | `fix-p2-web-hygiene.md` |
| R-8 | documented: the browser `event_cursor`/`revision` count channel events; `snapshot.completion` is a synthetic `not_done` | #77 | `fix-p2-web-hygiene.md` |
| R-2 | error details are content-free category codes: 404 `{"detail": "not_found"}` in both modes; 409 `{"detail": "stale_cas" \| "case_conflict" \| "approval_expired"}`; request validation 422 `{"detail": {"code": "request_invalid", "message": "request rejected"}}` instead of FastAPI's default body (which echoed input). The Runtime text (or, for 422, field locations and error types only) is logged server-side with the correlation id | #82 | `fix-p2-api-hygiene.md` |

Specs: `harness/context/fix-r10-terminal-delivery-callback-preflight.md`,
`harness/context/fix-r1-retryable-update-continues-as-new-preflight.md`.
Rejected alternatives, kept here because the R-1 spec cites them. R-10: B
(write channel tables only — violates 06B1 AC 9), C (refuse — loses the
receipt), D (store the cursor — heavier). R-1: (a) keep the Update open and
retry — needs a deadline anyway (then (f)), holds the lock or lets commands
jump the queue, blocks Continue-As-New, changes approval semantics; (b) a
non-failing "retry later" result — successes are cached too; (c) an attempt
salt — the client cannot know it without a live worker (or (g), a random
Update ID per request, which drops Update-level dedup globally and reverses
#62's T2 — kept as a fallback); (d) a bigger retry budget — only shortens
the window and exceeds the 30 s Next proxy timeout.

Other items (Minor unless marked):
- R-4 the ML compiler resolves capabilities by exact id (frozen via r4; consistent today).
- R-5 the channel route reads `expected_revision` outside the lock (redelivery recovers since #62).
- R-6 persisted Cases keep their 1-day manifest; a runtime > 24 h test needs an injectable offer TTL.
- R-7 `_snapshot(manifest=None)` re-mint — **done** in #68 (manifest required).
- R-9 shared `proxyloop_test` DB → run DB/Temporal gates serially (documented in #73); a per-run schema would remove the hazard.
- R-11 the canonical `material_terms_hash` excludes fees and applied changes. Option (a) **done** in #83 (`CONTEXT.md` Material Terms states the implemented definition and its limits); option (b), binding fees, credits, and applied changes (R-11b), deferred to contract set 1.2.
- **R-12 (Important, proposal stage 1)** rejected-result traces reach `CoordinatorOutcome` but the runtime raises before writing; needs a traces-only append.
- R-13 `model_traces` retention unbounded. Option (c) **done** in #83 (documented in `docs/architecture.md`); option (b), a separate append-only trace log at `storage_version` 3, planned with R-12.
- R-14 the 1.0/1.1 basis switch is duplicated in `runtime.py` and `contracts.py` — **done** in #85: one owner, `planning_basis_components` in the contracts package, called by the snapshot validator and the runtime's `_basis`; pinned by `runtime/packages/contracts/tests/test_planning_basis_components.py`. See `harness/log/refactor-r14-basis-switch-owner.md`.
- R-15 flaky: `ml/tests/test_teacher_pipeline.py::test_concurrent_workers_cannot_jointly_exceed_the_ceiling` asserts `8 <= calls <= 20` and saw 21 on CI (#71, a docs-only PR); the bound is timing-dependent — tighten the test or make the concurrency deterministic. Failed CI again on #75 (2026-09-24, run 35961699413 attempt 1: `assert 21 <= 20`; attempt 2 passed). A separate fix task has been proposed.
- **R-16 (Important; severity confirmed by the root)** the expiry path's `_expiry_failure_category` reads the innermost typed `ApplicationError`; every real activity failure is raised `from exc`, so the converter chain is `[('ApplicationError','case_conflict',True), ('ApplicationError','CaseConflictError',False)]` and a real non-retryable expiry failure (e.g. `case_conflict`) is classified retryable and retried with backoff instead of abandoned. The expiry tests miss it because their injected faults carry no `__cause__`. The fix changes expiry-path commands for recorded histories, so it needs a second workflow patch gate. See `harness/log/fix-r1-retryable-update-continues-as-new.md`.
- R-17 a channel ingest that exhausts on the delivery activity is not re-driven on redelivery (pre-existing; found in the R-1 design, `fix-r1-retryable-update-continues-as-new.md`).
- R-18 callback events on a terminal Case are not paired with their Provider-event Evidence: delivered/bounced `provider_event`s forged after the approval cursor without Evidence, or a deleted callback event whose Evidence remains, are accepted. Root decided it is out of scope for R-10 (`fix-r10-terminal-delivery-callback.md`, Known limits).
- R-19 `SafeObservationAdapter._adapt_offer` (`agent_core/observation.py`) raises on a contract-valid `ProviderOffer` with a negative fee sum or a duplicate feature, via `SafeOffer.__post_init__` (the same out-of-domain inputs B1-9 made total in the policy check). Used today by the `ml/` pipeline and evaluation and the `scripts/` benchmark/harness runners, not by the product runtime. Found in the B1-9 review.

Still open from the audit P2 list and not yet batched: runtime/router/api
hygiene (B2-8 in flight as PR-6, A-7f, R-5) and ops/tests (C-5, C-7, C-8, R-6).
The design-first items are settled: B1-9 is closed above, and A-3, A-5, A-9
are recorded as limits above. **Do not do**: D3-5/D3-6 (`qwen_mlx.py`
frozen by r4); D1-10/11/12 (V1 simulator frozen, superseded by V2); D2-9 and
D3-8 only if a check proves no committed report byte moves.

**Decisions the root took without asking in this run** (each preserves
committed evidence or fails closed; revisit if the user disagrees): V1
simulator frozen, V2 alongside (`d1-simulator-v2-design.md` decision 1);
per-type 1.1 versioning instead of a global bump (`schema-1.1-design.md`
decision 1); the execution claim on runtime state, not the snapshot;
COMPLETE ⇔ a snapshot-bound receipt at 1.1; A-10 counts APPROVED/REJECTED
approvals only; a non-v4 path id is 422 in both API modes; the Web's blocked
state is sticky; V2 `false_completion` ≠ V1's (a hazardous accept is
`harmful_offer_applied`, not a false completion).

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
5. Phase order: decision 17 supersedes decision 15 (no V0, scripted gates,
   no further training) and decision 18 takes Phase 03C's **GO_DISTILLED**
   adapter (#51, `harness/log/phase-03c-stage2-stage3.md`) as a local opt-in
   Fast candidate, then Phase 07 (`harness/context/audit-remediation-decisions.md`).

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
- **API errors** (`fix-p2-api-hygiene.md`). For a stale revision, direct
  mode (and the fake Temporal client) return `{"detail": "stale_cas"}` while
  real Temporal returns `case_conflict`, because the workflow activity
  classifies it; the fix belongs in `workflow_worker/activities.py`. A
  replayed receipt the Case has since moved past returns the current
  route and no `fast` (not the original turn's); no public command can
  follow the approval-opening event, so the "later event" case is covered
  only by a test that writes the later state directly into the repository.
  The 422 log names field locations, which for an extra field is the
  client-chosen key (never its value).
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
