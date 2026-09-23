# Fix: the event paths refresh an expired strategy through Slow (P1 B2-3, B2-5)

Bounded change under `harness/context/audit-remediation-decisions.md`
(decision 10: the 30-minute strategy lifetime is a Slow-refresh trigger, not a
session bound; `strategy.expires_at` does not gate execution; proposal §12 Q3).
Branch `fix/slow-refresh-strategy-expiry` from `main` @ `dcc2b43`.

## Defect (observed on main)

`ThinAgentRuntime._append_event_serialized` and `ingest_channel_event`
(`runtime/packages/case_runtime/src/proxyloop_case_runtime/runtime.py`) call
`CaseCoordinator.advance(..., fast=self._fast)` and never pass `slow`. Every
strategy expires 30 minutes after it is written (`ScriptedSlowAdapter` and
`openai_adapter/outputs.py` both set `created_at + 30 min`). Once it has
expired, `DeterministicRouter._mandatory_slow_reasons` adds `strategy_expired`
and `_select` returns `SLOW_REFRESH` (the event paths never set
`bounded_acknowledgement_allowed`, and an expired strategy forbids Fast anyway);
`advance` returns `SLOW_UNAVAILABLE`; the runtime raises
`ModelRuntimeError("fast")`. Every consumer message and every mailbox message
after T+30 min is refused, so the demo is dead at 30 minutes. The offer lives
one hour (`provider.py` `issued_at + 1 h`), so the Case dies with a valid offer.

B2-5: `strategy.expires_at` does not gate the approval/execution path today
(`_approve_serialized` checks approval and offer expiry only;
`capabilities.py` checks manifest, proposal, capability, intent, offer and
approval expiry but not the strategy's). Decision 10 keeps it that way; this
change pins it with a test so the router and executor keep agreeing.

## Frozen design

1. **One refresh helper in `runtime.py`**, used by both event paths before
   their existing Fast step:
   `_refresh_strategy_if_required(event_snapshot, event, occurred_at) -> CaseContextSnapshot`.
   - Route the event snapshot with `DeterministicRouter` (or
     `CaseCoordinator.advance(..., slow=self._slow)` directly). If the outcome
     is not `SLOW_REFRESH` / `FAST_NOW_AND_SLOW_REFRESH`, return the snapshot
     unchanged (no Slow call — the common path must stay exactly as today).
   - Otherwise call `advance(RouteRequest(...), slow=self._slow)`. Require
     `status is ACCEPTED`, `slow_result is not None`,
     `slow_result.strategy_proposal is not None`, **and** the new strategy's
     `(strategy_id, revision)` differs from the installed one; otherwise raise
     `ModelRuntimeError("slow")` with nothing persisted.
   - Return `_snapshot(...)` with the new strategy, revision
     `event_snapshot.revision + 1`, same phase, offers, approvals, evidence,
     events, manifest. Slow action proposals are ignored (the approval
     is still built by the existing offer-policy path; B1-3/A-4 are separate).
2. **Both event paths** then run their unchanged Fast step on the refreshed
   snapshot (`FAST_NOW`, so the Fast decision and the API `fast` payload stay
   present) and build any approval from it, so the approval and intent pin the
   **new** strategy. Revisions stay monotonic; intermediate snapshots are not
   persisted (as today). `ingest_channel_event`'s outbox pins the new strategy.
   The existing "raise `ModelRuntimeError("fast")`" stays for a Fast failure.
3. **`ScriptedSlowAdapter.reason`** (`agent_core/scripted.py`): when
   `request.view.strategy` is not `None` and has the same computed
   `strategy_id`, return `revision = view.strategy.revision + 1`; otherwise
   unchanged. The first strategy (`case_initialization`) is byte-identical to
   today, so no fixture or ML artifact changes.
4. **No execution gate** on `strategy.expires_at` (B2-5). Do not add one to
   `_approve_serialized`, `_execute_claim` or `capabilities.py`.
5. Out of scope: Router precedence changes, `bounded_acknowledgement_allowed`,
   Fast model text reaching the product, Slow action proposals, the manifest's
   24 h expiry (A-11), the "case approval is terminal" dead end after a
   rejected/expired approval (E-5 family), `schema_version` changes.

## Regression tests (write first; must fail on main where stated)

Runtime-level, in-memory repository with an injectable clock (pattern:
`tests/integration/test_phase_05a_case_runtime.py` `ThinAgentRuntime(repository, clock=...)`),
in a new file `tests/integration/test_slow_refresh_strategy_expiry.py`:

- **T1 (fails on main)**: create at T0; `append_event` consumer message at
  T0+31 min succeeds; the snapshot's strategy differs in `(id, revision)` from
  the T0 strategy, `created_at == T0+31 min`, `expires_at > T0+31 min`; a
  pending approval exists and pins the new strategy id/revision; the result
  carries a Fast decision.
- **T2 (fails on main)**: T1, then approve at T0+40 min → executes exactly
  once, Case complete.
- **T3 (passes on main; pins B2-5)**: create at T0; `append_event` at
  T0+10 min (approval pending under the T0 strategy); approve at T0+45 min
  (strategy expired, offer and approval still valid) → executes exactly once,
  complete. No Slow call is needed.
- **T4 (fails on main)**: the same stale-strategy situation through
  `ingest_channel_event` (reuse the Phase 06B1 channel fixtures/helpers) at
  T0+31 min → accepted; outbox record pins the new strategy.
- **T5**: a Slow adapter whose result is rejected (e.g. returns an expired
  strategy, or the same `(id, revision)`) → `ModelRuntimeError` and the stored
  snapshot revision is unchanged.
- **T6**: an `append_event` before T0+30 min makes no Slow call (count calls
  with a wrapping adapter) and is otherwise unchanged.
- Unit test for item 3 in the existing agent-core test module: a second
  `reason` with the prior strategy in the view returns revision 2 with the same id.

If the Postgres repository round-trips the refreshed strategy without
change, one assertion in the existing `postgres-check` suite is optional, not
required.

## Verification

Focused: `uv run pytest tests/integration/test_slow_refresh_strategy_expiry.py`
and the agent-core/runtime suites; `make preflight-fast`; final
`make preflight`; real-dependency `make postgres-check`, `make phase05a-check`,
`make phase06b1-check` (the change is under `case_runtime`).
