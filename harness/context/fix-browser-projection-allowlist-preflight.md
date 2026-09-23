# Fix: the browser receives an allow-listed projection, not the snapshot (P1 E-N1, B2-N1)

Bounded change under `harness/context/audit-remediation-decisions.md`
(decision 9: browser projection is an allow-list). Branch
`fix/browser-projection-allowlist` from `main` @ `dcc2b43`.

## Defect (observed on main)

Every browser route (`POST /cases`, `GET /cases/{id}`, `POST /cases/{id}/events`,
`POST /cases/{id}/approvals/{approval_id}`) returns `_result_payload`
(`runtime/services/api/src/proxyloop_api/app.py:770-810`), which emits the full
`Case.model_dump` as `case` and the full snapshot (minus channel events/evidence)
as `snapshot`: `pins` (`ModelInputPins` with fingerprints), `planning_basis`,
`capability_manifest`, `delegated_authority`, `fact_ledger`, `strategy`, the
full `ActionIntent`s (with `idempotency_key`), plus full `ApprovalRequest`,
`Evidence` and `FastTurnDecision` dumps. `_browser_snapshot_payload` is a
deny-list (it filters channel material only), so any field added to a
canonical contract reaches the browser by default.
`tests/integration/test_phase_06b1_channel_runtime.py:682` even asserts
`snapshot["pins"]` is present.

The Web (`apps/web/lib/runtime-client.ts` `parsePayload`,
`conversation-workspace.tsx`) reads a small subset (explorer inventory):
top-level `case_id, revision, event_cursor, route, execution_count`;
`completion.{decision, evidence_ids}`; `evidence[].evidence_id`;
`approval.{approval_id, case_revision, action_intent_revision, decision,
expires_at, material_terms_hash}`; `snapshot.pending_execution`;
`snapshot.case.{bill_snapshot.monthly_total, bill_snapshot.usage.data_gb,
goal.target_monthly_total, goal.required_features, goal.forbidden_changes,
constraints}`; `snapshot.offers[0].{provider_id, monthly_price, term_months,
features}`. It sends back `revision`, `approval.case_revision`,
`approval.action_intent_revision` and `approval.approval_id`; the
`Idempotency-Key` is client-generated and never read from a response.

## Frozen design

1. **One allow-list projection** in the API: replace `_result_payload` /
   `_browser_snapshot_payload` with explicit builders that construct every
   emitted dict field by field (never `model_dump()` of a whole canonical
   object followed by deletions). Keep the same top-level envelope keys
   (`case_id, case, snapshot, revision, event_cursor, route, approval,
   evidence, completion, execution_count`, optional `fast`) so the route
   contract stays stable; narrow their contents:
   - `case` and `snapshot.case`: `case_id, revision, phase`, `bill_snapshot`
     (only the sub-fields the Web reads plus `currency`/amount structure as
     `Money` needs), `goal` (`desired_outcome, target_monthly_total,
     required_features, forbidden_changes, deadline`), `constraints` (only the
     fields the Web actually reads — determine them from
     `conversation-workspace.tsx`; the implementer must list them in the log).
   - `snapshot`: `revision, event_cursor, phase, pending_execution, case`,
     `offers[]` (`offer_id, revision, provider_id, monthly_price,
     total_cost/fees/term_months/features/expires_at` as present on
     `ProviderOffer`, `material_terms_hash` if the offer carries one),
     `visible_events[]` (non-channel only, as today) projected to
     `event_cursor, actor, event_type, content, occurred_at`,
     `completion` identical to top-level `completion`.
   - `approval`: `approval_id, case_revision, action_intent_revision,
     action_type, decision, requested_at, decided_at, expires_at,
     material_terms_hash, offer_ref{offer_id, offer_revision}`.
   - `evidence[]`: `evidence_id, source_type, observed_at`.
   - `completion`: `decision, evidence_ids, missing_evidence, reason_codes`.
   - `fast` (when present): `dialogue_act, response_text, created_at`.
   Excluded everywhere: `pins`, `planning_basis`, any `*fingerprint*`,
   `capability_manifest`, `delegated_authority`, `fact_ledger`, `strategy`,
   `action_intents`, `idempotency_key`, `provider_config_ref`, channel material.
2. `_channel_result_payload` (mailbox route) is already minimal and is out of scope.
3. **Web**: narrow the TypeScript payload types in `runtime-client.ts` to the
   projection (no field the Web reads is removed; the validator must not
   require any excluded field). Update Web fixtures/tests accordingly.
   No UI behaviour change.
4. Out of scope: a canonical `BrowserCaseProjection` contract or generated TS
   type (target proposal §210 — revisit in the 1.1 bump or the Agent Status
   Bar stage), rendering dialogue, direct-mode routing, any runtime change.

## Regression tests (write first)

- **API (fails on main)**: a new test module (e.g.
  `tests/integration/test_browser_projection_allowlist.py`) driving the API
  with the FastAPI test client through create → event (pending approval) →
  approve, asserting at every step: (a) the exact key set of the envelope,
  `case`, `snapshot`, `approval`, `evidence[]`, `completion`, `fast`; (b) a
  recursive scan finds none of the excluded keys and no key containing
  `fingerprint` or `idempotency`; (c) the round-trip still works (the approval
  POST built only from projected fields succeeds).
- Update `tests/integration/test_phase_06b1_channel_runtime.py:682` to assert
  `pins` is **absent** (intended consequence; say so in the log).
- **Web**: `runtime-client.test.ts` — a payload with only the projected
  fields parses; `make web-check` green.
- Phase 07A demo assertion (`scripts/run_phase_07a_portfolio_demo.py`
  `assert_browser_projection_isolated`) must stay valid; do not weaken it.

## Verification

The new module; `tests/integration/test_phase_06b1_channel_runtime.py`; the
API test modules under `tests/` (find them); `make web-check`;
`make preflight-fast`; real-dependency `make phase06b1-check` and
`make postgres-check` (the API change is exercised there).
