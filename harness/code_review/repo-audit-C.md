# Repo audit — Lane C: persistence, workflow, channel, supervisor

Reviewer: `reviewer` (Opus, high), read-only; 82 tool uses, ~306K tokens.
Recorded by the root orchestrator from the lane's report; root verification
at the end. Reproductions under the session scratchpad `laneC/`
(`c1_pg_recovery.py`, `c2_temporal_b21.py`, `c3_expiry_exhaustion.py`,
`c4_update_id_failure_dedup.py`, `c5_supervisor_pidfile.py`,
`c6_multiproc_cas.py`, `c7_unkeyed_channel.py`); all ran against the audit
Compose stack (app DB `proxyloop` on 5432, never the gated `proxyloop_test`).

## 1. Module verdicts

| Module | Verdict | Why |
|---|---|---|
| `case_runtime/postgres_repository.py` | keep (one fix) | Revision CAS correct across connections and OS processes (c6: 8/8 rounds exactly one winner); receipts in the same row/transaction as state; channel writes single-transaction; broad tamper detection. Defect: the envelope admits only `COMPLETE` terminal Cases (`:1098`), so a non-`COMPLETE` late-recovery result is unpersistable (C-2). |
| `workflow_worker/workflow.py` | **refactor** | Update path sound (lock, handler counting, CAN carry). The expiry-timer path runs an activity inside `run()` with no failure boundary: retry exhaustion fails the run permanently (C-3). |
| `workflow_worker/activities.py` | keep | Taxonomy matches 05A; `RuntimeError → state_invalid` is the wire form of C-1. |
| `workflow_worker/{client,models,config,readiness,worker}.py` | keep | Strict, redacted, small; `_failure_category` maps a closed workflow to `temporal_unavailable` (C-3 aftermath). |
| `connectors/local_mailbox.py` | keep | Matches its own contract (unkeyed SHA-256, "conspicuously non-secret", `phase-06b1:106-111`); the docs misdescribe it (C-6). |
| `scripts/run_phase_07a_portfolio_demo.py` | keep (one fix) | Lock/stop/reset ordering sound; the refused-start path deletes `pids.json` and orphans running host processes (C-5). |
| `compose.yaml` | keep | No healthcheck on `temporal`; otherwise fine locally. |

## 2. Findings

### C-1 — Blocking — B2-1 confirmed on the real Temporal path; on the same worker the documented pin-less recovery also fails until the worker is restarted
- `runtime.py:1115-1119` (claim write, no receipt) → `:1244` (Provider commit) → `:1328` (final write); `runtime.py:1240-1243` caches an executor bound to the *old* provider object; `capabilities._execute_serialized` returns `REUSED` without `commit()`; `runtime.py:1261-1264` then reads `state.provider.confirmation` on the reconstructed provider (`postgres_repository.py:1087`, `awaiting_approval`) → `RuntimeError("Provider commit returned no confirmation Evidence")` → `activities.py:109-114` `state_invalid`.
- Claims: `phase-05a:142-155` ("post-commit retry must hit the stored command receipt"), fault row "Worker/activity stops after PostgreSQL commit before activity completion"; `phase-04c` AC6; `docs/architecture.md:54`; `README.md:87` "At-most-once execution".
- Repro (`c2_temporal_b21.py`, real Temporal + PostgreSQL, one worker): `DECIDE_APPROVAL` Update with `expected_revision`, repository raises `StorageUnavailableError` once on the final write → attempt 1 `storage_unavailable` (retryable), attempt 2 `case_conflict` (revision 5 ≠ 4); DB `rev=5 pending=True exec=0 receipts=[create_case, append_event]`. Same Update again → `case_conflict`. New pin-less approval on the same worker → `state_invalid` (503). Only a *replacement worker* plus a pin-less approval (which the Web never sends) converges: `rev=6 pending=False exec=1`.
- Q1: the "at most once" in `test_postgres_pending_claim_recovers_after_final_write_failure` rests on the first confirmation living in a discarded Python object; recovery re-executes `execute_approved_offer` on a provider reconstructed as `awaiting_approval` (c1 scenario C: 4 commits across 4 provider objects). With an external Provider this is at-least-once with amnesia. `architecture.md:54` disclaims real exactly-once; `README.md:87` does not.
- Q2: `make portfolio-demo-recovery` runs `test_live_temporal_local_mailbox_delivery_is_stable` (channel lost-response retry), not this path. No test in 04C/05A/06B1 retries `DECIDE_APPROVAL` after a partial write; `_FaultingAdapter` fails only around `CREATE_CASE` at the adapter boundary.
- Direction: persist a claim receipt (command id, `before_revision`, `evaluated_at`) in the claim write; `apply_command` recognises it and re-drives `_execute_claim` regardless of `expected_revision`; drop the process-local executor cache in favour of persisted idempotency evidence. Regression: c2 must end `terminal=True` on activity attempt 2 with one confirmation Evidence.

### C-2 — Important — a pending claim recovered after offer expiry can never be persisted; the Case is stuck forever and every attempt re-commits the reconstructed Provider
- `postgres_repository.py:1098-1099` (`only verified terminal Cases can be reconstructed`) rejects any `completion_decision` that is not `COMPLETE`, reached from `_encode_state` (`:906`) after `verify_completion` returned `needs_replan` (B2-2).
- Repro (`c1_pg_recovery.py` D): claim at T+2m with final write failed; fresh runtime at T+2h → `RuntimeError: Case state failed storage validation`; DB unchanged; second fresh runtime → same; 3 Provider commits in total. Temporal mode: `state_invalid` on every approval.
- Direction: the envelope must accept the full `CompletionOutcome` set for `candidate_complete`, or recovery must evaluate with the persisted claim time so the result is `COMPLETE`.

### C-3 — Important — PostgreSQL outage while the approval-expiry timer fires fails the workflow run permanently; the Case is unreachable through Temporal and the approval never expires
- `workflow.py:153-171` → `_expire_pending` (`:262-308`) → `_execute_command` (`:221-234`) awaited inside `run()` with no `try/except`; `ACTIVITY_RETRY_POLICY` exhausts after 5 attempts; the `ActivityError` propagates out of `run()`. `client.py:80-81` uses `REJECT_DUPLICATE`, so Update-with-Start cannot recreate the workflow.
- Claims: `phase-05a` fault row "PostgreSQL unavailable through retry exhaustion → Workflow remains available for a later distinct command"; `architecture.md:54`; `phase-05a` AC7.
- Repro (`c3_expiry_exhaustion.py`, time-skipping env + real PostgreSQL): `expiry activity attempts: 5`, `workflow status after outage: FAILED`, DB approval still `pending`; later distinct Update → `temporal_unavailable` (update not found); Update-with-Start create → `ALREADY_EXISTS`. The API reports `dependency unavailable` for a healthy Temporal.
- Direction: catch activity failure in the timer path, keep the workflow alive, re-arm/back off; consider `ALLOW_DUPLICATE_FAILED_ONLY` or a repair command.

### C-4 — Minor — a non-retryable Update outcome is replayed by Temporal for the same Update ID even when the retry body would succeed; a channel event whose first dispatch conflicted is poisoned until Continue-As-New
`client.py:91-97` (Update ID = command id); `app.py:551-554` (inbox `command_id` fixed at reservation; `expected_revision` read outside any lock); `app.py:535-544`. Repro (`c4`): `APPEND_EVENT` with wrong `expected_revision` → `case_conflict`; same command id with the correct revision → `case_conflict` again; direct `runtime.apply_command` → revision 4.

### C-5 — Minor — after a crashed supervisor, a refused second `make portfolio-demo` deletes `pids.json`, so `portfolio-demo-stop` can no longer find the running worker/runtime/web
`run_phase_07a_portfolio_demo.py:796-800` raises; `finally` at `:841-847` unlinks `pids.json` unconditionally; host processes started with `start_new_session=True` (`:574`) survive. Repro (`c5`): `pids.json exists: False`, host pids still running, `_running_processes → {}`; ports 3000/8000 stay occupied. Other supervisor checks (lock atomicity, dead-owner reclaim, stop-vs-build timeout, reset scope) are sound.

### C-6 — Important (docs claim) — `docs/planning/progress.md:98` says "HMAC-signed raw-byte fixtures"; there is no key and no HMAC
`local_mailbox.py:163-172` (`sha256=` + SHA-256 of body), `:189-190` (unkeyed recompute; `hmac.compare_digest` only for the comparison; timestamp header not covered). `delivery_id` and `provider_message_id` derive from the client-chosen `event_id`. The contract is truthful (`phase-06b1:109-111`); `README.md:37, 111` "signed" and progress.md "HMAC-signed" are not. Repro (`c7`): a third-party body with `build_fixture_headers` passes verification, is applied (rev 3), and a minted `delivered` callback is applied (rev 4) with `provider_event` Evidence. AC10 holds: none of it can complete the Case.

### C-7 — Minor — 04C AC3 "every non-Provider field" is not what the round-trip assertions compare (`test_phase_04c:164-174` omits `transitions`, `last_fast_decision`).

### C-8 — Minor — `replace_with_delivery_receipt` and the delivery-callback command have no automated real-PostgreSQL coverage (`postgres_repository.py:640-777`; only 07A Scene B, manual, and the `_ChannelRepository` double).

### Notes
- N1 `test_live_temporal_local_mailbox_delivery_is_stable` proves "one logical delivery" only because `LocalMailboxAdapter` is deterministic and in-memory; a replacement worker re-sends and regenerates the same `provider_message_id`.
- N2 `PostgresCaseRepository.__init__` runs `CREATE TABLE IF NOT EXISTS` on every construction; worker and runtime start concurrently in the demo — possible duplicate-key race at startup (not reproduced).
- N3 Workflow task time is the sole expiry authority; an Update accepted at `expires_at-1s` executes after wall-clock expiry. Consistent with the contract.
- N4 Worker crash mid-activity: safe for `CREATE`/`APPEND`/`INGEST`; unsafe for `DECIDE_APPROVAL` between claim and final write (C-1).
- N6 `_is_channel_evidence` would also hide any future non-channel `provider_message` Evidence whose `source_ref` is a UUIDv4.
- N7 `run_recovery_check` says "worker-restart/lost-response"; it runs a lost-response test only, one worker.

## 3. Acceptance-criteria table (E evidence / P partial / A attested only)

| Phase / AC | Status | Evidence |
|---|---|---|
| 04C-1, -2, -4, -5, -7, -8, -9 | E | `test_phase_04c` (`:633-639`, `:469-526`, `:435-485`, `:290-308`, `:314-325`, `:136-138`); c6 cross-process 8/8 |
| 04C-3 round-trip every non-Provider field | P | helper omits `transitions`, `last_fast_decision` (C-7) |
| 04C-6 crash after commit → recovery, no duplicate Evidence | P | fresh-instance pin-less only; pinned and same-instance retry fail (C-1); late recovery unpersistable (C-2) |
| 04C-10..12 | A | log; PR #23 |
| 05A-1 fault rows | P | "post-commit retry" row only for `CREATE_CASE`; timer path violates the exhaustion row (C-3) |
| 05A-2, -3, -4, -5, -7, -9, -10 | E | `models.py:27-35`; `test_phase_05a_temporal_api:195-221`; `client.py:70-97`; `test_phase_05a_temporal_workflow:164-245, 308-391, 394-465, 468-643`; `make phase05a-check` 24 passed |
| 05A-6 retry taxonomy + redaction | P | API maps 2 of ~11 categories |
| 05A-8 post-commit retry → one commit/Evidence | P | duplicates E; post-claim retry of approval fails (C-1) |
| 05A-11..13 | A | log; PR #26 |
| 06B1-1 | P | unkeyed hash per contract; C-4 reservation edge |
| 06B1-2 | A | Lane E |
| 06B1-3, -4, -5, -7, -10 | E | `make phase05a-check` after 06B1; stdlib-only connectors; `test_phase_06b1_temporal:129-286`; `verify_completion` requires confirmation |
| 06B1-6, -8, -9 | P→A | replay mismatch and unknown_binding only on the double; replacement/restart as new in-memory adapters; callback correlation double only (C-8) |
| 06B1-11..15 | A | log; PR #28 |
| 07A-1 | P | lock tests real fs; crash path defect (C-5) |
| 07A-2, -3, -4, -9, -10..13 | A | docs / browser attestation / not in any automated gate |
| 07A-5 recovery command | E | lost-response only (N7) |
| 07A-6, -8 | P | mocked tests; no crash/refusal, scene, or recovery-function test |
| 07A-7 no channel material in browser schema | E | `app.py:813-856`; `channel_runtime:540-566` |

## 4. Test quality

| File | Verdict | Notes |
|---|---|---|
| `test_phase_04c_persistent_case_store.py` (24) | load-bearing | tamper matrix and CAS race real; recovery uses the one retry shape that works; helper incomplete (C-7) |
| `test_phase_05a_case_runtime.py` (7) | load-bearing | no retry after partial write |
| `test_phase_05a_temporal_api.py` (9) | narrow / double | `FakeTemporalCaseClient` re-implements the dispatch seam |
| `test_phase_05a_temporal_workflow.py` (8) | load-bearing | real Temporal, replay, CAN, time-skipping; faults only around `CREATE_CASE`; no timer-path failure |
| `test_phase_06b1_connectors.py` (5) | load-bearing | "signature" test proves hash binding only |
| `test_phase_06b1_channel_runtime.py` (14) | mixed / double | ~120-line `_ChannelRepository` re-implements the Postgres channel seam; one tautological allowlist test |
| `test_phase_06b1_workflow_worker.py` (8) | load-bearing for branch logic | doubles |
| `test_phase_06b1_temporal.py` (2) | load-bearing | real rollback and lost-response; no real delivery callback (C-8) |
| `test_phase_07a_portfolio_demo.py` (15) | mixed | lock/stop-order real fs; two tests grep source text; no refused-start, scene, or recovery-function test |

## 5. Checks run / not run
Run (Compose `postgres`, `postgres-test`, `temporal` up; gated DB `proxyloop_test`): `make postgres-check` 24 passed; `make phase05a-check` 24 passed; `make phase06b1-check` 31 passed; scratch c1–c7. Not run: `make portfolio-demo*`, `make preflight` (root baseline), hosted CI, browser scenes. Compose torn down by the lane; zero containers; no repository edits.

## 6. Open questions
1. C-1/C-2: is `candidate_complete` with `needs_replan` an allowed durable state, or must recovery use the claim-time basis so it is always `COMPLETE`? Canonical-contract decision.
2. C-3: recoverable failed run (`ALLOW_DUPLICATE_FAILED_ONLY` + carry re-derivation) or a timer path that never fails the run? Either changes the 05A identity rules.
3. C-6: wording only, or an explicit README statement that the local channel has no authentication?
4. Promote `run_channel_scene` into an automated gate?

Lane recommendation: **Request Changes** (C-1 Blocking; C-2, C-3, C-6 Important).

## Root verification (2026-09-21)

Root brought the Compose stack up twice and re-ran `c2_temporal_b21.py`
(output identical: attempt 2 `case_conflict`, same-worker pin-less
`state_invalid`, replacement worker converges) and `c3_expiry_exhaustion.py`
(`expiry activity attempts: 5`, `workflow status after outage: FAILED`,
approval still `pending`, later Update `not found`, Update-with-Start
`ALREADY_EXISTS`); stack torn down afterwards, zero containers.

| Id | Verdict | Root note |
|---|---|---|
| C-1 | **confirmed, Blocking** (same defect as B2-1, now shown on the real worker) | The only converging path is "replace the worker process, then send a request shape the Web never sends". `README.md:87` "at-most-once execution" is not supported for any Provider whose state is not a discarded Python object. |
| C-2 | confirmed, Important | Read `postgres_repository.py:1098` gate; consistent with B2-2. |
| C-3 | confirmed, Important | Re-run by root. |
| C-6 | confirmed, Important (doc claim) | Read `local_mailbox.py:163-190`; there is no key. |
| C-4, C-5, C-7, C-8 | accepted as reported | Repros under `laneC/`. |
