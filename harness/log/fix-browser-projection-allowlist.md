# Fix log: the browser receives an allow-listed projection, not the snapshot (P1 E-N1, B2-N1)

Spec: `harness/context/fix-browser-projection-allowlist-preflight.md`.
Programme: `harness/context/audit-remediation-decisions.md` (decision 9).
Branch `fix/browser-projection-allowlist` from `main` @ `dcc2b43`.

## What changed

- `runtime/services/api/src/proxyloop_api/app.py`: `_result_payload` now
  builds every emitted dict field by field (`_browser_case`,
  `_browser_snapshot`, `_browser_offer`, `_browser_approval`,
  `_browser_completion`, `_browser_money`) and serializes once through
  `TypeAdapter(dict[str, Any]).dump_python(mode="json")` (same `...Z`
  timestamps as before). The deny-list `_browser_snapshot_payload` and its
  now-unused `_is_channel_evidence` / `_is_uuid4_reference` are removed;
  `_is_channel_visible_event` operates on `VisibleCaseEvent`. Top-level
  `evidence` keeps only `simulator_transition` / `confirmation` items on
  both branches (supplied `result.evidence` and the snapshot fallback).
  Routes, handlers and `_channel_result_payload` are unchanged.
- `scripts/run_phase_07a_portfolio_demo.py`: the browser guard's
  `_is_channel_evidence` flags any `provider_message` or `provider_event`
  item (the projection has no `source_ref`, so the former UUIDv4-ref rule
  would let every `provider_message` pass).
- `apps/web/lib/runtime-client.ts`: `RuntimePayload` loses its
  `[key: string]: unknown` index signature and the `JsonObject &`
  intersections; new `RuntimeCaseProjection` / `RuntimeSnapshotProjection`
  and an optional `fast`. Fields `parsePayload` does not validate stay
  `unknown`; validation logic is unchanged. No UI change;
  `conversation-workspace.tsx` untouched.
- Web tests: `runtime-client.test.ts` parses a projection-only payload
  (`hasValidTaskBrief` and `hasValidPendingApproval` true);
  `conversation-workspace.test.tsx` fixture drops `usage: {}`.

## Projected key sets

- Envelope: `case_id, case, snapshot, revision, event_cursor, route,
  approval, evidence, completion, execution_count` (+ `fast` when present).
- `case` / `snapshot.case`: `case_id, revision, phase,
  bill_snapshot{monthly_total{amount_minor, currency}}, goal{desired_outcome,
  target_monthly_total, required_features, forbidden_changes, deadline},
  constraints[]{classification, statement}`.
- `snapshot`: `revision, event_cursor, phase, pending_execution, case,
  offers, visible_events, completion` (`completion` equals the top level).
- `offers[]`: `offer_id, revision, provider_id, monthly_price, total_cost,
  fees[]{name, category, amount}, term_months, features, expires_at`.
- `visible_events[]` (non-channel only): `event_cursor, actor, event_type,
  content, occurred_at`.
- `approval`: `approval_id, case_revision, action_intent_revision,
  action_type, decision, requested_at, decided_at, expires_at,
  material_terms_hash, offer_ref{offer_id, offer_revision}`.
- `evidence[]`: `evidence_id, source_type, observed_at`.
- `completion`: `decision, evidence_ids, missing_evidence, reason_codes`.
- `fast`: `dialogue_act, response_text, created_at`.

Constraints: the Web reads only `classification` and `statement` (plus
array length) in `runtime-client.ts` `hasMatchingHardConstraint`;
`conversation-workspace.tsx` does not read constraints.

## Red → green

New `tests/integration/test_browser_projection_allowlist.py` drives
create → event (pending approval) → GET → approve → GET and asserts exact
key sets, a recursive scan for excluded keys / `*fingerprint*` /
`*idempotency*`, and the approval round-trip from projected fields only.

| Check | Pre-fix | Post-fix |
|---|---|---|
| new module | fails: `case` carries `created_at`, `contract_type`, `consumer_id`, ... | passes |
| excluded-key scan of the event response | `action_intents, approval_requests, capability_manifest, delegated_authority, fact_ledger, idempotency_key, pins, planning_basis, provider_config_ref, strategy` + nine `*_fingerprint` keys | none |

## Test edits (intended consequences, root-approved)

- `test_phase_06b1_channel_runtime.py`: `snapshot["pins"]` → assert `pins`
  absent; `snapshot["evidence"]` → assert `evidence` absent from the
  browser snapshot, and the non-channel-evidence check (exactly one
  `provider_message` with ref `pine-mobile:offer:pine-value-5g:v1`) now
  runs against `state.snapshot.evidence` filtered by the former channel
  rule (`provider_event`, or `provider_message` with a UUIDv4 ref). Added
  API-level checks on the HTTP payload after channel activity: top-level
  `evidence` source types are a subset of `{simulator_transition,
  confirmation}`, and every channel Evidence `evidence_id` and
  `content_hash` (one `provider_message`, one `provider_event`) is absent
  from `json.dumps(payload)`.
- `test_phase_07a_portfolio_demo.py`: guard fixtures use the projected
  shape (no `snapshot.evidence`, no `source_ref`); a top-level
  `provider_message` and a top-level `provider_event` Evidence item are
  each flagged as channel material.
- `test_phase_04a_agent_runtime.py`: `fast.completion_claim` → assert
  absent from the payload; the `not_done` claim status is read from
  `repository.get(...).last_fast_decision`. `bill_snapshot.line_items` →
  assert absent from both projected cases; the exact line items are
  verified on the stored snapshot. All other assertions unchanged.

## Deviations

- The snapshot contract has no `phase`; `snapshot.phase` is
  `snapshot.case.phase`.
- `ProviderOffer` carries no `material_terms_hash`, so offers do not emit
  one.
- `snapshot.evidence` is removed (not in the spec's snapshot key set). The
  Phase 07A demo `assert_browser_projection_isolated` tolerates its absence;
  its evidence rule is tightened (review I-1), not weakened.
- `snapshot.completion` is the synthetic `not_done` object (identical to the
  top-level `completion`) where the snapshot used to carry
  `completion_decision: null`.
- The test's excluded-key list also names `approval_requests` (already
  excluded by the exact snapshot key set).

## Known limits

- Pre-existing Web bug, not fixed here: the Usage cell reads
  `bill_snapshot.usage.data_gb`, but the contract's `UsageProfile` has
  `data_megabytes`; Usage therefore always showed "Runtime fact". The
  projection omits `usage`, so behaviour is unchanged.
- The projection is hand-maintained in the API with matching hand-written
  TS types; no canonical `BrowserCaseProjection` contract or generated type
  (out of scope per spec).
- N1 metadata residue: `event_cursor` / `revision` still count channel
  events, so cursor gaps between visible events reveal channel activity.
  Both are required for CAS and stay.
- The `CaseNotFoundError` / `CaseConflictError` handlers (`app.py:177/182`)
  echo `str(exc)` as `detail`; out of scope, backlog.

## Review

Independent review (`reviewer`): **Approve** with two Important and minor
items. Applied: I-1 (demo browser guard flags any `provider_message` /
`provider_event` Evidence; fixtures on the projected shape), I-2 (API-level
channel-evidence assertions in `test_phase_06b1_channel_runtime.py`), M-1
(source-type filter on both evidence branches). Not applied: M-5 (low
value).

## Checks

- Passed: new module + `test_phase_04a_agent_runtime.py` +
  `test_phase_06b1_channel_runtime.py` + `test_phase_07a_portfolio_demo.py`
  (non-Compose unit tests): 62 passed.
- Passed: runtime contracts/simulator/domain + `tests/contract` +
  `tests/integration`: 687 passed, 42 skipped (DB/Temporal-gated, no
  `PROXYLOOP_TEST_DATABASE_URL`).
- Passed: `make lint`, `make typecheck`, `make preflight-fast`,
  `make web-check` (lint, tsc, vitest 52, next build; web deps installed
  with `pnpm install --frozen-lockfile`).
- Passed (root, final diff): `make preflight` — runtime 687 passed / 42
  gated skips, ML 363 passed / 1 skipped, web 52 passed (one ruff reformat
  of the edited 06b1 assertion first).
- Passed (root, Compose profiles): `postgres-check` 27, `phase05a-check` 31,
  `phase06b1-check` 32.
- Not run: the Phase 07A portfolio demo end-to-end (`make portfolio-demo`)
  and a manual Browser pass; the Web change is type narrowing only and
  `web-check` builds it.
