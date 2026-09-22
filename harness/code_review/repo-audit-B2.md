# Repo audit — Lane B2: Case runtime and HTTP API

Reviewer: `reviewer` (Opus, high), read-only; 78 tool uses, ~272K tokens.
Recorded by the root orchestrator from the lane's report; root verification
at the end. Reproduction scripts live under the session scratchpad `b2/`
(not in the repository) and the Blocking/Important ones were re-run by root.

Scope audited on `main` @ `aaae134`: `case_runtime/{runtime,commands,repository}.py`,
`api/{app,config,operations,readiness}.py`, `tests/integration/**` for
04A/04B/04C (non-Postgres)/04D/05A/06B1 channel runtime.

## 1. Module verdicts

| Module | Verdict | Why |
|---|---|---|
| `case_runtime/runtime.py` | **refactor** | Core CAS/lane/receipt design is sound, but the approval→execution claim has no retry contract (B2-1), recovery re-verifies with the wrong time basis and dead-ends the Case (B2-2), and there is no Slow-refresh path so every Case is unusable 30 min after creation (B2-3). |
| `case_runtime/commands.py` | keep | Strict shape validation and `semantic_command_fingerprint` are correct; validator error branches almost entirely untested. |
| `case_runtime/repository.py` | keep | In-memory CAS correct and lock-protected. |
| `api/app.py` | **refactor** | `Idempotency-Key` semantics depend on orchestration mode and are silently ignored in the default mode (B2-4); sync runtime/model/DB calls inside `async def` handlers (B2-8); completion placeholder invents reason codes (B2-6). |
| `api/config.py`, `operations.py`, `readiness.py` | keep | Fail closed; allowlist enforced; readiness probes exactly what is configured (Q7: nothing reported ready that was not checked). |

## 2. Findings

### B2-1 — Blocking — pending-execution claim cannot be completed by the documented idempotent retry; the Provider side effect is already committed

- `runtime.py:1020-1022` (`_check_expected_revision` runs before the `APPROVED + pending_execution` recovery branch at `:1041-1051`); the claim write at `:1115-1119` persists no command receipt (receipt only written by the final write at `:1303-1316`); the Provider commit happens inside `executor.execute` at `:1244` before the final write at `:1328`.
- Claims violated: `docs/architecture.md:54`; `docs/ui/state-matrix.md` "pending_execution is recoverable"; `docs/ui/user-flows.md:19-22` (retry keeps the same `Idempotency-Key` and exact body, which includes `expected_revision`, `apps/web/lib/runtime-client.ts:486-489`); `docs/planning/progress.md:93-94` ("one exact pending-command retry via `Idempotency-Key`").
- Reproduction (`b2/s2_pending.py`, both modes): create → event (revision 4, pending approval) → approve with `expected_revision=4` against a repository whose final replace fails once. Observed: first call 409 `injected final CAS conflict`; the in-memory Provider is already `confirmed`; `GET` shows `pending_execution=true, execution_count=0, completion=not_done`; **exact retry (same key, same body) → 409 `case snapshot revision is stale`** in direct and fake-Temporal mode (the claim advanced the revision to 5). Only a body *without* `expected_revision` — which the Web never sends — completes it. In real Temporal a transient `storage_unavailable` between claim and final write is retried with the same command (`workflow.py:32-45`) → stale check → `case_conflict`, which is `non_retryable` (`activities.py:79-95`) → the Case stays pending with no driver.
- Test gap: `test_final_claim_write_failure_recovers_without_second_provider_commit` (`test_phase_04a_agent_runtime.py:454`) and `test_postgres_pending_claim_recovers_after_final_write_failure` (`test_phase_04c_persistent_case_store.py:328`) recover with `runtime.approve(CASE_ID, approval_id)` — no `expected_revision`, no `command_id` — so they never exercise the retry shape the Web and the Temporal activity send.
- Direction: persist a claim receipt (command id + `before_revision`) in the claim write so `apply_command`/`approve` recognise a retry of the same command and re-drive `_execute_claim` regardless of `expected_revision`; regression: the same `CaseCommand` applied twice around an injected final-write failure must return a terminal receipt on the second call.

### B2-2 — Important — late recovery re-verifies at "now", records `needs_replan` for an already-confirmed Provider action, and treats it as terminal

- `runtime.py:1044-1051` (`evaluated_at = occurred_at or clock_now()`), `:1265-1277`, `offer_policy.py:79-80` (`offer_expired`); non-COMPLETE decisions still set `completion_decision`, which `append_event` (`:832-836`), `_transition_ref` (`:1954-1955`) and `GET /cases` (`app.py:420-423`) treat as terminal.
- Claim: `docs/architecture.md:247` (`needs_replan` is a continuation outcome); `CONTEXT.md:95-96`.
- Reproduction (`b2/s3_late_recovery.py`): create T, event T+1m, approve T+2m (final write fails; Provider `confirmed_at=T+2m`), pin-less approve at T+2h → 200 `route=slow_refresh`, `completion=needs_replan ['offer_expired']`, `phase=candidate_complete`, `execution_count=1`; subsequent `POST /events` → 409 `case is terminal`; `GET route=terminal`. The bill was changed by the Provider; the Case says the action needs replanning; nothing can replan. POST and GET disagree on `route`.
- Direction: recovery must verify with the time basis of the original execution (persist `evaluated_at` in the claim); non-COMPLETE decisions must not be coerced into a terminal state.

### B2-3 — Important — every Case becomes unusable 30 minutes after creation; the failure is reported as a model rejection

- `runtime.py:874-886` (`advance(..., fast=self._fast)` never passes `slow`; `SLOW_UNAVAILABLE` → `raise ModelRuntimeError("fast")`), `app.py:250-264` (→ 409 `model_result_rejected`); strategy expiry fixed at 30 min (`agent_core/scripted.py:77`, `openai_adapter/outputs.py:165`); coordinator branch `coordinator.py:162-170`.
- Claim: `docs/architecture.md:185` (`slow_refresh` for mandatory Slow work), `:247`; `runtime.py:122` docstring ("A model proposal was rejected") — no proposal exists on this path.
- Reproduction (`b2/s8_expired.py`): event at T+30m / T+2h / T+25h → `status=slow_unavailable`, `route=slow_refresh`, `reasons=('strategy_expired',)`; via the API 409 `model_result_rejected`; no endpoint can refresh the strategy. No test covers an event more than a few minutes after creation.
- Direction: route `slow_refresh` in `append_event` to `self._slow`, or return a truthful category and document the 30-minute bound.

### B2-4 — Important — `Idempotency-Key` is silently ignored (and unvalidated) in the default direct mode; retry semantics differ per mode

- `app.py:387-395, 442-448, 471-481` (direct branches never read the header); `app.py:601-611` (`_command_id` only reached in Temporal branches).
- Claim: `README.md:66`, `docs/ui/user-flows.md:21-22`, `docs/planning/progress.md:93-94`.
- Reproduction (`b2/s1_direct_keys.py`, direct): same key twice on `POST /cases` → 201 then 409 `case already exists`; `Idempotency-Key: not-a-uuid` accepted; same key + exact body twice on `/approvals` → 200 then 409 `case snapshot revision is stale`. Fake-Temporal (`b2/s6_temporal_keys.py`) returns byte-identical deduplicated payloads. Mode divergence: pin-less approval re-POST after terminal → direct 200 (`_repeat_approved`, `runtime.py:1416-1455`), Temporal 409; `test_phase_04a_agent_runtime.py:115-123` asserts the direct-mode 200.
- Direction: reject the header in direct mode (422, stable code) or route direct POSTs through `service.apply_command` so both modes share receipt semantics; API-level tests for the key/body matrix in both modes (`app.py:450-460, 483-497` uncovered).

### B2-5 — Minor — execution proceeds under an expired strategy while Fast turns are refused for the same reason
`capabilities.py:153-157` compares strategy id/revision only; `runtime.py:1061` checks approval and offer expiry only. Repro (`b2/s9_strategy_expired_approve.py`): approve at T+45m → `complete`, `execution_count=1`, while a message at T+31m is refused (B2-3). Direction: decide whether `strategy.expires_at` gates execution; make router and executor agree.

### B2-6 — Minor — placeholder completion payload asserts a pending approval/execution that does not exist
`app.py:773-781`: when `completion_decision is None` the API emits `not_done` / `approval_or_execution_pending` unconditionally, including after a rejected or expired approval (repro `b2/s7_misc.py`). `not_done` is not a `CompletionOutcome`.

### B2-7 — Minor — deduplicated replay returns a receipt route that contradicts the returned snapshot
`runtime.py:321-354`: replaying the `/events` key after completion → 200 with `route=wait_for_approval`, `revision=6`, `completion=complete`. The Web's monotonic guard masks it.

### B2-8 — Minor (reliability) — async handlers run blocking runtime, model, and PostgreSQL calls on the event loop
`app.py:384-412, 437-462, 465-499` are `async def` calling sync `service.*`; the OpenAI client (30 s timeout) and psycopg are sync. Repro (`b2/s10_blocking.py`): a 2 s Slow adapter blocks a sibling `asyncio.sleep(0.05)` for 2.01 s; `/health/live` cannot be served during a model call. Direction: `def` handlers or `run_in_threadpool`.

### B2-9 — Minor — dead clock call in the terminal-approval branch
`runtime.py:1053-1056`: `if occurred_at is None: self._clock_now()` consumes a tick of injected sequence clocks, making test timing fixtures fragile.

### Notes
- N1 Projection (Q5): `GET /cases/{id}` returns the full `CaseContextSnapshot` (`app.py:770-827`): the complete `StrategyPacket` (`concession_ladder`, `fallback_outcomes`, `allowed_disclosures`, `escalation_conditions`), `action_intents[].idempotency_key`, `material_terms_hash`, all `planning_basis` fingerprints, `pins`, `capability_manifest`, `delegated_authority`, offer-evidence `content_hash`. Only local-mailbox events/evidence are filtered, heuristically (`_is_channel_visible_event`, `_is_channel_evidence`, `app.py:830-856`); `event_cursor` gaps still reveal filtered channel activity. Docs claim only channel-material exclusion (`architecture.md:332-333`), so a policy question (Lane E confirms what the Web renders).
- N2 `simulator_transition` Evidence is content-free: `content_hash = sha256(idempotency_key)`, created in `prepare` before commit (`runtime.py:173-184`); completion does not depend on it. Contrast `CONTEXT.md:88`.
- N3 `append_event` accepts only `consumer_message`; extra fields → 422; terminal → 409. Command `occurred_at` is trusted (no wall-clock cross-check); in Temporal mode the workflow clock is the only expiry authority (`s5b_time.py`: approval accepted at `expires_at-1µs` while the runtime clock is 3 days later).
- N4 `ingest_channel_event` accepts `command.content` overriding `inbox.content` when it matches the command's own `content_hash` (`runtime.py:375-379`); internal surface only.
- N5 `except` inventory: `app.py:135` (middleware → 500; with B2-1 a committed Provider action is reported as failure with no completing driver); `app.py:607` (→ 422); `app.py:695-697` (recorder failure swallowed); `app.py:717, 852` (→ None/False); `readiness.py:48-59` (fails closed); `runtime.py:307-313`, `:960-966` (rollback + re-raise). `_operation_record` at `app.py:687-692` runs outside the `try`; a non-allowlisted category would raise inside the middleware `finally` — currently unreachable.
- N6 One Case per process/store (`SCRIPTED_CASE_ID`, `runtime.py:100`); second `POST /cases` → 409.
- N7 Multiple `ThinAgentRuntime` instances over one in-memory repository have separate lanes/executors; a second instance recovering a pending claim hits `IllegalOfferTransitionError` → 500 (test-only topology). With PostgreSQL the Provider is reconstructed as `awaiting_approval` and re-committed (`test_phase_04c_persistent_case_store.py:349-354`) — Lane C to confirm that "at most once" there rests on the un-persisted first confirmation being discarded.
- N8 Approval pins are all optional at the API (`app.py:68-74`).

## 3. Test quality

| File | Verdict | Gaps |
|---|---|---|
| `test_phase_04a_agent_runtime.py` (17) | load-bearing | "duplicate approval" omits `expected_revision` (B2-1 undetectable); `_record_rejection`, pin mismatches, `approval not found`, `_repeat_approved` conflicts, `case approval is terminal`, `clock time must advance` untested |
| `test_phase_04b_model_runtime.py` (14) | load-bearing | `ModelRuntimeError` API mapping never hit at HTTP level |
| `test_phase_04c_persistent_case_store.py` (4 run / 22 skipped) | Postgres-gated (Lane C) | only rejection-path test is gated |
| `test_phase_04d_control_plane_operations.py` (17) | load-bearing | no record asserted for a successful approval |
| `test_phase_05a_case_runtime.py` (5 / 2 skipped) | load-bearing | no retry of a command that failed after a partial write (B2-1) |
| `test_phase_05a_temporal_api.py` (9) | narrow | events/approvals in Temporal mode via API uncovered; 2 of ~10 `TemporalDispatchError` categories mapped |
| `test_phase_06b1_channel_runtime.py` (14) | mostly load-bearing | `_ChannelRepository` hand-written double; ingest-conflict and delivery-binding branches never executed |
| `commands.py` validators | — | 2 of ~20 error branches tested |

Statement trace under the non-Postgres suite: `runtime.py` 87/465 statements unexecuted, `commands.py` 26/121.

## 4. Checks run / not run
Run: the 7 in-scope test files → 95 passed, 22 skipped (DB-gated); scratch reproductions `s1`–`s10`, `trace_cov.py`. Not run: Postgres-gated tests, Temporal workflow/worker tests, 07A demo test (Lane C), `make` targets (root baseline).

## 5. Open questions for the root orchestrator
1. B2-1/B2-2: is the intended recovery contract "same command retried" (Temporal/Web) or "new pin-less approval" (what the tests do)? Code supports only the latter; docs promise the former.
2. B2-3: is the 30-minute strategy lifetime an intended session bound? If yes, document it and fix the error code; if no, `append_event` needs a Slow-refresh path before further agent-side work.
3. B2-4: should direct mode honour `Idempotency-Key` or refuse it?
4. B2-5: does `strategy.expires_at` gate execution?
5. N1: is the full `StrategyPacket` and `idempotency_key` an intended part of the browser projection?
6. N7 for Lane C.

## Root verification (2026-09-21)

Root re-ran `s2_pending.py`, `s3_late_recovery.py`, `s8_expired.py`; every
quoted output reproduced. Root read `runtime.py:872-887` (no `slow=` passed
to `advance`), `runtime.py:1016-1052` (`_check_expected_revision` before the
pending-execution branch), `app.py:383-396` (direct mode ignores the header).

| Id | Verdict | Root note |
|---|---|---|
| B2-1 | **confirmed, Blocking** | Completion-truth and idempotency claim: Provider committed, Case says `not_done`, the documented exact retry cannot finish it, and in Temporal mode the retry is classified non-retryable. The 06A/07A "recovery" evidence exercises a different retry shape (pin-less approve), so the documented recovery result does not cover the path the Web and Temporal actually take. Lane C to check whether `portfolio-demo-recovery` hits this. |
| B2-2 | confirmed, Important | Same root cause family (claim carries no time basis); makes B2-1's stuck state permanently wrong once the offer expires. |
| B2-3 | confirmed, Important | A hard 30-minute session bound reported as `model_result_rejected`; there is no Slow-refresh path in the product runtime. Directly relevant to any "runnable agent demo" claim. |
| B2-4 | confirmed, Important | Default mode drops the header; docs state the key semantics unconditionally. |
| B2-5 … B2-9, N1–N8 | accepted as reported | Repro scripts present under `b2/`. |
