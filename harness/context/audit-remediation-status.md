# Audit remediation: live status and handoff

Single status source for the 2026-09-21 repository audit
(`docs/research/2026-09-21-repository-audit.md`) and the target architecture
proposal (`docs/research/2026-09-21-target-architecture-proposal.md`).
Authorization and adopted decisions: `harness/context/audit-remediation-decisions.md`.
Group 2 design: `harness/context/group2-evaluator-proposal.md`.

**Updated 2026-09-23 (second session, P1 close). `main` @ `724ada2`.
Everything below is merged to `main` unless the row says otherwise.**

A new session should read, in order: `harness/status.toml`, this file
(§0 first), `harness/context/audit-remediation-decisions.md`, then only the
spec and log named by the item it picks up.

## 0. Next session — start here

The session that produced #52–#70 paused on a usage limit with work in
flight. Every unmerged branch below is committed with the suffix
"(unreviewed WIP)" and **pushed**; no PR is open for it. Resume in this
order:

1. **1.1 PR4 — the last P1 item.** Branch `feat/persisted-claim-and-traces`
   (spec `harness/context/feat-persisted-claim-and-traces-preflight.md`,
   log `harness/log/feat-persisted-claim-and-traces.md`). Implemented and
   locally green on `6932596`, **not reviewed**. Remaining: rebase onto
   `main` (PR3 #70 has landed); in `runtime.py` pass `clock=self.now` and
   `monotonic=time.perf_counter` to every `CaseCoordinator(...)` built for an
   `advance` call (8 call sites) and add a test that persisted traces carry
   the runtime clock's time; independent review; `make preflight` +
   `postgres-check`, `phase05a-check`, `phase06b1-check` **run serially**;
   PR → CI → merge. From the PR3 review: `trace_id` is not an idempotency
   key (dedup is by command).
2. **R-10 (Important, pre-existing correctness bug).** Diagnosed, not fixed —
   see §4a. Implement fix option A after PR4 (both touch `runtime.py` /
   `postgres_repository.py`).
3. **R-1 (Important).** Design in §4a; implement after PR4.
4. **Four P2 batches, implemented, not reviewed.** Each needs: rebase,
   independent review, `make preflight`, the Compose gates where marked,
   PR → CI → merge.
   - `docs/p2-reconciliation` — A-7d/e/g, G-1 (what `preflight` runs vs the
     real-dependency gates, the serial-run rule), `docs/development.md` check
     targets, pinned `hosted-rerun-check: hosted-rescore-check`. Also changed
     one word in `CONTEXT.md` ("Case version" → "Case revision"); confirm or
     revert.
   - `fix/p2-adapter-domain` — B1-6 (model match: exact or `-YYYY-MM-DD`
     snapshot), B1-7 (SDK `ValidationError` → `invalid_output`), B1-8
     (`offer_case_mismatch`), B1-10 (executor marks key/approval in progress
     before `commit()`; a raised commit is never re-run — **changes a runtime
     edge case**: a same-process retry after a raising commit now gets
     `execution_outcome_unknown`; the reviewer must confirm), B1-11 (constant
     owned by `offer_policy.py`; V1 `scenarios.py` untouched, pinned by a
     test). **Compose gates required** (executor).
   - `fix/p2-web-hygiene` — E-7 (polls never regress to `confirm` during an
     in-flight command), E-8 (Progress shows only payload-backed steps), E-9
     (`usage.data_megabytes` added to the browser allow-list and rendered),
     E-10 (USD parser aligned with its prompt), R-8 (documented). Touches the
     `app.py` projection → **Compose gates required**.
   - `fix/p2-ml-eval-hygiene` — D3-7 reason codes (`schema_invalid`,
     `hash_mismatch`; names to confirm), a D2-6 replay test; D3-7's
     `rejection_reasons`, D3-9, D2-7, D2-8 recorded as limits (frozen modules
     or committed report bytes). `data/` unchanged.
5. The rest of P2 (§4), then the proposal stages (§5). **Before stage 1, ask
   the user about decision 15** (training-after-V0 vs Phase 03C
   GO_DISTILLED); the Phase 03C next-phase choice (A promote / C Phase 07 /
   B 06B2) is also the user's.

Gate hygiene learned the hard way: the DB/Temporal gates share the
`proxyloop_test` database and fixed Case ids, so two concurrent runs truncate
each other (`case_not_found`, `state_invalid`). Run them one at a time and
tell implementers not to set `PROXYLOOP_TEST_*`. A fresh worktree needs
`pnpm install --frozen-lockfile` before `make test` or `make preflight` (the
generated-contract tests call `tsc`/`json2ts`).

## 1. Where the programme stands

| Group | Scope | State |
|---|---|---|
| Audit itself | 10 review lanes, Pine reference, target architecture | done, #37 |
| Group 1 | every Blocking and the Important defects in the runtime, workflow and Web | **done**, #38 #39 #40 #43 #44 #46 |
| Group 2 | simulator / evaluation authority, evaluator evolution, verifier, leakage | **done**, #47 #48 #49 #50 |
| P1 | 11 backlog rows, staged | **done except 1.1 PR4** (#54–#70, see §3) |
| P2 | ~40 hygiene items + R-1…R-14 found in the P1 run | four batches implemented, unreviewed (§0, §4) |
| Proposal stages | intake, Fast dialogue wiring, Judge, Agent Status Bar | **not started** (see §5) |

Every audit finding rated Blocking or Important is closed. What remains is
feature work (P1, the proposal) and hygiene (P2).

Latest root gate on `main`'s tip (#70, PR3 diff, DB/Temporal-gated tests
enabled): `make preflight` exit 0 with runtime 1185 passed, ML and web
green; `postgres-check` 27, `phase05a-check` 36, `phase06b1-check` 34.
Real-dependency gates are not part of `preflight`; run them serially.

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

## 3. P1 — closed in the second session (except 1.1 PR4)

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
| canonical `ExecutionClaim`, trace persistence (PR4) | **open** — branch `feat/persisted-claim-and-traces`, see §0 | — | `feat-persisted-claim-and-traces.md` |

Also merged: #55 (the 03C training check visits all committed manifests),
#58 (the `architect` role runs on Opus). Designs with root decisions:
`harness/context/schema-1.1-design.md`, `harness/context/d1-simulator-v2-design.md`.

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

## 4a. Found during the P1 run (R-1 … R-14) and designs in hand

**R-10 (Important, pre-existing since #28; the 1.0 half since #68).** A
channel delivery callback on a COMPLETE Case fails. The 06B1 contract
requires the callback to append a Provider-event evidence and advance the
revision on a terminal Case; `record_channel_delivery` does so and moves
`pins.event_cursor`, but the Postgres codec's terminal rule
(`postgres_repository.py` ~1115-1146) demands
`execution_source_pins == snapshot.pins`, i.e. it silently assumes a
terminal Case is never written again → "Case state failed storage
validation" (Temporal: non-retryable `state_invalid`; inbox stuck
`reserved`). For a stored 1.0 COMPLETE Case the callback's `_snapshot(...)`
also defaults to 1.1 and trips the receipt rule. Diagnosed by a
root-cause investigation (codec-level repro, no DB). **Recommended fix A**
(root decision still to record): the terminal rule becomes
`execution_source_pins == snapshot.pins.model_copy(update={"event_cursor": c})`
where `c` is the cursor of the deterministic `approval_decision` event, plus
"every event after `c` is a callback `provider_event`" (no loss of forgery
protection); the callback passes `schema_version=snapshot.schema_version`
once `completion_decision` is set. Regression tests first: a codec-round-
tripping `_ChannelRepository` + "first delivered callback after COMPLETE"
(revision +1; decision, receipt and source pins unchanged); a stored 1.0
COMPLETE Case stays 1.0; tampered source-pin cursor or a non-delivery event
after approval is rejected. Rejected: B (write channel tables only —
violates 06B1 AC 9), C (refuse — loses the receipt), D (store the cursor —
heavier). The existing test `test_phase_06b1_channel_runtime.py:620-646`
used a fake repository without the codec, which is why this was missed.

**R-1 (Important).** An identical retry after retryable exhaustion
(`temporal_unavailable`) receives the cached Update failure until
Continue-As-New; the Web's "safe retry preserved" copy is untrue within a
run and an approval stuck at `pending_execution` cannot be finished by its
own identical retry. **Design (architect, Opus, probed on the Compose Temporal 1.28.1 with
in-memory repositories): option (f)** — on retryable exhaustion the Update
still fails with `temporal_unavailable`, **and the run requests
Continue-As-New**; the new run's Update cache is empty, so the identical
retry reaches the Runtime (receipt / claim rules decide). Non-retryable
failures stay cached (#62's T2 unchanged). Observed on `main`: 5 ×
`storage_unavailable` → `temporal_unavailable` after 15.1 s; the identical
retry returns the cached failure in 0.00 s with no new activity; an
approval whose final write exhausted stays `pending_execution` forever. A
completed Update (success or failure) can never be evicted within a run;
only a new run clears it. Rejected: (a) keep the Update open and retry —
needs a deadline anyway (then (f)), holds the lock or lets commands jump
the queue, blocks Continue-As-New, changes approval semantics; (b) a
non-failing "retry later" result — successes are cached too; (c) an
attempt salt — the client cannot know it without a live worker (or (g), a
random Update ID per request, which drops Update-level dedup globally and
reverses #62's T2 — kept as a fallback); (d) a bigger retry budget — only
shortens the window and exceeds the 30 s Next proxy timeout.

**R-1b (pre-existing on `main`, found by the probes; fix in the same PR —
root decision still to record):** when the Continue-As-New threshold is
reached while a command is queued on the lock, `run()` busy-loops: both
`wake_changed` conditions return True on `_continue_requested` while
`_active_handlers > 0` forbids Continue-As-New, so the WFT spins
(`TMPRL1101 Potential deadlock` ×8) and both commands hang. Option (f)
would make it common.

**Exact change (`workflow_worker/workflow.py` only; client, models,
activities, API and Web unchanged — the Web's "safe retry preserved" copy
becomes true):**
1. `_can_continue_as_new()` = `_continue_requested and _active_handlers == 0
   and not _activity_in_flight`; use it in `run()`'s Continue-As-New check
   and in **both** `wake_changed` predicates (R-1b; no patch needed — the
   old and new conditions differ only in states that deadlock).
2. In `apply_case_command`, inside the lock:
   `try: transition = await self._execute_command(command)`
   `except ActivityError as error:` classify with the existing
   `_expiry_failure_category` (rename to `_activity_failure_category`); if
   not non-retryable **and** `workflow.patched("retryable-update-failure-continues-as-new")`,
   set `self._continue_requested = True`; re-raise.
3. In both success paths (`apply_case_command` and `_expire_pending`):
   `self._continue_requested = self._continue_requested or (self._commands_in_run >= self._continue_as_new_after)`
   (observed: without `or`, a queued command's success clears the flag and
   the retry still hits the cache).
4. Update the `update_id_for_command` docstring (a retryable failure
   rolls the run).

**Tests first** (`tests/integration/test_phase_05a_temporal_workflow.py`;
each ~16 s real time — the backoff runs on the server clock): T1 identical
append retry after exhaustion reaches the Runtime (attempts 6, run rolled);
T2 identical approval retry finishes a claim whose final write exhausted
(`terminal`, `execution_count == 1`); T3 exhaustion with a queued command —
the queued one succeeds, A's identical retry reaches the Runtime
(`case_conflict`); T4 `continue_as_new_after=2` with a stuck X and a queued
Y — both complete (hangs on `main`, R-1b); T5 Replayer over a committed
history fixture recorded on `main` ("exhaustion, then a success in the same
run"; strip local paths) proves the patch gate (unpatched →
`NondeterminismError`); optional T6 over HTTP (503 then 200 with the same
`Idempotency-Key`). Then `phase05a-check`, `phase06b1-check`,
`postgres-check` serially and `make preflight`. Risks: a delayed roll while
other handlers run (≤ one retry still cached, typically ≤ 15 s); expiry
backoff resets on each roll (P0-3 limit, now more frequent); one extra run
per exhaustion. Separate pre-existing gap to backlog: a channel ingest that
exhausts on the delivery activity is not re-driven on redelivery.

Other items (Minor unless marked):
- R-2 `app.py` error handlers echo `str(exc)` to the browser.
- R-3 = E-9 (in `fix/p2-web-hygiene`).
- R-4 the ML compiler resolves capabilities by exact id (frozen via r4; consistent today).
- R-5 the channel route reads `expected_revision` outside the lock (redelivery recovers since #62).
- R-6 persisted Cases keep their 1-day manifest; a runtime > 24 h test needs an injectable offer TTL.
- R-7 `_snapshot(manifest=None)` re-mint — **done** in #68 (manifest required).
- R-8 the browser `event_cursor`/`revision` count channel events; `snapshot.completion` is synthetic `not_done` (documented in `fix/p2-web-hygiene`).
- R-9 shared `proxyloop_test` DB → run DB/Temporal gates serially (documented in `docs/p2-reconciliation`); a per-run schema would remove the hazard.
- R-11 the canonical `material_terms_hash` excludes fees and applied changes.
- **R-12 (Important, proposal stage 1)** rejected-result traces reach `CoordinatorOutcome` but the runtime raises before writing; needs a traces-only append.
- R-13 `model_traces` retention unbounded.
- R-14 the 1.0/1.1 basis switch is duplicated in `runtime.py` and `contracts.py`.

Still open from the audit P2 list and not yet batched: runtime/router/api
hygiene (B1-12, B2-7, B2-8, B2-9, A-7f, R-2, R-5, R-14 — after PR4 and
R-10), ops/tests (C-5, C-7, C-8, G-3, R-6), architecture-test replacement
(grep → Router precedence tests), and the design-first items A-3, A-5, A-9,
B1-9 (route through `architect`). **Do not do**: D3-5/D3-6 (`qwen_mlx.py`
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
