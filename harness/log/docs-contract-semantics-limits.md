# Docs log: contract-semantics limits (A-3, A-5, A-9, R-11 (a), R-13 (c))

Spec: `harness/context/docs-contract-semantics-limits-preflight.md`. Branch
`docs/contract-semantics-limits` from `origin/main` @ `74e2073`. No product
behaviour change; no generated contract change.

## What changed, and what each statement was checked against

Line numbers are at `74e2073` plus this diff.

- **A-3, capability vocabulary** (`docs/architecture.md` Model Collaboration
  and Routing and Safety invariants; ADR amendment 2026-09-24 plus a pointer
  sentence at the end of "Capabilities and side effects").
  - Executor binding: `capabilities.py:205-214` (`_find_capability` at
    `:292-302` matches `capability_id` and `version` against
    `snapshot.capability_manifest`; a miss is `unsupported_capability` at
    `:207`, a capability without the intent's `action_type` is
    `capability_action_mismatch` at `:209`).
  - No contract binding: `ActionIntent` (`contracts.py:375-421`) has
    `action_type` and no capability or proposal field; `DelegatedAuthority`
    (`:150`) lists `ActionType`s; the `SlowWorkResult` validator
    (`:1459-1506`) checks case, revisions, and strategy of each action but
    never reads `capability_proposals` against `action_proposals`; the
    coordinator's `validate_slow_result` (`coordinator.py:475-529`) checks
    only created/expiry times per action (`:518-522`).
  - The Safety invariant keeps "MCP/channel capabilities cannot appear in
    accepted model work" because it is contract-enforced:
    `CapabilityReference.namespace: Literal["simulator"]` and the
    `simulator.` prefix check (`contracts.py:968-977`).
- **A-5, `Evidence.content_hash`** (`CONTEXT.md` Evidence; a referent table
  in `docs/architecture.md` Core Domain Contracts; a `#` comment above
  `class Evidence`, `contracts.py:491-496`). Producers checked:
  - quote `provider_message`: `provider.py:94-105`, hash `_quote_hash`
    `:205-218` (compact, key-sorted, default `ensure_ascii`), `source_ref`
    `pine-mobile:offer:pine-value-5g:v1`.
  - channel `provider_message`: `runtime.py:416-427`, `content_hash =
    command.content_hash`; the API sets it to SHA-256 of the UTF-8 content
    (`app.py:594-603`); `source_ref = str(event_id)`.
  - `provider_event`: `runtime.py:633-645`, `content_hash =
    command.artifact_hash`; the API sets `artifact_hash =
    event.raw_payload_hash` (`app.py:617`), which is SHA-256 of the raw
    fixture bytes (`local_mailbox.py:204`); `source_ref =
    provider_message_id`.
  - `confirmation`: `provider.py:188-199`, `confirmation_hash`
    (`domain.py:118-129`, `ensure_ascii=False`, compact, key-sorted over
    `AppliedOfferConfirmation.to_dict()`).
  - `simulator_transition`: `runtime.py:182-192`, SHA-256 of the idempotency
    key, minted in `prepare()` before `commit()`; the ML runner uses a
    different formula (`runner_v2.py:449-460`, fingerprint of the attempt);
    the PostgreSQL codec rebuilds the runtime value to check determinism
    (`postgres_repository.py:1407-1419`).
  - Storage integrity, not verification: on load the codec replays the
    simulator and requires the stored quote (`postgres_repository.py:1176-1184`),
    confirmation (`:1245-1251`), and simulator-transition (`:1252`,
    `:1386-1420`) Evidence to equal the replayed values.
  - `bill`: no producer (grep `EvidenceType.` in `runtime/`).
  - Only completion-verification input: verifier `domain.py:274-275`
    (`evidence_hash_mismatch`); `CompletionReceipt` validator
    `contracts.py:679-704`; snapshot receipt match `contracts.py:1279-1289`.
- **A-9, ephemeral `revision`** (`docs/architecture.md` revision paragraph;
  `CONTEXT.md` Entity Revision). An AST scan of every contract constructor in
  `runtime/packages` and `runtime/services` (tests excluded) shows
  `revision=1` at every construction site of the nine listed types, and no
  `model_copy` updates their `revision` (grep `"revision":`). None is compared
  by revision: the manifest is identified by `manifest_version`
  (`contracts.py:1166`, `:1381-1382`) and its fingerprint (`:1232`). The previous
  architecture sentence said every contract except `Evidence` and
  `FastTurnDecision` carries an Entity Revision, which contradicted the
  `CONTEXT.md` definition (a mutable business entity's history).
- **R-11 option (a), Material Terms** (`CONTEXT.md`; `docs/architecture.md`
  `ProviderOffer`, `ActionIntent`, `ApprovalRequest` bullets;
  `negotiation_catalog.py` `BoundTerms` docstring only).
  - Terms: `material_terms.py:18-32` (monthly price, 12-month total,
    currency, term, features, offer expiry). Effective date, fees, credits
    and applied changes are absent, so the old sentence's "effective date"
    was also dropped.
  - Aggregate fee binding: `offer_policy.py:131-142` (`expected_total =
    monthly*12 + fees - known credits`, else `fee_total_mismatch`); runtime
    approval is built only when `offer_compliance_violations_for_case`
    (`runtime.py:926`, `:1687-1715`) returns nothing. Offer id and revision
    binding: executor `current_offer_mismatch` and approval `offer_ref`
    (`capabilities.py:241-259`, `:327`).
  - Applied changes: `ProviderOffer` (`contracts.py:347-359`) has no such
    field; the runtime policy passes `applied_changes=()`
    (`runtime.py:1712`); the verifier checks the confirmation's applied
    changes after commit (`domain.py:224-241`, `forbidden_change_applied`).
    In the negotiation simulator, `offer_violations` does check applied
    changes on its public offer (`negotiation_catalog.py:332-349`); the
    docstring says so.
- **R-13 option (c), trace retention** (`docs/architecture.md` after the
  PostgreSQL-aggregate paragraph). `model_traces` in `CaseRuntimeState`
  (`repository.py:50`) and `_CaseStorageEnvelope` (`postgres_repository.py:99`);
  every write goes through `_encode_state` and `UPDATE ... SET payload`
  (`:301-313`, `:668`, `:755`); traces are only appended (`runtime.py:505-510`,
  `:982-985`, `:1277`, `:1452`, `:1529`). Direct flow count: 3 commands, 2
  traces (`test_persisted_claim_and_traces.py:390-424`). Channel ingest adds
  refresh plus Fast traces per message (`runtime.py:505-510`;
  `test_persisted_claim_and_traces.py:509-530`). The fix is recorded as
  planned, not implemented.

## `CONTEXT.md` before and after (deliberate ubiquitous-language changes)

Only these three entries changed; every other entry and the file structure
are untouched.

- **Evidence**
  - Before: "An immutable reference to a simulator or controlled external
    artifact used to support facts or completion."
  - After: the same sentence, then "Its content hash is the SHA-256 of the
    canonical bytes of the artifact named by its source type and source
    reference; the referent for each source type is listed in
    `docs/architecture.md`. Only a confirmation's content hash is an input to
    completion verification; a simulator-transition content hash is an executor
    attestation whose value its producer defines, and it must not be relied
    on."
- **Entity Revision**
  - Before: "The optimistic sequence number of one immutable snapshot in a
    mutable business entity's history."
  - After: the same sentence, then "The ephemeral contract values
    `ModelInputPins`, `PlanningBasis`, `VisibleCaseEvent`,
    `CapabilityManifest`, `FastModelView`, `SlowReasonerView`,
    `RoutingDecision`, `SlowWorkRequest`, and `SlowWorkResult` carry a
    `revision` field that the product runtime always writes as 1 and that is
    not an Entity Revision; consumers must not compare it. The write-once
    records `ModelTrace`, `CompletionDecision`, `ExecutionClaim`, and
    `CompletionReceipt` are immutable and have no revision history: their
    `revision` is always 1 and must not be compared either."
- **Material Terms**
  - Before: "The price, fees, credits, effective date, duration, expiry, and
    feature changes whose alteration can invalidate an action or approval."
  - After: "The offer terms an Action Intent and Approval Request bind
    through their material-terms hash: monthly price, 12-month total,
    currency, term, features, and offer expiry; a change to any of them
    invalidates the action or approval. Fees and credits are bound only in
    aggregate, through the 12-month total (policy rejects a total that
    disagrees with the monthly price, fees, and known credits as
    `fee_total_mismatch`) and the exact offer identity and revision the
    approval pins. An approval binds neither the fee breakdown nor the
    changes the Provider will apply: an Offer has no applied-changes field,
    so a forbidden applied change is caught only by the completion verifier
    after execution."

## Tests added

- `tests/integration/test_phase_03a1_agent_core.py`: a
  `capability_action_mismatch` row in
  `test_capability_executor_rejects_unauthorized_requests` (the manifest
  capability allows only `send_message`); it asserts the reason is exactly
  that one code. `unsupported_capability` was already a row of that table
  (added by the approval-ledger fix), so audit B1 N1 is now closed for both.
- `tests/integration/test_contract_semantics_limits.py`:
  - `test_contract_validation_does_not_bind_an_action_to_a_capability`:
    `ActionIntent` has no capability/proposal field; a `SlowWorkResult` with
    an accept-offer action and no capability proposal validates from JSON,
    and `CaseCoordinator.validate_slow_result` accepts it
    (`slow_result_current`).
  - `test_completed_case_evidence_hashes_recompute_from_their_referents`: a
    local-mailbox message, approval, completion, and delivery callback, with
    every write through the PostgreSQL codec (`_CodecChannelRepository` from
    the R-10 test) and real fixture bytes verified by
    `verify_local_mailbox_event`. It asserts the Evidence multiset is exactly
    2 `provider_message`, 1 `simulator_transition`, 1 `confirmation`,
    1 `provider_event`, and recomputes each hash from the table. The channel
    commands are built the way `app.py:583-618` builds them; the API route
    itself is not exercised (it requires Temporal).

These are characterization tests: they pass on the unchanged code, and they
fail if the documented behaviour changes.

No doc-wording pin changed: `tests/contract/test_phase_03a0_architecture.py`
pins no sentence touched here (its ADR markers are all still present).

## Verification (this worktree, no `PROXYLOOP_TEST_*` set)

- New and touched tests:
  `pytest tests/integration/test_contract_semantics_limits.py` 2 passed;
  `-k rejects_unauthorized_requests` in the 03A1 agent-core file 7 passed.
- `make format-check lint typecheck`: exit 0 (after `ruff format` joined one
  f-string in the new test).
- `make contracts-check`: "Contract artifacts match the canonical Pydantic
  source." and `tsc` clean; `git status` shows nothing under `contracts/`.
- `make preflight-fast`: exit 0.
- `pnpm install --frozen-lockfile`, then `make test`: exit 0. Runtime unit
  tests 1203 passed, 51 skipped (the DB/Temporal-gated tests; no
  `PROXYLOOP_TEST_*` set); ML tests 397 passed, 1 skipped; every `*-check`
  target in `test` passed (last line: "Negotiation V2 ceiling report is
  current and its gate passed.").
- After `make test`, the wording "recomputed during verification" was
  narrowed to "completion-verification input" in `CONTEXT.md`, the
  `docs/architecture.md` Evidence paragraph, and the `contracts.py` comment
  (the PostgreSQL codec also replays simulator Evidence for storage
  integrity). Rerun after that edit: `make contracts-check` exit 0,
  `make format-check lint typecheck` exit 0, `make preflight-fast` exit 0,
  and `pytest tests/integration/test_contract_semantics_limits.py
  tests/integration/test_phase_03a1_agent_core.py tests/contract` 134
  passed. The full `make test` was not rerun for this comment-and-docs-only
  edit.
- Not run: `make preflight`, the DB/Temporal gates (`postgres-check`,
  `phase05a-check`, `phase06b1-check`), and independent review.

## Open points for the root orchestrator

- Resolved by root decision (see "Root decision: write-once records" below):
  `ModelTrace`, `CompletionDecision`, `ExecutionClaim`, and
  `CompletionReceipt` are write-once records.
- `simulator_transition` hashes are not a completion-verification input, but
  the PostgreSQL codec rebuilds the runtime's exact quote, confirmation, and
  transition Evidence on load (`postgres_repository.py:1176-1184`,
  `:1245-1252`, `:1407-1419`); changing any producer formula therefore needs a
  storage decision. The architecture text now says so.

## Root decision: write-once records

The root orchestrator decided that `ModelTrace`, `CompletionDecision`,
`ExecutionClaim`, and `CompletionReceipt` are write-once immutable records,
not entities with a revision history, and that their `revision` must not be
compared. They are listed as a second category next to the ephemeral values
in `CONTEXT.md` (Entity Revision) and `docs/architecture.md`.

Producer check before listing (AST scan of every constructor call plus grep
for `"revision":` updates, over `runtime/packages`, `runtime/services`, `ml`,
and `scripts`, tests excluded):

- `ModelTrace`: `coordinator.py:583` and `scripts/run_phase_03a1_harness.py:146`,
  both `revision=1`.
- `CompletionDecision`: `domain.py:282`, `revision=1`.
- `ExecutionClaim`: `runtime.py:1173` and `postgres_repository.py:171` (the
  storage_version 1 upgrade), both `revision=1`.
- `CompletionReceipt`: `runtime.py:1889`, `revision=1`.
- None of the four is ever updated through `model_copy(update={"revision": ...})`,
  and no code reads their `revision`.

The same scan found one exception to the ephemeral list's "always 1": the ML
evaluation runner increments `PlanningBasis.revision` when it rebuilds a basis
(`ml/evaluation/src/proxyloop_evaluation/runner_v2.py:388`, an r4-frozen
path). Nothing reads that value. The product runtime writes 1 at every site.
The `CONTEXT.md` sentence therefore now says "that the product runtime always
writes as 1", and `docs/architecture.md` names the exception.
