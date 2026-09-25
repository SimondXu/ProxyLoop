# PR-14: Stage 2 Judge seam — frozen spec

Status: **frozen** by the root orchestrator on 2026-09-25, which adopted every
§11 recommendation. Implementation starts only after PR-13
(`feat/pr13-slow-drives-intent`) merges, because both write `runtime.py`, and
only once the root gives the go.

## Root answers (2026-09-25)

1. The Judge reviews **every admitted Slow result**: create and each refresh,
   with or without proposals. There is no `judge_required` predicate.
2. There is **one revise code**, `judge_premature_give_up`. Other codes arrive
   with a model Judge as `judge-verdict-v2`.
3. **If the Slow adapter lacks `FeedbackReasoningSlowAdapter`, there is no
   retry.** The revise is traced and the first admitted result is used.
4. **If the retry call raises, the exception propagates.** Record as a known
   limit that the run's traces are then lost (PR-7 limit 8). This cannot happen
   under decision 17.
5. **A retry that the coordinator admits but the Runtime cannot use** (K2) is a
   recorded known limit. The Runtime's rules are not copied into `agent_core`.
6. **Constructor injection**: `CaseCoordinator(judge=...)`, passed only by
   `ThinAgentRuntime._coordinator()`.
7. **The split report carries call and retry counts only.** It has no verdict
   distribution (decision 7, read strictly).
8. **PR-9b merges before PR-14.** PR-14 keeps `check_local_report` passing,
   and the local reports stay pre-Judge observed artifacts.
9. **`CONTEXT.md` gains a "Judge" term** with the §11.9 wording. It is added
   through the `domain-modeling` procedure during implementation.

---

This branch is based on PR-13 @ `23932a2`, and
line numbers below refer to that head. Tags: **[O]** observed in code or docs,
**[I]** inferred, **[P]** proposed.

Binding inputs:
- the build plan PR-14 row: a scripted Judge, at most one Slow retry,
  `role=judge` traces, evaluation never imports the Judge, feedback off the
  contract. Verification is `make preflight`, an import-boundary test, and the
  DB lane.
- decision 7: the Judge is quality only. It never enters a metric or authority,
  and a Judge that reaches a metric repeats D2-1.
- decision 17: no second-family Judge. Every gate is scripted. This supersedes
  decision 13's family rule for this build.
- decision 20: no `SlowWorkRequest.revision_feedback`.
- PR-13 root answer 7: retry Slow only on a Judge `revise`. If the retry is
  rejected, fall back to the first accepted result.
- PR-13 §5: the Judge sits inside `advance`, after the A-3 hook.
- PR-7 I4, I6, I8, I10, I11 and the G8 source guard.
- PR-8 §5.3: the split-report schema.
- PR-9 §2.8 and Q4: typed failure capture, with no masking of anything else.
- Proposal §3/§7 (`docs/research/2026-09-21-target-architecture-proposal.md:92-95,
  :454-465`): an advisory verdict, at most one retry, "the second result is
  final", and the Judge only as an invocation count.

## 1. Current state [O]

- `CaseCoordinator.advance` (`agent_core/coordinator.py:193-385`) handles Slow
  in `:238-288` in this order:
  1. `_reason` (timed)
  2. `validate_slow_result`
  3. the A-3 hook (`slow_proposal_check`, `:264-269`)
  4. `audits.append`, and one `role="slow"` trace (`:270-286`)
  5. `slow_result = slow_output` if accepted

  Fast follows in the same run only on `FAST_NOW_AND_SLOW_REFRESH`.
- Runtime-only behaviour is injected through the constructor (`:131-149`):
  `fast_gate`, `capture_fast_failures`, `slow_proposal_check`. The only
  constructor call is `ThinAgentRuntime._coordinator()` (`runtime.py:1738-1755`).
  ML callers construct a bare coordinator.
- The Runtime consumes only `CoordinatorOutcome.slow_result`. It uses it in
  three places: `create_case` (`runtime.py:800-852`),
  `_refresh_strategy_if_required` (`:1653-1713`, used by `append_event` and
  `ingest_channel_event`), and `_standing_proposal`.
- `_advance` (`:1715-1736`) appends `outcome.traces` in one call before the
  caller inspects the outcome. That is PR-7 I6.
- `_model_trace(role: Literal["fast","slow"])` is at `:669-735`.
  `ModelTrace.role` already admits `"judge"` (`contracts.py:591`), so no
  contract change is needed.
- `turn_split.fast_slow_split` **raises on any role other than fast or slow**
  (`turn_split.py:57-59`). `_turn_calls` pairs a Fast trace with the Slow trace
  *immediately before it* (`:99-112`). A Judge trace therefore breaks
  `make fast-slow-split-check` on the first scripted run. PR-14 has to change
  the split. This is the concrete form of PR-13 K6.
- The Runtime is constructed without a Judge argument in four places:
  `activities.py:277`, `config.py:52`, `config.py:79` (model mode, where the
  OpenAI adapter is both Fast and Slow), and `app.py:149`. A default argument
  covers all four.
- The trace-order assertions that will churn are listed in §8.4.

## 2. The Judge adapter protocol and verdicts [P]

There is one new module, `agent_core/judge.py`. Everything about the Judge
lives in it, so the boundary test has one unit to guard. It imports only
`proxyloop_contracts` and `.interfaces`.

```python
JUDGE_VERDICT_VERSION: Final = "judge-verdict-v1"   # trace output_schema_version
JUDGE_REVISE_CODES: Final = frozenset({"judge_premature_give_up"})   # closed; root Q2
JUDGE_ADAPTER_FAILURE_CODES: Final = frozenset(
    {"judge_adapter_timeout", "judge_adapter_unavailable", "judge_adapter_invalid_output"}
)

@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    verdict: Literal["accept", "revise"]
    request_id: UUID           # the judged SlowWorkRequest
    result_id: UUID            # the judged SlowWorkResult
    reason_codes: tuple[str, ...] = ()
    # __post_init__ raises ValueError for:
    #   - a verdict that is not "accept" or "revise"
    #   - accept with any code
    #   - revise with no code
    #   - a code not in JUDGE_REVISE_CODES
    #   - a duplicate code

class JudgeAdapter(Protocol):
    def judge(self, request: SlowWorkRequest, result: SlowWorkResult) -> JudgeVerdict: ...

class JudgeAdapterFailure(RuntimeError):   # the FastAdapterFailure pattern
    def __init__(self, reason_code: str) -> None: ...   # a code outside the allow-list raises ValueError
    @property
    def reason_codes(self) -> tuple[str, ...]: ...

@runtime_checkable
class FeedbackReasoningSlowAdapter(Protocol):
    """Optional: a Slow adapter that can take the Judge's verdict on a retry."""
    def reason_with_feedback(
        self, request: SlowWorkRequest, verdict: JudgeVerdict
    ) -> tuple[SlowWorkResult, ModelCallUsage]: ...

class ScriptedJudgeAdapter: ...   # §3
```

- **The verdicts are `accept` and `revise`. There is no `block`.**
  - A block would let a model veto an admitted proposal. That makes the Judge
    an authority, which decision 7 forbids.
  - A serious quality concern is a `revise`. If the retry does not improve
    things, deterministic policy still decides on the first result.
  - "accept" rather than the proposal's "approve", because an approve verdict
    would collide with the Approval Request domain term.
- **Content-free.** A verdict carries closed codes only. It has no free-text
  note, so nothing a Judge writes can reach a trace, a view, or a Slow prompt.
  (The proposal's `note ≤ 400 chars` is dropped until a model Judge exists.)
- **Not a contract.** The verdict is an `agent_core`-internal dataclass. It is
  never serialized except as the trace's codes.

## 3. `ScriptedJudgeAdapter` [P]

```python
model_identity = ModelIdentity("scripted", "scripted_judge", "rules-v1", "scripted-v1", "no-prompt")

def judge(self, request, result) -> JudgeVerdict:
    # A pure function of (request, result). It reads no clock, no state, no I/O.
    live_offer = any(o.expires_at > request.created_at for o in request.view.offers)
    accept_def = any(d.allowed_action_types == (ActionType.ACCEPT_OFFER,)
                     for d in request.view.capability_manifest.capabilities)
    if not result.capability_proposals and live_offer and accept_def:
        return JudgeVerdict("revise", request.request_id, result.result_id,
                            ("judge_premature_give_up",))
    return JudgeVerdict("accept", request.request_id, result.result_id)
```

- **The rule is quality, not authority.** Slow had a live offer and a capability
  to act on it, and proposed nothing. The Judge does not read compliance, since
  `agent_core` cannot import `telecom_domain`, and it repeats none of the A-3
  rules. It only asks Slow to reconsider. Any retried proposal still passes A-3
  and policy.
- **The default path never revises. Proof:** `ScriptedProposingSlowAdapter`
  proposes exactly when an offer has `expires_at > request.created_at` and the
  manifest has an accept-only definition (`scripted.py`, `reason`; its strategy
  is never `None`). The Judge revises only when those same two conditions hold
  *and* there is no proposal. With the default Slow those cannot all be true,
  so there is no retry, and decisions and state are identical to PR-13. The
  only addition is one Judge trace per admitted Slow result.
- `ScriptedJudgeAdapter` lives in `judge.py`, not in `scripted.py`. That keeps
  `scripted.py`, whose output the harness manifest pins, untouched.

## 4. Where the Judge runs [P]

- **Injection:** through the constructor, like the other Runtime-only hooks:
  `CaseCoordinator(..., judge: JudgeAdapter | None = None)`, passed only by
  `ThinAgentRuntime._coordinator()` as `judge=self._judge`.
  `ThinAgentRuntime.__init__(..., judge: JudgeAdapter | None = None)` defaults
  to `ScriptedJudgeAdapter()`.
  - The signature of `advance` stays the same. Every test double that overrides
    `advance(request, *, fast, slow)`, such as `_RecordingCoordinator` in
    `test_persisted_claim_and_traces.py:355`, keeps working.
  - A future Slow call site cannot forget the Judge.
  - Root Q6.
- **Which results:** every Slow result that `validate_slow_result` **and** the
  A-3 hook admitted, on the Runtime coordinator. That is create, each refresh
  on `append_event`, and each refresh on `ingest_channel_event`, in direct,
  API, and Temporal modes. Results with and without proposals are both judged
  (root Q1).
  - A stale, invalid, or A-3-rejected result is not judged, and the command
    fails as today.
  - Fast is never judged.
- **Where in `advance`:** immediately after the Slow trace is appended
  (`:286`), inside the same Slow branch and before Fast. The trace order of one
  run is therefore `slow, judge, [slow retry], [fast]`.
- **Not in model or Runtime configuration.** No env var is added and
  `adapter_mode` is unchanged. The Judge is scripted in every mode, including
  model mode (`config.py:79`), per decision 17. `RuntimeProfile` and
  `phase04d-profile-check` do not move.

## 5. The retry flow [P]

Inside `advance`, once the first result `R1` is admitted:

```
verdict_call = judge.judge(slow_request, R1)            # timed; JudgeAdapterFailure captured
if the call failed (typed):          trace judge FAILED (failure codes)                 -> use R1
elif the verdict does not bind:      trace judge REJECTED (judge_verdict_request_mismatch /
                                     judge_verdict_result_mismatch)                     -> use R1
elif verdict == "accept":            trace judge SUCCEEDED ("judge_accept",)            -> use R1
elif Slow is not a FeedbackReasoningSlowAdapter:
                                     trace judge SUCCEEDED ("judge_revise", *codes)     -> use R1 (no retry; root Q3)
else:                                trace judge SUCCEEDED ("judge_revise", *codes)
    R2 = slow.reason_with_feedback(slow_request, verdict)   # the same request object; timed
    audit2 = validate_slow_result(R2, snapshot, expected_request=slow_request, evaluated_at=created_at)
             then the same A-3 hook
    trace slow (audit2)                                     # role=slow; SUCCEEDED or REJECTED
    -> use R2 if audit2.accepted else R1
```

- **At most one retry per run, and no second Judge call.** The retry result is
  final (proposal §7). There is one Judge call per admitted first result.
- **Feedback is off the contract and off the log.**
  - The feedback is the in-memory `JudgeVerdict` (closed codes), passed as an
    argument to an `agent_core`-internal optional protocol.
  - `SlowWorkRequest` is the same object for both calls: the same
    `request_id`, the same pins, and no new field (decision 20). r4 prompts
    serialize the request, and they are untouched.
  - Nothing reads the trace log (PR-7 I8).
- **Fallback.** Two cases use the first admitted result: a failed or
  non-binding Judge call, and a retry that `validate_slow_result` or A-3
  rejects. In both, the run's outcome equals the Judge-less outcome except for
  its traces. `status` is `ACCEPTED`, because `slow_result = R1`.
- **Audits pair 1:1 with traces.** The existing invariant that
  `trace.role == audit.source` holds (`test_model_trace_producer.py:141-145`).
  Each Judge call appends
  `ResultAudit(source="judge", accepted=<verdict binds>, reason_codes=<the trace's codes>, …)`,
  and the retry appends its Slow audit.
- **Only a typed `JudgeAdapterFailure` is captured.** It is always captured
  when a Judge is configured, with no flag, because only the Runtime configures
  one. Any other exception from the Judge propagates, as PR-9 Q4 requires: no
  masking.
- **An exception raised by the retry call propagates too** (root Q4). Under
  PR-7 limit 8 the run's earlier traces are then lost. This cannot happen under
  decision 17: no product Slow implements the feedback protocol.

## 6. Traces [P]

| Call | `role` | `result` | `reason_codes` | `request_id` | `output_ref` | `output_schema_version` | `input_schema_version` |
|---|---|---|---|---|---|---|---|
| Judge, the verdict binds | `judge` | `SUCCEEDED` | `("judge_accept",)` or `("judge_revise", *codes)` | the Slow request's | `None` | `judge-verdict-v1` | the judged result's `schema_version` |
| Judge, the verdict does not bind | `judge` | `REJECTED` | the mismatch codes | same | `None` | `judge-verdict-v1` | same |
| Judge, typed failure | `judge` | `FAILED` | `(failure code,)` | same | `None` | `none` | same |
| Slow retry | `slow` | `SUCCEEDED` / `REJECTED` | its audit codes (the existing rule) | same as the first Slow call | the retry's `result_id` | as the first call | as the first call |

- There is one Judge trace per Judge call, and each trace takes its identity
  from the Judge adapter (`_identity`). Tokens are 0 and usage is `None`. There
  is no `UsageReportingJudgeAdapter` (YAGNI).
- Latency and window come from `_timed`, as for Fast and Slow.
  `input_pins` is `request.snapshot.pins`, so the traces join the turn's
  cursor.
- `_model_trace`'s `role` literal gains `"judge"`. No other trace code changes.
- A Judge trace's `result` is the coordinator's verdict on the *Judge output*:
  `SUCCEEDED` means a well-formed, binding verdict, whether accept or revise.
  It is not the verdict itself. This extends PR-7 I11, and the docs say so.
- **Appended before acting.** The whole run, `slow, judge, [slow]`, sits in one
  `CoordinatorOutcome.traces` tuple, so `_advance`'s single append records it
  contiguously and in call order before the Runtime inspects the outcome
  (PR-7 I4 and I6). The G8 guard is unchanged in meaning, and PR-14 extends it
  (§8.3 G1).
- **The retry's Slow trace carries no marker.** A reader identifies a retry by
  position: a `slow` trace immediately after a `judge` trace whose first code
  is `judge_revise`, at the same cursor. The coordinator cannot emit any other
  sequence (§7).

## 7. Effect on the split report [P]

This work is required, because `fast_slow_split` raises on a Judge trace today.

- **`turn_split.py`**:
  - Accept `role ∈ {"fast","slow","judge"}`. Still refuse `intake` and `None`.
  - Replace "the Slow trace immediately before Fast" with a small grammar over
    the traces at one cursor, in log order. A group is `S [J [S′]]`:
    - `J` must directly follow a group's first `S` when that `S` is
      `SUCCEEDED`. Otherwise raise `ValueError("orphan judge trace")`.
    - `S′` is an `S` directly after a `J` whose first code is `judge_revise`.
      Any other `S` starts a new group.
  - An attempt is `group`, `group F`, or `F`, where `F` directly follows its
    group.
  - The delivered attempt is the one holding the last `F`. For a turn with no
    Fast, it is the first attempt whose first `S` is `SUCCEEDED`, which is
    today's creation rule.
  - Every other trace at the cursor is unapplied, as today.
- **Per turn, additive:**
  - `judge_calls` (0 or 1)
  - `slow_retry`: `null`, `"admitted"`, or `"rejected"`. It is derived from the
    retry Slow trace's `result`.
  - `slow_calls` now counts `S′` too. It is still a Slow call.
  - `class` is unchanged: it depends only on whether there are Slow or Fast
    calls.
- **Per scenario, additive:**
  - `judge_calls_by_result` `{failed, rejected, succeeded}`
  - `slow_retry_counts` `{admitted, rejected}`
  - `unapplied_judge_calls_by_result`
- **Unchanged:**
  - `calls_by_role_and_result` keeps only `fast` and `slow`.
  - `unapplied_model_calls` still counts Fast and Slow only.
  - `fast_only_turn_share`, `slow_involved_turn_share`, `fast_model_line_rate`,
    and `gate_fallback_rate` never count the Judge.
- **No verdict distribution.** The report does not include accept or revise
  counts. Decision 7 allows the Judge in a report only as invocations (proposal
  §7: "`judge_invocation_count`"). The split reads a `judge_revise` code only to
  parse structure (root Q7).
- **Report header.**
  - `schema_version` becomes `"fast-slow-split-v2"`.
  - A new field, `judge_backend`, holds the one `model` shared by every Judge
    trace. The script asserts that value is `"scripted_judge"` as a literal and
    does not import the Judge.
  - `claim_boundary` is unchanged.
- **Expected v2 values**, derived from §3 and the scenario code (the run
  confirms them):
  - `demo_path`: turn 1 has `judge_calls: 1`. `judge_calls_by_result` is
    `{succeeded: 1}`. `unapplied_judge_calls_by_result` is `{succeeded: 1}`,
    from the repeated create.
  - `dialogue_path`: three Judge calls, at create, +61 min, and +92 min, all
    `succeeded`. There are no retries.
- **Byte obligation:** in both scenarios, every key present in v1 has the same
  value in v2 except `schema_version` and `report_fingerprint`. The implementer
  proves it with the command in §9 and records the output in the log.
- **PR-9b interaction.** If PR-9b has merged, `fast-slow-split-distilled.json`
  and `-untuned.json` are observed artifacts that only the local model can
  regenerate.
  - They stay byte-unchanged and pre-Judge.
  - `check_local_report` must still pass against the v2 scripted report. Its
    `TURN_STRUCTURE_KEYS` values are unchanged by construction.
  - The docs state that the local reports predate the Judge.

## 8. Invariants, red tests, acceptance

### 8.1 Invariants

- **JG1 Advisory.** Verdicts are `accept` or `revise`. The Judge never blocks,
  authorizes, compiles, or edits anything.
- **JG2 Placement.** Only the Runtime's coordinator has a Judge. It judges only
  admitted Slow results, after A-3 and before Fast and the Runtime's policy
  step. An ML or bare coordinator (`judge=None`) is byte-identical to PR-13.
- **JG3 One retry.** A retry happens only on a binding `revise` verdict, and
  only when Slow is a `FeedbackReasoningSlowAdapter`. It uses the same
  `SlowWorkRequest` and passes the same validation and A-3. It is followed by
  no second Judge call.
- **JG4 Never blocking.** A typed Judge failure, a non-binding verdict, or a
  rejected retry leaves the first admitted result as `slow_result`.
- **JG5 Off contract, off log.** The feedback is the in-memory verdict. No
  contract, schema, fixture, or `SlowWorkRequest` field changes, and nothing
  reads the trace log.
- **JG6 Traces.** Each Judge call gets one `role=judge` trace, and each retry
  gets one `role=slow` trace. All of them are in the run's outcome and are
  appended by `_advance` before the Runtime acts. Audits pair 1:1 with traces.
- **JG7 Output isolation.**
  - `CoordinatorOutcome` gains no field.
  - `runtime.py` never reads a verdict.
  - The executor, policy, admission, router, gate, repositories, `turn_split`,
    `ml/`, and `scripts/` never import the Judge.
  - Judge calls never enter a Fast or Slow share.
- **JG8 Content-free.** Codes are closed. There is no free text.
- **JG9 Scripted equivalence.** With the default adapters, every snapshot,
  receipt, approval, intent, standing proposal, and Provider state is
  byte-identical to PR-13. The trace log gains exactly one `judge SUCCEEDED
  ("judge_accept",)` after each admitted Slow trace.
- **JG10 Deterministic.** `ScriptedJudgeAdapter` is a pure function of
  `(request, result)`.

### 8.2 Red first (record each failure on the PR-13 head)

- **R1** `test_runtime_judges_each_admitted_slow_result`: a default in-memory
  `create_case` produces the log roles `["slow","judge"]`. The Judge trace is
  `SUCCEEDED ("judge_accept",)`, from `scripted_judge`, with the Slow request's
  `request_id`.
- **R2** `test_revise_retries_slow_once_with_the_verdict_in_process`, at
  coordinator level with a feedback-capable fake Slow and a revising stub:
  - the traces are `[slow, judge, slow]`
  - `slow_result` is `R2`
  - the fake received the verdict object and the identical request object (`is`)
  - the Judge was called once
- **R3** `test_a_rejected_retry_falls_back_to_the_first_admitted_result`: the
  retry fails A-3, so its trace is `REJECTED` and `slow_result` is `R1`.
- **R4** `test_a_typed_judge_failure_is_traced_failed_and_never_blocks`, for
  each allow-listed code.
- **R5** `tests/contract/test_judge_boundary.py` (§8.3 B1-B3).
- **R6** `test_split_counts_judge_calls_apart`: `fast_slow_split` over
  `[S J F]`, `[S J S′ F]`, `[S J S′(REJECTED) F]`, and create plus create-again
  `[S J S J]`. It raises today.

### 8.3 Other tests

- **Pure (`judge.py`):** a table for the scripted rule (a proposal, no
  proposal with a live offer, an expired offer, a manifest without accept, and
  determinism); `JudgeVerdict` validation (the five `ValueError` cases); and
  the `JudgeAdapterFailure` allow-list.
- **Coordinator:**
  - A stale or A-3-rejected Slow result means the Judge is not called.
  - A non-binding verdict gives a `REJECTED` Judge trace and `R1`.
  - A revise with a non-feedback Slow gives `[slow, judge]`, no retry, and `R1`.
  - On `FAST_NOW_AND_SLOW_REFRESH` the traces are `[slow, judge, fast]`.
  - An untyped Judge exception propagates.
  - With `judge=None` the outcome equals the PR-13 outcome.
- **Runtime:**
  - JG9 differential: the default run against runs with an always-revise stub
    (non-feedback Slow) and an always-failing stub. Every state and receipt is
    equal, and only the log differs.
  - End-to-end retry: a fake Slow that returns the plain `ScriptedSlowAdapter`
    result first and the proposing result on feedback. Create gives `[S J S′]`,
    and the consumer event opens the approval from `S′`'s standing proposal.
  - The same flow with an incoherent retry gives no approval, and the command
    applies.
  - A channel-ingest refresh is judged.
- **G1** extends the G8 source guard, which appears in
  `test_persisted_claim_and_traces.py:684`, `test_fast_failure_fallback.py:309`,
  `test_fast_dialogue_delivery.py:435`, and `test_slow_driven_intent.py:579`:
  - one `.advance(`, one `._coordinator(`, one `CaseCoordinator(`
  - `judge=self._judge` exactly once
  - zero `.judge(`, `.reason_with_feedback(`, `.decide(`, `.reason(`
  - no `verdict` token in `runtime.py`
- **Boundary (`tests/contract/test_judge_boundary.py`, AST, following
  `test_status_block_boundary.py`):**
  - **B1:** no file under `ml/` or `scripts/` imports `proxyloop_agent_core.judge`
    or imports or names `ScriptedJudgeAdapter`, `JudgeAdapter`, `JudgeVerdict`,
    `JudgeAdapterFailure`, `FeedbackReasoningSlowAdapter`, or a `JUDGE_*`
    constant.
  - **B2:** the same holds for `capabilities.py`, `proposal_admission.py`,
    `router.py`, `disclosure_gate.py`, `turn_split.py`, `repository.py`,
    `postgres_repository.py`, and every `telecom_domain` source.
  - **B3:** `judge.py` imports only the stdlib, `proxyloop_contracts`, and
    `.interfaces`, and `CoordinatorOutcome`'s field set is unchanged.
  - Each scanned root has Python sources, so the scan cannot pass vacuously.
- **DB (`postgres-test`):**
  - **P1:** on the PostgreSQL Runtime, create gives the log roles
    `["slow","judge"]` and the round trip is equal.
  - The churned assertion at `test_phase_04c_persistent_case_store.py:891`
    becomes `["slow","judge","fast"]`.
  - Update the per-file pin in `scripts/check_gated_skips.py` if a gated test
    is added.

### 8.4 Expected churn

For each change the implementer lists the old assertion, the new assertion, and
the reason ("a `judge` trace follows each admitted Slow trace"). No
approval, state, or receipt expectation may change.

- Role lists:
  - `test_persisted_claim_and_traces.py`: 392-681, twelve sites
  - `test_slow_refresh_strategy_expiry.py`: 267, 346, 360
  - `test_phase_04c_persistent_case_store.py`: 891 (shows only in the DB lane)
- Positional trace reads in `test_slow_driven_intent.py`: 228, 453, 488, 559
- Positional trace read in `test_phase_04b_model_runtime.py`: 388
- The report test: `test_fast_slow_split_report.py`

### 8.5 Acceptance criteria

1. R1-R6 and §8.3 pass. Every red is recorded.
2. JG9 holds on the direct, API (`apply_command`), and Temporal scripted paths.
   The existing phase05a and phase06b1 suites pass unchanged, apart from the
   churn listed in §8.4.
3. The only committed artifact that moves is
   `data/evaluation/fast-slow-split-scripted.json`, which becomes v2 and meets
   the §7 byte obligation.
4. Docs:
   - `docs/architecture.md`:
     - a Judge paragraph in Model Collaboration and Routing
     - a Safety-invariants bullet: the Judge is advisory and never an
       authority or a metric
     - a `:56` addendum on the Judge trace `result` meaning and on typed
       `JudgeAdapterFailure` being traced
     - an update to the `:192` split paragraph
   - `docs/decisions/2026-08-23-fast-slow-orchestration.md`: an amendment
     (Judge seam, no block, one retry, off-contract feedback)
   - `CONTEXT.md`: a "Judge" term via `domain-modeling` (root Q9)
   - `audit-remediation-status.md` and the build-plan row updated
   - a log at `harness/log/feat-pr14-judge-seam.md`

## 9. Owned files and gates

**New files:**
- `runtime/packages/agent_core/src/proxyloop_agent_core/judge.py`
- `tests/integration/test_judge_seam.py`
- `tests/contract/test_judge_boundary.py`

**Edited files:**
- `agent_core/{coordinator.py, __init__.py}` (exports)
- `case_runtime/runtime.py`: the `judge` constructor argument and the
  `_coordinator()` wiring only
- `case_runtime/turn_split.py`
- `scripts/run_fast_slow_split_report.py`
- `data/evaluation/fast-slow-split-scripted.json`, regenerated
- the churned tests in §8.4
- `tests/integration/test_fast_slow_split_report.py`
- `scripts/check_gated_skips.py`, only if the pin moves
- the docs in §8.5

**Not owned** (escalate if a change there seems needed): contracts and
`contracts/`, `validate_slow_result`, `proposal_admission.py`, `scripted.py`,
`router.py`, `capabilities.py`, `repository.py`, `postgres_repository.py`,
`app.py`, `config.py`, `workflow.py`, `activities.py`, `ml/`, and every other
`data/` file.

**Gates:**
- Focused: `uv run --project runtime --all-packages pytest -c runtime/pyproject.toml -q`
  over the new and churned files, plus `test_model_trace_producer`,
  `test_phase_04a_agent_runtime`, `test_phase_04b_model_runtime`,
  `test_phase_05a_case_runtime`, `test_phase_06b1_channel_runtime`,
  `test_slow_proposal_admission`, and `test_browser_projection_allowlist`.
- Then `make lint`, `make typecheck`, `make fast-slow-split-report`, and
  `make test`, which includes every `*-check`.
- Proof obligations:
  - `git diff --stat origin/main -- contracts/ ml/ data/` shows only the split
    report.
  - `make phase04d-profile-check` passes.
  - The v1-key check:
    `python -c` loads `git show origin/main:data/evaluation/fast-slow-split-scripted.json`
    and the new file, projects the new file onto the old file's keys
    recursively, and asserts equality except `schema_version` and
    `report_fingerprint`.
- `make preflight` once, on the stable diff.
- The DB lane, serially: `make postgres-check` → `make phase05a-check` →
  `make phase06b1-check`.
- An independent `reviewer` pass (an authority-adjacent seam), with the root
  checking specifically that the Judge output reaches no metric or authority.

## 10. Risks

| # | Risk | Mitigation |
|---|---|---|
| K1 | **The seam is unexercised in the product.** The scripted Judge never revises on the default Slow, and no product Slow implements feedback, so a retry happens only in tests. | This is intended under decision 17. It is stated in the docs and the log. The end-to-end retry test uses a fake Slow. |
| K2 | **A retry admitted by the coordinator can still be unusable by the Runtime**: `strategy_proposal is None` on create, or the same strategy id at a revision no higher than installed (`runtime.py:808-814`, `:1686-1696`). The command then fails although `R1` was usable, so the Judge turned a valid outcome into a failure. | This cannot happen under decision 17. Record it as a known limit (root Q5) rather than copy Runtime rules into `agent_core`. |
| K3 | **A retry exception loses the run's traces** (PR-7 limit 8). | Root Q4. It cannot happen under decision 17. |
| K4 | **The split grammar relies on in-process log order.** Cross-process interleaving can produce an orphan `J`, and the split then raises. | It fails closed rather than misattributing. The existing risk R6 covers the cross-process case. |
| K5 | **Test churn hides a regression.** | The implementer lists every changed assertion (§8.4). The reviewer checks that only trace roles and indices change. |
| K6 | **Serialization.** `runtime.py` follows PR-13. PR-9b rewrites `run_fast_slow_split_report.py` and adds the local reports. | Merge `origin/main` after both, without a rebase. Root Q8 sets the order. |
| K7 | **A model Judge is out of scope.** `JUDGE_REVISE_CODES` is minimal and there is no usage protocol, so a model Judge later needs a `judge-verdict-v2`. | This is deliberate (YAGNI, decision 17). |
| K8 | **An untyped Judge exception fails the command.** | This is the PR-9 Q4 posture: a future model Judge must map its transport errors to `JudgeAdapterFailure`, as the local Fast adapter does. |

## 11. Root decisions needed

1. **Which Slow results are judged.** The options are every admitted Slow
   result (create and each refresh), or only results with proposals (proposal
   §7 `judge_required`). **Recommend every admitted result.** It is one rule
   with no predicate, it enables the `premature_give_up` check (the one case
   where a retry can add value), and it costs nothing with a scripted Judge.
   Add `judge_required` when a paid Judge exists.
2. **The revise vocabulary.** **Recommend only `judge_premature_give_up`**, the
   one code with a producer. The proposal's other four (`incomplete_search`,
   `arithmetic_error`, `constraint_misread`, `disclosure_risk`) arrive with a
   model Judge as `judge-verdict-v2`. The alternative is to freeze all five now,
   with four that have no producer.
3. **A revise when the Slow adapter has no feedback protocol.** **Recommend no
   retry**: the revise is traced and `R1` is used. A retry without feedback is
   a blind re-roll, and with a deterministic Slow it is identical by
   construction.
4. **The retry call raises.** **Recommend propagating** (PR-9 Q4, no masking;
   this cannot happen under decision 17). The alternative is to catch
   `Exception` at the retry only, record a `FAILED` Slow trace, and fall back.
   That honours the "never blocking" principle but hides bugs.
5. **A retry that is admitted but unusable** (K2). **Recommend a recorded
   limit.** The alternative duplicates the Runtime's strategy-usability rules
   in the coordinator.
6. **Injection point.** **Recommend constructor injection** through
   `_coordinator()`, the pattern of the other Runtime-only hooks. It leaves the
   `advance` signature and every test double as they are. The alternative is
   `advance(..., judge=)`, the proposal's sketch.
7. **The split report carries invocations, not verdicts.** **Recommend it**
   (the strict reading of decision 7). The alternative is to add accept and
   revise counts.
8. **Order against PR-9b.** **Recommend PR-9b first.** It is in flight and its
   local reports become pre-Judge observed artifacts. PR-14 then keeps
   `check_local_report` passing. If PR-14 lands first, PR-9b's local run must
   parse v2 splits that contain Judge traces.
9. **`CONTEXT.md`.** Add **Judge**: "An advisory, quality-only reviewer of an
   admitted Slow Work Result. Its verdict is accept or revise, and a revise
   may cause one Slow retry. It authorizes, blocks, and measures nothing."
   _Avoid_: Critic, verifier, approval, reward model. This goes through
   `domain-modeling`.
