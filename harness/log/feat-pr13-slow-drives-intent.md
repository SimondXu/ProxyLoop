# Feature log: Slow's proposal drives the intent, with an A-3 coordinator admission check (PR-13)

Spec (frozen by the root, 2026-09-24, root answers 1–8):
`harness/context/pr13-slow-drives-intent-design.md`, committed as the first
commit of this branch. Build-plan item PR-13 (decisions 19, 20). Branch
`feat/pr13-slow-drives-intent` from `main` @ `a8fdf5b`, which already includes
PR-8a (#94, the disclosure gate and `assistant_message`), PR-9a (#97, typed
Fast failures), PR-7 (the single `_advance` site), PR-3 and PR-5.

Non-goals, per the spec and the root's answers: no contract or `contracts/`
change, no change to `validate_slow_result`, `ScriptedSlowAdapter`,
`router.py`, `capabilities.py`, `app.py`, `workflow.py`, `activities.py`,
`commands.py`, `ml/`, `data/` or the Web; no Slow re-consult trigger
(deferred); no Web input.

## What changed

- `agent_core/proposal_admission.py` (new, imports `proxyloop_contracts`
  only). `SLOW_PROPOSAL_CHECK_VERSION = "slow-proposal-v1"`,
  `SlowProposalCheck`, and `slow_proposal_violations(result, snapshot,
  evaluated_at)`, which applies the 11 spec rules in fixed order
  (`slow_proposal_count_exceeded`, `_unpaired`, `_capability_unsupported`,
  `_capability_action_mismatch`, `_capability_expired`, `_predates_result`,
  `_offer_binding_mismatch`, `_offer_not_current`, `_terms_mismatch`,
  `_intent_binding_mismatch`, `_action_not_delegated`). Rules 3–11 are skipped
  when rule 1 or 2 fires, and rule 4 and the definition part of rule 5 are
  skipped when rule 3 finds no definition. `standing_proposal_offer(proposal,
  snapshot, *, evaluated_at)` is the use-time admissibility test.
- `agent_core/coordinator.py`: `CaseCoordinator(..., slow_proposal_check=None)`.
  After `validate_slow_result` accepts, a non-empty verdict replaces the Slow
  audit with a rejected audit carrying the check's codes. This happens before
  the audit is appended and before the trace is built, so the trace is
  `REJECTED` with those codes and `slow_result` is `None`. Without the hook
  nothing changes.
- `agent_core/scripted.py`: `ScriptedProposingSlowAdapter(ScriptedSlowAdapter)`,
  identity `scripted / scripted_slow / proposing-v1 / scripted-v1 / no-prompt`.
  It returns `super().reason(request)` plus one accept-offer pair for the first
  offer with `expires_at > request.created_at`, provided the manifest has the
  `(ACCEPT_OFFER,)` capability. Both halves of the pair expire with the offer.
  The result is re-validated through `SlowWorkResult.model_validate`.
  `ScriptedSlowAdapter`'s class body is byte-for-byte unchanged; only the
  module's imports and `__all__` grew. Both new names are exported from
  `proxyloop_agent_core`.
- `case_runtime/repository.py`: `CaseRuntimeState.standing_proposal:
  CapabilityProposal | None = None`. `__post_init__` refuses a standing
  proposal beside any approval.
- `case_runtime/runtime.py`:
  - The default Slow is `ScriptedProposingSlowAdapter()`.
  - `_coordinator` passes `slow_proposal_check=slow_proposal_violations`
    (still the one `CaseCoordinator(` and the one `.advance(`).
  - `_refresh_strategy_if_required` also returns the admitted result.
  - `create_case`, `append_event` and `ingest_channel_event` install
    `_standing_proposal(result, snapshot)`.
  - `append_event` opens the approval only when `standing_proposal_offer(...)`
    names an offer and `offer_compliance_violations_for_case` is empty for it.
    It uses the unchanged `_build_approval` and then clears the standing
    proposal in the same write.
  - Both `record_channel_delivery` writes carry the proposal.
- `case_runtime/postgres_repository.py`:
  - `_CaseStorageEnvelope.standing_proposal` is optional, and
    `storage_version` stays 3.
  - `_encode_state` omits the key when there is no proposal, so such a row is
    the pre-PR-13 document.
  - `_verify_standing_proposal`, called from `_reconstruct_provider` on both
    encode and decode, checks three things: there is no proposal beside an
    approval, the proposal names the manifest's accept-offer capability, and
    it has exactly one `offer_id`, equal to the stored offer's. Expiry is not
    checked on load.
- Docs:
  - `docs/architecture.md`: the Model Collaboration A-3 paragraph plus a new
    standing-proposal paragraph, the Phase 04A decision-loop sentence, and
    the Safety invariant.
  - The ADR `docs/decisions/2026-08-23-fast-slow-orchestration.md` gets a new
    amendment that supersedes the "only enforcement point" bullet.
  - `CONTEXT.md` gains "Standing Proposal" (added through the
    `domain-modeling` procedure: a glossary entry only, with no
    implementation detail).
  - `harness/context/audit-remediation-status.md` gets a §0 row and the two
    A-3 entries.
  - The `test_contract_semantics_limits.py` docstring is reworded; its
    assertions still hold, because `validate_slow_result` still does not
    join.

### Implementation choices the spec left open

- **An admitted Slow result on a Case that already holds an approval installs
  no standing proposal.** A channel ingest after a rejected or expired
  approval can refresh the strategy (the rejection changes the planning
  basis), and the proposing Slow proposes again while the offer lives. J5
  requires "None whenever `approval_requests` is non-empty" (`__post_init__`
  and the codec), so `_standing_proposal` returns None there. That is still
  "replaced by each admitted result, including with None". No consumer event
  is accepted after any approval, so no behaviour depends on it.
  `test_a_case_with_a_decided_approval_holds_no_standing_proposal` pins it.
- **The storage key is omitted when there is no proposal.** Waiting,
  approved, terminal and no-proposal rows keep exactly their pre-PR-13 bytes.
  Only a row that holds a proposal is unreadable by a pre-PR-13 process
  (K3). Mixed versions remain unsupported.

## Red (on `main` @ `a8fdf5b`, before any production edit)

`pytest -q tests/integration/test_slow_driven_intent.py` with R1–R3 only
(full output in the scratch file `impl-pr13/red-r1-r3.txt`):

```
FAILED test_slow_without_proposal_opens_no_approval - assert ApprovalRequest(...) is None
FAILED test_incoherent_slow_proposal_is_rejected_and_traced - Failed: DID NOT RAISE ModelRuntimeError
FAILED test_model_slow_without_next_capability_opens_no_approval - assert ApprovalRequest(...) is None
3 failed in 4.04s
```

These reproduce probe rows 1 and 2: main opens an approval on any consumer
event with a compliant offer, whatever Slow proposed, and main traces the
incoherent result as `SUCCEEDED`.

## Test churn

After the production change, the non-gated runtime suite had exactly 8
failures, all in files the spec lists (§6.4) and all of the same kind:

- `test_slow_refresh_strategy_expiry.py` t3 and t6, and
  `test_strategy_basis_binding.py` (4 tests). They use `_CountingSlow`
  (strategy-only) and expect an approval, so they now use
  `_CountingProposingSlow(_CountingSlow, ScriptedProposingSlowAdapter)`. The
  refresh-mangling fakes (`_SameRevisionSlow`, `_RegressedRevisionSlow`,
  `_ExpiredStrategySlow`) and the tests that expect no approval keep the
  strategy-only base. Their coordinator-versus-Runtime refusal semantics
  (for example I11 `SUCCEEDED` for a same-revision refresh) are unchanged.
- `test_phase_04b_model_runtime.py`: the fake-transport approval test now
  returns `_slow_output_proposing_accept()`, and the scripted default class
  name is now `ScriptedProposingSlowAdapter`.

One DB-gated test changed (it shows only in the DB lane):
`test_phase_04c_persistent_case_store.py::test_postgres_explicit_model_to_scripted_switch_continues_case`
(P3). Its model Slow now proposes the accept. It also asserts that the
model-authored standing proposal (5-minute expiry) round-trips through the
PostgreSQL row before the consumer event. No assertion was weakened. Every
changed test still expects the approval to open for a proposing Slow. No
DB-gated test was added, so the per-file pin stays at 63.

## Tests added

- `tests/integration/test_slow_proposal_admission.py` (44, no DB):
  - A1a: one row per code, the 1+2 short-circuit, and the order of 7 codes
    in a single result.
  - A1b: the scripted proposing result and an OpenAI-compiled accept (via
    `compile_slow_output`) both give `()`.
  - A2: the `standing_proposal_offer` table.
  - A3: rules 3, 4, 7, 8, 9 are refused by `CapabilityExecutor` with
    `unsupported_capability`, `capability_action_mismatch`,
    `capability_offer_binding_mismatch`, `current_offer_mismatch`,
    `action_material_terms_hash_mismatch` and `current_offer_terms_mismatch`.
  - C1–C3: the hook rejects the result and traces it; without the hook the
    outcome is main's; a stale result never reaches the hook.
- `tests/integration/test_slow_driven_intent.py` (30, no DB):
  - R1–R3, and the model path in both directions.
  - D1: the main-equivalence table over +1 s, +29 min, +31 min, +59 min 59 s,
    +60 min and +61 min on the direct and command paths. Approval presence
    equals main's compliance rule, and the intent and approval equal
    `_build_approval` with main's arguments.
  - D2: the lifecycle through `_CodecChannelRepository`, so every write goes
    through the PostgreSQL codec. The proposal is carried on a channel ingest
    without a refresh, a first delivery callback, an exact replay and a
    receipt-deduplicated callback. It is replaced on a refresh (and by None
    after the offer expires), consumed by the approval, and never installed
    beside a decided approval. The `__post_init__` invariant is checked too.
  - D3: a proposal that outlives its offer, used at +61 min, gets policy
    `offer_expired`. No approval opens, the command applies, the proposal is
    not consumed, and one assistant line is delivered.
  - D4: `adapter_mode == "scripted"` and the G8 source guard.
  - D5: the proposal id and the word "standing" appear in no API body,
    trace, or snapshot.
  - Codec: a round-trip with the proposal; no key without one; a pre-PR-13
    v3 row decodes to None; the decoder refuses a proposal beside an
    approval, an unknown capability, and a foreign offer; the encoder refuses
    a foreign-offer proposal.

Mutation check (scratch `impl-pr13/mutate.sh`): each of the four carry
sites was removed in turn (ingest, delivery dedup write, first delivery
write, append). Each removal fails the new tests (2, 1, 1, and 1 failures),
so risk K1 (a construction site silently dropping the proposal) is pinned.

## Byte identity

- `git diff --stat origin/main -- contracts/ data/ ml/ scripts/` is empty.
- `make test` passed with exit 0, so every committed `*-check` passed on the
  committed bytes. That includes `harness-check` (`ScriptedSlowAdapter`
  untouched), `hosted-rerun-check`, `hosted-rescore-check`,
  `validity-smoke-check`, `baselines-historical-check`, `phase03c-*`,
  `negotiation-check`, `contracts-check`, `benchmark-check`,
  `data-pilot-check` and `fast-slow-split-check`.
- The `drifted_since_*` lines in the output are state reports computed from
  committed files only, and those files are unchanged.
- `data/evaluation/fast-slow-split-scripted.json` did **not** move. It
  embeds no Slow identity, and the scripted Slow call count, order, results
  and delivered lines are unchanged, so it needed no regeneration and no
  version note.
- `make phase04d-profile-check` passed (exit 0).
- Main-versus-branch state differential (scratch `impl-pr13/differential.py`
  and `run-differential.sh`). The same 57 scenario states were run on
  `origin/main` sources (`git archive`) and on this branch, with the same
  interpreter:
  - Scenarios: create, a consumer event at each of the six offsets, then
    approve or a second event, on the direct and command paths. The command
    path adds a deduplicated replay and approval expiry. Channel ingest runs
    at +5, +31 and +61 min, followed by a consumer event, a rejection, and
    ingest after the rejection.
  - Identical: the full PostgreSQL payload (with only the PR-13
    `standing_proposal` key removed; 14 states held one), the Provider
    state, the confirmation, the command receipts, the outbox, and every
    trace field.
  - The only differences: the Slow trace `model_version` (`deterministic-v1`
    → `proposing-v1`, and therefore `trace_id`), and `latency_ms` /
    `completed_at` on 6 labels. Those two are measured by `time.perf_counter`
    and differ between any two runs.

## Checks

On the final tree, with no `PROXYLOOP_TEST_*` variable set:

- `make lint`: passed (runtime and ml ruff; `git diff --check`).
- `make typecheck`: passed (runtime 76 source files, ml 59).
- `make test`: passed, exit 0. Runtime pytest: 1668 passed, 63 skipped (all
  DB/Temporal-gated). ml pytest: 397 passed, 1 skipped. Every `*-check`
  passed.
- `make phase04d-profile-check`: passed, exit 0.
- `make preflight`: passed, exit 0. It covers format-check, lint, typecheck,
  test, check-layout, web-check (Web 189 tests and a production build),
  lock-check, compileall, and compose config. The gated-skip counts match
  the pinned 63 per file.
- Not run: the DB lane (`make postgres-check`, `make phase05a-check`,
  `make phase06b1-check`); it needs the Compose `postgres-test` and
  `temporal` services and is left to the root. Also not run: the independent
  review and `/security-review`.
