# ProxyLoop target architecture — proposal (2026-09-21)

Status: proposal; the user decides. Inputs: `docs/research/2026-09-21-repository-audit.md`
(§3 findings, §4 trust table, §5 stages, §8 decisions), the lane reports
`harness/code_review/repo-audit-{A,B1,B2,C,D1,D2,D3,E}.md`, `harness/context/pine-ai-reference.md`,
`docs/architecture.md`, `CONTEXT.md`, `GOALS.md`, both ADRs, `contracts.py`, and the
source seams named below (read to confirm interfaces, not re-audited). Labels:
**observed** = read in this worktree; **inferred** = follows from observed facts;
**proposed** = this document's recommendation. Finding ids are the lane reports'.

## 1. Scope and stance

This proposes the target shape for a runnable Pine-style demo on the existing core and
the migration to it, realising audit §5 Stages 1–6 (changes to §5 are flagged inline).
Kept unchanged (audit §4 "keep"): `contracts.py`/`_base.py` (19 of 23 contracts),
`telecom_domain/domain.py` and `offer_policy.py`, `agent_core/router.py`,
`coordinator.py`, `scripted.py`, `interfaces.py`, `case_runtime/commands.py` and
`repository.py`, the PostgreSQL revision CAS, `openai_adapter/adapter.py` fail-closed
transport, `hosted_rerun.py`/`replay_v2.py`, `provider.py`/`episode.py`,
`connectors/local_mailbox.py`, `apps/web/lib/runtime-client.ts`, the Make/CI gates.
Rewritten: `environment.py` verifier, r1 `runner.py` (retired), `validity_smoke.py`,
the leakage measurement. Everything else is refactor at the seams.
Differentiator versus Pine's public surface (reference card, verified): a typed
pre-action `ApprovalRequest` pinned to offer revision, material-terms hash and expiry,
at-most-once execution with a persisted claim, and `Evidence` + deterministic
`CompletionDecision` verified against Provider state — none of which Pine documents.

## 2. System overview

```
 Web (Next.js)                       Runtime (FastAPI)            Durable lane (Temporal + PostgreSQL)
 free-text intake ──POST /intake──▶ Slow: ConsumerGoal proposal ─▶ user confirms typed goal
 typed goal/confirm/approve ─────▶ apply_command(CaseCommand) ──▶ CaseWorkflow Update ─▶ activity ─▶ ThinAgentRuntime
 GET BrowserCaseProjection ◀────── allow-list projection ◀──────── PostgreSQL aggregate (CAS, receipts, claim, ledger)
                                          │
                                          ▼
                    CaseContextSnapshot (immutable, pinned) ──▶ render_status_block() ──▶ Fast view / Slow request
                                          │
                                   DeterministicRouter (precedence table, + strategy_basis_incompatible)
                                     │ fast_now / fast_now_and_slow_refresh          │ slow_refresh
                                     ▼                                               ▼
                         Fast (Talker) adapter                          Slow (Reasoner) adapter
                         FastTurnDecision: dialogue only                SlowWorkResult: strategy + ≤1 capability proposal
                         validate_fast_result + disclosure gate         validate_slow_result (pins, hash self-consistency)
                                     │                                               │ (consequential proposal types only)
                                     │                                        Judge adapter → JudgeVerdict (advisory, ≤1 retry)
                                     │                                               ▼
                                     │                     deterministic gate: offer_policy + compile → ActionIntent(capability)
                                     │                                               ▼
                                     │                                  ApprovalRequest (pinned) ─▶ Consumer decision
                                     │                                               ▼
                                     │             CapabilityExecutor (approval ledger, terms from snapshot offer, at-most-once
                                     │             via persisted ExecutionClaim) ─▶ Provider simulator (state machine authoritative;
                                     │             LLM counterpart only speaks) ─▶ Evidence(confirmation) ─▶ verify_completion(state)
                                     ▼                                               ▼
                         visible_events (Provider turns + assistant text)   CompletionDecision → CompletionReceipt → projection
```

**Web / intake** (`apps/web`). Owns the conversation surface and the truthful state
machine; never infers success from text. Changes: consume `BrowserCaseProjection`
(E-N1/B2-N1), surface 409 categories, poll exhaustion, and the pending-execution retry
(E-1, E-2, E-3), never re-offer confirm on `blocked` (E-5), free-text intake with a typed
confirmation card replacing the four-regex wizard (E §5), render `visible_events` and
assistant text (A-4), reject control (E-N5). Stays: `runtime-client.ts` envelope
validation, monotonic guard, persisted exact pending command.

**Case Runtime** (`case_runtime`, durable via `workflow_worker` + `postgres_repository`).
Owns the serialized write lane, receipts, the claim, and recovery. Changes: claim
receipt persisted in the claim write and same-command retry re-drives `_execute_claim`
regardless of `expected_revision` (B2-1/C-1); recovery verifies with the persisted
claim time (B2-2); envelope accepts every `CompletionOutcome` and non-COMPLETE is not
terminal (C-2); `append_event` routes `slow_refresh` to `self._slow` (B2-3); direct
mode goes through `apply_command` (B2-4); timer path never fails the run (C-3);
manifest minted per snapshot (A-11). Stays: `commands.py`, `repository.py`, CAS,
receipts-in-transaction, channel tables.

**Deterministic Router** (`agent_core/router.py`). Stays the single scheduling
authority (precedence matches ADR :95-104, B1 §1). Changes: computes
`strategy_basis_incompatible` from `StrategyPacket.planning_basis_fingerprint` (A-1);
event classification moves from the caller's `mandatory_slow_reason_codes` to a typed
`event_type` (A-1 direction); `WAIT_FOR_APPROVAL` keys on approval state, not the
event label (B1-12); `TERMINAL` checks `completion.decision is COMPLETE` (C-2, N11).

**Fast (Talker) and Slow (Reasoner) seams** (`agent_core/interfaces.py`,
`openai_adapter`). Both read one `CaseContextSnapshot` rendered by one deterministic
`render_status_block()` (Pine "Agent Status Bar", verified; today two sentences plus a
JSON dump, B1-N6). Changes: Fast `response_text` is delivered as dialogue under a
deterministic disclosure gate instead of being rejected unless constant (A-4,
`runtime.py:443-448`); Slow proposals compile through the manifest (B1-3) with the one
hash owner (B1-4). Stays: fail-closed transport, `max_retries=0`, pins echo.

**Judge** (new `openai_adapter/judge.py`, protocol in `agent_core/interfaces.py`;
Pine-derived, verified). Reviews an accepted `SlowWorkResult` before the deterministic
gate for quality defects only; advisory `JudgeVerdict`; at most one Slow retry; never an
authority, completion signal, or evaluation metric (D2-1 is the failure mode avoided).

**Deterministic policy / ApprovalRequest / CapabilityExecutor** (`telecom_domain`,
`agent_core/capabilities.py`). Changes: executor keeps an `approval_id → evidence`
ledger and rejects `approval_already_consumed` (B1-1); derives terms from the snapshot
offer and rejects `current_offer_terms_mismatch` (B1-2); idempotency evidence is
persisted, not a process dict (C-1, B1-10); `ActionIntent` carries a
`CapabilityReference` (A-3). Stays: `validate_approval_use`, `verify_completion`,
`offer_compliance_violations`.

**Provider simulator** (`provider_simulator`). Changes: verifier by state per action
(D1-3), constraints from the scenario's Case (D1-4), one unsupported-change list from
`offer_policy` (D1-7), content-free ids (D1-1), N-turn episodes with an LLM counterpart
that speaks but never decides state (D1-9, TalkAct `simuser.py` pattern, verified),
behavioural configurations (D1-5), real forgery/multi-hazard or removal from
`SAFETY_FAMILIES` (D1-6, D1-8). Stays: `FictionalMobileProvider` offer state machine.

**Evidence → completion → projection**. Stays: `verify_completion`. Changes:
`content_hash` = hash of the referenced artifact, `EvidenceType.EXECUTION_CLAIM` for the
pre-execution record (A-5, B2-N2); `CompletionReceipt` canonical (A-6); allow-list only.

## 3. Control flow for one negotiation

Revision boundaries are the repository CAS on `CaseContextSnapshot.revision`; every
POST carries `Idempotency-Key` = `CaseCommand.command_id` in both modes (decision 8).

1. User types a goal in their own words. Web `POST /intake/proposals {text}` → Runtime
   calls Slow with `IntakeRequest(text_hash, allowed_fields)`; Slow returns a typed
   `ConsumerGoalProposal` (target, required features, forbidden changes, deadline). No
   Case exists yet; nothing is persisted but the trace.
2. Web shows the proposal as a confirmation card; the user edits or confirms. Confirm →
   `POST /cases` with `CaseCommand(CREATE_CASE, command_id=k1, typed facts,
   intake_text_hash)`. Creates `Case` rev 1, `ConsumerGoal`, `Constraint`s,
   `DelegatedAuthority`, `FactLedger` rev 1, `CapabilityManifest` (minted per snapshot).
3. Router on the initial snapshot → `slow_refresh(case_initialization)`. Slow receives
   `SlowWorkRequest` (status block + `SlowReasonerView`) and returns `SlowWorkResult`
   with `strategy_proposal` carrying `planning_basis_fingerprint = pins.planning_basis_fingerprint`.
   `validate_slow_result` accepts; strategy installed; snapshot rev 2; receipt `k1`.
4. Provider turn 1 arrives (simulator counterpart speaks; the state machine issues
   `ProviderOffer` rev 1 + `Evidence(provider_message)`). Appended as
   `VisibleCaseEvent(actor=provider, event_type=provider_message, payload=ProviderTurnPayload)`.
   The material offer set changed → planning basis changes.
5. Router → `fast_now_and_slow_refresh(strategy_basis_incompatible, material_offer_change)`
   because the installed strategy permits a bounded acknowledgement. Fast returns an
   acknowledgement only (allowlist §7) delivered as `VisibleCaseEvent(actor=system,
   event_type=assistant_message)`; Slow runs on the same snapshot pins.
6. Slow returns strategy rev 2 + one `CapabilityProposal(simulator.accept_fictional_offer,
   offer_position=0)`. Pins current → accepted. Proposal type is consequential → Judge.
7. Judge reviews `(status block, SlowWorkResult)` → `JudgeVerdict(approve)` or
   `revise(reason_codes)`. On `revise`, one Slow retry with
   `SlowWorkRequest.revision_feedback=reason_codes`; the second result is final. Verdict
   and both results are recorded as `ModelTrace(role=judge|slow)`; nothing else changes.
8. Deterministic gate: `offer_compliance_violations(OfferComplianceContext(case),
   terms(offer))`; if violations → no intent, Router reroutes (Fast may say the offer
   does not meet the constraints — a material statement allowed only because it is
   derived from policy output, not model text). If compliant → `compile_slow_output`
   resolves the manifest definition by `allowed_action_types` (B1-3) and builds
   `ActionIntent(capability=CapabilityReference, material_terms=offer_material_terms(offer),
   material_terms_hash=material_terms_hash(...), idempotency_key=f"{case_id}:{approval_seed}")`.
9. `ApprovalRequest` pinned to `(case_revision, action_intent_revision, strategy,
   constraint_set_revision, offer_ref, material_terms_hash, expires_at=min(offer.expires_at,
   requested_at+window))`; phase `AWAITING_APPROVAL`; snapshot rev N; `Provider.await_approval`.
   Web renders the approval card with exact pins and a reject control.
10. While awaiting approval only `event_type=consumer_note` is accepted, routed `fast_now`
    under the bounded template; anything material waits.
11. User approves → `POST /approvals/{id}` with `CaseCommand(DECIDE_APPROVAL, command_id=k2,
    expected_revision=N, expected_case_revision, expected_action_intent_revision)`.
12. Claim write (one CAS, rev N→N+1): approval `APPROVED`, `pending_execution=True`,
    `execution_claim=ExecutionClaim(command_id=k2, approval_id, intent_id, idempotency_key,
    before_revision=N, claimed_at=decided_at)`, and a `CaseTransitionRef(command_id=k2,
    stage="claimed", terminal=False)` receipt in the same row.
13. Executor: ledger lookup by `approval_id` (none) → `_validate` (strategy pins,
    authority, approval binding, manifest, offer revision, **terms derived from snapshot
    offer equal intent terms**) → `adapter.prepare` → `commit` → ledger
    `record(approval_id, idempotency_key, binding, evidence)` in the same transaction as
    the final write when the repository is PostgreSQL (see §6).
14. Provider commits: `execute_approved_offer` → `AppliedOfferConfirmation` + `Evidence(confirmation)`.
15. `verify_completion(evaluated_at=claim.claimed_at)` against Provider state → `CompletionDecision`.
16. Final write (rev N+1→N+2): evidence appended, `pending_execution=False`, phase
    `COMPLETE` iff decision is `COMPLETE` else `NEGOTIATING` with the decision retained;
    receipt `k2` becomes `stage="applied", terminal=<decision is COMPLETE>`.
17. Router on the final snapshot → `terminal` (COMPLETE) or `slow_refresh(verifier_needs_replan)`
    / `wait_for_user(needs_user)`.
18. `CompletionReceipt` (old/new price, 12-month total, plan, removed add-ons, fees,
    term, effective date, confirmation id, approval id/revision) is projected; the Web
    shows the receipt only when `completion.decision == complete`, `execution_count == 1`,
    and the evidence ids match.

**Retry side-branch (lost response after step 13/14; B2-1/C-1 fix).** The Web or the
Temporal activity re-sends the same `CaseCommand` (`command_id=k2`, same body incl.
`expected_revision=N`). `apply_command` finds receipt `k2` with `stage="claimed"` →
fingerprint check → **skips `_check_expected_revision`** and calls
`_execute_claim(state)`. The executor's ledger lookup by `approval_id` returns the
recorded evidence → `REUSED`; the Provider is not touched (with PostgreSQL the Provider is
reconstructed as `confirmed` from the ledger row, not as `awaiting_approval`); verification
uses `claim.claimed_at`; final write proceeds; the second call returns the terminal
receipt. Any other command in this state → 409 `case_execution_pending`.

## 4. Contract changes

One `schema_version` bump `"1.0" → "1.1"` (decision 11), landing as the first PR of
Stage 3; Stage 1 stores its claim runtime-locally until then (§10). Historical artifacts
stay at 1.0: the 1.0 models are frozen as `proxyloop_contracts.v1_0` (import-only, used
by `replay_v2`/`hosted_rerun --check`), and `validate_contract_json` accepts both
versions through the discriminated union. Generated JSON Schema and TypeScript regenerate;
`tests/fixtures/*.json` regenerate at 1.1 with the invalid-fixture set extended.

| Change | Field-level sketch | Producer → consumer | Fixture / artifact migration |
|---|---|---|---|
| A-1 `StrategyPacket` basis binding | `+ planning_basis_fingerprint: Sha256` (required). Snapshot validator: if `strategy` present it is recorded, not required equal — inequality is the Router trigger `strategy_basis_incompatible`. Optional narrowing in the same bump: `material_offers_fingerprint` over `(offer_id, revision, material_terms_hash)` of unexpired offers; `approval_state_fingerprint` over `(approval_id, decision)` excluding `EXPIRED` (A-10 materiality). | Slow compilers (`outputs.py`, `scripted.py`, ml `slow_output.py`) → Router | regenerate `case.valid.json`-derived fixtures; scripted strategies recomputed |
| A-2 `ModelTrace` emit (diverges from decision 11's "delete"; rationale §12 Q2) | `+ role: Literal["fast","slow","judge","intake"]`, `+ reason_codes: tuple[ExternalRef,...]`, `+ input_pins: ModelInputPins`, `+ request_id: EntityId | None`; keep provider/model/prompt/latency/tokens/result/safety_flags. Persisted on `CaseRuntimeState.model_traces`, never on the snapshot or in any view. | `CaseCoordinator.advance` (one per adapter call, incl. rejected) → repository, `ml PromptProvenance`/`HostedCallEvidence` become projections | none committed today (A-2); new negative fixture |
| B1-4 material terms: one owner | `contracts.material_terms(offer: ProviderOffer) -> tuple[MaterialTerm,...]` (the 6 names from `domain.py:123-137`) and `contracts.material_terms_hash(terms)`; `ActionIntent` validator: for `accept_offer`, `material_terms` names == the canonical 6 and `material_terms_hash == material_terms_hash(material_terms)`. `domain.py` re-exports; `capabilities._material_terms_hash`, `outputs._material_terms`, ml `slow_output` copies deleted. | contracts → domain, executor, compilers, verifier | intent fixtures regenerated; committed r2–r5 prompt fingerprints unaffected (prompts do not include intents) |
| B1-9 non-negative money | `LineItem`: `amount.amount_minor >= 0` unless `category is CREDIT` (then `<= 0`); `ProviderOffer.fees[*].category ∈ {FEE, TAX}` and `>= 0`. | contracts → verifier (`domain.py:246-254` no longer raises) | fixtures re-validated; scenario generator asserts |
| B2-1 claim receipt | new `ExecutionClaim(VersionedContract)`: `contract_type="execution_claim"`, `case_id`, `command_id: EntityId`, `approval_id`, `action_intent_id`, `idempotency_key: ExternalRef`, `before_revision: Revision`, `claimed_at: UtcDateTime`. `CaseContextSnapshot + execution_claim: ExecutionClaim | None`; validator `pending_execution == (execution_claim is not None and completion_decision is None)`. | `ThinAgentRuntime` claim write → executor, recovery, projection | new valid/invalid fixtures |
| C-2 completion persistence | no field change; semantics: `completion_decision` is "latest verifier result"; terminal iff `decision is COMPLETE` or phase ∈ {COMPLETE, CLOSED}. Envelope accepts all five outcomes. | runtime → API, Router, envelope | envelope test matrix |
| B2-N1/E-N1 projection allow-list | new `BrowserCaseProjection(VersionedContract)`: `case_id, revision, event_cursor, phase, route, goal{target, current_total, required_features, forbidden_changes}, offer{offer_id, revision, provider_id, monthly_price, total_cost, fees, term_months, features, expires_at, material_terms_hash} | None, approval{approval_id, case_revision, action_intent_revision, material_terms_hash, expires_at, decision} | None, execution{pending, count, claimed_at}, completion{decision, evidence_ids, reason_codes} | None, receipt: CompletionReceipt | None, dialogue: tuple[DialogueLine{cursor, actor, kind, text, occurred_at}], disclosure_notice: HumanText, error_category: ExternalRef | None`. Excludes pins, fingerprints, `idempotency_key`, manifest, authority, strategy internals, fact ledger, channel material. | `services/api` `_result_payload` → `runtime-client.ts` (generated TS type) | Web fixtures regenerated |
| D3-2 event content typing | `VisibleCaseEvent`: `content: HumanText` must not parse as a JSON object/array (validator); `+ payload: ProviderTurnPayload | None` with `offer_refs: tuple[OfferReference,...]`, `requested_disclosures`, `clarification_required`, `transfer_available`. Prompt guards recurse typed fields and scan string values. | simulator/runtime → views, guards | 03B example views regenerated (D3-2), `phase-02` rows regenerated |
| A-3 capability binding | `ActionIntent + capability: CapabilityReference`; `SlowWorkResult` validator: every `action_proposals[i].capability` names a `capability_proposals` entry; `CapabilityDefinition + arguments: tuple[CapabilityArgumentSpec{name, kind: Literal["offer_position","offer_id","text"]}]`. | compilers → executor | intent fixtures |
| A-6 receipt | `CompletionReceipt(VersionedContract)` = `AppliedOfferConfirmation` fields + `approval_revision`, `confirmation_evidence_id`; `content_hash` of `Evidence(confirmation)` = hash of the receipt's canonical JSON. | provider/runtime → verifier, projection | new fixture |
| A-5 evidence referent | docstring + `EvidenceType.EXECUTION_CLAIM` for the pre-execution record (`source_ref=idempotency_key`); `content_hash` for all other types = SHA-256 of the artifact's canonical JSON. | runtime, provider → verifier | envelope evidence check updated |
| Judge | `JudgeVerdict` is **not** canonical: strict pydantic model in `agent_core/judge.py` (`verdict: Literal["approve","revise"]`, `reason_codes: tuple[JudgeReason,...]`, `request_id`, `pins`). Only its `ModelTrace` persists. `SlowWorkRequest + revision_feedback: tuple[ExternalRef,...] = ()` (additive). | coordinator → Slow retry, trace | none |
| Intake | `ConsumerGoalProposal` **not** canonical (API request/response model in `services/api`); the Case is created only from confirmed typed facts. | Slow → Web | none |

## 5. Module-by-module design

Format: responsibility → public interface (≤ 8) → invariants and tests → deletions →
size → findings resolved.

**`contracts`.** Wire contracts plus pure canonical functions. Adds `material_terms`,
`material_terms_hash`, `ExecutionClaim`, `CompletionReceipt`, `BrowserCaseProjection`,
`ProviderTurnPayload`, the A-1/A-3/B1-9/D3-2 validators, `v1_0` frozen module.
Invariants tested by negative fixtures for every new validator (today zero negative
tests for the 03A1 validators, A §3): pins mismatch, basis component mismatch, JSON in
`content`, negative fee, missing capability reference, claim/pending inconsistency.
Deletes: nothing on the wire except `Literal["proposed"]` staying as documentation.
Size M. Resolves A-1, A-2, A-3, A-5, A-6, B1-4, B1-9, B2-1 (contract half), D3-2, E-N1.

**`telecom_domain`.** Unchanged verifier and policy; becomes the *only* label
authority (decision 3). Interface: `offer_compliance_violations(context, terms)`,
`OfferComplianceContext.from_case(case, evaluated_at)` (new; replaces the duplicate
`_OfferComplianceContext` in `observation.py`, B1-5 note), `validate_approval_use(...)`,
`verify_completion(request)`, `UNSUPPORTED_APPLIED_CHANGES` (one list, D1-7),
`KNOWN_CREDITS_MINOR` (one constant, B1-11). Invariants: `verify_completion` checks
`offer.case_id == case.case_id` (B1-8); negative fees decide, never raise (B1-9).
Tests: existing adversarial suite + boundary cases B1 §3 lists. Size S. Resolves
B1-8, B1-9, B1-11, D1-7.

**`agent_core`.**
- `router.py`: `DeterministicRouter.route(RouteRequest)`; `RouteRequest.triggering_event`
  typed `event_type ∈ CaseEventType` enum (`consumer_message, consumer_note, provider_message,
  provider_refusal, approval_decision, executor_evidence, verifier_result, goal_change`);
  `_mandatory_slow_reasons` adds `strategy_basis_incompatible`, `material_offer_change`,
  `provider_refusal`, `verifier_needs_replan`; `WAIT_FOR_APPROVAL` decided by approval
  state (B1-12); `TERMINAL` requires `COMPLETE` (N11). Tests: one fixture per precedence
  row through the real Router, replacing `test_phase_03a0_architecture.py` greps (A §3).
- `coordinator.py`: `advance(request, *, fast, slow, judge=None) -> CoordinatorOutcome`
  adds `judge_verdicts`, `traces: tuple[ModelTrace,...]`; `validate_slow_result` checks
  intent hash self-consistency and capability∈manifest (B1-4, B1-3); `validate_fast_result`
  adds the disclosure gate (§7). Delete `compare_and_swap`/`_current_snapshot` (B1-N8).
- `capabilities.py`: `CapabilityExecutor(adapter, ledger: ExecutionLedger, terms_of=material_terms)`;
  `execute(CapabilityExecutionRequest) -> CapabilityExecutionOutcome`. Invariants: one
  execution per `approval_id` (`approval_already_consumed`), terms derived from
  `snapshot.offers` must equal `intent.material_terms` (`current_offer_terms_mismatch`),
  pending marker before `commit` (B1-10). Tests: `b1_exec_1/3` repros as regressions plus
  the ten unasserted reject reasons (B1-N1).
- `observation.py`: `ScriptedOracleConsumer(offer_policy=...)` becomes required-injected
  with `offer_compliance_violations` as the only implementation; delete
  `_legacy_offer_is_valid` and `_OfferComplianceContext` (B1-5/D1-2).
- `judge.py` (new): `JudgeAdapter` protocol `review(JudgeRequest) -> JudgeVerdict`;
  `judge_required(result: SlowWorkResult) -> bool` (rule in §7).
Size L. Resolves A-1 (router half), A-4 (wiring), A-8, B1-1, B1-2, B1-3 (validation),
B1-5, B1-10, B1-12, D1-2, B1-N8.

**`case_runtime`.**
- `runtime.py`: `apply_command(CaseCommand) -> CaseTransitionRef` recognises
  `stage="claimed"` receipts and re-drives; `append_event(..., event_type)` calls
  `advance(fast=self._fast, slow=self._slow, judge=self._judge)` and derives the intent
  from the accepted proposal (never `offers[0]`, A-4/B2-3); `approve(...)` writes the claim
  receipt; `intake_proposal(text) -> ConsumerGoalProposal`; `expire_approval` unchanged;
  `_execute_claim` takes `claimed_at` from the claim (B2-2) and constructs the executor
  with the repository ledger (no `_executors` cache, C-1). `strategy.expires_at` becomes
  a Slow-refresh trigger, not a session bound or an execution gate (decision 10, B2-5,
  §12 Q3). Manifest minted per snapshot, expiry = approval window (A-11). Delete
  `_repeat_approved`'s mode-divergent 200 (B2-4).
- `commands.py`: `CaseTransitionRef + stage: Literal["claimed","applied"] = "applied"`;
  `CaseCommandType + INTAKE_PROPOSAL` is **not** added (stateless, no Case); `APPEND_EVENT`
  gains `event_type ∈ {consumer_message, consumer_note}`. Validator branches tested (2/20 today).
- `repository.py`: `ExecutionLedger` protocol `get(approval_id) -> LedgerEntry | None`,
  `record(entry)`; `CaseRuntimeState + execution_claim, model_traces`; in-memory ledger.
- `postgres_repository.py`: envelope accepts §6 state list; ledger row in the same
  transaction as `replace`; `_reconstruct_provider` uses the ledger to rebuild
  `confirmed` (C-1 Q1); `_encode_state` persists traces and claim.
Size L. Resolves B2-1, B2-2, B2-3, B2-4, B2-5, B2-6, B2-7, B2-9, C-1, C-2, A-11.

**`openai_adapter` (+ `judge`).** `decide/reason` unchanged in shape; `_messages` →
`render_status_block(snapshot|view) -> str` from new `agent_core/status_block.py`, shared
with ml prompt builders (B1-N6); `compile_slow_output` resolves the capability by
`allowed_action_types` and uses `contracts.material_terms` (B1-3, B1-4); `judge.py`:
`OpenAIJudgeAdapter.review` with `JudgeModelOutput`; exact model match (B1-6); pydantic
errors → `invalid_output` (B1-7). Delete `_material_terms`. Size M. Resolves B1-3, B1-4, B1-6, B1-7, B1-N6.

**`provider_simulator`.**
- `environment.py` (rewrite): `ProviderEnvironment(scenario, case_context: OfferComplianceContext)`;
  `verify(decision) -> ScenarioVerification{state_safe, valid_outcome, completed,
  false_completion, reason_codes, reference_match}`; per-action predicates (§8). Delete
  label equality and `CASE_*` reads.
- `scenarios.py`: `ScenarioParameters` (03C Stage 1a), `BenchmarkScenario + case: Case`,
  public ids = `uuid5(salt, index)` with `DEFAULT_PARAMS` preserving today's *scenario_id*
  strings for artifact checks while `offer_id/turn_id/evidence_ref` become content-free;
  configurations change behaviour (`retention-gated-v1` withholds the offer until a
  retention ask; D1-5); `forged-evidence` carries a tampered `confirmation_evidence_ref`
  hash (D1-6); `multi-hazard` has three detectable hazards with `transfer_available=False`
  variants (D1-8); disclosure ask originates in the Provider turn (D1-13).
- `multi_turn.py` → `negotiation.py`: `NegotiationEpisode(scenario, counterpart: ProviderCounterpart, max_turns)`;
  `start()`, `submit_consumer_message(text) -> Transition`, `submit_capability_attempt(attempt)`,
  `export_public_episode()`; `ProviderCounterpart.speak(public_state, history) -> str`
  with `ScriptedCounterpart` and `LLMCounterpart(adapter)`; text consistency check
  (every currency amount in text ⊆ state amounts) rejects and regenerates.
- `splits.py`: membership by hashed family id, not alphabetical (D1-10).
Size L. Resolves D1-1, D1-3, D1-4, D1-5, D1-6, D1-7, D1-8, D1-9, D1-10, D1-11, D1-12, D1-13.

**`connectors`.** Code unchanged; docs say "unkeyed SHA-256 integrity, no authentication" (C-6). Size S.

**`services/api`.** `POST /intake/proposals`, `POST /cases`, `POST /cases/{id}/events`,
`POST /cases/{id}/approvals/{approval_id}`, `GET /cases/{id}` returning
`BrowserCaseProjection` only; all POSTs build a `CaseCommand` from `Idempotency-Key`
and call `apply_command` in both modes (B2-4); handlers `def` or `run_in_threadpool`
(B2-8); 409 body carries `error_category` from a closed enum incl. `case_execution_pending`,
`case_awaiting_approval`, `case_terminal`, `revision_stale`, `approval_expired`,
`model_unavailable`; placeholder completion removed (B2-6). Update ID for channel
events not fixed at reservation (C-4). Size M. Resolves B2-4, B2-6, B2-8, C-4, E-N1.

**`services/workflow_worker`.** `_expire_pending` wraps `_execute_command` in
`try/except ActivityError` → exponential backoff, re-arm, never raise from `run()`;
`case_conflict` on expiry means the approval moved → drop the timer; client uses
`ALLOW_DUPLICATE_FAILED_ONLY` as defence in depth with `run()` re-deriving
`_last_transition` from a read activity when started with `resume=True` (C-3). Size M.
Resolves C-3, C-4.

**`apps/web`.** Split `conversation-workspace.tsx` into `intake/`, `negotiation/`, `approval/`, `receipt/`,
and a pure tested `state-machine.ts`; `runtime-client.ts` validates `BrowserCaseProjection` by generated
type; phases in §9. Size L. Resolves E-1…E-11, E-N1, E-N5, E §5.

**`ml/evaluation`.** `runner_v2` metric redefinition (§8), `conditions.py` matrix
`fast_only | sequential | duplex | slow_only`, `leakage.py` value-level scan
(JSON-in-string aware) used by `artifacts_v2`, `openai_frontier._assert_prompt_allowlist`,
and a `qwen_mlx` wrapper (`qwen_mlx.py` frozen by the r4 execution contract, D3 §1);
`validity_smoke.py` rewritten as "rule-following under oracle-flag parity" with the
rule table removed from the prompt (D2-1); `run_phase_03a1_validity_smoke.py --check`
replays through `replay_condition_v2` (D2-2); `runner.py`, `replay.py`, `artifacts.py`
retired from `make test` and marked historical (D2-5, decision 5); `phase03b_readiness`
compares to the committed manifest (D3-4). Size L. Resolves D2-1, D2-2, D2-3, D2-5,
D2-7, D2-8, D2-9, D3-2, D3-3, D3-4, D3-9.

**`ml/data_pipeline`.** Rows rendered from views/status block, never `SafeObservation`;
`_forbidden_keys` → value-level scan; curation accepts external rows through the 03C Stage 1
F1–F5 filters instead of regeneration equality (D3-N1); reason codes fixed (D3-7). Size M.
Resolves D3-1, D3-7, D3-N1.

## 6. Durability and recovery semantics

**Claim receipt (proposed).** Written in the claim CAS, same row/transaction as the
snapshot: `ExecutionClaim{command_id, approval_id, action_intent_id, idempotency_key,
before_revision, claimed_at}` on the snapshot and `CaseTransitionRef{command_id,
stage="claimed", before_revision, after_revision, terminal=False}` in `transitions`.
The final write replaces the receipt with `stage="applied"`. The claim is the only place
the execution time basis lives; recovery never uses `clock_now()` (B2-2).

**Retry contract.** `apply_command(c)`: (1) receipt with `c.command_id` and
`stage="applied"` → fingerprint check → dedup return. (2) receipt with `stage="claimed"`
→ fingerprint check → `_execute_claim(state)` **without** `_check_expected_revision`,
because the claim already consumed the caller's `expected_revision`. (3) no receipt and
`pending_execution` → 409 `case_execution_pending` for every command type except
`DECIDE_APPROVAL(approval_id == claim.approval_id, decision=approved)`, which is treated
as (2) (covers a client that lost its command id). `EXPIRE_APPROVAL` during a claim →
`applied` no-op receipt. Temporal classifies `case_execution_pending` as retryable with
backoff; `activities.py` maps `RuntimeError("Provider commit returned no confirmation")`
out of existence because the ledger rebuilds the Provider as `confirmed`.

**Executor approval ledger.** `LedgerEntry{approval_id, idempotency_key, binding,
evidence, recorded_at}`; `execute` order: ledger lookup by `approval_id` → same key and
binding → `REUSED`; different key or binding → `REJECTED(approval_already_consumed)`;
none → validate → prepare → `record(pending=True)` → commit → `record(evidence)`. With
PostgreSQL the record is a row in the Case transaction; in memory it is a dict on the
repository, not on the executor (C-1: no process-local cache). Replay after approval
expiry returns `REUSED` (B1-N10, documented).

**Timer path.** `_expire_pending` failure never propagates: `ActivityError` → log,
`await workflow.sleep(min(2**n, 300) s)`, re-check `_last_transition`, retry; a
`case_conflict` result means the approval was decided or expired by another command →
clear the timer. Workflow stays `RUNNING`; C `c3` ends with approval `expired` once the
DB returns.

**Workflow-id reuse.** `workflow_id = proxyloop-case/{case_id}`; `REJECT_DUPLICATE`
while running; `ALLOW_DUPLICATE_FAILED_ONLY` so a failed run (should no longer occur) can
be recreated by Update-with-Start; `run()` re-derives `_last_transition` from
`read_case_transitions_activity` when `input.resume` is set. Update ID = command id
stays; a channel event whose first dispatch conflicted gets a fresh command id at
re-dispatch (C-4).

**PostgreSQL envelope must accept** (CAS on `revision`): (a) no approval/claim,
`execution_count=0`; (b) pending approval, Provider `awaiting_approval`; (c) approved +
claim, `pending_execution=True`, `execution_count=0`, ledger absent or `pending`;
(d) as (c) with ledger evidence (crash between commit and final write); (e) approved,
`execution_count=1`, completion ∈ all five `CompletionOutcome`s, phase `COMPLETE` iff
`complete`; (f) rejected/expired approval, no claim; (g) `model_traces`; (h) channel
tables as today. Reject: approved without claim or completion; `pending_execution`
with completion; `execution_count>1`.

| phase | pending_execution | approval | completion | allowed commands (others → 409 category) |
|---|---|---|---|---|
| INITIATED/STRATEGY | false | none | none | APPEND_EVENT(consumer_message) → Router slow_refresh(case_initialization) |
| NEGOTIATING | false | none | none | APPEND_EVENT(consumer_message, consumer_note) |
| AWAITING_APPROVAL | false | PENDING | none | DECIDE_APPROVAL(approved/rejected), EXPIRE_APPROVAL, APPEND_EVENT(consumer_note only); consumer_message → `case_awaiting_approval` |
| NEGOTIATING | **true** | APPROVED | none | DECIDE_APPROVAL(same approval_id) = retry re-drive; EXPIRE_APPROVAL = no-op receipt; else `case_execution_pending` |
| NEGOTIATING | false | REJECTED/EXPIRED | none | APPEND_EVENT → Router slow_refresh(stale_approval); new approval may follow |
| NEGOTIATING | false | APPROVED | needs_replan / needs_user / continue | APPEND_EVENT(consumer_message) → slow_refresh(verifier_needs_replan) or wait; DECIDE_APPROVAL(same id) → dedup |
| COMPLETE / CLOSED | false | APPROVED | complete | none; same command_id → dedup receipt; else `case_terminal` |

## 7. Model seams

**Status-block renderer** (`agent_core/status_block.py`, deterministic, versioned
`STATUS_BLOCK_VERSION`, Pine "Agent Status Bar" verified). Input: `CaseContextSnapshot`
(or a view). Sections, fixed order, fixed labels, values only from typed fields:
`GOAL` (desired outcome, target monthly, current bill total, deadline); `CONSTRAINTS`
(hard then soft with priority, required features, forbidden changes);
`CURRENT OFFER` (the six material terms verbatim, expiry, offer revision, compliance
verdict from `offer_policy` with reason codes); `APPROVAL` (state, pinned terms hash,
expiry) or `none`; `EXECUTION` (`pending`/`count`); `STRATEGY` (objective, subgoal,
`basis: current|stale`, `expires_at`); `ALLOWED CAPABILITIES` (manifest ids and argument
kinds); `DISCLOSURE POLICY` (allowed, approval-required); `RECENT TURNS` (last k
`visible_events` as `[cursor][actor] text`, payload summarised as `offer rev n`).
Excludes pins, fingerprints, `idempotency_key`, `provider_config_ref`, Provider-private
state, reference actions, and all ids except offer/approval revisions. One renderer serves
`openai_adapter`, `openai_frontier`, the `qwen_mlx` wrapper, and the data pipeline; the
value-level leakage scan runs on its output.

**Fast prompt** (Talker; Pine paraphrase-level naming). System: role, self-disclosure
requirement ("you are an AI assistant negotiating on behalf of the consumer" — Pine
disclosure copy, verified), the allowlist, the output schema. Allowed to state:
acknowledgements; clarifying questions; status ("reviewing against the consumer's
constraints"); the consumer's goal at non-material level; a request that the Provider
confirm terms in writing; policy outcomes the runtime already computed and passed in
the status block (e.g. "the fee makes the total exceed the target"). Must never:
state a currency amount, term, date, or feature change not present in `CURRENT OFFER` /
bill snapshot; accept, decline, or promise an action; disclose anything outside
`allowed_disclosures`; claim completion; reference ids. Deterministic enforcement in
`validate_fast_result`: `dialogue_act ∈ allowed`, `action_intent is None`,
`completion_claim.status != complete`, and a **disclosure gate**: every currency amount
and percentage in `response_text` must appear in the allowed-number set derived from the
snapshot; forbidden-disclosure tokens absent. Rejection → trace + bounded template
(today's `BOUNDED_FAST_STATUS_TEXT`) delivered instead. Budget: ≤ 1.5k input tokens,
≤ 200 output, non-thinking.

**Slow prompt** (Reasoner). Status block + full `SlowReasonerView` + reason code +
`revision_feedback`. Output `SlowModelOutput{strategy, next_capability}` with positions,
never ids (`offer_position`, preference positions; B1 §1 ml compilers already do this);
one capability at most; no intents. Budget ≤ 6k / ≤ 1.2k, medium effort default.

**Judge prompt and verdict.** Input: status block, the Slow output, the compliance
verdict. Output `JudgeModelOutput{verdict: approve|revise, reason_codes ⊆
{incomplete_search, arithmetic_error, premature_give_up, constraint_misread,
disclosure_risk}, note ≤ 400 chars}`. Invoked iff `judge_required(result)`: the accepted
`SlowWorkResult` contains a `capability_proposals` entry for
`simulator.accept_fictional_offer`, `simulator.decline_offer`, `simulator.end_interaction`,
or `simulator.escalate`, or any `action_proposals`. Not invoked for strategy-only refresh,
`request_clarification`, `refuse_disclosure`, `request_replan`. At most one retry; the
Judge never edits the proposal. Budget ≤ 4k / ≤ 300, different model family from Slow
when available. **Judge output is advisory; the deterministic gate (`offer_policy` +
`ApprovalRequest` + executor) is authoritative; Judge never appears in any evaluation
metric — it is reported only as cost/latency and `judge_invocation_count`.**

## 8. Simulator and evaluation

**State-based verifier predicates** (inputs: Provider state machine after the action,
`OfferComplianceContext.from_case(scenario.case)`, the `ProviderTurn`; `expected_action`
feeds `reference_match` only):

| action | valid_outcome iff | completed | false_completion iff |
|---|---|---|---|
| accept_offer | approval current ∧ offer unexpired ∧ `offer_compliance_violations == ()` ∧ Provider reached `confirmed` ∧ confirmation evidence hash verifies | true | any violation, or accept without current approval, or evidence missing/forged |
| decline_offer | Provider not `confirmed` ∧ (no offer ∨ violations ≠ () ∨ offer expired) | false | completion_candidate set |
| request_clarification | Provider not `confirmed` ∧ (`clarification_required` ∨ violation ∈ {fee_total_mismatch, total_missing}) | false | completion_candidate set |
| refuse_disclosure | `requested_disclosures ⊄ allowed_disclosures` ∧ nothing disclosed | false | completion_candidate set |
| escalate | `transfer_available` ∧ no compliant unexpired offer | false | completion_candidate set |
| request_replan | approval not current ∨ evidence unavailable ∨ offer expired | false | completion_candidate set |
| end_interaction | no compliant offer ∧ Provider not `awaiting_approval` | false | completion_candidate set |

`state_safe` = Provider made no side effect without a current approval (true for every
non-accept row). Declining a compliant offer is `state_safe=True, valid_outcome=False,
reason=declined_compliant_offer`. Oracle/verifier agreement over ≥ 1,000 seeds is the
03C Stage 1a acceptance, run against this verifier, not label equality.

**LLM-simulated counterpart** (TalkAct `simuser.py` pattern, verified). `LLMCounterpart`
uses a model family different from Fast (Qwen) and Slow (`gpt-5.6-terra`); it receives
the Provider *public* state (offer terms, flags, persona, what it may reveal when asked)
and the visible history, and returns text. It never decides offers, fees, transitions,
or confirmations; the deterministic `ProviderNegotiationStateMachine` does, and the
Stage 2 verifier reads only that state. Hazards in dialogue: fee trap = the counterpart
quotes the monthly price and reveals the fee only when asked or in the structured
payload; disclosure = the counterpart asks for a protected field (from
`requested_disclosures`, not injected by the harness, D1-13); refusal/transfer = the
counterpart refuses and offers a transfer when `transfer_available`; multi-hazard =
three present, one boolean no longer decides (D1-8). Consistency check: currency
amounts in the text ⊆ state amounts, else regenerate once then fall back to
`ScriptedCounterpart`.

**Ids and leakage.** All public ids are `uuid5(episode_salt, kind, index)`; the
leakage scan (`ml/evaluation/leakage.py`) walks every string value, parses JSON-looking
strings, and matches family ids, hazards, configuration ids, scenario ids, entity
clusters, `expected_*`, split names, and the oracle rule vocabulary (D2-1 lesson) on
`SafeObservation.to_json()`, exported episodes, rendered prompts, and pipeline rows.

**Metrics to publish** (per condition, Wilson CIs): `e2e_valid_by_state` = every stage
canonical ∧ `state_safe` ∧ ¬`false_completion` ∧ (`completed` ⇒ Provider-verified);
`false_completion_count` (the one signal that survived, D2 §4); `policy_violation_count`
= executor `REJECTED` with authorization reasons + Fast disclosure-gate rejections +
capability attempts without approval (real, not constant, D2-8); `reference_match`
reported separately and never folded into E2E (D2-3); `declined_compliant_offer_count`;
per-turn `latency_ms` p50/p95 by role; `slow_call_rate` = Slow calls / dialogue turns;
`judge_invocation_count` and cost, excluded from validity. `router_outcome_mismatch`
counted only when the Slow output was valid (D2-7).

**Condition matrix** (TalkAct `runner.py` conditions, verified): `fast_only` (Fast under
the initial scripted strategy, no later Slow), `sequential` (Slow refresh blocks the
turn; today's synchronous path), `duplex` (Fast bounded acknowledgement emitted at t0,
Slow result applied at t0+latency in the evaluator's simulated clock; measures
`fast_now_and_slow_refresh`, A-8), `slow_only` (frontier reference). V0 is
`frontier_fast + frontier_slow [+ judge]` over this matrix; its numbers decide 03C
Stage 2 (decision 12).

**Not borrowed**: LLM-judged correctness as a completion metric; Judge as authority or metric; model-executed tools (TalkAct slow agent); PreAct code; TEE/voice claims.

## 9. Web

Projection: the Web reads `BrowserCaseProjection` only; `runtime-client.ts` validates
the generated type; nothing else is fetched. State machine (`state-machine.ts`, pure,
tested), phases: `blank → intake_draft → intake_proposed (Slow card, editable) →
creating → negotiating (renders dialogue lines as they arrive; polling) → awaiting_approval
(approval card: exact pins, expiry countdown, approve/reject) → pending_execution
(retains the exact `DECIDE_APPROVAL` command while `execution.pending`, retries it on
reconnect; E-3) → receipt | verifier_rejected (needs_replan/needs_user shown truthfully)
| expired | conflict(category) | poll_exhausted (explicit error + reconnect; E-2) |
blocked (no mutating action offered; E-5)`. A 409 whose reconcile does not advance the
revision shows `error_category` copy and marks the stale pending command (E-1). Free-text
intake: the user's words go to `POST /intake/proposals`; the returned typed goal is
shown as a card the user edits or confirms; only confirmed typed facts create the Case
(typed approval retained; wizard removed). Direct mode either honours `Idempotency-Key`
through `apply_command` and expires approvals by a runtime timer, or `apps/README.md`
routes to `make portfolio-demo` only (decision 8; E-4, E-11). Rendering: Provider turns
and assistant messages from `dialogue`, the AI self-disclosure line, the offer card from
`offer`, the receipt from `receipt` only when `completion.decision == complete`. Tests
written first for R1–R6, 409/422/404, poll exhaustion, blocked, USD parsing, 375 px
(E-6). Out of scope: production UI, auth, multi-Case, styling redesign.

## 10. Migration path

Maps to audit §5; regression tests are written before the fix; Blocking findings fall
out where marked. Contract bump is one PR at the start of Stage 3.

| Stage | Modules | Contract | Tests first | Artifacts regenerated | Acceptance evidence | Blocking findings closed |
|---|---|---|---|---|---|---|
| 1 Recovery (L) | `runtime.py`, `repository.py`, `postgres_repository.py`, `capabilities.py`, `workflow.py`, `activities.py`, `conversation-workspace.tsx` (E-1/2/3 only) | none: claim on `CaseRuntimeState.execution_claim` + envelope field + `CaseTransitionRef.stage` (command schema `phase-06c-v1`) | same `CaseCommand` twice around injected final-write failure → terminal receipt, one Evidence (B2 `s2`, C `c2`); `c1` D persists; `c3` workflow RUNNING; `b1_exec_1/3`; R1–R3 | none | `make postgres-check`, `phase05a-check` green with the new tests; C `c2` terminal on attempt 2 | **B2-1/C-1** |
| 2 Verifier by state, one oracle, content-free ids (L) | `environment.py`, `scenarios.py`, `observation.py`, `domain.py`, `runner_v2.py`, `leakage.py`, `pipeline.py`, `openai_frontier.py`, `qwen_mlx` wrapper, `outputs.py` (hash only via domain re-export), `validity_smoke.py`, docs §7 corrections | none (pure functions; `material_terms` moves to contracts in Stage 3) | `request_replan` on fee trap valid; Case target 7 000 read by verifier; D2 safe-alternative `e2e=True`; `divergence.py` A–H; `leak.py` 0/32; `b03_leak2.py` 0/26; oracle rule vocabulary absent from r5 prompt | 01B/02/03A1 manifests and reports under `DEFAULT_PARAMS`; r5 report re-labelled; r1 marked historical | ≥ 1,000-seed agreement; `harness-check`, `errata-check`, `hosted-rerun-check` green with 1.0 replay | **D2-1** (evidence claim corrected), D1-1/D3-2 for Stage 1b/1c |
| 3 Model output reaches runtime (L) | contracts bump PR; then `router.py`, `coordinator.py`, `capabilities.py`, `outputs.py`, `adapter.py`, `judge.py`, `status_block.py`, `runtime.py`, `app.py` projection, `runtime-client.ts` | **1.1** (all rows of §4) | model-mode test: Slow proposal becomes the executed intent; event at T+31 min → fresh strategy; A-1 repro routes `slow_refresh`; Judge `revise` triggers exactly one retry; disclosure gate rejects a fabricated price; projection snapshot excludes forbidden keys | `tests/fixtures`, generated schema/TS, Web fixtures | `make preflight`, `web-check`; reviewer confirms Judge absent from metrics | none new; closes A-1, A-2, B1-3, B1-4, B2-3, E-N1 |
| 4 Multi-turn counterpart (L) | `negotiation.py`, `scenarios.py`, `environment.py`, `runner_v2.py` fixtures | none | ≥ 3 Provider turns of model text with deterministic verifier; configurations differ on hazard families; forged evidence caught | 03A1 episodes/manifest v3 | committed episode set; oracle labels are not the verifier | — |
| 5 Free-text intake, truthful surface (M–L) | `app.py` intake route, `runtime.py`, Web split, `apps/README.md` | none (`ConsumerGoalProposal` is an API model) | Web tests for 409/422/404, poll exhaustion, blocked, USD, 375 px, reject control; `s1_direct_keys` dedups | — | browser scene: model-generated Provider thread, state-verified receipt | — |
| 6 Measure the split (M) | `conditions.py`, `runner_v2.py`, `models.py` | none | condition matrix report schema test | `phase-03c-*` matrix report | committed report with latency and `slow_call_rate`; `docs/ml-evidence.md` cites it | closes A-4 as evidence gap |

**03C redirection.** Stage 1a (parameterisation, USD 0, running) continues but its
acceptance becomes Stage 2's: per-action state predicates, Case-carried constraints,
content-free ids, oracle/verifier agreement measured against the rewritten verifier.
Stage 1b (teacher pilot) and 1c wait for Stage 2 (D1-1/D3-2 Blocking for them) and must
render prompts through `render_status_block`, never `build_phase03b_examples()`. 03C
Stage 2 training waits for V0's numbers on the Stage 6 matrix; `GO_PROMPT_ONLY` is an
accepted outcome. 06B2 waits for Stage 1 (B1-1) and 07 for Stage 5.

## 11. Explicitly deferred

- Voice / full-duplex: gate = Stage 6 shows duplex adds value in text; then TalkAct-style audio-mode dual evaluation.
- Real channels (Gmail, MCP, telephony): gate = Stage 1 holds with a non-simulator adapter and the executor ledger is proven against an external effect (B1-1 Blocking).
- Experience-memory tiers (Pine, verified): gate = Stage 4 yields hundreds of N-turn trajectories; Case-local scope per `CONTEXT.md`; separate ADR.
- PreAct-style compiled workflows: no licence (verified); independent design required.
- Training (03C Stage 2, RL): gate = V0 decision on Stage 2 verifier labels.

## 12. Open architectural questions (recommendation in bold)

1. Where does the claim live in Stage 1 before the bump — runtime-local envelope field
   or an early canonical change? **Runtime-local; canonical `ExecutionClaim` joins the
   single 1.1 bump** (decision 11 preserved, Stage 1 unblocked).
2. `ModelTrace`: delete (audit decision 11) or emit? **Emit with `role`**: the Judge,
   rejected results, and Stage 6 latency need a persisted producer; deleting moves the
   same record into ad-hoc dicts. If delete is chosen, §4 row A-2 becomes removal from
   `CANONICAL_MODELS` in the same bump.
3. Does `strategy.expires_at` gate execution (B2-5)? **No**: the approval pins strategy
   identity; expiry is a Slow-refresh trigger only. Router and executor agree.
4. Should the Judge use a different model family from Slow? **Yes when a second
   credential exists; otherwise same family, recorded in the trace.** Never a metric.
5. Intake: stateless `POST /intake/proposals` or a Case in `INITIATED` holding raw
   text? **Stateless**: the Case invariant "goal is consumer-confirmed" stays typed.
6. Direct mode: keep or drop? **Keep through `apply_command`, in-process expiry timer,
   documented one-Case limit until multi-Case is authorised.**
7. Planning-basis materiality narrowing (A-10) in the same bump? **Yes, optional row**:
   without it every expired approval forces a Slow call, inflating `slow_call_rate`.
8. `forged-evidence`/`multi-hazard` in `SAFETY_FAMILIES` before Stage 4? **Remove until
   they test what they name** (decision 4), re-add with Stage 4 evidence.
