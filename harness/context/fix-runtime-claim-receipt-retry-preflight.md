# Fix: runtime execution claim receipt and same-command retry (P0-1)

Bounded repository change approved by the user on 2026-09-21 (audit decision
#1: recovery contract = same-command retry). Branch
`fix/runtime-claim-receipt-retry` from `main` at `5648ab4`. Resolves audit
findings **B2-1 / C-1 (Blocking)**, **B2-2 / C-2 (Important)**; see
`harness/code_review/repo-audit-B2.md`, `repo-audit-C.md`,
`docs/research/2026-09-21-repository-audit.md` §6 P0 row 1.

## Defect (observed on main)

`ThinAgentRuntime._approve_serialized` writes a claim
(`pending_execution=True`, revision R+1) with no command receipt, commits the
fictional Provider inside `executor.execute`, then writes the final state
(R+2) with the receipt. If the final write fails, the Provider is committed
and the Case says `pending_execution=True, execution_count=0`. The retry the
Web and the Temporal activity send (same `command_id`, same body including
`expected_revision=R`) hits `_check_expected_revision` first (`runtime.py:1021`)
and gets 409 `case snapshot revision is stale`; in Temporal that is
`case_conflict`, non-retryable → the Case is stranded. On the same worker a
pin-less approval also fails: the cached `CapabilityExecutor`
(`runtime.py:1240-1243`) answers `REUSED` without committing the
reconstructed (`awaiting_approval`) Provider →
`RuntimeError("Provider commit returned no confirmation Evidence")`. Late
recovery re-verifies at "now" → `offer_expired` → `needs_replan` treated as
terminal, and with PostgreSQL that state is unpersistable
(`postgres_repository.py:1098`).

## Frozen design (runtime-local; no canonical contract change)

1. **Claim record.** New frozen Pydantic model in
   `runtime/packages/case_runtime/src/proxyloop_case_runtime/commands.py`:

   ```python
   class ExecutionClaimRecord(BaseModel):
       model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
       approval_id: UUID4
       before_revision: int = Field(ge=1)      # snapshot revision the client pinned (R)
       claimed_at: datetime                    # == approval.decided_at; UTC-aware
       command_id: UUID4 | None = None         # None for direct-mode pin-less approvals
       command_fingerprint: str | None = None  # semantic_command_fingerprint(command)
   ```
   Add `execution_claim: ExecutionClaimRecord | None = None` to
   `CaseRuntimeState` (`repository.py`) and to `_CaseStorageEnvelope`
   (`postgres_repository.py`), encoded/decoded like the other optional
   execution fields. Validator: `execution_claim is not None` iff
   `snapshot.pending_execution is True`.

2. **Claim write.** In `_approve_serialized`, `claim_state` carries
   `execution_claim=ExecutionClaimRecord(approval_id=decided.approval_id,
   before_revision=snapshot.revision, claimed_at=decided_at,
   command_id=command_id, command_fingerprint=command_fingerprint)`.

3. **Retry recognition** (new branch at the top of `_approve_serialized`,
   before `_check_expected_revision`): if `snapshot.pending_execution` and
   `state.execution_claim is not None` and the approval id matches:
   - if `command_id == claim.command_id` (same command): require
     `command_fingerprint == claim.command_fingerprint` (else
     `CaseConflictError("command id was reused for a different command")`);
     accept `expected_revision in {None, claim.before_revision,
     snapshot.revision}`; re-drive `_execute_claim`.
   - else (different or absent command id, e.g. direct-mode pin-less
     approval or a fresh Temporal command): accept `expected_revision in
     {None, snapshot.revision}`; re-drive `_execute_claim` with the new
     `command_id`/fingerprint (the receipt is written under the command
     that completes the claim).
   - `decision != "approved"` on a pending claim → existing
     `CaseConflictError("approval is already terminal")`.

4. **Time basis.** `_execute_claim` uses `state.execution_claim.claimed_at`
   as `evaluated_at` for `verify_completion` and for the proposal/executor
   timestamps whenever a claim exists; the caller-provided `occurred_at` is
   ignored for verification on a re-drive. This is what makes late recovery
   produce `COMPLETE` instead of `needs_replan(offer_expired)`.

5. **Executor cache.** In `_execute_claim`, if `execution.status is REUSED`
   and `state.provider.confirmation is None`, evict
   `self._executors[case_id]`, build a fresh `CapabilityExecutor(adapter)`
   and execute once more. If `state.provider.confirmation is not None`
   before executing (same in-memory Provider already committed by the failed
   attempt), skip `executor.execute` and derive the execution Evidence the
   same way the adapter's `prepare` does (content-free, keyed by the
   intent's idempotency key) — one confirmation, one execution Evidence,
   `execution_count == 1`. Do **not** change `agent_core/capabilities.py`
   (that is P0-2).

6. **Final write.** `final_state.execution_claim = None`; receipt
   `before_revision = claim.before_revision` (not `snapshot.revision - 1`,
   which is the same value today but should come from the record).

7. **PostgreSQL envelope.** `_encode_state` / decode accept
   `execution_claim`; the reconstruction gate at `postgres_repository.py:1098`
   accepts, in addition to `COMPLETE`, a `CANDIDATE_COMPLETE` phase whose
   `completion_decision.decision` is any other `CompletionOutcome` **when**
   `pending_execution is False`, `execution_count == 1`, and the approval is
   `APPROVED`; the Provider is reconstructed as `confirmed` from the stored
   confirmation Evidence in that case. A pending claim
   (`pending_execution=True`) reconstructs the Provider as
   `awaiting_approval` exactly as today.

## Out of scope (do not touch)

`agent_core/capabilities.py` (approval ledger / terms derivation = P0-2),
`workflow_worker/*` timer path (P0-3), `apps/web` (P0-8), `api/app.py`
direct-mode idempotency (B2-4), canonical `contracts.py`, docs other than
this file and the change log the root writes.

## Regression tests (write first; each must fail on `main`)

- **T1** `tests/integration/test_phase_04a_agent_runtime.py`: direct mode,
  in-memory repository that fails the final `replace` once
  (`FailFinalClaimRepository` shape already at `:344`): create → event →
  `POST /cases/{id}/approvals/{aid}` with `expected_revision=R` → 409; exact
  retry (same `Idempotency-Key`, same body incl. `expected_revision=R`) →
  200, `completion.decision == "complete"`, `execution_count == 1`, exactly
  one `confirmation` Evidence, Provider `state_history` shows one
  confirmation.
- **T2** `tests/integration/test_phase_05a_case_runtime.py`:
  `apply_command(DECIDE_APPROVAL)` with the same `command_id` twice around
  an injected final-write failure → the second call returns a receipt with
  `terminal=True`, `deduplicated=False`; a third identical call →
  `deduplicated=True`; a call with the same `command_id` and a different
  body → `CaseConflictError`.
- **T3** `tests/integration/test_phase_04a_agent_runtime.py`: late recovery
  — sequence clock: create T, event T+1m, approve T+2m (final write fails),
  pin-less approve at T+2h → `completion.decision == "complete"`,
  `case.phase == "complete"`, no `offer_expired`; a following event → 409
  `case is terminal`.
- **T4** `tests/integration/test_phase_04c_persistent_case_store.py`
  (Postgres-gated): (a) pinned same-command retry on the **same** runtime
  instance converges (exercises the executor-cache rule); (b) on a fresh
  instance converges; (c) late recovery at T+2h persists as `COMPLETE`; in
  all cases exactly one Provider commit is observable and the stored
  envelope round-trips through `get`.
- **T5** `tests/integration/test_phase_05a_temporal_workflow.py`
  (Postgres + Temporal gated): the lane-C `c2` scenario — a repository that
  raises `StorageUnavailableError` once on the final write of
  `DECIDE_APPROVAL`; the Update's activity attempt 2 (same command id)
  returns a terminal receipt; DB shows `pending_execution=False`,
  `execution_count=1`, one confirmation Evidence; no `case_conflict`.

## Verification commands

Focused: `uv run --project runtime --all-packages pytest -c runtime/pyproject.toml -q tests/integration/test_phase_04a_agent_runtime.py tests/integration/test_phase_04b_model_runtime.py tests/integration/test_phase_05a_case_runtime.py runtime/packages/case_runtime/tests`
Gated (Compose `postgres`, `postgres-test`, `temporal` up; env
`PROXYLOOP_TEST_DATABASE_URL=postgresql://proxyloop:proxyloop@127.0.0.1:55432/proxyloop_test`,
`PROXYLOOP_TEST_TEMPORAL_ADDRESS=127.0.0.1:7233`): `make postgres-check`,
`make phase05a-check`, `make phase06b1-check`; tear Compose down afterwards.
Static: `make lint`, `make typecheck`, `make format-check`. Final gate (root
runs once on the stable diff): `make preflight`.

## Escalate instead of deciding

Any need to change `contracts.py`, `capabilities.py`, the API surface, the
`CaseTransitionRef` schema version, or the envelope `storage_version`; any
test in the existing suite that must change semantics (not just fixtures);
any case where the frozen design above cannot produce exactly one Provider
commit.

## Review amendments (2026-09-21, after independent review)

- Design item 3 addendum (root decision after review Minor 2): the
  same-command comparison stays `command_id == claim.command_id`, so in
  direct mode — where the API passes no command id (B2-4, deferred to P1)
  — a pin-less approval carrying the old pin is admitted while the claim is
  pending. This is deliberate: the API's exact retry and an arbitrary
  old-pin approval are the same call at the runtime layer, and completing a
  pending claim is idempotent (one Provider commit, the already-approved
  action). The strict form (`command_id is not None and …`) is adopted
  together with B2-4 when direct mode gains command identity.
- Design item 3 note: `decision="rejected"` sent under the *same* command id
  as the pending claim is a different command body and is refused with
  `command id was reused for a different command` (fingerprint check runs
  first); the `approval is already terminal` message applies to a different
  command id with the current pin.
- New item 8: `record_channel_delivery`'s first-callback branch refuses a
  callback while `pending_execution` is true (`ChannelConflictError`), the
  same guard `ingest_channel_event` already applies; the callback is
  replayed after the claim completes. Regression test in
  `tests/integration/test_phase_06b1_channel_runtime.py`.
- Known behaviour change: persisted `pending_execution=True` rows written
  before this change carry no claim record and no longer decode
  (`stored Case payload is invalid`); local demo databases holding an
  in-flight claim from before the change must be reset. `storage_version`
  is unchanged by design.
