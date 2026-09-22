# Repository Audit — Lane A: Architecture and Contracts

Auditor: `architect` (Fable, high). Date: 2026-09-21. Baseline: worktree
`worktree-phase-03c-parallel` at `aaae134` (`main`).

Scope read completely: `GOALS.md`, `CONTEXT.md`, `docs/architecture.md`,
`docs/decisions/2026-08-22-implementation-defaults.md`,
`docs/decisions/2026-08-23-fast-slow-orchestration.md`, the boundary /
invariant / Fast-Slow / simulator / baseline sections of
`docs/specs/2026-08-21-telecom-bill-optimization-agent.md` (lines 1-122,
170-234), `runtime/packages/contracts/src/proxyloop_contracts/{contracts,_base,__init__}.py`,
`runtime/packages/contracts/tests/test_contracts.py`,
`tests/contract/test_architecture.py`, `tests/fixtures/*.json`.

Extra reads made only to verify a specific doc claim (each noted inline):
`docs/decisions/2026-08-22-contract-wire-format.md` (schema-version semantics);
`tests/contract/test_generated_contracts.py` and
`tests/contract/test_phase_03a0_architecture.py` (what "architecture tests"
enforce); `runtime/packages/agent_core/src/proxyloop_agent_core/{router,coordinator,capabilities,interfaces}.py`
(Router precedence, stale-result handling, executor binding);
`runtime/packages/case_runtime/src/proxyloop_case_runtime/runtime.py` lines
160-235, 425-470, 725-770, 868-960, 1500-1600, 1600-1870 (producers of
snapshot / manifest / planning basis / evidence / approval);
`runtime/packages/telecom_domain/src/proxyloop_telecom_domain/domain.py` lines
40-90, 230-318 (verifier); `runtime/packages/provider_simulator/.../provider.py`
line 114 (offer expiry); `ml/evaluation/src/proxyloop_evaluation/models.py`
lines 30-70 (parallel trace model); `docs/ml-evidence.md` lines 1-45 and
`data/evaluation/phase-03a1-r4-hosted-rerun-report.json` `matrix_result.conditions`
(Fast/Slow evidence); `PLANS.md` lines 20-24 (03A1 status);
`tests/integration/test_phase_03a1_agent_core.py` and
`tests/integration/test_phase_04b_model_runtime.py` (grep only, for validator
coverage).

Evidence labels: **observed** = read or executed in this worktree; **inferred**
= follows from observed facts; **proposed** = a direction, not a fact.

---

## 1. Verdict per unit

Note on count: the packet says "13 canonical contracts". `architecture.md:199-211`
lists 13 "core domain contracts"; `contracts.py:1156-1180` registers 23
(`CANONICAL_MODELS`), the extra 10 being the Phase 03A1 routing/view set
(`architecture.md:213`). All 23 are judged below.

### Canonical contracts (`contracts.py`)

| Unit | Lines | Verdict | One sentence |
|---|---|---|---|
| `Case` | 588-617 | keep | Produced and consumed everywhere (19 runtime files); aggregate id checks are real. |
| `ConsumerGoal` | 165-188 | keep | Consumed by verifier policy (`domain.py:232-244`) and fingerprinted into planning basis. |
| `Constraint` | 191-216 | keep | Fingerprinted and projected; hard/soft-priority rule is coherent. |
| `BillSnapshot` | 219-245 | keep | Sum/currency/evidence validators are load-bearing and consumed by verifier. |
| `FactLedger` / `FactRecord` | 251-285 | refactor | Contract is sound but the product runtime never writes an entry (`runtime.py:1778` is the only producer, `entries=()`); Fast `fact_updates` are validated for provenance (`coordinator.py:337-342`) and then dropped. |
| `StrategyPacket` | 288-318 | refactor | Carries no planning-basis binding (A-1); `hard_constraint_ids` and `ranked_preference_ids` have zero consumers in `runtime/`; the five prose tuples are copied by the adapter compiler (`outputs.py:166-178`) and read by no deterministic code. |
| `FastTurnDecision` | 571-585 | keep | Real producer/consumer path; but its staleness pins live off-contract in `FastAdapterResult` (`interfaces.py:23-27`), unlike `SlowWorkResult` (A-9). |
| `ProviderOffer` | 321-346 | keep | Consumed by verifier, executor, router; lacks the spec's receipt fields, which live in a non-canonical dataclass (A-6). |
| `ActionIntent` | 349-395 | refactor | `authorization_state: Literal["proposed"]` is a constant, and the intent is not bound to a `CapabilityReference` at the type level (A-3). |
| `ApprovalRequest` | 398-462 | keep | The best-specified contract; exact binding is enforced twice (`capabilities.py:244-257`, `domain.py:183-198`) and at routing (`router.py:152-173`). |
| `Evidence` | 465-481 | refactor | `content_hash` has no defined referent; two producers hash different things (A-5). |
| `CompletionDecision` | 484-523 | keep | Typed "complete requires evidence" rule is real and tested; only 3 of 5 outcomes are ever produced (A-8). |
| `ModelTrace` | 526-550 | rewrite or delete | Zero producers or consumers in `runtime/` and `ml/`; only `scripts/run_phase_03a1_harness.py:145` constructs it (A-2). |
| `ModelInputPins` | 620-641 | keep | The real staleness seam; produced at `runtime.py:1637`, compared at `coordinator.py:131,324,372`. |
| `PlanningBasis` | 644-674 | keep | Self-consistent aggregate hash; but no contract binds a strategy to it (A-1). |
| `VisibleCaseEvent` | 725-735 | keep | `event_type` is an open string used as protocol (`router.py:67`), see A-10. |
| `CapabilityManifest` / `CapabilityDefinition` / `CapabilityReference` | 738-816 | keep | `simulator.` prefix and expiry rules are typed and tested; argument schema is absent (A-10); runtime mints it once per Case with a 24 h expiry (A-11). |
| `CaseContextSnapshot` | 819-952 | keep | The deepest contract: 110 lines of validator that recompute pins and planning-basis components; zero negative tests in the contracts package (section 3). |
| `FastModelView` | 955-995 | keep | Allowlist by construction; `pending_slow_work` is never `True` anywhere in the repository. |
| `SlowReasonerView` | 998-1051 | keep | Allowlist by construction; validator failure branches untested in contracts package. |
| `RoutingDecision` | 1054-1067 | keep | Produced by `router.py:77`; `revision` is a meaningless required field (A-9). |
| `SlowWorkRequest` | 1070-1091 | keep | Produced at `coordinator.py:302`; pin echo is typed. |
| `SlowWorkResult` | 1094-1153 | keep | Best-typed model output: pins, basis, `authorization_state` and revision cross-checks; but `action_proposals` are not required to reference a `capability_proposals` entry (A-3). |
| `_base.py` | all | keep | Strict/frozen/extra-forbid base, UTC and UUIDv4 rules are exactly what the wire-format ADR says. |

### Documents

| Unit | Verdict | One sentence |
|---|---|---|
| `GOALS.md` | keep (one stale line) | Line 27 still names Qwen3-4B after the 2026-09-21 amendment moved the default to Qwen3-8B (A-7a). |
| `CONTEXT.md` | refactor | Defines `Planning Basis` and `Model Trace` in ways the contracts do not honor (A-1, A-2) and omits terms the runtime relies on (Capability Proposal, Visible Case Event, Model Input Pins, Case Phase, command receipt / outbox / channel binding) (A-10). |
| `docs/architecture.md` | refactor | The status block (47-54) is honest, but the Model Responsibilities, Decision Loop, Safety, State Ownership and Deployment sections mix built, planned and stale text without marking which (section 6, Q7 table). |
| ADR `2026-08-22-implementation-defaults.md` | keep | It says it is defaults, not results; the amendment supersedes the 4B rows cleanly; MLflow/vLLM rows are unimplemented but labeled as defaults. |
| ADR `2026-08-23-fast-slow-orchestration.md` | refactor | Status line is stale (A-7c); the frozen trigger list and planning-basis binding are not implemented as frozen (A-1); "traced" has no contract producer (A-2). |
| Spec boundary / invariant sections | keep | Consistent with the ADRs; two drifts: Qwen3-4B (A-7a) and the "required completion receipt" that no canonical contract carries (A-6). |
| `runtime/packages/contracts/tests/test_contracts.py` | refactor | Load-bearing for the Phase 00B surface; the Phase 03A1 validators (snapshot, views, `SlowWorkResult`) have only happy-path construction (section 3). |
| `tests/contract/test_architecture.py` | keep | Narrow but real: import purity and single-dependency rule. |
| `tests/contract/test_phase_03a0_architecture.py` | rewrite or delete | Asserts that markdown contains sentences; passes if `router.py` were deleted (section 3). |

---

## 2. Findings (most severe first)

### A-1 — Important — Installed strategy is never invalidated by a material planning-basis change; the Router's "mandatory Slow" list is mostly caller-supplied

**Paths.** `contracts.py:288-318` (`StrategyPacket`: fields are `case_revision`,
`fact_ledger_revision`, `expires_at`; no basis field);
`runtime/packages/agent_core/src/proxyloop_agent_core/router.py:133-149`
(`_mandatory_slow_reasons`: only `stale_approval`, `case_initialization`,
`strategy_expired`, `slow_work_pending` are computed internally; everything
else comes from `RouteRequest.mandatory_slow_reason_codes`); `router.py:96-104`
(`verify_only` keys on `pending_execution` / phase / candidate, never on
"new Evidence"); `runtime.py:436, 739, 875, 917, 1336` (all five product
`RouteRequest` constructions; none passes `mandatory_slow_reason_codes`; grep
shows the parameter is supplied only by `scripts/run_phase_03a1_harness.py:832`
and `tests/integration/test_phase_03a1_agent_core.py:293`).

**Claims violated.**
- ADR `2026-08-23`:110 "Strategy validity is bound to a `planning_basis_fingerprint` computed from material state"; :85 "expired or planning-basis-incompatible Strategy Packet" and :84 "Provider refusal or a materially changed offer" and :91 "new Evidence that can change the strategy" are mandatory Slow triggers; :100 priority 2 `verify_only` for "New executor/Provider Evidence".
- `architecture.md:189` "A planning-basis fingerprint binds the Strategy Packet to material goal, constraint, authority, verified-fact, offer, approval, Provider-configuration, and capability-manifest state"; :105 "A deterministic Router requests Slow work ... on material goal, constraint, authority, offer, Evidence ... events"; :185.
- `CONTEXT.md:55-57` "Planning Basis: The versioned material Case state whose change invalidates a Strategy Packet".

**Reproduction (observed).** Script at
`/private/tmp/claude-501/-Users-edison-Desktop-projects-pine-clone/a0093867-861c-48dc-bfeb-3b1eb7443a28/scratchpad/laneA/repro_strategy_basis.py`
builds two valid `CaseContextSnapshot`s from `tests/fixtures/case.valid.json`
with the same installed, unexpired `StrategyPacket`; the second adds one
`ProviderOffer` and its `Evidence` (material offer set changes, so
`planning_basis_fingerprint` changes). Output:

```
planning basis changed: fd32cd0a -> 82d5038d
route before: fast_now ('current_strategy_dialogue',)
route after material offer + new Evidence: fast_now ('current_strategy_dialogue',)
StrategyPacket fields mentioning basis/fingerprint: []
```

Per the ADR the second route must be `verify_only` (new Evidence) or at least
`slow_refresh` (material offer / basis-incompatible strategy). A failing
regression test can be written today in
`tests/integration/test_phase_03a1_agent_core.py` with the same fixture.

**Why this is Important, not Blocking (inferred).** Authorization is still
safe: the executor and domain policy bind approvals to the exact offer
revision (`capabilities.py:181-192`, `domain.py:183-198`), so `architecture.md:272`
("A stale strategy or approval cannot authorize a changed offer") holds at
execution time. What fails is the routing/strategy-validity contract the ADR
freezes; in the fixed Phase 04A path the runtime sequences Slow-then-Fast by
hand-coded control flow (`runtime.py:739-746` then `874-886`), so the Router
is not the authority the ADR describes.

**Direction (proposed).** Either add `planning_basis_fingerprint: Sha256` to
`StrategyPacket` (breaking wire change under the wire-format ADR:53, so a new
`schema_version`), or carry `strategy_basis_fingerprint` on
`CaseContextSnapshot` next to `strategy`; have `_mandatory_slow_reasons`
compare it to `snapshot.planning_basis.planning_basis_fingerprint` and emit
`strategy_basis_incompatible`; move event classification (goal change,
refusal, new offer, new evidence) into the coordinator from a typed
`triggering_event.event_type` enum instead of a free `tuple[str, ...]`
parameter on `RouteRequest`.

### A-2 — Important — `ModelTrace` has no producer or consumer in the product runtime or ML packages; "traced and rejected" is not a contract-level fact

**Paths.** `contracts.py:526-550`; `contracts.py:513` (`CompletionDecision.candidate_model_trace_id` references it);
`runtime/packages/agent_core/src/proxyloop_agent_core/coordinator.py:140-148,355-361`
(rejections are recorded in an in-process `ResultAudit` dataclass, not a
contract); `ml/evaluation/src/proxyloop_evaluation/models.py:31-54`
(`ModelProvenance`, `PromptProvenance`: a parallel, non-canonical trace
schema); `scripts/run_phase_03a1_harness.py:139-165` (sole constructor).

**Claims violated.** `architecture.md:211` lists `ModelTrace` among the core
contracts; `:276` "Every trace links `case -> prompt/model -> evidence -> dataset derivation -> model version`";
ADR `2026-08-23`:114-115 "a stale Fast result is traced and rejected", "a
stale Slow result is traced and rejected"; `CONTEXT.md:99-101`.

**Reproduction (observed).**
`grep -rn -E 'ModelTrace|model_trace|prompt_version|safety_flags' --include='*.py' runtime ml`
(excluding `contracts/src`) returns only `runtime/packages/contracts/tests/test_contracts.py:174`
(registry name list) and `ml/.../runner.py`, `runner_v2.py`, `models.py`
`prompt_version` strings that belong to the ML `PromptProvenance` model, not
`ModelTrace`. No product code path can ever emit a `model_trace` document, so
`candidate_model_trace_id` can never be populated by the runtime.

**Direction (proposed).** Decide one of: (a) remove `ModelTrace` from
`CANONICAL_MODELS` and `ContractDocument` and update the registry test (wire
change, new `schema_version`), or (b) make `CaseCoordinator.advance` emit one
`ModelTrace` per adapter call (including rejected ones) and persist it via the
repository, and make `ml` `PromptProvenance` a projection of it. Until then
`architecture.md:211,276` and ADR :114-115 should say "audited in process,
not persisted".

### A-3 — Minor — "Capability manifest is the sole action vocabulary" is enforced only in the executor; the contracts carry two vocabularies

**Paths.** `contracts.py:30-35` (`ActionType`, 5-value closed enum);
`contracts.py:349-395` (`ActionIntent` has `action_type` but no
`CapabilityReference`); `contracts.py:137-149` (`DelegatedAuthority` is over
`ActionType`, not capabilities); `contracts.py:749-758` (`CapabilityReference`
is an open `simulator.`-prefixed string); `contracts.py:1094-1153`
(`SlowWorkResult` validator never requires an `action_proposals` entry to
reference a `capability_proposals` entry); binding happens only at
`capabilities.py:136-145` (lookup by proposal) and `:173-180` (offer id
matched through a string-typed `CapabilityArgument` named `"offer_id"`).

**Claims.** `architecture.md:193` "`CapabilityManifest` is the sole
model-facing vocabulary for executable actions"; `:269`; ADR :123 "the only
action/tool vocabulary available to models and the executor".

**Reproduction (observed).** A `SlowWorkResult` with one `accept_offer`
`ActionIntent` in `action_proposals` and `capability_proposals=()` validates
(no validator line in 1106-1153 cross-checks the two tuples). An
`ActionIntent` never names a capability; the executor reconstructs the link
from a separate `CapabilityProposal` argument that arrives through
`CapabilityExecutionRequest`, i.e. the invariant is a property of the
executor's call site, not of the contract.

**Direction (proposed).** Add `capability: CapabilityReference` to
`ActionIntent` (or a `proposal_id` back-reference) and require in
`SlowWorkResult` that every action proposal's capability appears in the
manifest namespace; declare argument names/types on `CapabilityDefinition` so
the `"offer_id"` convention is typed.

### A-4 — Minor — The Fast/Slow split is asserted, not measured: the product runtime never uses Fast-generated dialogue, and the only matrix shows no Fast contribution

**Paths.** `runtime.py:443-448` (channel path raises `ModelRuntimeError("fast")`
unless `fast_decision.response_text == BOUNDED_FAST_STATUS_TEXT`, and then
sends the constant at `:455`); `runtime.py:874-899,946` (append-event path
stores the decision as `last_fast_decision` while the approval is derived
deterministically from `event_snapshot.offers[0]` and compliance policy,
independent of the Fast decision); `interfaces.py:19` (the constant);
`coordinator.py:347-354` (bounded mode also requires the constant).

**Claims.** `architecture.md:5` "conducts low-latency dialogue against a
provider"; spec:65 "Fast Model conducts turn-level dialogue"; spec:107 "Slow
calls ... no more than 20%-30% of dialogue turns"; ADR :144 rejects
"Slow on every turn" because it "makes Fast value impossible to measure".

**Reproduction (observed).** `grep -rn BOUNDED_FAST_STATUS_TEXT runtime/packages/*/src`
shows the three enforcement sites above; there is no product code path in
`runtime.py` where `fast_decision.response_text` or `dialogue_act` changes
state or is delivered verbatim. Measured evidence
(`data/evaluation/phase-03a1-r4-hosted-rerun-report.json`,
`matrix_result.conditions`): `untuned_fast_slow_off_r2` 0/32 end-to-end valid;
`untuned_fast_frontier_slow_{medium,high}` 0/32; `frontier_reference_{medium,high}`
3/32 and 1/32; `model_call_count` 40-42 per 32 episodes in every model
condition, i.e. about one Slow and one Fast call per episode, so no
"Slow call rate per dialogue turn" exists to compare against spec:107.
`docs/ml-evidence.md:31` reports the r5 5/6 diagnostic without attributing it
to Fast or Slow.

**What removing Fast would lose (inferred from the docs' own rationale).**
Only the latency/cost hypothesis (ADR :144, `implementation-defaults.md:27-28`)
and the trainability boundary (ADR :129-139). Nothing in the repository
measures latency per turn, and no product path depends on Fast output, so
today "Slow + deterministic policy" is functionally what runs. The
architecture is not wrong for keeping the seam; it is wrong to describe the
seam as exercised.

**Direction (proposed).** Mark the Fast dialogue path as "evaluation-only"
in `architecture.md:124-170` until a product path consumes `response_text`;
add `slow_call_rate` and per-turn latency to the evaluation report before
citing spec:107.

### A-5 — Minor — `Evidence.content_hash` has no defined referent

**Paths.** `contracts.py:465-481` (no docstring or validator defines what is
hashed); `runtime.py:173-184` (`SIMULATOR_TRANSITION` evidence created
*before* execution with `content_hash = sha256(idempotency_key)`, `source_ref =
idempotency_key`); `postgres_repository.py:1243` (same); `provider.py:195`
(`CONFIRMATION` evidence hashes the confirmation payload);
`domain.py:292` (verifier checks the hash only for the confirmation kind);
`capabilities.py:203` (executor accepts evidence whose `source_ref` equals the
idempotency key).

**Claims.** `CONTEXT.md:87-89` "Evidence: An immutable reference to a simulator
or controlled external artifact"; `architecture.md:209`; ADR :117 "an
executor result is recorded idempotently as immutable Evidence".

**Reproduction (observed).** Two producers in the same runtime yield
`Evidence` whose `content_hash` means "hash of the artifact" in one case and
"hash of our own idempotency key" in the other; the second is minted before
any transition occurs (`prepare()` at `runtime.py:166`), so it references no
artifact at all. The contract accepts both.

**Direction (proposed).** Define `content_hash` as the SHA-256 of the
canonical JSON of the referenced artifact and add `artifact_kind`/`hash_input`
semantics to the docstring; forbid pre-execution evidence or give it a
distinct `EvidenceType`.

### A-6 — Minor — The spec's "required completion receipt" is not a canonical contract

**Paths.** spec:34-46 (old/new price, 12-month total, plan id/name, removed
add-ons, fees/credits, term, promotion expiry, effective date, confirmation
id, approval version); `contracts.py:321-346` (`ProviderOffer` has none of
plan id, effective date, removed add-ons, promotion expiry);
`contracts.py:484-523` (`CompletionDecision` carries only ids and reason
codes); `runtime/packages/telecom_domain/src/proxyloop_telecom_domain/domain.py:45-63`
(`AppliedOfferConfirmation`, a plain `@dataclass` outside the contract seam,
JSON Schema and TypeScript outputs).

**Claims.** `GOALS.md:11` "Domain, authorization, evidence, and completion
concepts are represented by versioned typed contracts"; `architecture.md:197`
"The canonical contract layer defines these Pydantic contracts before service
code".

**Reproduction (observed).** `grep -n -E 'plan_id|effective_date|removed_add_ons' contracts.py`
returns nothing; the receipt exists only as `AppliedOfferConfirmation.to_dict()`
(`domain.py:65-86`), unversioned and unvalidated at the wire.

**Direction (proposed).** Promote the confirmation/receipt to a canonical
`VersionedContract` (it is the product's headline output) or state in the spec
that the receipt is a domain-package value, not a contract.

### A-7 — Minor — Cross-document contradictions (each with both passages)

a. **Fast checkpoint.** `GOALS.md:27` "Qwen3-4B as the Fast Model default
   candidate"; spec:5 "fine-tuning one Qwen3-4B Fast Response Model" and :74
   "Fine-tuning `Qwen/Qwen3-4B-Instruct-2507`" — versus
   `implementation-defaults.md:46-50` "redirected ... to **`Qwen/Qwen3-8B`** ...
   where they conflict with this amendment, the amendment wins" and
   `architecture.md:126`.
b. **Research MVP deployment shape.** `architecture.md:301-310` "Research MVP
   ... no Temporal, Gmail, or telephony" — versus `architecture.md:49`
   "**Implemented**: ... one explicit scripted/PostgreSQL Temporal
   CaseWorkflow mode, and a bounded credential-free `local_mailbox` connector".
c. **ADR status.** `fast-slow-orchestration.md:5` "Runtime contracts and
   implementations remain gated by Phase 03A1" — versus `PLANS.md:21-24`
   (03A1-H/B/E/R all "Complete") and `architecture.md:213` "Phase 03A1
   implemented and generated the canonical wire contracts".
d. **Revision vocabulary.** `architecture.md:111-112` "`strategy_id`,
   `version`, ... `case_version` and `fact_ledger_version`" and `:215` "All
   mutable objects use optimistic versions" — versus `contracts.py:288-292`
   (`revision`, `case_revision`, `fact_ledger_revision`) and `CONTEXT.md:107-109`
   "Entity Revision ... _Avoid_: Schema version".
e. **Case owner.** `architecture.md:199` "`Case`: lifecycle identity, owner,
   phase, version" — versus `contracts.py:588-599` (`consumer_id`, `phase`,
   `revision`; no owner field).
f. **Verifier outcomes.** `architecture.md:245` "The verifier decides
   `continue`, `needs_user`, `needs_replan`, `candidate_complete`, or
   `complete`" — versus `domain.py:307-311` (only `COMPLETE` or `NEEDS_REPLAN`)
   and `runtime.py:1282` (`CANDIDATE_COMPLETE`); `CONTINUE` and `NEEDS_USER`
   have no producer in `runtime/` (grep).
g. **Contract count.** Audit packet and `architecture.md:197-211` describe 13
   contracts; `contracts.py:1156-1180` registers 23 and
   `test_contracts.py:160-185` freezes 23.

Reproduction for each is the pair of quoted passages. Direction: one docs
PR that reconciles a-g; d and e should follow `CONTEXT.md`.

### A-8 — Note — Router precedence text matches, but two frozen conditions are structurally unreachable in the product runtime

`router.py:22-29` mirrors ADR :95-104 exactly (observed). However:
`fast_now_and_slow_refresh` requires `bounded_acknowledgement_allowed=True`,
which the runtime passes only at `runtime.py:743` with `slow=` and no `fast=`
adapter, so the combined branch never runs both models in product code;
`pending_slow_work` is never set `True` anywhere
(`grep -rn 'pending_slow_work=True' runtime ml scripts tests` is empty), so
the `slow_work_pending` reason (`router.py:147-148`) and
`FastModelView.pending_slow_work` (`contracts.py:968`) are dead. ADR :93
already says the concurrent path is "later"; `architecture.md:133`
("pending Slow-work status") and `:187` should say so too.

### A-9 — Note — Over-engineering: fields and pins with no consumer, and `revision` on ephemeral values

- `VersionedContract.revision` (`_base.py:89-91`) is required on
  `RoutingDecision`, `PlanningBasis`, `ModelInputPins`, `FastModelView`,
  `SlowReasonerView`, `SlowWorkRequest`, `SlowWorkResult`, `VisibleCaseEvent`,
  `CapabilityManifest`; every product producer hard-codes `revision=1`
  (27 sites across `agent_core`, `case_runtime/runtime.py`, `openai_adapter`,
  `provider_simulator`). The wire-format ADR:38 defines `revision` as "a
  positive optimistic-concurrency counter for one mutable business entity";
  these are immutable one-shot values, so the field is noise that a reviewer
  must learn to ignore.
- `ActionIntent.authorization_state: Literal["proposed"]` (`contracts.py:379`)
  can hold exactly one value; the `SlowWorkResult` check at `:1139-1140` can
  never fire. It documents intent but is not an invariant.
- `SchemaVersion = Literal["1.0"]` (`_base.py:19`) with no compatibility
  policy beyond wire-format ADR:53; any of the fixes above is a "new schema
  version and migration decision" that has no defined mechanism.
- Zero-producer enum members / fields in `runtime/` (grep): `EvidenceType.BILL`,
  `ActionType.DISCLOSE_INFORMATION`, `ActionType.END_INTERACTION`,
  `DialogueAct.{COUNTER,CONFIRM,CHALLENGE,ESCALATE,CLOSE}` (only `CLARIFY` is
  produced), `Evidence.media_type` (set to a constant at `runtime.py:183`),
  `StrategyPacket.hard_constraint_ids`, `StrategyPacket.ranked_preference_ids`,
  `Constraint.valid_until`, `ModelTrace.*`.
- `CapabilityDefinition.namespace: Literal["simulator"]` and
  `CapabilityReference.namespace: Literal["simulator"]` are gate pins for the
  deferred real-provider/voice/MCP roadmap; they are cheap and tested
  (`test_contracts.py:341-355`), so keep.
- The `json_schema_extra` `dependentSchemas` blocks (`contracts.py:350-366,
  399-429, 485-500`) duplicate three Python validators so that the generated
  JSON Schema rejects the same fixtures; this is the cost of the wire-format
  ADR's "JSON Schema is a required public validation seam" and is covered by
  `test_generated_contracts.py:28-40`. Acceptable, but every new
  cross-field rule must be written twice.
- Fast staleness pins are off-contract: `FastTurnDecision` carries only
  `case_revision` and strategy pins, while `FastAdapterResult.pins`
  (`interfaces.py:23-27`) is copied from the view by the adapter
  (`adapter.py:70`). `SlowWorkResult` carries pins and basis on the wire. The
  asymmetry means a persisted `fast_turn_decision` document cannot be judged
  stale on its own; `architecture.md:189` "Every model output echoes its input
  pins" is true for Slow and true-by-wrapper for Fast.

### A-10 — Note — Under-specification: declared concepts with no defined producer or semantics

- **Prompt versioning.** Only `ModelTrace.prompt_version` (dead, A-2) and the
  ML-side `PromptProvenance` (`ml/.../models.py:49-53`). `openai_adapter` has no
  prompt version string (grep `prompt_version` in `runtime/packages/openai_adapter/src`
  is empty). The product runtime's prompts are unversioned.
- **Capability manifest contents.** `CapabilityDefinition` declares
  `allowed_action_types` and free-text `description`, no argument schema;
  `CapabilityArgument` is `name: str, value: FactValue`. The executor's
  `"offer_id"` convention (`capabilities.py:173-180`) is the only "schema".
- **PlanningBasis semantics.** "Material offers" is implemented as *all*
  offers in the snapshot (`runtime.py:1830-1832`, `contracts.py:927-929`) and
  "approval state" as *all* approval requests including decided/expired ones;
  so a non-material offer revision or an expired approval changes the basis.
  `CONTEXT.md:55-57` says "material"; nothing defines materiality.
- **Reason codes and event types.** `RoutingDecision.reason_codes`,
  `SlowWorkRequest.reason_code`, `VisibleCaseEvent.event_type` are open
  `ExternalRef` strings; `router.py:30-39` and `:67` hard-code the vocabulary
  (`"approval_decision"`, six Fast reasons) with no contract enum. ADR :80-91
  lists ten trigger conditions; the Router's accepted Fast reasons are six
  different strings.
- **Fact Ledger.** `architecture.md:203` "append-only candidate/verified/rejected
  facts with provenance"; no runtime code appends (A-1 verdict row).
- **CONTEXT.md gaps.** No entries for Capability Proposal, Visible Case Event,
  Model Input Pins, Case Phase, Command Receipt, Outbox, Channel Binding, all of
  which appear in `architecture.md:221` or the contracts.

### A-11 — Note — Capability manifest is minted once per Case with a 24 h expiry and never regenerated

`runtime.py:731` mints `_manifest(created_at)`; `:1629` reuses it or re-mints
from `case.created_at`; `:1790,1797` set `expires_at = issued_at + 1 day`;
`capabilities.py:127-128,141-145` reject execution at or after that instant
with `capability_manifest_expired`; no code handles or tests that reason
outside the executor (grep). Today this is masked because the simulator offer
(`provider.py:114`) and therefore the approval and intent
(`runtime.py:1546,1564`) expire after 1 hour. It becomes a live defect the
moment an offer or approval window exceeds 24 h, which `GOALS.md:5`
("survive waits") and `architecture.md:10` ("wait across days") say is the
target. Direction: mint the manifest per snapshot or per execution, or drop
manifest expiry.

---

## 3. Test-quality assessment

**Load-bearing (exercise a failure branch or a real seam):**
- `test_contracts.py:56` unknown field rejected; `:63` discriminant and
  `schema_version` required; `:84` decision must precede expiry; `:94`
  `complete` without evidence rejected; `:101` `EvidenceType` cannot be
  `model_output` and `completion_claim` cannot be `complete`; `:140` money is
  integer and frozen; `:149` non-UTC rejected; `:341` non-simulator capability
  and bad manifest expiry rejected; `:273-296` `ModelInputPins` strategy
  identity rule and `PlanningBasis` aggregate-hash rule.
- `tests/contract/test_generated_contracts.py` (all five): schema validity,
  four invalid fixtures rejected by the *generated* schema, UUIDv4/UTC wire
  rules, `tsc` compile, `generate_contracts.py --check` drift.
- `tests/contract/test_architecture.py` (both): stdlib+pydantic-only imports
  and single runtime dependency.

**Weak or misnamed:**
- `test_contracts.py:75` `test_approval_offer_reference_requires_exact_revision`
  uses a fixture whose `offer_ref` simply lacks `offer_revision`; the assertion
  is `type == "missing"`. It tests a required field, not a revision mismatch.
- `test_contracts.py:160` registry equals a literal list of 23 names —
  tautological; it freezes the surface but verifies nothing about it.
- `test_contracts.py:299` "routing is closed" constructs a `RoutingDecision`
  with `SLOW_REFRESH` and asserts it is `SLOW_REFRESH`.
- `test_contracts.py:258` constructs one valid `CaseContextSnapshot`; the
  110-line validator at `contracts.py:840-952` (pins mismatch, basis component
  mismatch, cursor order, cross-case ids) has **no negative test** in the
  contracts package.

**Never exercised in the contracts package (failure branches):**
`FastModelView` (955-995) and `SlowReasonerView` (998-1051) validators;
`SlowWorkResult` (1106-1153, thirteen branches); `SlowWorkRequest` (1080-1091);
`ActionIntent` accept-offer rules (384-395) beyond the generated-schema
fixture; `DelegatedAuthority` disjointness (142-147); `StrategyPacket`
disclosure overlap / empty completion evidence (308-318); `BillSnapshot`
sum/currency (231-245); `FactRecord` provenance (261-267); `CapabilityProposal`
duplicate arguments (775-782); `RoutingDecision` empty/duplicate reasons
(1061-1067). Some coordinator-level equivalents are covered in
`tests/integration/test_phase_03a1_agent_core.py:382,390,528,840` and
`tests/integration/test_phase_04b_model_runtime.py:288,307`, but those test
`CaseCoordinator`, not the contract validators, and are out of this lane.

**Tautological with respect to architecture:**
`tests/contract/test_phase_03a0_architecture.py` (11 tests) asserts that
specific sentences and table rows exist in three markdown files and
`PLANS.md` (e.g. `:33-46`, `:71-78`, `:159-173`, `:202-216`). None imports
`router.py` or any contract; deleting the Router would not fail them. They
are docs-freeze tests and should be labeled as such or replaced by a test
that routes a fixture through `DeterministicRouter` for each precedence row.

---

## 4. Checks run / not run

**Run (observed):**
- `uv run --project runtime --all-packages pytest -c runtime/pyproject.toml runtime/packages/contracts/tests tests/contract/test_architecture.py tests/contract/test_phase_03a0_architecture.py tests/contract/test_generated_contracts.py -q`
  → `31 passed in 1.00s` (includes `pnpm exec tsc` and `generate_contracts.py --check`).
- Repro script `scratchpad/laneA/repro_strategy_basis.py` (A-1) → output quoted above.
- Report inspection of `data/evaluation/phase-03a1-r4-hosted-rerun-report.json` `matrix_result.conditions` (A-4).
- `grep` inventories for every contract symbol, enum member, and the
  strings named in findings (A-2, A-3, A-8, A-9, A-10, A-11).

**Not run:** `make preflight`, `make lint`, `make typecheck`, `make test`
(other suites), integration suites, `make postgres-check`,
`make phase05a-check`, `make phase06b1-check`, any browser or hosted-model
check. No file outside this lane output was modified.

---

## 5. Open questions for the root orchestrator

1. A-1 needs a wire change (new field on `StrategyPacket` or on
   `CaseContextSnapshot`). The wire-format ADR:53 requires "a new schema
   version and migration decision" for breaking changes and none exists. Who
   decides the versioning mechanism before any contract fix lands?
2. A-2: delete `ModelTrace` or make the runtime emit it? The answer changes
   whether `architecture.md:276` and ADR :114-115 are edited or implemented.
3. A-4 is a product/scope question as much as technical: is the Fast dialogue
   path meant to be product-runtime behavior in this roadmap, or
   evaluation-only until 03C promotes a checkpoint? The docs should say which.
4. Should `revision` be dropped from ephemeral contracts (A-9)? It is
   harmless but every producer fakes it, which is exactly the "hand-maintained
   noise" the wire-format ADR set out to avoid.
5. `test_phase_03a0_architecture.py`: keep as an explicit docs-freeze suite or
   replace with Router precedence tests? It currently reads as architecture
   enforcement to a newcomer and is not.

---

## 6. Brief answers to the packet questions

**Q1 (modeled vs speculative).** 22 of 23 contracts are produced and consumed
in `runtime/` (grep counts in section 1). `ModelTrace` is speculative (A-2).
`FactLedger` is produced but never populated. Several enum members and
`StrategyPacket` fields have no consumer (A-9).

**Q2 (Fast/Slow split).** Justified in the docs by a latency/cost hypothesis
and a trainability boundary (ADR :129-147, defaults ADR :27-30); the
repository holds no per-turn latency or Slow-call-rate measurement, the only
matrix shows 0/32 for every Fast condition and 3/32 for frontier-only, and no
product code path consumes Fast dialogue (A-4). Removing Fast today would
lose nothing observable; it would lose the stated research question.

**Q3 (contradictions).** A-1 (basis binding), A-2 (trace), A-7 a-g.

**Q4 (invariants: typed vs prose).**
- *Model never authorizes/executes*: typed for Slow (`authorization_state`
  Literal, `SlowWorkResult` checks) and `completion_claim` Literal; **prose +
  runtime check** for Fast `action_intent` (`Optional` on the wire,
  rejected at `coordinator.py:335`); tested at `test_contracts.py:101` and
  `test_phase_03a1_agent_core.py:390`.
- *Approval version-bound*: typed fields on `ApprovalRequest`, but the
  equality with the intent/offer is **runtime-enforced** (`capabilities.py:244-257`,
  `domain.py:183-198`, `router.py:152-173`), not expressible in the contract;
  contracts test `:75` is a required-field test, not a binding test.
- *Completion only by evidence*: typed (`contracts.py:515-523`) and tested
  (`:94`); the evidence's case/type binding is verifier-side (`domain.py:286-297`).
- *Capability manifest sole vocabulary*: typed only as the `simulator.`
  prefix; the intent-to-capability link is executor-side (A-3).
- *No hidden state in views*: typed as allowlists with `extra="forbid"` and
  verified-facts-only checks; "no Provider-private state" cannot be typed
  because `VisibleCaseEvent.content` is free text; no negative view tests.
- *Stale output rejected*: typed pin echo for Slow; wrapper-level for Fast;
  runtime-enforced in `coordinator.py`; integration-tested, not contract-tested.
- *Strategy bound to planning basis*: **prose only** (A-1).
- *Single Router outcome with frozen precedence*: enum makes outcomes
  exclusive; precedence is code (`router.py:87-131`) tested only by prose
  markers (`test_phase_03a0_architecture.py:159-173`).

**Q5 (over-engineering).** A-9; the namespace Literal pins are worth keeping.

**Q6 (under-specification).** A-10, A-5, A-11.

**Q7 (`architecture.md` section status).**
| Section (lines) | Status |
|---|---|
| Purpose (1-12) | matches intent; "conducts low-latency dialogue" aspirational (A-4) |
| High-Level Shape + status block (14-54) | matches code (honest status list); diagram labeled target |
| Experience Layer (58-62) | matches (files exist; behavior is lane E) |
| Control Plane (64-68) | matches (endpoint at `app.py:501`; "target" sentence labeled) |
| Durable Orchestration (70-75) | matches existence (lane C for behavior) |
| Agent Intelligence (77-82) | mostly matches; "fact-update validation" exists, fact merge does not |
| Provider and Channel Layer (84-89) | `voice/worker` is a `.gitkeep` — stale listing |
| ML and Data Layer (91-99) | matches; `ml/training`, `ml/serving` are `.gitkeep`, labeled "Target" |
| Slow Reasoner (103-122) | aspirational trigger list (A-1); stale field names (A-7d) |
| Fast Response Model (124-170) | matches contract shape; `pending Slow-work status` dead (A-8); example JSON is illustrative, not a valid document |
| Model Collaboration and Routing (172-193) | precedence matches; basis binding aspirational (A-1); manifest "sole vocabulary" prose (A-3) |
| Core Domain Contracts (195-215) | stale terminology (A-7d,e); "enforced by drift checks" overclaims: drift checks enforce schema = models, not architecture |
| State Ownership (217-226) | MLflow row aspirational (no `mlflow` in any `.py`/`.toml`); rest lane C |
| Agent Decision Loop (228-245) | steps 6 and 10 aspirational (A-1 row, A-7f); the 04A caveat at :234 is honest |
| Data and Training Flow (247-262) | aspirational roadmap, correctly caveated at :262 |
| Safety and Reliability Invariants (264-276) | :268, :272, :273 match; :269 prose at type level (A-3); :276 aspirational (A-2) |
| Observability (278-297) | aspirational (inferred: no trace producer, no span code read) |
| Deployment Shape (299-340) | Research MVP list stale (A-7b); 07A paragraph honest |
| Extension Points (342-347) | aspirational |

## Root verification (2026-09-21)

| Id | Verdict | Evidence inspected by root |
|---|---|---|
| A-1 | confirmed, Important | `router.py:118-149` (only four internally computed mandatory reasons; the rest come from `RouteRequest.mandatory_slow_reason_codes`); the five `RouteRequest(` sites in `runtime.py` (436, 739, 875, 917, 1336) pass no reason codes; `StrategyPacket` fields 289-306 carry no planning-basis fingerprint. Authorization remains bound to the offer revision at execution, so not Blocking. |
| A-2 | confirmed, Important | `grep "ModelTrace("` across runtime/ml/scripts → only `scripts/run_phase_03a1_harness.py:145`. |
| A-4 | confirmed, and raised in weight for the synthesis | `runtime.py:443-448` rejects any Fast `response_text` other than `BOUNDED_FAST_STATUS_TEXT`; `runtime.py:889-899` derives the approval from `offers[0]` + `offer_compliance_violations_for_case`, independent of the Fast decision. The product demo is a deterministic state machine; the model seams are exercised only by the evaluation harness. Severity stays Minor as a defect (nothing is unsafe) but it is the central fact for any "runnable agent demo" claim. |
| A-3, A-5 … A-11 | accepted as reported | Not independently re-derived; each cites path:line and was produced from full reads. |
