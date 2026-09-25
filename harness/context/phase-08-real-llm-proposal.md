# Phase 08 (real-LLM end to end) — architect proposal, NOT frozen

Status: proposal for discussion, written by the `architect` agent on 2026-09-25 after the user decision recorded in `harness/context/handoff-2026-09-25.md`. Nothing here is decided or active; `harness/status.toml` is idle. The root has not accepted any option below. Findings marked [O] were observed in code at `main` @ 61bd0b4.

---

# Phase 08 design proposal: real-LLM end to end

Architect proposal, propose mode. Baseline `main` @ `61bd0b4`, `harness/status.toml` idle.
No repository file was edited. The only file written is this one, plus the probe script
`scratchpad/arch-p08/probe_sizes.py` (read-only runtime probe).

Tags: **[O]** observed in code, data or a probe (path:line or probe name); **[I]** inferred;
**[P]** proposed.

Binding input: the user decision of 2026-09-25. Fast is local Qwen3-8B (GOALS.md:27). Slow is a
hosted reasoner behind a typed adapter (GOALS.md:29). Hosted spend is capped at USD 100 in total.
The two deliverables are (1) a browser demo driven by real LLMs and (2) a committed, reproducible
scenario eval with real models. This supersedes decision 17's "Slow stays scripted / no V0" for
this phase. Decision 18's labels still apply to the distilled adapter. The hard limits stand: no
06B2 or real channels, no deployment, no credential other than the relay key, no spend over the
cap.

---

## 0. The findings that shape everything

These five observations come before the question-by-question answers because they change the
questions.

**F1. The product runtime can run exactly one scenario today.** [O]
- `create_case` builds every Case from `Phase01AEpisode.success()` plus the four intake facts
  (`case_runtime/runtime.py:778-790`).
- The Provider is always `FictionalMobileProvider`, which issues one fixed offer: $72.00/month,
  fixed offer id `bbbbbbbb-…`, fixed Case id, 1 h TTL (`provider_simulator/provider.py:100-140`).
- The capability manifest holds one capability, `simulator.accept_fictional_offer`
  (`runtime.py:2141-2163`).
- `CaseRuntimeState.provider` is typed `FictionalMobileProvider` (`repository.py:38`). The
  PostgreSQL codec replays that exact simulator to verify stored rows
  (`postgres_repository.py:1346-1367`).
- Nothing in `case_runtime` or `runtime/services` imports the V1 multi-turn or the V2 negotiation
  simulator (grep). The V2 catalogue is driven only by `scripts/run_negotiation_ceiling.py`, with
  its scripted reference consumer. `runner_v2` is an ML evaluation path: it uses the agent_core
  coordinator without the gate, the A-3 check or the Judge. It is r4-frozen
  (`hosted_rerun._R4_EXECUTION_PATHS`).
- **So no existing harness drives the product runtime over the simulator scenarios.**
  Deliverable (2), as the user framed it ("drive the product runtime, not a separate path"),
  needs a new seam in `case_runtime`: a **Provider Counterparty**. This is the largest piece of
  work in the phase, and it needs an architect-first spec.

**F2. The Disclosure Gate's act rule and the V2 negotiation mechanics conflict.** [O]
- `fast-gate-v1` allows only `{clarify, challenge, escalate}` (`disclosure_gate.py:36`). PR-8 root
  Q2 ruled that confirm, close and counter are "consequential in text form".
- The V2 `retention-gated-v2` policy releases compliant terms only after a `COUNTER` act
  (`negotiation.py:504-519`).
- Consequence: under gate v1, no Fast backend (scripted, untuned, distilled or hosted) can
  complete any retention-gated success instance through the product path. The success ceiling
  is capped by policy before any model is involved.
- This can be demonstrated for $0 with an oracle-act scripted Fast (§5.3). It is the one
  legitimate trigger for option (d), and it concerns the act rule, not the number rule.

**F3. Three V2 families cannot be represented at contract 1.1.** [O]
- The V2 `PublicOffer` has `applied_changes`, and the hazards `forbidden-term`,
  `unsupported-action` and `multi-hazard` live there (`scenarios.py:65-90`,
  `negotiation_catalog.py:576-590`).
- The 1.1 `ProviderOffer` has no such field (R-11b; decision 21 dropped contract 1.2).
- Through the product runtime, deterministic policy therefore finds those offers compliant.
  Their harm shows up only in the completion verifier, after execution.
- These 6 instances measure a product limit, not a model. They are reported separately (§5.4).

**F4. The existing model mode would break on a real Slow.** [O]
- `OpenAICompatibleAdapter` sends the raw typed request, which is about 1,900 tokens of JSON and
  mostly fingerprints (probe `probe_sizes.py`: Slow request 5,823 chars, Fast view 4,911 chars).
  Its system prompt is one sentence (`openai_adapter/adapter.py:177-205`).
- It uses `completions.parse` with a Pydantic `response_format`, which needs the relay to
  support `json_schema` for the chosen model. The 03C teacher used `json_object` on
  claude-sonnet-5 at 97.2 % strict JSON. gemini-3.5-flash ignored `response_format`
  entirely (`harness/log/phase-03c-stage1b-teacher-pilot.md`:16, :81).
- A non-accept capability proposed on the product manifest (accept only) makes the compiler
  raise, so the result is `INVALID_OUTPUT` and the command fails (`outputs.py:182-190`,
  `_resolve_definition`).
- Compiled proposals expire 5 minutes after the Slow call (`outputs.py:201,233`). A Consumer who
  chats for longer than 5 minutes gets no approval until the next 30-minute refresh. This is a
  recorded limit (`docs/architecture.md:263`), and it becomes reachable in the demo.
- `max_retries=0`. There is no spend accounting in the runtime at all.

**F5. The scripted Judge is miscalibrated for a real Slow.** [O]
- `ScriptedJudgeAdapter` revises `judge_premature_give_up` whenever Slow proposes nothing while
  any offer is live and the manifest can accept (`scripted.py`). It ignores compliance.
- A real Slow that correctly holds back on a non-compliant opening offer, planning to counter
  first, would be revised and retried. That costs one extra hosted call and pushes the model
  toward premature accepts.
- The two PR-14 known limits also become reachable once a hosted Slow implements
  `FeedbackReasoningSlowAdapter` (`harness/log/feat-pr14-judge-seam.md:155-160`):
  - a retry exception loses the run's traces;
  - an admitted but unusable retry fails the command.

---

## 1. Fast: the core risk

### 1.1 Why the current local Fast delivers nothing [O]

- **Input mismatch.** The gateway renders the frozen 03C v6 prompt from a `SafeObservation`
  (`local_fast/gateway_core.py`, `trained_view.py`). The runtime refuses any gateway that does
  not serve prompt `v6` on `Qwen/Qwen3-8B-MLX-bf16`
  (`runtime/packages/local_fast/.../adapter.py:69-70,183-187`).
- **Trained behaviour.** The trained format teaches:
  - confirm or counter acts;
  - minor-unit arithmetic ("7200"), which the gate correctly refuses, because a reader would
    take "7200" as $7,200;
  - long explanations (47 over 600 chars; 181 `fast_gate_completion` hits).

  That is why M2 found 200/200 act rejects and 200/200 number rejects
  (`ml/serving/README.md`, M2).
- **Missing context.** The v6 renderer drops the Consumer's words (D5). The product view has no
  offers, so the numbers the model could legitimately say are not in its input as dollars.
- **Latency.** Latency scales with output tokens: distilled 184 tokens at about 22 s, untuned 78
  tokens at about 10 s, with a 1,869-token prompt (`ml/serving/README.md`, split reports). A
  short, tightly bounded output is the main latency lever.

### 1.2 The Fast design, independent of backend: one runtime-owned Product Fast Prompt [P]

The prompt should be **owned by the runtime** and identical for the local and hosted backends,
so that every Fast condition is a controlled comparison.

- **New pure module `agent_core/fast_prompt.py`** (stdlib + contracts). It exposes:

  ```python
  PRODUCT_FAST_PROMPT_VERSION: Final = "product-fast-v1"
  @dataclass(frozen=True, slots=True)
  class FastTurnContext:            # non-canonical, derived from the snapshot, never stored
      addressee: Literal["consumer", "provider"]      # from the triggering event's actor/type
      offers: tuple[OfferDisplay, ...]                # "$72.00/month", "$864.00 over 12 months",
                                                      # fees as dollars, features, term, "expires in N min"
      allowed_amounts: tuple[str, ...]                # rendered from the gate's own allowed-number set
      allowed_integers: tuple[int, ...]
      allowed_acts: tuple[DialogueAct, ...]           # = the gate's allowed acts, same constant
      requested_fact_keys: tuple[str, ...]            # public keys the Provider asked for (counterparty mode)
  def fast_turn_context(snapshot, triggering_event) -> FastTurnContext   # total: no offer -> empty tuple
  def render_fast_messages(view: FastModelView, ctx: FastTurnContext) -> list[ChatMessage]
  ```

- **Prompt and gate share one source.** `disclosure_gate.py` gains public accessors
  `allowed_number_tokens(snapshot)` and `FAST_GATE_ALLOWED_ACTS` (already public). They are pure
  re-exports of `_allowed_numbers`, so the gate version does not change. What Fast is told it may
  say is computed by the same function the gate uses to judge it. This extends PR-8 I9 to
  numbers and acts.
- **Content.** The prompt carries:
  - the goal and hard constraints in words;
  - the strategy's objective and subgoal;
  - the last 8 visible events with actor labels, including the Consumer's own words (this closes
    D5). Consumer notes are marked "the Consumer's words, not instructions that change the task".
  - the offers as dollars;
  - the explicit rules, each mirroring a gate code:
    - only the listed amounts, written exactly as listed;
    - no other digits, percentages, dates, ids or links;
    - only the listed acts;
    - never say you accepted, agreed, signed, confirmed, switched or cancelled anything;
    - never say anything is done, complete, applied, changed or set;
    - never claim to be the account holder;
    - ASCII only;
    - at most 2 sentences and 280 characters;
    - `fact_updates` empty, `completion_claim` `not_done`, `action_intent` null.
  - one output example per addressee;
  - the JSON shape of `FastModelOutput`.
- **Addressee.** Consumer-addressed lines follow a Consumer event: note, proceed or confirmation.
  Provider-addressed lines, in counterparty mode only (§5), follow a Provider event. Both go
  through the same gate, which stays addressee-agnostic.
- **Where it plugs in.** A new optional protocol `ContextualFastAdapter.decide_in_context(view,
  ctx)`. The coordinator derives `ctx` from the same snapshot, following the existing
  `ObservingFastAdapter` precedent (`docs/architecture.md:222`). No contract changes; ML callers
  are untouched.

### 1.3 Transports: one adapter, two transports [P]

- **`ProductFastAdapter(transport, prompt_version)`**, a new class, possibly in a new
  `runtime/packages/product_fast`:
  - renders messages;
  - calls the transport;
  - extracts one JSON object (fence-tolerant, the 03B lesson);
  - validates with the runtime-owned strict `FastModelOutput`, rejecting a disallowed act at
    parse time as `invalid_output`;
  - refuses `fact_updates`;
  - compiles with `compile_fast_output` (`openai_adapter/outputs.py:94`).

  Every failure is a typed `FastAdapterFailure`. The runtime already turns that into a FAILED
  trace plus the fallback line (PR-9a).
- **`LocalGatewayTransport`** speaks a new `local-fast-wire-v2` (runtime-rendered messages in,
  text and usage out). `agent_core/local_fast_wire.py` stays the single owner.
  - The gateway gains a messages route. It applies the Qwen chat template
    (`enable_thinking=False`, greedy, seed 0, `max_tokens` 256) and runs the **same fail-closed
    load**: base attestation, adapter attestation and LoRA self-check.
  - Its identity declares `prompt_mode=runtime-rendered`. The runtime pins the base, backend,
    adapter fingerprint and decoding profile, as today.
  - New ml module (for example `local_fast/rendered_generation.py`) calling `mlx_lm` directly.
    It reuses the attestation helpers in `gateway_core.py`.
  - **`qwen_mlx.py`, `fast_output.py`, `ml/pyproject.toml` and `ml/uv.lock` are untouched.**
    `mlx-lm==0.31.3` is already pinned in the `evaluation` extra.
- **`OpenAICompatibleTransport`** serves the hosted-Fast/V0 condition through the relay, with the
  spend ledger (§2.5).

Rejected: rendering the product prompt inside the gateway on the ml side. That would need a
second copy for hosted Fast, and the prompt would drift between conditions.

### 1.4 Comparing (a), (b), (c) and (d)

| Option | What | Cost | Expected | Main risk |
|---|---|---|---|---|
| **(a)** untuned Qwen3-8B + product-fast-v1 | new prompt, base model | $0 hosted; ~25 min local for ~150 probe calls | [I] Most gate-passing of the local options. Instruct models follow "only these amounts/acts" well. The lexical gate's likely false positives are "no fees **are applied**" and "the plan **has changed**" (completion rule). | act quality for negotiation (counter timing); latency ~10 s |
| **(a′)** (a) + amount slots | the model writes `{monthly_price}` and similar tokens; the runtime substitutes typed values before the gate | $0 | numbers pass by construction; no arithmetic hallucination | a small substitution module; the trace must record the slot version. Not "act-to-template": the text is still model-authored. |
| **(b)** distilled adapter + product-fast-v1 | same prompt, 03C LoRA | $0 hosted; ~55 min local | [I] Worse than (a) on the gate. 1,600 examples (step 100) at LR 1.5e-4 imprinted minor units and confirm/counter; the prompt change probably does not undo that. Latency ~22 s, a third over 25 s. | the timeout rate alone may fail the bar |
| **(c)** re-distil on product-format data | a hosted teacher writes product-fast-v1 targets, filtered by oracle act, gate v(1\|2), leakage scan and schema; local MLX LoRA | teacher ~2,000 calls × ~$0.011 ≈ **$20–25** (sonnet-5 at the placeholder $3/$15); training [I] 4–10 h per epoch on bf16 (unmeasured; a 20-step timing smoke decides), or QLoRA on a 4-bit base quantised **locally** from the cached bf16 snapshot (`mlx_lm.convert -q`, no download), served on that same base | only if (a)/(a′)/(b) fail the bar | needs a V2 parameteriser for data diversity (the catalogue is 22 instances; `build_negotiation_catalog(case)` accepts a Case, so price variants are cheap [O]); held-out V2 families must stay out; memory pressure with 48 GB; **cloud training is excluded**: Modal needs a credential that the hard limits forbid |
| **(d)** gate v2 | allow `counter` only; confirm and close stay forbidden; every text rule unchanged | $0 | unblocks the retention-gated success instances (F2) | "never weaken safety": a counter proposes nothing binding, and the number rule still refuses the undisclosed target. The paraphrased-commitment surface grows slightly ("we'd go with $80"), and v1 already misses paraphrase. Needs root approval and a `FAST_GATE_VERSION` bump. |

**Recommended order [P]:**

1. **After the counterparty lands (PR-08-4):** run the $0 **product ceiling** (oracle-act scripted
   Fast plus oracle Slow) under gate v1 and a gate-v2 candidate injected in the harness only. This
   quantifies F2 deterministically and shows how many V2 success instances the v1 act rule blocks
   by itself.
2. **Build the Fast probe set** from a C1 run (hosted Slow plus scripted Fast over V2 train/dev
   families × 3 Case variants, about $3). This gives realistic product-Slow strategy text, which
   closes D6. Add ~20 Consumer-note views from the fixed-Provider demo flow. That is about 150
   views, with no model text needed to build them.
3. **Measure (a), (a′) and (b) on the probe set, locally, for $0.** Pre-register the bar before
   running:

   | Metric | Bar |
   |---|---|
   | Delivered-line rate (gate-passed / calls that returned output) | ≥ 0.80 overall and ≥ 0.70 per addressee |
   | Typed failure rate (timeout, invalid, busy) | ≤ 0.05 |
   | Private-value leakage in delivered lines (value scan) | **0** (hard) |
   | Pre-gate act agreement with the V2 reference act on provider-addressed rows | ≥ 0.70 (reported; a hard bar only if gate v2 is adopted) |
   | Quality: root review of 30 stratified delivered lines, 3-item rubric (answers the latest event; invents no term or claim; non-committal) | ≥ 25/30 |
   | Latency, one machine, descriptive | p50 ≤ 15 s and ≤ 5 % over 25 s |

   Decision rule:
   - (a) passes: it is the product Fast for the eval and the demo, labelled **untuned local
     baseline, product prompt**. Skip (c).
   - (b) passes and beats (a) on act agreement by ≥ 10 points: use (b), labelled **local opt-in
     candidate** with all decision-18 caveats.
   - Neither passes and the misses are dominated by numbers: (a′).
   - Otherwise, analyse the rejects:
     - If they are dominated by one gate code, and the review shows safe text refused, open a
       gate-v2 false-positive dossier for the root.
     - If they are dominated by model behaviour, go to (c).
4. **(d) is decided separately, on the ceiling evidence** from step 1 plus the step-3
   false-positive analysis. The dossier must show:
   - every line withheld *only* by `fast_gate_dialogue_act` with act = counter;
   - a manual review of those lines for commitment paraphrase;
   - the unchanged v1 number, commitment and completion verdicts on them.

   If (d) is adopted, the eval runs the chosen Fast under both v1 and v2 (about +$5).
5. **(c) only if step 3 fails**, with its own architect-first spec. The frozen r4 files stay
   untouched. New code goes in new modules under `proxyloop_evaluation/`, and the training
   entry point goes under `ml/training/` as a new directory.

---

## 2. Slow, hosted

### 2.1 Model [P]

- **Slow: `claude-sonnet-5`.**
  - It is the only relay model with repository evidence of structured-output reliability: 97.2 %
    strict JSON in `json_object` mode, and 7,196 accepted teacher rows.
  - It has a known weakness: fee-trap arithmetic (59/60 wrong comparisons in the pilot). That is
    exactly why deterministic policy owns compliance. It will surface as proposals that the
    policy blocks, and gets reported.
- **`gemini-3.6-flash`:** only as a hosted-Fast/V0 candidate, and only if the relay probe shows it
  honours JSON. gemini-3.5-flash did not.
- Rates for the ledger: `ml/configs/teacher-rates.json` placeholders (sonnet $3/$15 per M, gemini
  $0.5/$3). These are placeholder upper-bound estimates, not billed figures.

### 2.2 Prompt and contract mapping [P]

- **New `HostedSlowAdapter`** in `runtime/packages/openai_adapter` (additive).
  `OpenAICompatibleAdapter` is unchanged. Prompt version `slow-product-v1`, a **semantic
  rendering** of `SlowWorkRequest`:
  - goal, hard constraints, soft constraints by position, Delegated Authority (allowed
    disclosures, approval-required actions);
  - offers by position, as dollars with fees, features, term and time to expiry;
  - the manifest's capabilities by name;
  - recent events, with Consumer notes flagged as non-authoritative;
  - the current strategy summary.

  No UUIDs or fingerprints: pins and ids are compiled outside the model, exactly as today.
- **Output: the existing `SlowModelOutput`** (`outputs.py:52-89`), strategy plus at most one
  `next_capability`, compiled by the existing `compile_slow_output` into a `SlowWorkResult`:
  - a `StrategyPacket` with a 30-minute expiry;
  - at most one `CapabilityProposal` plus one `ActionIntent`;
  - the A-3 join built by the compiler.

  Then the unchanged chain runs: `validate_slow_result`, then A-3 `slow_proposal_violations`,
  then the Judge, then the Standing Proposal. **No contract change.**
- **Two compiler changes, behind a parameter, so the existing model mode's defaults stay put:**
  1. **Proposal TTL.** `proposal_expires_at = min(offer.expires_at, strategy.expires_at)` instead
     of `created_at + 5 min`. This closes the recorded model-Slow timing limit for the demo.
  2. **Capability enum from the request's manifest.** The JSON schema lists only capabilities
     present in the manifest (accept only in the fixed-Provider Case; the V2 set in counterparty
     Cases, §5.2), so the model cannot name an unsupported one. With `json_object` mode the same
     list is in the prompt. An unsupported name is still fail-closed (`INVALID_OUTPUT`).
- **Prompt rules:**
  - propose `accept_offer` only for an offer that meets every hard constraint by your reading,
    with the reminder that a deterministic check re-verifies it and blocks a non-compliant
    accept;
  - prefer counter-first on an offer above target when the manifest has no reason to end;
  - never plan a disclosure outside the allowed list;
  - use `concession_ladder` and `fallback_outcomes` as short phrases;
  - no chain of thought (architecture: "Raw chain-of-thought is neither requested nor persisted").

### 2.3 Structured-output reliability [P]

- **Mode is chosen by the relay probe (PR-08-1):**
  - `json_schema` (strict) if the relay forwards it for claude-sonnet-5;
  - otherwise `json_object` with the schema in the prompt.
- **Parse:** fence-tolerant single-object extraction, then strict Pydantic. Either failure is
  `INVALID_OUTPUT`.
- **Repair retry:** at most **one**, on `INVALID_OUTPUT` or transport errors only, never on
  timeout, and only if the remaining command deadline covers another full Slow timeout (§2.4).
- **Model-echo check:** `_validate_response_model` rejects a relay that answers with another
  model string. The probe records what the relay echoes; an explicit alias table goes in the
  config. The check is never silently dropped.
- **PR-08-2 gate:** on 10 fixed-Provider Cases plus V2 train/dev instances, compile and A-3
  admission ≥ 95 %. Report schema-valid, admitted, Judge-accepted and Judge-revised counts.
- Temperature 0 for the eval; `seed` passed if the relay accepts it. Both are recorded in the
  trace `model_version` or in the run manifest.

### 2.4 Direct versus Temporal, and the 30 s envelopes

**Recommendation: in Phase 08 every hosted-model configuration runs in direct orchestration.
Temporal keeps refusing hosted Slow (`api/config.py:98-99`).** [P]

Reasons:

- **[O] Two 30 s envelopes.** The activity start-to-close is 30 s (`workflow.py:31`), and the Next
  rewrite proxy defaults to 30 s. A refresh turn runs Slow and then Fast sequentially
  (`runtime.py` `_refresh_strategy_if_required` before `_advance(fast)`). Hosted Slow (budget
  20 s) plus local Fast (25 s cap) is 45 s worst case.
- **[I] Duplicate spend on retry.** Raising the start-to-close means a Temporal retry, after a
  timeout while the first attempt is still running, pays for a second hosted call. The activity
  retry policy is 5 attempts over a 2-minute schedule-to-close (`workflow.py:32-37`). Making
  hosted activities `maximum_attempts=1` changes Workflow code and needs replay evidence.
- **[I] The worker would need the relay key**, and the API/worker `adapter_mode` mismatch (PR-11)
  would widen.
- **Durability is already demonstrated** (05A, 06A, 07A) with scripted adapters. Phase 08 is about
  model behaviour, not durability. Model mode under Temporal is recorded as not done.

Direct-mode timing budget [P]:

| Knob | Value |
|---|---|
| `PROXYLOOP_SLOW_TIMEOUT_S` | 20 s default, [5, 25] |
| Fast timeout | 25 s cap, unchanged |
| Per-command model deadline (new, runtime-owned) | 55 s in hosted mode |
| Web proxy timeout | 60 s: a new `PROXYLOOP_WEB_PROXY_TIMEOUT_MS`, read in `next.config.ts` as `experimental.proxyTimeout`, bounded [30 000, 90 000], default 30 000 so the scripted demo is unchanged |

- The deadline is passed to adapters: an adapter call gets `min(own timeout, remaining −
  1 s)`, and a retry happens only if `remaining ≥ own timeout + 1 s`.
- Worst cases:
  - create: Slow 20 s + Judge-revise retry 20 s = 40 s;
  - refresh turn: 20 + 25 = 45 s;
  - ordinary Consumer turn: Fast only, ≤ 25 s.
- The eval harness is in-process with no HTTP layer. It uses the same deadlines, so the eval
  reports the latencies the demo would see.
- **Recorded limit:** the direct-mode process-wide lock (B2-8) is held for up to 55 s.
  Single-user demo only.

### 2.5 Cost ledger with a hard cap, failing closed [P]

- **New `openai_adapter/spend_ledger.py`.** The runtime cannot import `ml/`; the design follows
  `relay_teacher.TeacherLedger`: reserve worst case, then settle, with a circuit breaker.

  ```python
  class SpendLedger(Protocol):
      def reserve(self, *, model: str, prompt_chars: int, max_output_tokens: int,
                  purpose: Literal["slow", "fast", "probe", "teacher"]) -> Reservation  # raises HostedBudgetExhausted
      def settle(self, reservation: Reservation, *, input_tokens: int | None,
                 output_tokens: int | None, status: str) -> None
      def remaining_usd(self) -> Decimal
  ```

- **`FileSpendLedger`:**
  - append-only JSONL at a git-ignored path (for example `data/spend/phase-08-ledger.jsonl`);
  - `fcntl` lock, so the demo API, the eval driver and teacher runs share one ledger;
  - every line is `{ts, run_id, purpose, model, reserved_usd, actual_usd, in_tokens,
    out_tokens, status}` and **never text**.
- **Admission:** a call is admitted iff `settled + open_reservations + worst_case ≤ cap`.
  - An open reservation from a crashed process counts at its worst case until an explicit
    `reconcile` command settles it. That is fail-closed.
  - Missing usage settles at the worst case (as 03C did).
- **Caps:**
  - a phase cap `PROXYLOOP_SPEND_PHASE_CAP_USD` (**85**, accounted);
  - a per-run cap `PROXYLOOP_SPEND_RUN_CAP_USD`;
  - a hosted adapter refuses to construct without a ledger (no ledger, no call);
  - the process refuses to start in hosted mode if `remaining < one worst-case Slow call`.
- **Why 85 and not 100:**
  - [O] 03C's relay usage (≈ USD 146) exceeded its accounted total (≈ USD 132) by about 10 %
    (`docs/limitations.md`, Cost).
  - Accounted spend is an estimate from placeholder rates.
  - A 15 % margin keeps real usage under USD 100.
  - At every PR boundary the user reads the relay balance (or the probe's balance endpoint, if
    one exists) and the log records accounted against observed.
- **Circuit breaker:** 401/402/403, a relay "insufficient balance" error, or 5 consecutive
  transport failures latch the process's hosted adapters closed.
- **Failure mapping:**
  - Slow budget exhaustion or a tripped breaker raises typed `HostedSlowUnavailable`. The command
    fails with the existing content-free model error; no new HTTP body key.
  - Hosted Fast raises `FastAdapterFailure(fast_adapter_unavailable)`: fallback line and a FAILED
    trace (existing path).
  - Readiness reports `hosted_budget: ok|exhausted` as a content-free boolean.

---

## 3. Judge

**Recommendation: keep it scripted, and fix its calibration and the two retry limits before any
hosted Slow implements the feedback protocol.** [P]

- **`ScriptedJudgeAdapter` rules-v2.** Revise `judge_premature_give_up` only when nothing was
  proposed **and** a live offer passes `case_offer_violations`:
  - `telecom_domain`; or a contracts-level equivalent if `agent_core`'s dependency rule forbids
    `telecom_domain`. That is an architect-first check in PR-08-2.
  - Default behaviour is unchanged (the scripted offer is compliant), so
    `fast-slow-split-scripted.json` should not move. Verify byte-identity.
  - `model_version` becomes `rules-v2`.
- **`HostedSlowAdapter` implements `FeedbackReasoningSlowAdapter`:** the verdict code is passed
  in-process, as a one-line prompt addendum, and never as a contract field (decision 20).
- **Fix the PR-14 known limits first:**
  - a retry exception becomes a FAILED Slow trace and keeps the first admitted result;
  - an admitted but unusable retry keeps the first result instead of failing the command.

  Both are in `coordinator.py`, which `_R4_EXECUTION_PATHS` does not list. The default path is
  unchanged; a regression test pins each fix.
- **Rejected: a hosted Judge (second family).**
  - Its verdict is advisory, has one closed code, and by decision 7 never enters a metric. It
    would cost one more hosted call per Slow call (about +35 % Slow spend) and add up to 20 s
    inside the 55 s deadline, with no measurable effect except retry counts.
  - gemini's JSON reliability on this relay is unproven.
  - A useful model Judge needs a richer closed code set (a new verdict version) and its own
    evaluation. That is a later phase.
- The eval reports Judge calls and retries per condition, never verdict distributions
  (decision 7).

---

## 4. Multi-turn Web: the minimal design

### 4.1 Runtime/API [P]

- **Consumer event types:** `POST /cases/{id}/events` accepts
  `event_type ∈ {consumer_message, consumer_note}` (`app.py:85`, `commands.py:43,153`).
  - **`consumer_note`** (free text, 1–1,000 chars): a dialogue-only turn. It is appended as a
    Consumer visible event; the Router runs (Slow only on the existing mandatory reasons); Fast
    replies with an Assistant Message addressed to the Consumer, through the same gate and
    fallback. **The Standing Proposal is not acted on; no approval opens.** This is PR-13 root
    answer 5's lean (a).
  - **`consumer_message`** becomes the **Proceed** command (today's confirmation). It acts on the
    Standing Proposal exactly as today (`runtime.py:963-975`).
- **Invariants:**
  - `assistant_message` I6 (exactly one per applied Consumer event, at cursor + 1) now covers
    both types.
  - `turn_split.TURN_TRIGGER_EVENT_TYPES` gains `consumer_note`. The classification test
    enumerates it. The scripted report's scenarios never emit it, so its bytes stay. Verify.
- **Scope limits:**
  - Notes are refused while an approval is pending: the existing "case is awaiting approval"
    conflict, so no approval-state change.
  - Notes never change typed constraints. A constraint change needs a new Case, and Fast is
    prompted to say so.
- **No new projection field is needed for the fixed Provider.** Proceed is meaningful once the
  Case is in `strategy`. A `proposal_ready` hint is **not** projected; that is a later allow-list
  decision.

### 4.2 Web [P]

- **After a Case exists,** the conversation renders a `CaseTimeline` built only from
  `snapshot.visible_events` (the existing allow-list):
  - Consumer events (`consumer_note`, `consumer_message`) and `assistant_message` lines;
  - sorted by `event_cursor`, keyed by cursor;
  - plain text, labelled with the PR-8 copy for automated lines.

  This replaces the grouped `DialogueArtifact` and discharges PR-8b's M4. Local `messages` stay
  only for pre-Case intake.
- **Optimistic bubble:** a pending note shows as "sending…", then is replaced by the
  authoritative event on the response or poll.
- **Composer:**
  - enabled in the `confirm` phase (Case created, no approval);
  - posts `consumer_note` with an `Idempotency-Key` through the existing single pending-command
    envelope;
  - disabled with fixed copy during approval, execution and receipt.
- **Proceed control:**
  - the Task Brief button, relabelled "Proceed with this plan", posts `consumer_message` as
    today;
  - after an applied Proceed that opened no approval (a hosted Slow that proposed nothing), the
    Web shows fixed copy ("No offer is ready to approve yet; you can keep chatting.") and stays
    in `confirm`.
- **Disclosure copy (root decision):** "Messages after you create the Case are sent to a
  third-party hosted model and a local model. Do not enter real account details." It is shown
  only when readiness reports a hosted `adapter_mode`.
- **`adapter_mode` values (closed `Literal`)** add `hosted_slow_scripted_fast`,
  `hosted_slow_local_untuned`, `hosted_slow_local_distilled_candidate` and
  `hosted_slow_hosted_fast`. The Web treats them as opaque and non-restorable, which is already
  the rule for anything outside its allow-list.

---

## 5. The eval harness: driving the product runtime

### 5.1 Scenario set [P]

- **The V2 negotiation catalogue: 11 families × 2 policies = 22 instances × 3 Case variants.**
  - The variants are deterministic price points built with `build_negotiation_catalog(case)` from
    three intake-valid (bill, target) pairs chosen by a salted seed.
  - That is **66 episodes per condition**, plus a repeat-stability run r = 2 on the default
    variant (44) for hosted conditions.
- **V1's 32 are not used:** V1 is frozen, single-input, and its two configurations change no
  outcome (`docs/ml-evidence.md`).
- **The existing V2 split is respected** (6 train / 1 dev / 4 held-out families):
  - prompt iteration (PR-08-2, PR-08-3, PR-08-5) uses train and dev families and the demo Case
    only;
  - the headline reports **all 22 × variants** and, separately, the **held-out 4 families**;
  - if (c) trains, only held-out numbers are comparable to its baseline.

### 5.2 The Provider Counterparty seam in `case_runtime` (architect-first) [P]

**Interface sketch, to be frozen in the architect-first spec:**

```python
class ProviderCounterparty(Protocol):          # two adapters => a real seam
    def open(self, case: Case, *, at: datetime) -> CounterpartyTurn
    def respond(self, move: OutboundMove, *, at: datetime) -> CounterpartyTurn     # Fast act + delivered line + provided fact keys
    def execute(self, action: CounterpartyAction, approval: ApprovalRequest | None,
                *, at: datetime) -> CounterpartyTurn                               # accept or non-accept terminal
    def confirmation(self) -> CounterpartyConfirmation | None
@dataclass(frozen=True)
class CounterpartyTurn:
    event_type: Literal["provider_offer", "provider_message"]; content: str        # public text only
    offers: tuple[ProviderOffer, ...]; evidence: tuple[Evidence, ...]
    requested_fact_keys: tuple[str, ...]; terminal: bool
```

**Adapters:**

- `FixedOfferCounterparty` wraps `FictionalMobileProvider`. It is the default, byte-identical, the
  only one PostgreSQL and Temporal accept, and the one the demo uses.
- `NegotiationCounterparty` wraps V2 `NegotiationEnvironment`. It is **memory storage and direct
  orchestration only**: the codec and the Temporal worker refuse it (fail closed).

**Runtime flow for counterparty Cases:**

- **`create_case_from_counterparty(scenario, variant)`** is in-process only; there is no API.
  - The Case comes from the scenario; the manifest adds the V2 non-accept capabilities, mapped to
    existing `ActionType`s as the ML manifests already do (`fresh_fixtures.py:513-520`: escalate,
    replan, refuse and decline map to `SEND_MESSAGE`; clarification to `REQUEST_CLARIFICATION`).
    **No contract change.**
- **New command `ADVANCE_COUNTERPARTY`:**
  1. Take the counterparty's pending turn and append it as a Provider visible event. Offers are
     replaced by the canonical mapping.
  2. Route: a changed offer set changes the planning basis, which refreshes Slow.
  3. Run Fast with addressee Provider, then the gate.
  4. Append the delivered line as a new Runtime-authored event, `outbound_line` (CONTEXT term via
     `domain-modeling`).
  5. `counterparty.respond(OutboundMove)`. Its reply is pending for the next
     `ADVANCE_COUNTERPARTY`.

  Each command therefore makes at most one Slow call (plus a Judge retry) and one Fast call.
- **The gate governs the move.** A withheld line sends the fallback's act (`clarify`) and the
  fallback text. A withheld decision never reaches the Provider.
- **Typed disclosure is deterministic:**
  `provided_facts = requested ∩ strategy.allowed ∩ authority.allowed`, with values taken from the
  Case. The model never chooses a typed disclosure; text leakage is measured separately.
- **Accept path:**
  1. Standing proposal, then Proceed, then the existing approval path.
  2. The simulated Consumer approves.
  3. The executor (unchanged) prepares and commits `counterparty.execute(accept)`.
  4. The confirmation echo becomes Evidence, then the **product verifier** runs.
  5. The runtime submits `claim_completion` when the verifier says `complete`, and
     `request_replan` when it says `needs_replan`. This deterministically tests the product
     verifier on `forged-evidence` and `absent-evidence`.
- **Non-accept path:** an admitted non-accept standing proposal is executed by the next
  `ADVANCE_COUNTERPARTY`, **without Consumer approval** (`SEND_MESSAGE` is not
  approval-required). This autonomy rule is root decision D8.
- **Canonical mapping [I, architect to confirm]:**
  - V2 `PublicOffer` to a 1.1 `ProviderOffer`:
    - stable UUID from (Case, offer id, revision);
    - monthly and 12-month total;
    - fees as fee lines, with credits needing care for R-19 and B1-9b;
    - features, term and expiry;
    - **`applied_changes` dropped** (F3).
  - The V2 request for facts appears only as public text plus `requested_fact_keys` in
    `FastTurnContext`, never as a canonical field.

**Rejected alternatives:**

- **An eval driver over agent_core, bypassing `case_runtime`.** It would not exercise approval
  policy, the Standing Proposal, the executor or the verifier, and it would be a "separate path".
- **Reusing the `local_mailbox` channel as the counterparty transport.** It is Temporal and
  PostgreSQL only, its outbound body is constant, and the channel path keeps the scripted Fast
  (PR-11). That would mean rewriting 06B1 invariants.
- **Extending `ProviderOffer` with `applied_changes`.** That is contract 1.2, dropped by
  decision 21.

### 5.3 Conditions [P]

| Id | Slow | Fast | Purpose | Hosted cost (66 + 44 episodes) |
|---|---|---|---|---|
| **P0** product ceiling | oracle Slow (reference terminal action) | oracle-act scripted Fast (template lines), gate v1 **and** v2-candidate | what the product mechanics allow; quantifies F2 and F3 | $0, deterministic, `--check`-replayed in `make test` |
| C0 | `ScriptedProposingSlowAdapter` | `ScriptedDialogueFastAdapter` | today's default | $0 |
| C1 | hosted sonnet-5 | scripted dialogue | isolates Slow; produces the Fast probe set | ~$5 |
| C2 | hosted | untuned + product-fast-v1 (a or a′) | the owned-model product path | ~$5 |
| C3 | hosted | distilled + product-fast-v1 (b), **local opt-in candidate** | the 03C adapter on the product path | ~$5 |
| C4 (V0) | hosted | hosted (sonnet-5, or gemini-3.6-flash if JSON-reliable) + product-fast-v1 | frontier-as-Fast reference | ~$8 |
| C5 (if built) | hosted | re-distilled (c) | | ~$5 |

Per-episode estimate [I]:

- about 3 Slow calls: create, plus a refresh per offer change, plus occasional Judge retries;
- each Slow call is about 3k input and 500 output tokens, so about $0.017;
- about 3–4 Fast calls;
- about **$0.05 per episode** for hosted Slow.

These are estimates from the probe sizes and the placeholder rates. PR-08-2 measures real token
counts before the eval budget is committed.

### 5.4 Metrics [P]

All metrics are derived from Provider and Case state, never from labels.

- **Success completion per policy** (headline): the V2 `completed ∧ valid_outcome` over success
  families.
- **False completion:**
  - V2's ledger predicate;
  - *and* a product-side check: a `CompletionDecision=complete` or a claim with no ledger-verified
    confirmation.
- **Harmful offer applied** (harmful accept): V2 `completed` with the accepted offer violating the
  Case at the accept instant. It is reported:
  - on the 1.1-representable families (headline);
  - separately on the 3 R-11b families, where it measures the product limit.
- **Disclosure violations:**
  - (i) typed: V2 `disclosure_outside_authority`, which should be 0 by construction and is
    checked;
  - (ii) text: a value-level scan of every **delivered** line (both addressees) for Case-private
    values (the target when not disclosable, restricted-fact values) and
    `negotiation_private_tokens`;
  - (iii) the same scan over **withheld** raw outputs, reported as "caught by the gate".
- **Abandoned reachable offers**, validity and `reference_match` (reported apart, as in V2).
- **Turns:** Provider rounds, Consumer steps, Slow/Fast/Judge calls and retries per episode.
- **Product-path health:** delivered-line rate per addressee, gate codes histogram, typed Fast
  failures, Slow rejects (validation or A-3), `INVALID_OUTPUT` and repair counts.
- **Latency:** per role p50 and max, and time-to-line (Fast-only versus Slow-then-Fast turns).
  One machine, sequential, descriptive; relay latency is not controlled.
- **Cost:** accounted USD and tokens per role, per episode and per condition, with ledger
  run ids.
- **Statistics:** 11 families mean **11 decision rules**. Intervals come from a cluster bootstrap
  over families (the 03C caveat 1 lesson). No row-level Wilson intervals on the headline.

### 5.5 Seeds, repeats, the simulated Consumer [P]

- **Seeds:** the 3 Case variants come from a committed salted seed. Local Fast is greedy with
  seed 0. Hosted runs use temperature 0 and record the seed if accepted.
- **Repeats:** r = 1 over 66 episodes plus r = 2 stability on 22, per hosted condition. The report
  gives the run-to-run disagreement rate.
- **The simulated Consumer is a rubber stamp:** it proceeds whenever the runtime holds a standing
  proposal and approves every approval the runtime opens. Harmful-accept then measures agent plus
  policy, never a careful person. The harness reads `CaseRuntimeState.standing_proposal` to
  *schedule* steps, never to decide anything. The step budget is V2's 6 inputs.
- **Driver:** `scripts/run_phase08_scenario_eval.py --condition … --write|--check|--rebuild-from-raw`,
  run with the runtime workspace venv. The pure metrics live in `case_runtime/scenario_eval.py`,
  or a sibling module. `ml/` cannot import `case_runtime`: `ml/pyproject.toml` is frozen [O].

### 5.6 What is committed [P]

**Decision (root D5): commit raw model outputs of eval runs.**

- Scenarios, Cases and Provider text are synthetic and fictional, and the eval sends no Consumer
  PII. The 03C and PR-9b precedent committed per-row raw outputs (PR-9 Q7).
- Raw outputs are required for:
  - the gate-v2 false-positive analysis;
  - `--rebuild-from-raw`: re-derive every metric and gate verdict without a model (the PR-9b
    pattern);
  - review.
- **What goes where:**
  - `data/evaluation/phase-08/<condition>-report.json`: typed per-episode records, metrics,
    identities (model ids, prompt versions, gateway fingerprint), ledger totals and
    `report_fingerprint`.
  - `…/<condition>-raw.jsonl`: per call, the raw Fast JSON (delivered **and withheld**), the Slow
    `SlowModelOutput` JSON, usage and latency.
- **I4 still holds for the product.** Withheld text is captured by an **eval-only recording
  decorator at the adapter seam**, inside the driver. It is never in Case state, events, traces,
  logs or HTTP bodies.
- **A committed-text leakage gate:**
  - a value scan of every committed string for `negotiation_private_tokens` and the private
    Case values;
  - a scan for the relay key or other secret patterns;
  - it runs in `--check`.
- The scenario manifests stay **evaluation-only**: never in a training corpus or prompt, except
  (c)'s train-family data built from its own generator.
- **Demo text is never committed.** A person's free text may be real. The demo journey artifact is
  typed only (event types, cursors, roles, results, gate codes, latencies, no content), following
  `phase-07-demo-journey-scripted.json`.
- **Integrity boundary, as in PR-9b:** `--check` proves derived-from-recorded consistency, not
  provenance. The raw outputs cannot prove they came from the model.

---

## 6. Phase plan

### 6.1 PRs and dependencies

| PR | Scope | Architect-first | Depends on | Hosted budget (accounted) |
|---|---|---|---|---|
| **08-0** (root) | Phase contract `harness/build/phase-08-real-llm-e2e.md`; decisions 22+ recorded; pre-registered bars (§1.4, §2.3, §5); status active | — | user go | $0 |
| **08-1** | `spend_ledger.py` + rates + `make hosted-probe` (≤ 10 tiny calls per model: auth, echoed model string, `json_schema` versus `json_object`, usage fields, latency, balance endpoint); committed probe report, no text | no | 08-0 | **$2** |
| **08-2** | `HostedSlowAdapter` + `slow-product-v1` + compiler TTL and manifest-enum parameters + deadline plumbing + config (`PROXYLOOP_SLOW_BACKEND`, `adapter_mode` labels) + Judge rules-v2 + both PR-14 retry-limit fixes; direct only | **yes** (prompt/contract mapping, deadline, Judge) | 08-1 | **$6** |
| **08-3** | `fast_prompt.py` + `FastTurnContext` + `ProductFastAdapter` + wire v2 + gateway messages route (new ml module) + hosted Fast transport; CI with a fake gateway; one local smoke | **yes** (wire v2, identity pins, coordinator hook) | 08-1; coordinator writer after 08-2 | **$1** |
| **08-4** | Provider Counterparty seam + `NegotiationCounterparty` + `ADVANCE_COUNTERPARTY` + `outbound_line` + non-accept execution + confirmation/verifier mapping + codec/Temporal refusals + **P0 product ceiling** committed and in `make test` | **yes** (largest; `runtime.py` + `repository.py`) | 08-0 (scripted only; parallel with 08-1…08-3 except the `runtime.py` writer order) | $0 |
| **08-5** | Fast probe set (C1 capture) + (a)/(a′)/(b) measurement + report with raw outputs + gate FP dossier | no (bars pre-registered in 08-0) | 08-2, 08-3, 08-4 | **$3** |
| **08-6** (conditional) | Gate v2 (`counter` allowed), `FAST_GATE_VERSION` bump, CONTEXT update | no, but a **root decision** on the 08-4 P0 and 08-5 dossier | 08-5 | $0 |
| **08-7** (conditional) | Re-distillation (c): V2 parameteriser for train families, teacher run, local MLX LoRA, parity and product-path measurement | **yes** | 08-5 fails the bar | **$22** |
| **08-8** | Scenario eval driver + metrics + conditions C0–C4 (C5) + committed artifacts + `phase08-eval-check` | no (spec in 08-4) | 08-5 (and 08-6/08-7 if taken) | **$30** |
| **08-9** | Multi-turn Web (`consumer_note`, Proceed, `CaseTimeline`, proxy timeout, disclosure copy) + `make portfolio-demo-model` (direct, memory, hosted Slow, the 08-5-selected local Fast) + typed journey artifact + Browser verification | light (the root approves copy) | 08-2, 08-3 (08-5 for the Fast choice); `runtime.py` writer after 08-4 | **$4** |
| **08-10** (optional) | Demo negotiation scene: Web renders `outbound_line`, Provider turns and offer revisions for a counterparty Case (direct, memory) | yes (Web predicates assume one fixed offer) | 08-4, 08-9 | $2 |
| **08-11** (root) | Docs (`ml-evidence`, `limitations`, `architecture`, README, CONTEXT), the ops-report extension, log, independent review, final gates, status idle | — | all | $0 |

Reserve **$15** holds at least one full rerun of one condition. Total accounted cap: 2 + 6 + 1 + 3 +
22 + 30 + 4 + 2 + 15 = **$85**. Accounting margin to the USD 100 real cap: **$15**. If 08-7 is not
triggered, its $22 moves to the reserve or to r = 3 repeats. Nothing is re-planned upward without a
user decision.

**Hot-file writer order:**

- `runtime.py` and `repository.py`: 08-4, then 08-9.
- `coordinator.py`: 08-2, then 08-3.
- `conversation-workspace.tsx`: 08-9, then 08-10.
- `openai_adapter/`: 08-1, then 08-2, then 08-3.

### 6.2 Gates, per PR

- Focused tests, `make lint`, `make typecheck`, `make test`.
- **Every pre-Phase-08 committed `*-check` stays byte-identical.** Any intentional move is
  regenerated explicitly with a version bump and a reason in the log (PR-13 Q3 rule).
- `make preflight` once on the stable diff.
- Any change under `case_runtime`, `agent_core` or `api` runs the serial real-dependency gates:
  `postgres-check`, then `phase05a-check`, then `phase06b1-check`. They prove the default and
  fixed-Provider paths are unchanged and that the counterparty and hosted refusals fail closed.
- The r4 frozen files show no diff (`git diff --stat` on `_R4_EXECUTION_PATHS`).
- An independent `reviewer` on 08-2, 08-3, 08-4, 08-6 and 08-9. Add `/security-review` on 08-1
  (credential handling), 08-6 (the disclosure boundary) and 08-9 (the relay-bound text).
- A ledger reconciliation line in each spending PR's log.

### 6.3 Definition of done

1. **Demo.**
   - `make portfolio-demo-model` runs in direct orchestration with memory storage, hosted Slow
     (sonnet-5) and the selected local Fast.
   - A person completes intake, Case, **at least 2 free-text turns with gate-passed model lines**,
     Proceed, approval, one execution, and a verified receipt.
   - The trace log shows hosted `role=slow`, local `role=fast` and scripted `role=judge`.
   - Browser verification is recorded, with a typed journey artifact committed.
   - If the selected Fast delivers mostly fallback lines, the demo is still honest (the fallback
     is visible and counted), but DoD item 1 is **not met** and the phase stops for a user
     decision.
2. **Eval.**
   - P0, C0–C4 (C5 if built) are committed, with `--check` in `make test` and `--rebuild-from-raw`
     working offline.
   - The report carries the claim boundaries (single machine, 11 decision rules, the R-11b
     families, accounted cost).
3. **Spend.** Ledger ≤ $85 accounted, the relay balance reconciled, and no hosted call without a
   reservation (a test pins it).
4. **Docs and gates.** Docs updated, final gates green, status idle. The limits carried forward
   are: Temporal model mode not done, hosted Judge not done, and so on.

### 6.4 Manual steps and hardware assumptions

- **Hardware:**
  - one Apple M4 Pro with 48 GB;
  - `Qwen/Qwen3-8B-MLX-bf16@6766fd4b` already in the HF cache (`HF_HUB_OFFLINE=1` enforced);
  - the 03C adapter converted (`make phase03c-mlx-adapter`);
  - the gateway is single-flight, so every local-Fast condition runs sequentially.
- **Local wall time [I]:**
  - (a) about 25 min and (b) about 55 min on the probe set;
  - C2 about 2 h and C3 about 3 h, local-Fast bound;
  - C4 under 1 h;
  - (c) training 4–10 h per epoch, unmeasured.
- **Keep the machine otherwise idle** during the latency-bearing runs, and record the load. The
  03C numbers were taken under uncontrolled load.
- **User-held manual steps:**
  - put the relay key in the git-ignored `.env` (never in a log or artifact);
  - read the relay balance before and after 08-1, 08-5, 08-7 and 08-8;
  - start the gateway (`make local-fast-gateway BACKEND=…`);
  - run the Browser demo;
  - approve the 08-6 and 08-7 decisions.

---

## 7. Risks and root decisions

### 7.1 Root decisions needed (recommendation in bold)

| # | Decision | Recommendation |
|---|---|---|
| D1 | Build the Provider Counterparty seam in `case_runtime` so the eval drives the product runtime | **Yes.** It is the only way to meet "not a separate path" (F1). Memory storage and direct only in Phase 08. |
| D2 | Hosted modes under Temporal | **No.** Direct only; recorded as not done (§2.4). |
| D3 | Scenario set | **V2 22 × 3 Case variants**; V1 unused; headline on all 22 plus the held-out 4. |
| D4 | R-11b families | **Report separately as a product limit**; no contract 1.2 (decision 21 stands). |
| D5 | Commit raw eval outputs, withheld Fast text included | **Yes** for the synthetic eval, via an eval-only recorder, with the leakage gate in `--check`. **Never** demo text. |
| D6 | Gate v2 allowing `counter` | **Decide after** the P0 ceiling and the 08-5 dossier, not now. |
| D7 | Judge | **Scripted rules-v2**; hosted Judge not built. |
| D8 | Non-accept terminal proposals in counterparty mode run without Consumer approval | **Yes** (`SEND_MESSAGE` class, not approval-required); accept keeps the approval. |
| D9 | Rubber-stamp simulated Consumer | **Yes** (worst case for harm). |
| D10 | Demo scope | **Fixed Provider by default**; the negotiation scene (08-10) is optional. |
| D11 | Web disclosure copy for relay-bound text | **Yes**, wording approved by the root. |
| D12 | Downloading a quantised MLX snapshot | **No by default.** Local quantisation from the cached bf16 is allowed if the latency bar fails. |
| D13 | "End to end" includes intake? | **No.** Intake stays deterministic and typed; Consumer-confirmed facts are the authority. A model intake is a scope expansion for the user. |
| D14 | Cloud training for (c) | **Excluded** (Modal is a credential); local MLX only. |
| D15 | Budget split and the $85 accounted cap | **As in §6.1.** |
| D16 | The `adapter_mode` label set | **As in §4.2.** |

**Product or scope questions for the user, not technical ones:** D8, D10, D11, D13. Also whether
a demo whose model lines are mostly fallback counts as "driven by real LLMs".

### 7.2 Risks

| # | Risk | Mitigation or recording |
|---|---|---|
| R1 | Relay: unknown balance and pricing; `json_schema` support for Claude unknown; model-string echo may differ; gemini JSON unproven | 08-1 probe before any design lock; `json_object` fallback; alias table; the ledger's 15 % margin |
| R2 | Fast still gate-fails, or its lines are bland. The lexical gate's completion rule refuses "no fees are applied" and similar. | Pre-registered bar, (a′) slots, (d) only on evidence, (c) as the last resort; the fallback stays honest and visible |
| R3 | Counterparty seam size and regression risk in a 2,409-line `runtime.py` plus codec coupling | Architect-first; the default adapter byte-identical; the codec refuses the new adapter; serial DB gates |
| R4 | 1.1 representability: `applied_changes`, requested facts and credit lines (R-19, B1-9b) | F3 reporting; `requested_fact_keys` stays non-canonical; the credit mapping is an architect item |
| R5 | Latency: 55 s worst case in direct mode; relay variance; B2-8 lock | Deadline plumbing; the 60 s proxy for the model demo only; descriptive latency, never p95 |
| R6 | Eval validity: 11 decision rules; hosted nondeterminism; prompt overfitting; accounted ≠ billed | Cluster bootstrap; r = 2 stability; iterate on train/dev only; ledger reconciliation |
| R7 | Judge retries spend or skew proposals | rules-v2 compliance-aware; retry counts reported; the retry fits the deadline or is skipped |
| R8 | Privacy: demo text goes to a third-party relay | Disclosure copy; demo text never committed; fictional-only copy; loopback-only demo |
| R9 | 03C comparability | The new prompt includes the Consumer's words and product-Slow strategy (closing D5 and D6), so the numbers are **not comparable** with the 03C M1/M2 numbers. The report says so; decision 18 labels are carried. |
| R10 | Gate v1 caps success on retention-gated | P0 makes this explicit before any spend; D6 |
| R11 | Local memory pressure (bf16 16 GB model + Next + API + training) | Never train while serving; one model process at a time, as today |
| R12 | Scope creep into Temporal, a model intake, a model Judge or a real Provider | Out of scope, as in §7.1; any of them needs a new user decision |

---

## 8. Files an implementer would own (by PR)

- **08-1:**
  - new `runtime/packages/openai_adapter/src/proxyloop_openai_adapter/spend_ledger.py`;
  - new `scripts/run_phase08_hosted_probe.py`;
  - rates config;
  - `.gitignore` entry for `data/spend/`;
  - Makefile targets;
  - tests;
  - `data/evaluation/phase-08/relay-probe.json`.
- **08-2:**
  - `openai_adapter/{hosted_slow.py (new), outputs.py (parameterised compile), errors.py}`;
  - `api/src/proxyloop_api/config.py`;
  - `case_runtime/runtime.py` (the `adapter_mode` Literal and inference only; coordinate with the
    08-4 writer order, or move the label inference to config);
  - `agent_core/{scripted.py (Judge rules-v2), coordinator.py (retry-limit fixes)}`;
  - tests; `docs/architecture.md`.
- **08-3:**
  - new `agent_core/fast_prompt.py`;
  - `agent_core/{disclosure_gate.py (public accessors only, no rule change), local_fast_wire.py
    (v2), coordinator.py (ContextualFastAdapter hook)}`;
  - new `runtime/packages/product_fast` (or inside `local_fast`);
  - new `ml/evaluation/src/proxyloop_evaluation/local_fast/rendered_generation.py`;
  - `local_fast/{http_server.py, identity.py}`;
  - fixtures under `tests/fixtures/local-fast-wire/`.
- **08-4:**
  - new `case_runtime/counterparty.py`;
  - `case_runtime/{runtime.py, repository.py, commands.py, turn_split.py,
    postgres_repository.py (refusal only)}`;
  - `workflow_worker/activities.py` (refusal only);
  - new `scripts/run_phase08_product_ceiling.py`;
  - `data/evaluation/phase-08/p0-product-ceiling.json`;
  - `CONTEXT.md` (Counterparty, Outbound Line).
- **08-5 / 08-8:**
  - new `scripts/run_phase08_fast_probe.py`, `scripts/run_phase08_scenario_eval.py`;
  - new `case_runtime/scenario_eval.py`;
  - `data/evaluation/phase-08/*`.
- **08-9:**
  - `api/app.py` (event type allow-list), `case_runtime/commands.py`;
  - `apps/web/{next.config.ts, lib/runtime-client.ts, app/components/conversation-workspace.tsx}`
    plus tests;
  - `scripts/run_phase_07a_portfolio_demo.py` (a model profile) or a new launcher;
  - `docs/portfolio-demo.md`.
- **Never, without a new root decision:**
  - `contracts/`;
  - the r4 `_R4_EXECUTION_PATHS`;
  - `workflow.py` (activity options);
  - the gate rules (except 08-6);
  - any committed pre-Phase-08 artifact.

## 9. Verification that would prove the design

- **P0 product ceiling (08-4), deterministic, in `make test`:**
  - every representable success instance completes under gate v2-candidate;
  - under gate v1, exactly the retention-gated success instances fail with "consumer input
    budget exhausted";
  - the 3 R-11b families show "harmful applied" under oracle adapters, which proves the limit is
    the product's, not a model's;
  - forged and absent evidence end in a valid `request_replan` through the product verifier.
- **08-5 report:** the pre-registered bar evaluated on committed raw outputs, re-derivable with
  `--rebuild-from-raw`.
- **08-8:** `phase08-eval-check` passes. Two `--check` runs are byte-identical. The leakage scan is
  clean. Ledger totals equal the report's cost fields.
- **08-9:** a Browser run on `make portfolio-demo-model` (reload is not claimed in direct mode),
  plus vitest ordering tests for `CaseTimeline`, interleaving by cursor with duplicates and gaps.
- **Every PR:** pre-Phase-08 `*-check` bytes unchanged; the r4 diff empty; serial DB gates for
  runtime changes.
