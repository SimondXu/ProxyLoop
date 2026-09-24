# PR-13: Slow's proposal drives the intent + A-3 coordinator validator — frozen spec

Status: frozen by the root orchestrator on 2026-09-24 from the `architect`
proposal below (decisions 16, 19, 20). Root answers to §8:

1. A Slow result that fails the A-3 admission check is **rejected as a whole**
   (trace REJECTED with `slow_proposal_*` codes; the command fails as today) —
   fail closed; the proposal is not silently stripped.
2. Storage scope approved: the standing proposal survives a restart via an
   **additive optional field in the `storage_version` 3 envelope** (absent ⇒
   none), no version bump. PR-13 owns `repository.py` and
   `postgres_repository.py` while it is open. Mixed-version processes remain
   unsupported (PR-7).
3. `ScriptedProposingSlowAdapter` (new subclass) becomes the runtime default;
   `ScriptedSlowAdapter` stays byte-for-byte unchanged. Every committed
   `*-check` that predates PR-8 must stay byte-identical. If PR-8's
   `fast-slow-split-scripted.json` must move because the Slow output changes,
   regenerate it explicitly, bump its schema/version note, and say why in the
   log; do not fake the old identity to avoid the move.
4. The Slow re-consult trigger is deferred.
5. No Web input in PR-13. A later Web PR (after PR-12 and PR-14) adds free-text
   consumer turns; root leaning: a dialogue-only `consumer_note` plus an
   explicit "proceed" control — decided in that PR's spec.
6. `CONTEXT.md` gains "Standing Proposal" (via `domain-modeling`).
7. PR-14 retry rule adopted: retry Slow only on a Judge "revise"; if the retry
   is rejected, fall back to the first accepted result.
8. PR-8 S2 redefinition routed to PR-8a (done before its report is frozen).

Sequencing: `runtime.py` writers in order PR-8a → PR-9a → PR-13.

---

# PR-13 design proposal: Slow's proposal drives the intent, with an A-3 coordinator validator

Architect proposal (propose mode). No repository file was edited.

- Baseline: `origin/main` @ `1573a42` (#91, PR-7 trace log). The local `main` checkout is at `c73f6a7`, so the code was read from `git archive 1573a42` in `scratchpad/arch-pr13/src/`.
- Line numbers are at `1573a42`. The PR-8 spec cites `runtime.py:928-955` from `c73f6a7`; at `1573a42` the same block is `runtime.py:919-946`.
- Tags: **[O]** observed in code or by the probe, **[I]** inferred, **[P]** proposed.

Binding inputs:
- build plan rows PR-8/9/13/14, "Do not do", and DoD item 2
- decisions 7, 16–20
- the A-3 limits log and the ADR amendment
- proposal §3/§4/§5/§7
- PR-7 spec I1–I11 (G8)
- PR-8 frozen spec (I1–I12, R4)
- PR-9 spec (D6, §4 structural invariance, runtime.py writer order)

## 0. Probes (read-only, run against the `1573a42` sources)

`scratchpad/arch-pr13/probe.py` and `probe2.py` were run with the `runtime/.venv` interpreter and the exported packages first on `PYTHONPATH`. Nothing was written outside the scratchpad.

```
scripted Slow (today default)   slow_calls=1 cap_props=[0] act_props=[0] approval=yes route=wait_for_approval
                                traces=[slow SUCCEEDED slow_result_current, fast SUCCEEDED fast_result_current]
incoherent Slow proposal        slow_calls=1 cap_props=[1] act_props=[1] approval=yes route=wait_for_approval
  (END_INTERACTION action + capability "simulator.not_in_manifest" v9.9 + offer_id "not-an-offer")
                                traces=[slow SUCCEEDED slow_result_current, fast SUCCEEDED ...]
target $70 via intake           create_case raised ValueError: target_monthly_total is incompatible with the fixed offer
consumer at +61 min             slow_calls=2 (strategy expired → refresh) approval=no route=fast_now
probe2: every intake-valid (current, target) on a grid of 16 points → offer_compliance_violations == ()
```

## 1. Current state (Q1)

### 1.1 Who opens an approval today: deterministic policy only [O]

- `_append_event_serialized` (`case_runtime/runtime.py:847-1009`) runs three steps in order:
  1. refresh (`:903`, Slow only if the Router says `SLOW_REFRESH`)
  2. Fast (`:906-918`)
  3. the approval rule at `:921-946`:
     `if event_snapshot.offers and not offer_compliance_violations_for_case(case, offers[0], evaluated_at=occurred_at)`
     → `_build_approval(...)` (`:1699-1752`) → phase `AWAITING_APPROVAL`, followed by `await_approval` (`:987`).
- The intent is compiled entirely by the Runtime:
  - `intent_id = stable("intent:{case}:{offer}")`
  - `idempotency_key = "phase-04a:{case}:accept-offer"`
  - `action_type = ACCEPT_OFFER`, terms from `offer_material_terms(offer)`
  - the installed strategy's id and revision
- At approval time the executor's `CapabilityProposal` is also fabricated by the Runtime: `_capability_proposal(offer, decided_at)` (`:1149`, `:1780-1795`).
- The PostgreSQL codec requires that proposal to equal the deterministic value (`postgres_repository.py:1367`, `:1525-1527`).
- Consequence: any consumer event on a compliant offer opens the approval. Every intake-valid Case has a compliant offer for its first hour (probe2), because intake refuses `target < 7200` and the offer is $72.00 (`runtime.py` `_case_with_intake`). So the only reachable "consumer event without an approval" is after the offer expires (issued + 1 h, `provider.py:114`). Multi-turn dialogue before approval is therefore unreachable today, not merely rare.

### 1.2 What Slow proposes, and whether it is used [O]

- `SlowWorkResult` carries three fields: `strategy_proposal`, `capability_proposals: tuple[CapabilityProposal, ...]`, and `action_proposals: tuple[ActionIntent, ...]` (`contracts.py:1472-1473`).
- **The Runtime and the services never read `capability_proposals` or `action_proposals`.** A grep over `runtime/packages/case_runtime` and `runtime/services` finds no hit. Only `strategy_proposal` is used, at `runtime.py:785` and `:1596`.
- The scripted Slow always returns `capability_proposals=()` and `action_proposals=()` (`agent_core/scripted.py:145-146`).
- The model compilers do build a joined pair. `openai_adapter/outputs.py:182-245` produces one `CapabilityProposal` plus one `ActionIntent`, with the offer-id argument, material terms, the new strategy's id and revision, and `expires_at = created_at + 5 min`. The Runtime ignores both (probe row 2).
- Slow is called only on a Router `SLOW_REFRESH` (`coordinator.py:202-245`). The mandatory reasons are case initialization, strategy expired, basis incompatible, stale approval, and pending slow work (`router.py:127-144`). The planning basis excludes events and phase (`contracts.py:910-962`). So a consumer turn on a current strategy runs Fast only.

### 1.3 What validates Slow today [O]

- `CaseCoordinator.validate_slow_result` (`coordinator.py:474-529`) checks:
  - pins, basis, case, request id, and times
  - strategy binding
  - for actions, only `created_at` and `expires_at` (`:518-522`)
- It never relates `action_proposals` to `capability_proposals` or to the manifest. The `SlowWorkResult` contract validator checks case, revisions, and strategy per action, but not the join.
- The executor is the only point that enforces the join (`capabilities.py:182-275`): `unsupported_capability`, `capability_action_mismatch`, `capability_offer_binding_mismatch`, `current_offer_mismatch`, and `current_offer_terms_mismatch`. This is recorded in `docs/decisions/2026-08-23-fast-slow-orchestration.md` (amendment 2026-09-24) and `harness/log/docs-contract-semantics-limits.md` (I-1).
- `validate_slow_result` is also the ML evaluator's validity function:
  - `runner_v2.py:584-595` (scripted ceiling, reached from `replay_v2.py:224`)
  - `runner_v2.py:948-953` (frontier)
  - `run_phase_03a1_harness.py:1068` and `:1295`
- `ScriptedSlowAdapter`'s output is fingerprinted into the committed `data/manifests/phase-03a1-episodes.json` (32 `output_fingerprint`s; `run_phase_03a1_harness.py:1294-1335`).

### 1.4 What A-3a is [I, from the sources]

- A-3 is the audit finding that the manifest is the sole action vocabulary only at the executor (`harness/code_review/repo-audit-A.md` §A-3).
- A-3a is the **contract** remedy in proposal §4, A-3 row:
  - `ActionIntent + capability: CapabilityReference`
  - a `SlowWorkResult` validator requiring every `action_proposals[i]` to name a `capability_proposals` entry
  - `CapabilityDefinition + arguments: tuple[CapabilityArgumentSpec]`
- That is a wire-schema change, which needs 1.2, regenerated fixtures, and moved frozen fingerprints.
- Decision 19 replaces it with a coordinator validator, with no wire change. [I: "A-3a" names the contract option; no document spells the letter out.]

## 2. Target design (Q2)

### 2.1 Shape [P]

The model proposes. The coordinator admits or rejects the proposal as a whole. The Runtime holds the admitted proposal as the Case's **standing proposal**. On a consumer event, the Runtime compiles an intent from the standing proposal only if the proposal is still admissible and deterministic policy finds the named offer compliant.

- **"propose-action"** = an admitted Slow result with exactly one (`CapabilityProposal`, `ActionIntent`) pair.
- **"continue-dialogue"** = an admitted result with no proposals.
- No contract field is added (decisions 19 and 20).

Flow, with the PR-8 steps unchanged:

1. **Slow admission** (inside `advance`, product coordinator only):
   `validate_slow_result` → if accepted, run the A-3 validator hook → trace (PR-7 I6) → `CoordinatorOutcome.slow_result` is the admitted result, or `None`.
2. **Standing proposal update.** Every admitted Slow result replaces the standing proposal with its `capability_proposals[0]`, or with `None`. Update sites:
   - `create_case` (`:767-781`)
   - `_refresh_strategy_if_required` (`:1568-1626`), used by `append_event` and `ingest_channel_event`
3. **Consumer event** (`append_event`, replacing `:921-930`), where `standing` is the post-refresh value:
   ```python
   offer = standing_proposal_offer(standing, event_snapshot, evaluated_at=occurred_at)
   if offer is not None and not offer_compliance_violations_for_case(case, offer, evaluated_at=occurred_at):
       intent, approval = _build_approval(case, strategy, offer, ...)   # unchanged compiler
       standing = None                                                    # consumed in the same write
   ```
   The intent, approval, and executor proposal stay Runtime-compiled (`_build_approval`, `_capability_proposal`). A model-authored `ActionIntent` never enters the snapshot. It is only validated for coherence.
4. `routed` advance, then the PR-8 assistant line appended last (PR-8 I6), then persist `standing_proposal` with the state.

### 2.2 The A-3 coordinator validator [P]

- **Placement.** The validator is a pure function in a new `agent_core/proposal_admission.py`. It is injected through a constructor hook `CaseCoordinator(..., slow_proposal_check=...)`, which is passed only by `ThinAgentRuntime._coordinator()`. This mirrors PR-8's `fast_gate` exactly.
- Inside `advance`, after `validate_slow_result` accepts:
  ```python
  if audit.accepted and self._slow_proposal_check is not None:
      codes = self._slow_proposal_check(slow_output, request.snapshot, request.created_at)
      if codes:
          audit = replace(audit, accepted=False, reason_codes=codes)
  ```
  This runs before `audits.append` and before the trace is built, so the trace carries the verdict (PR-7 I6, I11).
- **Not inside `validate_slow_result`.** That function is the ML evaluator's validity function (§1.3). New codes there can change the `canonical`/`failures` values that `replay_v2` and the rescore checks recompute from stored model outputs. For example, a frontier `escalate` proposal with no offer argument would newly fail a binding rule. A hook makes the ML path identical by construction.

Rules. They are checked in fixed order, and each code appears once. `evaluated_at` = `request.created_at`. `m` = `snapshot.capability_manifest`. `c` and `a` are the capability and action proposals.

| # | Code | Rule | Executor counterpart |
|---|---|---|---|
| 1 | `slow_proposal_count_exceeded` | `len(c) > 1` or `len(a) > 1` (proposal §7: one capability at most) | — |
| 2 | `slow_proposal_unpaired` | `len(a) != len(c)`: the join in both directions. With ≤ 1 of each, the pair is positional | — |
| 3 | `slow_proposal_capability_unsupported` | `(capability_id, version)` of `c` is not in `m.capabilities` | `unsupported_capability` |
| 4 | `slow_proposal_capability_action_mismatch` | `a.action_type ∉ definition.allowed_action_types` | `capability_action_mismatch` |
| 5 | `slow_proposal_capability_expired` | any of `c.expires_at`, `definition.expires_at`, `m.expires_at` is `≤ evaluated_at` | `capability_proposal_expired`, `capability_expired`, `capability_manifest_expired` |
| 6 | `slow_proposal_predates_result` | `c.created_at < result.created_at` (mirrors `slow_action_predates_result`) | `capability_proposal_not_current` |
| 7 | `slow_proposal_offer_binding_mismatch` | the `offer_id` arguments of `c` ≠ `(a.offer_ref.offer_id,)`; or `a.offer_ref is None` while `c` has an `offer_id` argument | `capability_offer_binding_mismatch` |
| 8 | `slow_proposal_offer_not_current` | `a.offer_ref` (id, revision) is not in `snapshot.offers`. Offer **expiry is not checked here**: policy owns it (`offer_expired`) | `current_offer_mismatch` |
| 9 | `slow_proposal_terms_mismatch` | `a.material_terms_hash ≠ material_terms_hash(a.material_terms)`, or the sorted terms ≠ `offer_material_terms(offer)`. Both functions come from contracts, so `agent_core` keeps its single dependency | `action_material_terms_hash_mismatch`, `current_offer_terms_mismatch` |
| 10 | `slow_proposal_intent_binding_mismatch` | any of `a.case_id`, `case_revision`, `constraint_set_revision` ≠ snapshot; or `a.strategy_id/revision` ≠ `result.strategy_proposal` (else ≠ the installed strategy) | `action_case_*`, `action_strategy_mismatch` |
| 11 | `slow_proposal_action_not_delegated` | `a.action_type ∉ authority.allowed_actions ∪ authority.approval_required_actions` | `delegated_authority_denied` |

- Rules 3–11 run only for a well-formed pair: when rule 1 or 2 fires, only those codes are returned.
- A result with no proposals yields `()`.
- The OpenAI compiler's accept pair satisfies every rule by construction (`outputs.py:182-245`). [I; red-first test A1b proves it.]

Use-time admissibility (Runtime, deterministic, no model call, not traced) goes behind one small interface:

```python
def standing_proposal_offer(proposal: CapabilityProposal | None, snapshot: CaseContextSnapshot,
                            *, evaluated_at: datetime) -> ProviderOffer | None:
    """The current offer the standing proposal names, or None when there is none or it is not admissible now."""
```

- It returns `None` if any of these holds:
  - the proposal is `None`
  - its capability is not in the manifest
  - the definition's `allowed_action_types != (ACCEPT_OFFER,)`, since the Runtime compiles only accept today
  - any expiry of the proposal, definition, or manifest is `≤ evaluated_at`
  - the proposal does not carry exactly one `offer_id` argument naming a snapshot offer
- Offer expiry and compliance stay with `offer_compliance_violations_for_case`, the only label authority (decision 3).

### 2.3 On a reject [P]

There are two distinct classes.

| Class | Examples | Trace | Command | Approval | Dialogue |
|---|---|---|---|---|---|
| **Model reject**: the coordinator refuses the Slow result | any `validate_slow_result` code (unchanged), any `slow_proposal_*` code | Slow trace `REJECTED`; its `reason_codes` are the A-3 codes (they replace `slow_result_current`), `output_ref` = result id | Fails as today: `ModelRuntimeError("slow")` → content-free `model_result_rejected`; no state write; traces are kept (PR-7) | none | The consumer's message is not applied (same as any Slow reject today) |
| **Deterministic refusal**: an admitted proposal is not compiled | no standing proposal ("continue-dialogue"); `standing_proposal_offer` is `None` (stale); policy violations such as `offer_expired` | none new (no model call) | **Applies** | none | Continues: the PR-8 assistant line is delivered, and the phase and standing proposal stay unchanged |

- **Atomic reject is recommended** (root Q1). A result with an incoherent proposal is not trusted for its strategy either. This matches the existing posture: one expired action already voids the whole result, at `coordinator.py:518-522`.
- It keeps PR-7 I11 honest: `REJECTED` means nothing from this call was used.
- Rejected alternative, "strip the proposal and install the strategy": the trace would say `SUCCEEDED` for a partly used output, or it would need a new partial result state.
- Flakiness is PR-14's retry to absorb, not PR-13's.

## 3. Byte-identity (Q3)

### 3.1 The scripted Slow [P]

- Add `ScriptedProposingSlowAdapter(ScriptedSlowAdapter)` in `agent_core/scripted.py`. `ScriptedSlowAdapter` stays byte-for-byte unchanged: the harness manifest pins its output (§1.3).
- `reason(request)` calls `super().reason(request)`, so the strategy text is unchanged. That matters for PR-9 D6 parity, and it also keeps the `result_id` formula `slow-result:{request_id}`.
- Then it re-validates a copy through `SlowWorkResult.model_validate(...)`, never `model_copy`, so the contract validators run:
  - **If** `view.offers` has an offer with `expires_at > request.created_at` (the first such offer), add one pair:
    - `CapabilityProposal`:
      - `proposal_id = stable_uuid4("scripted-capability:{request_id}")`
      - capability = the manifest definition whose `allowed_action_types == (ACCEPT_OFFER,)`, if one exists
      - `arguments = (offer_id,)`
      - `created_at = request.created_at`
      - `expires_at = offer.expires_at` (load-bearing: see the proof)
    - `ActionIntent`:
      - `intent_id = stable_uuid4("scripted-intent:{request_id}")`
      - the request pins' case revision and constraint revision, and the result strategy's id and revision
      - `ACCEPT_OFFER`, `offer_ref`, and `offer_material_terms(offer)` with its hash
      - `approval_required = ACCEPT_OFFER ∈ authority.approval_required_actions`
      - `idempotency_key = "scripted:{request_id}:0"`
      - `created_at = request.created_at`
      - `expires_at = offer.expires_at`
  - **Else** no proposal.
- It proposes **regardless of compliance**. `agent_core` cannot import `telecom_domain`, and this way the default path shows that policy, not the model, decides.
- Identity: `ModelIdentity("scripted", "scripted_slow", "proposing-v1", "scripted-v1", "no-prompt")` (root Q3).
- `ThinAgentRuntime(slow=None)` → `ScriptedProposingSlowAdapter()`. That one change covers direct mode, API scripted mode, and the Temporal worker (`activities.py:269`, `config.py:49`, `app.py:146`).
- `_infer_adapter_mode` still reports `scripted`, because the class is a subclass.

### 3.2 Proof that decisions and states are identical [I, argued from code; P for the tests that pin it]

Setup: `O` is the single offer. The codec requires exactly one offer (`postgres_repository.py:1297`), and the Runtime never adds offers. `t` is a consumer-event time. `t_s ≤ t` is the time of the last admitted Slow call (create at `T0`, or a refresh at an event time, which may equal `t`).

Two facts about today:
- the approval rule is `A_main(t) ⇔ compliant(O, t)`
- compliance includes `O.expires_at > t` (`offer_policy.py:118-119`)

What the proposing Slow guarantees:
- It sets `standing = P(O)` iff `O.expires_at > t_s`, with `P.expires_at = O.expires_at`.
- `P` passes all 11 A-3 rules by construction:
  - pair and manifest: the manifest is `phase-04a-runtime-v1` with only `accept_fictional_offer`
  - expiry: the manifest and definition expire at the goal deadline, created + 9 days (`runtime.py:1902`, `:2005-2027`), which is after `O.expires_at`, created + 1 h
  - terms: the same function as the offer's
  - intent binding and delegation: `ACCEPT_OFFER` is approval-required (`episode.py:308`)

So the trace audit stays `("slow_result_current",)` / `SUCCEEDED`. Every Slow result that main accepts is also admitted, and no new command fails.

Equivalence:
- `compliant(O,t) ⇒ O.expires_at > t ≥ t_s ⇒ standing = P(O)`
- `P` is admissible at `t`: `P.expires_at = O.expires_at > t`, and the manifest is current
- `⇒ A_13(t) = compliant(O,t) = A_main(t)`
- Conversely, `A_13(t) ⇒ compliant(O,t)` by construction.
- The comparator must be `≤` on both sides, identical to `offer_expired`.

Compiled objects:
- the approval, the intent, and the claim-time `_capability_proposal` come from the unchanged functions with the same arguments (`offer = O = offers[0]`)
- snapshots, receipts, the Provider state, and `last_fast_decision` are identical

Traces:
- the call count, order, roles, results, reason codes, `output_ref`, and `request_id` are identical
- only `model_version` differs (`proposing-v1`), and therefore `trace_id`
- traces are not a committed artifact

Consumption:
- after an approval exists, every consumer and channel event is refused (`runtime.py:868-877`, `:399-403`)
- so `standing = None` on consumption changes no decision

### 3.3 Committed `*-check` status under this design [I; verification in §6.6]

| Artifact / check | Why unchanged |
|---|---|
| `contracts-check` | no contract or schema change (A-3a not taken) |
| `harness-check` (`data/manifests/phase-03a1-episodes.json`) | `ScriptedSlowAdapter` untouched |
| `hosted-rerun-check` / `hosted-rescore-check`, `baselines-historical-check`, `validity-smoke-check`, `phase03c-*` | `validate_slow_result`, `advance` with no hook, and the Router are untouched; r4 `_R4_EXECUTION_PATHS` are untouched (`coordinator.py` is not listed, but its default behaviour is unchanged) |
| `fast-slow-split-check` (PR-8, `data/evaluation/fast-slow-split-scripted.json`) | same Slow and Fast calls per turn, the same results, and the same delivered lines. **Obligation:** confirm the report does not embed the Slow `model_version`; if it does, keep `scripted_slow`/`deterministic-v1` as the identity and record the provenance limit instead |
| `phase04d-profile-check` | statuses and shape unchanged |
| `negotiation-check`, `benchmark-check`, `data-pilot-check` | not on this path |

What **would** move under the rejected designs:
- **A-3a:** `contracts/` plus fixtures.
- **Validator inside `validate_slow_result`:** possibly the replayed and rescored ML reports.
- **Proposals added to `ScriptedSlowAdapter`:** `phase-03a1-episodes.json`.
- **A Slow consult on every consumer turn:** `fast-slow-split-scripted.json` (S1's consumer turn becomes `slow_then_fast`).

## 4. Multi-turn and the Web (Q4)

- **PR-13 alone does not make Web multi-turn possible with the scripted default, and it should not.**
  - Byte-identity requires the first consumer event on a compliant offer to still open the approval.
  - Every intake-valid Case is compliant for its first hour (§1.1).
- What PR-13 changes is the reason: the approval is now caused by a proposal, not by the event. That seam is what a multi-turn follow-up needs.
- **Recommendation: no Web input in PR-13; a separate PR ("PR-13w").**
  - Order: after PR-12, keeping the single writer of `conversation-workspace.tsx` in the order 8b → 10 → 12 → 13w; and after PR-14.
  - It needs product decisions the root owns, including the Slow deliberation policy and the regeneration of the split report.
- Options for that PR:
  - **(a)** A free-text turn is a dialogue-only `consumer_note`: Fast replies and the standing proposal is not acted on. An explicit "proceed" control posts `consumer_message`, which acts on it. This matches proposal §6's table. It is deterministic, adds no model cost, needs no re-consult trigger, and keeps today's bytes. It touches `commands.py:43,153`, `app.py:85`, and the Web.
  - **(b)** The scripted demo Slow deliberates: it proposes only after k consumer turns. This needs a Slow re-consult trigger (for example `approvable_offer_without_proposal`, passed through the existing `RouteRequest.mandatory_slow_reason_codes`). It moves `fast-slow-split-scripted.json` (a deliberate regeneration with a version bump).
  - I lean to (a). It is a product decision.
- Side finding for PR-8a [O]:
  - PR-8 S2 as written ("$92 → $70, non-compliant, 4 consumer messages") cannot be constructed: intake raises for a target below $72.00.
  - With any valid target, the first message opens the approval and the later messages get 409 "awaiting approval".
  - The only runtime multi-turn shape is consumer events after offer expiry (+60 min). Route this to the PR-8a implementer.

## 5. Interaction with PR-14 (Q5)

| Concern | Frozen by PR-13 | PR-14's job |
|---|---|---|
| Where the Judge sits | Inside `advance`, after `validate_slow_result` and the A-3 hook admit a result. The Judge sees only admitted results, and its traces go through `_advance` (PR-7 I6, one `.advance(`) | add `judge=` and `role=judge` traces |
| What the Runtime consumes | Only `CoordinatorOutcome.slow_result`, meaning "the final admitted Slow result". The standing proposal comes from it; the Runtime never reads the log (PR-7 I8) | keep that meaning; the retry's result replaces the first only if admitted |
| Retry trigger | A-3 codes are in `ResultAudit.reason_codes` | Recommend Judge-`revise`-only retry. On a rejected retry, fall back to the first admitted result: the Judge is advisory and must never turn a valid outcome into a failure. Feedback goes in-process, off-contract (decision 20) and off-log (PR-7 I8), for example through an optional `FeedbackReasoningSlowAdapter` protocol |
| `judge_required` | The scripted Slow proposes on every Slow call with an unexpired offer | The Judge will then fire on create and on each refresh in S1/S2, so PR-14 **will** move `fast-slow-split-scripted.json`. Its row does not require byte-identity; plan a report version bump |
| Import boundary | `proposal_admission.py` is pure (imports contracts only) and may be imported by evaluation; it must never import the Judge | the import-boundary test |

## 6. Recommendation

### 6.1 Frozen interfaces [P]

```python
# agent_core/proposal_admission.py (new; imports proxyloop_contracts only)
SLOW_PROPOSAL_CHECK_VERSION: Final = "slow-proposal-v1"
SlowProposalCheck = Callable[[SlowWorkResult, CaseContextSnapshot, datetime], tuple[str, ...]]
def slow_proposal_violations(result: SlowWorkResult, snapshot: CaseContextSnapshot,
                             evaluated_at: datetime) -> tuple[str, ...]: ...
def standing_proposal_offer(proposal: CapabilityProposal | None, snapshot: CaseContextSnapshot,
                            *, evaluated_at: datetime) -> ProviderOffer | None: ...

# agent_core/coordinator.py (additive, next to PR-8's fast_gate)
class CaseCoordinator:
    def __init__(self, router=None, snapshot=None, *, clock=None, monotonic=None,
                 fast_gate=None, slow_proposal_check: SlowProposalCheck | None = None) -> None: ...

# agent_core/scripted.py (additive; ScriptedSlowAdapter untouched)
class ScriptedProposingSlowAdapter(ScriptedSlowAdapter): ...

# case_runtime/repository.py
@dataclass(frozen=True, slots=True)
class CaseRuntimeState:
    ...
    standing_proposal: CapabilityProposal | None = None
    # __post_init__: standing_proposal is None whenever snapshot.approval_requests is non-empty

# case_runtime/postgres_repository.py
class _CaseStorageEnvelope:  # storage_version stays 3; additive optional field, absent ≡ None
    standing_proposal: CapabilityProposal | None = None
def _verify_standing_proposal(envelope, snapshot) -> None:
    """None if any approval exists; else the capability is in the manifest with allowed (ACCEPT_OFFER,),
    and it has exactly one offer_id argument naming snapshot.offers[0]. Expiry is not checked on load."""

# case_runtime/runtime.py
# ThinAgentRuntime(slow=None) -> ScriptedProposingSlowAdapter()
# _coordinator(): + slow_proposal_check=slow_proposal_violations
# _refresh_strategy_if_required -> (snapshot, admitted SlowWorkResult | None)
# create_case / append_event / ingest_channel_event: standing proposal replaced by each admitted result
# append_event: approval iff standing_proposal_offer(...) is not None and policy is compliant; then standing = None
# record_channel_delivery (both sites): carry standing_proposal
```

### 6.2 Invariants [P]

- **J1 Authority.** An intent or approval exists only if all three hold:
  - an admitted Slow result proposed it (through `validate_slow_result` and the A-3 validator)
  - `standing_proposal_offer` admits it at the event time
  - `offer_compliance_violations_for_case` is empty for the named offer

  Intent, approval, and executor proposal are Runtime-compiled by the unchanged `_build_approval` and `_capability_proposal`. Model intent fields never reach the snapshot.
- **J2** The proposal source is `CoordinatorOutcome.slow_result` only, never the trace log (PR-7 I8).
- **J3** The A-3 validator runs only on the Runtime's coordinator. `validate_slow_result`, `advance` without the hook, `ScriptedSlowAdapter`, `router.py`, and every contract are unchanged.
- **J4** A-3 reject = Slow trace `REJECTED` with `slow_proposal_*` codes, `slow_result=None`, and the caller's existing `ModelRuntimeError("slow")`. No state write.
- **J5 Lifecycle.**
  - Each admitted Slow result replaces the standing proposal, including with `None`.
  - The write that creates the approval clears it.
  - Every other transition carries it.
  - It is `None` whenever `approval_requests` is non-empty (`__post_init__` and codec).
- **J6** A deterministic refusal never fails the command: no approval, one assistant line (PR-8 I6), command applied.
- **J7** There is one `.advance(` in `runtime.py` (PR-7 G8).
- **J8 Scripted equivalence.** With the default adapters, `approval(t) ⇔ offers ∧ compliant(offers[0], t)`. Snapshots, receipts, and Provider states are byte-identical to main.
- **J9** The standing proposal is Runtime-local: it appears in no snapshot, view, projection, API body, log line, or trace.
- **J10** There is no contract change and no `SlowWorkRequest.revision_feedback`.

### 6.3 Acceptance criteria

1. With a Slow that returns a strategy only ("continue-dialogue"), a consumer event on a compliant offer:
   - applies (200)
   - delivers the assistant line
   - opens **no** approval
   - leaves the phase `STRATEGY`
2. With the probe's incoherent Slow, `create_case` fails as `model_result_rejected`:
   - the Slow trace is `REJECTED` with exactly `(slow_proposal_capability_unsupported, slow_proposal_offer_binding_mismatch, slow_proposal_action_not_delegated)`
   - rule 4 and the definition part of rule 5 are skipped when rule 3 finds no definition
   - no Case is persisted
3. The default scripted Runtime reproduces main exactly. This is a differential test over consumer-event offsets {+1 s, +29 min, +31 min (refresh), +59 min 59 s, +60 min, +61 min} and over direct, API, and Temporal paths, comparing approval presence and the byte-equal intent and approval.
4. The model path works in both directions:
   - OpenAI-compiled `_slow_output_proposing_accept()` → approval
   - `_slow_output()` (no `next_capability`) → no approval
5. The standing proposal survives, in memory and in PostgreSQL:
   - a channel ingest without a refresh
   - a delivery callback
   - a dedup replay

   It is replaced on a refresh and cleared on approval. The codec rejects a proposal while an approval exists, an unknown capability, and a foreign offer id. A pre-PR-13 v3 row decodes with `None`.
6. Every committed `*-check` is byte-identical (§6.6 proof obligation).
7. Docs:
   - `docs/architecture.md`: Model Collaboration and Routing, and Safety invariants. "the executor is the only enforcement point" becomes "the coordinator's A-3 validator (Runtime path) and the executor"; the ML evaluator path is unchanged.
   - an ADR amendment on the A-3 coordinator validator, superseding the 2026-09-24 amendment's "only enforcement point" bullet
   - `CONTEXT.md` "Standing Proposal" (via `domain-modeling`, root Q6)
   - `audit-remediation-status.md`: A-3 changes from recorded limit to coordinator validator
   - the `test_contract_semantics_limits.py` docstring wording (its assertions stay valid: `validate_slow_result` itself still does not join)
   - a PR log

### 6.4 Red-first test list

**Red on main (write first and record the failure):**
- **R1** `test_slow_without_proposal_opens_no_approval` (in-memory). Main opens one (probe row 1 mechanism).
- **R2** `test_incoherent_slow_proposal_is_rejected_and_traced` (in-memory). Main returns SUCCEEDED and an approval (probe row 2).
- **R3** `test_model_slow_without_next_capability_opens_no_approval` (fake transport, adapted from `test_phase_04b_model_runtime.py:155`).

**Pure (`tests/integration/test_slow_proposal_admission.py`, no DB):**
- **A1a** one row per code 1–11, plus the rule 1/2 short-circuit and deterministic order.
- **A1b** a scripted proposing result and an OpenAI-compiled accept result both return `()`.
- **A2** `standing_proposal_offer` table: `None`, unknown capability, non-accept definition, expired proposal/definition/manifest, zero or two `offer_id` args, a foreign offer; and the happy path returns the offer.
- **A3** Agreement with the executor: for rules 3, 4, 7, 8 and 9, the same crafted inputs make the executor `_validate` refuse with the counterpart code. This pins the duplication against drift.

**Coordinator (no DB):**
- **C1** A hook reject gives an audit rejected with the A-3 codes, a trace `REJECTED`, and `slow_result=None`.
- **C2** No hook plus the incoherent result gives an outcome equal to main's (ML guard).
- **C3** A stale Slow result: the hook is not called and only validation codes appear.

**Runtime (in-memory):**
- **D1** the differential equivalence (criterion 3), direct and `apply_command`
- **D2** lifecycle J5 across create, append with and without refresh, channel ingest, delivery callback, dedup, and the `__post_init__` invariant
- **D3** a coherent proposal whose `expires_at` exceeds the offer's, used at +61 min: policy `offer_expired` → no approval and the command applies (policy stays authority)
- **D4** `adapter_mode == "scripted"`; PR-7 G8 still holds
- **D5** J9: the projection allow-list is unchanged; no standing proposal in the API body
- **D6** the Temporal/API scripted path via the existing `test_phase_05a_case_runtime` flow, unchanged

**DB (need `postgres-test`, and some need Temporal):**
- **P1** codec round-trip of set, carried, and consumed states; decoding a v3 payload without the key
- **P2** codec rejections (criterion 5)
- **P3** `test_phase_04c_persistent_case_store.py:239-270`, the model → scripted switch: its model output must propose (`_slow_output_proposing_accept`). A model-authored standing proposal (5-min expiry) must round-trip, and the scripted Runtime continues. This test is **DB-gated, so it shows only in the DB lane.**
- `postgres-check`, `phase05a-check`, and `phase06b1-check` pass unchanged, by equivalence.

**Expected test churn (the implementer lists every failure and shows each is only this):**
- Fakes deriving from `ScriptedSlowAdapter` that expect an approval must derive from `ScriptedProposingSlowAdapter`:
  - `test_slow_refresh_strategy_expiry.py:48-94`
  - `test_strategy_basis_binding.py` (the Runtime cases)
  - `test_phase_04a_agent_runtime.py:425-435`
  - `test_persisted_claim_and_traces.py` flows
- Model outputs expecting an approval must propose: `test_phase_04b_model_runtime.py:155-172`, `test_phase_04d_control_plane_operations.py:322,349`, and the 04c test above.

### 6.5 Owned files, order, split

- **Single PR (size M), after PR-8a and PR-9b merge.** Both write `runtime.py` (PR-9 spec: "PR-13 comes later"). It merges before PR-14.
- New files:
  - `runtime/packages/agent_core/src/proxyloop_agent_core/proposal_admission.py`
  - `tests/integration/test_slow_proposal_admission.py`
  - `tests/integration/test_slow_driven_intent.py`
- Edited:
  - `agent_core/{coordinator.py, scripted.py, __init__.py}`
  - `case_runtime/{runtime.py, repository.py, postgres_repository.py, __init__.py}`
  - the churned tests above
  - docs: `docs/architecture.md`, the ADR, `CONTEXT.md`, `harness/context/audit-remediation-status.md`, a spec under `harness/context/`, and the log under `harness/log/`
- **Scope addition the root must approve:** the build-plan row names only `runtime.py`. This design also writes `repository.py` and **`postgres_repository.py` (a hot file)**, because the standing proposal must survive a restart between `create_case` and the consumer event (Temporal and PostgreSQL).
- Not owned (escalate if needed): contracts and `contracts/`, `validate_slow_result`, `ScriptedSlowAdapter`, `router.py`, `capabilities.py` (the executor), `app.py`, `commands.py`, `workflow.py`, `activities.py`, `ml/`, `data/`, the Web.
- Fallback split, only if review is too large:
  - 13a: `agent_core` only (validator, hook, adapter, pure tests). Inert, no DB lane.
  - 13b: Runtime and storage wiring (behaviour change, DB lane).

  13a alone is an unwired seam ("one adapter = hypothetical seam"), so prefer one PR.

### 6.6 Gates

- Focused tests: pytest on the new and churned tests, plus:
  - `test_phase_04a/04b/05a_case_runtime`
  - `test_model_trace_producer`
  - `test_persisted_claim_and_traces`
  - `test_phase_06b1_channel_runtime`
  - `test_contract_semantics_limits`
  - `test_phase_03a1_agent_core`
- `make lint typecheck`, then `make test`, which includes every `*-check` and PR-8's `fast-slow-split-check`.
- **Proof obligation:** `git diff --stat origin/main -- contracts/ data/ ml/ scripts/` shows nothing, and `make phase04d-profile-check` passes.
- `make preflight` once, on the stable diff.
- The DB lane, serially: `postgres-check` → `phase05a-check` → `phase06b1-check`.
- An independent `reviewer`, because this is an authorization boundary and a storage change. Also run `/security-review` as a quick scan.

## 7. Risks

| # | Risk | Mitigation / note |
|---|---|---|
| K1 | **Silent drop.** `runtime.py` constructs `CaseRuntimeState` explicitly at 10 sites. A pre-approval site that omits `standing_proposal` silently stops approvals, most likely on the channel paths | D2 lifecycle test over every command type; the J5 invariant; a review checklist. Optionally move the carry sites to `dataclasses.replace` |
| K2 | **Model-mode behaviour change (intended).** A model Slow that proposes nothing opens no approval. The OpenAI compiler's 5-min proposal expiry means a consumer who confirms after 5 min gets no approval until the 30-min strategy refresh, a stranded wait | No re-consult trigger in PR-13 (root Q4). Model Slow is outside every gate (decision 17; credentials are a hard limit). Stated as a known limit |
| K3 | **Storage.** The field is additive in v3 with `extra="forbid"`. Code from before PR-13 cannot read rows written by PR-13, so a branch switch on the demo volume fails closed | Root Q2: no bump, or bump to 4 with a v3 upgrade path |
| K4 | **Codec cannot replay model output.** It validates the proposal's structure only | Stated; expiry is handled at use time |
| K5 | **Duplication with the executor.** The A-3 validator re-implements parts of `capabilities._validate` | A3 agreement test; the executor stays untouched and authoritative at execution |
| K6 | **PR-14 moves the split report.** The Judge fires on every scripted proposal | Planned in PR-14 (§5) |
| K7 | **Hot files and ordering.** `runtime.py` (PR-8a → PR-9b → PR-13 → PR-14) and `postgres_repository.py` | Merge `origin/main` after each prior writer; no rebase |
| K8 | **The policy verdict on a proposal is invisible.** The split report cannot tell "Slow proposed, policy refused" from "Slow did not propose" | Accepted limit; a later "proposal disposition" on the transition receipt, if needed |
| K9 | **Test churn hides a regression** | The implementer lists every changed assertion with the reason. The reviewer checks that none weakens the expectation that an approval opens for a scripted proposal |

## 8. Questions the root must decide

1. **Reject semantics:** atomic rejection of a Slow result that fails A-3 (trace `REJECTED`, command fails as today). The alternative is to strip the proposal and install the strategy. **Recommend atomic.**
2. **Scope and storage:** approve adding `repository.py` and `postgres_repository.py` to PR-13, and choose between an additive v3 field (recommended, with a pre-PR-13-row decode test) and `storage_version` 4.
3. **Scripted Slow identity:** `ScriptedProposingSlowAdapter` as a subclass, with `model_version="proposing-v1"`. **Recommend yes**, unless PR-8a's report embeds the Slow identity; then keep `deterministic-v1` and record the limit.
4. **Re-consult trigger** (Slow re-run when an approvable offer has no admissible standing proposal): **recommend defer** to the multi-turn follow-up. It is inert for scripted runs and needed only once a non-proposing Slow is reachable in the demo.
5. **Web free-text input:** **not in PR-13.** A separate PR-13w after PR-12 and PR-14, which needs a product decision between (a) dialogue-only `consumer_note` plus an explicit proceed control (my lean) and (b) scripted Slow deliberation plus the re-consult trigger (which moves the split report).
6. **`CONTEXT.md`:** add "Standing Proposal" now via `domain-modeling`, or name it differently.
7. **For the PR-14 spec:** a Judge-only retry, and fall back to the first admitted result when the retry is rejected.
8. **PR-8a:** S2 ("$92 → $70") cannot be constructed through intake. Redefine it, for example as consumer events after offer expiry, before its report is frozen.
