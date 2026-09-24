# PR-8 Stage 1a: Fast dialogue reaches the product — frozen spec

Status: frozen by the root orchestrator on 2026-09-24 from the `architect`
proposal below (decision 16 authority). Root answers to §8:

1. Carrier: `visible_events` `assistant_message` (actor SYSTEM); `fast` stays a
   per-command echo the Web does not read; `app.py` unchanged. **Yes.**
2. Gate v1 rule set as written (§2.2), allowed acts {clarify, challenge,
   escalate}, 600-character cap. **Yes** — false positives fail safe to the
   fallback and are measured; rule changes bump `FAST_GATE_VERSION`.
3. The fallback uses the same `assistant_message` type; the verdict lives only
   in the trace. **Yes.**
4. Scope: no free-text consumer turns in the Web in PR-8; multi-turn Web
   dialogue waits for PR-13. **Confirmed.**
5. The channel outbound body stays constant in PR-8; PR-11 decides. **Yes.**
6. Report placement `case_runtime/turn_split.py` + `scripts/` +
   `data/evaluation/fast-slow-split-scripted.json`; `fast-slow-split-check`
   runs in `make test`. **Yes.**
7. `CONTEXT.md` gains "Disclosure Gate" and "Assistant Message" in 8a (via the
   `domain-modeling` procedure), because every step updates its docs. **Now.**
8. Web label for automated lines (8b), exact copy:
   "ProxyLoop AI · automated message — it cannot accept, sign, or change
   anything without your approval."
9. (PR-9) Leaning yes: an adapter that raises or times out delivers the
   fallback with a `FAILED` trace — a deterministic per-call fallback, distinct
   from the excluded "automatic fallback under load". Decided in the PR-9 spec.

Additional binding note from the PR-7 review (M7): a repeated `create_case`
on an existing Case appends a SUCCEEDED Slow trace before `CaseConflictError`.
The turn-split report must classify such traces as unapplied attempts (§5.1),
and S1 must include that case.

Amendment, 2026-09-24 (root, decided from the PR-9 design, Q8), to §5.2. It applies
from day one so PR-9 needs no schema bump:

1. The per-turn record carries `fast_result` ∈ {"succeeded", "rejected", "failed", null}
   (null when the turn had no Fast call) and `fallback_cause` ∈ {null, "gate", "failure"}.
   "gate": the disclosure gate rejected the output and the fallback was delivered.
   "failure": reserved for PR-9, where a typed adapter failure produces a FAILED trace and
   the fallback. The aggregates include the count of each `fallback_cause`.
2. For the scripted backend `fallback_cause` is always null; "failure" never occurs.
3. The schema stays generic enough that PR-9 can add
   `--fast-backend {scripted,distilled,untuned}` without changing the scripted file's
   bytes. PR-8 does not implement the flag.

The report still contains no model text.

Amendment, 2026-09-24 (root, from the PR-13 design review), to §5.3 scenario S2.
"Create $92 → $70; the offer is non-compliant" cannot be built: intake refuses any
target below $72.00, and every intake-valid Case has a compliant offer for its
first hour. S2 (`dialogue_path`) is redefined with public runtime commands only:
create $92 → $75 at T0, then consumer events after the offer has expired (the
offer lives 60 minutes, a strategy 30), so no approval opens and the expired
strategy refreshes through Slow: +61 min (`slow_then_fast`), +62…+65 (four
`fast_only`), +92 (31 minutes after that refresh, `slow_then_fast`), +93
(`fast_only`). AC 5's intent is kept: S1 = {`slow_only`: 1, `fast_only`: 1};
S2 has ≥ 1 `slow_then_fast`; the scripted fallback rate is 0. S1 (`demo_path`)
also carries one repeated `create_case` (the M7 note), counted as an unapplied
attempt; it adds no turn.

Amendment, 2026-09-24 (root, from the PR-8a review, `harness/code_review/feat-pr8a-fast-dialogue.md`).
The gate is not merged yet, so it stays `fast-gate-v1`.

- §2.2, B1: new code `fast_gate_non_ascii_text`. Any non-ASCII character in
  Unicode category C* (format, control, private use, surrogate, unassigned),
  L* (letters), or M* (combining marks) is refused on the raw text: invisible
  characters and lookalike letters otherwise split or disguise the words the
  phrase rules look for. (The root named Cf, Co, Cs and L*; the implementation
  also refuses non-ASCII Cc, Cn and M*, which split words the same way.)
  Non-ASCII punctuation and symbols (an em dash, curly quotes) are allowed.
- §2.2, I1: `fast_gate_completion` adds {is, are, was, has been, have been}
  [now|just|already] + the existing list, and a bare consequential participle
  {accepted, approved, signed, agreed, confirmed, finalized/finalised, locked
  [it|this|that] in} with or without an auxiliary. `fast_gate_commitment` is
  first person + optional contraction ('ll, 've, 'd, 'm, 're) + optional
  auxiliary (will, have, am, are) + optional adverb {now, just, already} +
  {accept(ed), agree(d), approve(d), sign(ed), commit(ted), confirm(ed),
  switch(ed), cancel(l)ed, upgrade(d), downgrade(d), purchase(d), pay, paid,
  order(ed), lock(ed) [it|this|that] in}. Refusals such as "I can't accept
  that", "I won't accept that", "I will not accept that", "I cannot sign that"
  and "We don't agree to that" pass; the passive "That can't be accepted" is
  refused by the bare-participle rule (a safe false positive).
- §2.2, M1: `fast_gate_number_not_allowed` also covers `%` anywhere, "percent",
  "per cent", "pct", and a signed amount ("-$72", "-72") whose sign does not
  join two words.
- §2.2, M2: `fast_gate_identifier_or_link` also covers any `scheme://` and a
  scheme-less domain (a word, a dot, two or more letters); "e.g." and "i.e."
  pass.
- §5.1, M4: "the last in log order is the delivered attempt" holds within one
  process, where the Case lane and the API's direct lock serialize a Case's
  commands; across processes log order is not guaranteed, and a concurrent
  losing attempt at the same cursor can be mistaken for the delivered one (R6).
- §5.2, M3: `fast_fallback_rate` is renamed `gate_fallback_rate` = applied
  Fast turns whose line was the gate fallback / applied Fast turns.
  `fallback_cause_counts`, `calls_by_role_and_result`, and
  `fast_reject_reason_histogram` count applied turns and calls only; unapplied
  attempts are reported apart (`unapplied_model_calls`,
  `unapplied_calls_by_role_and_result`,
  `unapplied_fast_reject_reason_histogram`).

Split: 8a (runtime + gate + report) starts after PR-7 merges; 8b (Web) is
written now against the frozen event shape and merges after 8a, before PR-10
and PR-12 touch `conversation-workspace.tsx`.

---

# PR-8 design proposal — Stage 1a: Fast dialogue reaches the product (scripted, disclosure-gated, measured per turn)

Architect proposal, propose mode. Baseline `main` @ `c73f6a7`. No repository file was edited.
Tags: **[O]** observed in code (file:line) or by the probe below, **[I]** inferred, **[P]** proposed.
Binding inputs: PR-7 frozen spec (`scratchpad/specs/r12-model-trace-log-design.md`: trace log,
`list_model_traces`, `_advance` as the only `.advance(` site, I1–I11), PR-6 (`app.py` threadpool +
direct-mode lock), decisions 7, 16–20, build plan rows PR-8…PR-14 and Definition of done items 2–3.

Probe run (read-only, `scratchpad/arch-pr8/probe.py`, `uv run --project runtime --all-packages`):

```
scripted  fast.response_text = I am checking that and will update you.
          events before/after = [(1,'provider','provider_offer')] -> [..., (2,'consumer','consumer_message')]
leaky     fast.response_text = Deal accepted: your target is $61.00 and I signed you up.
          events before/after = [(1,'provider','provider_offer')] -> [..., (2,'consumer','consumer_message')]
          route = wait_for_approval  approval = True   adapter_mode = scripted
```

---

## 1. Current state

### 1.1 What "constant Fast text" means [O]

- `BOUNDED_FAST_STATUS_TEXT = "I am checking that and will update you."` (`agent_core/interfaces.py:17`).
- The only product Fast adapter is `ScriptedFastAdapter.decide` (`agent_core/scripted.py:41-71`). It returns
  `dialogue_act=CLARIFY`, `response_text=BOUNDED_FAST_STATUS_TEXT` on every turn, whatever the view holds.
  `ThinAgentRuntime` defaults to it (`case_runtime/runtime.py:217`), and so do both process entry points in
  scripted mode (`api/config.py:47-49`; `workflow_worker/activities.py:256-269`).
- Two code paths enforce the constant:
  - `validate_fast_result(..., bounded=True)` rejects anything other than the constant with
    `bounded_fast_output_violation` (`coordinator.py:458-465`). That applies only on
    `FAST_NOW_AND_SLOW_REFRESH`, which the runtime's event paths never reach
    (`runtime.py:1609-1611`, "FAST_NOW_AND_SLOW_REFRESH is unreachable here").
  - The channel path raises `ModelRuntimeError("fast")` unless `response_text == BOUNDED_FAST_STATUS_TEXT`
    (`runtime.py:458-463`). It also raises `ChannelConflictError` without send authority (`:464-467`), and the
    outbox body is hard-wired to the constant (`:470`), so the Fast text is never what is sent.
- Model mode (direct only, `config.py:52-72`; Temporal refuses it, `config.py:88-90`) passes an
  `OpenAICompatibleAdapter` as Fast. Its `response_text` is free model text of 1–4000 characters
  (`openai_adapter/outputs.py:49,128`).

### 1.2 Where Fast output is dropped or never surfaced [O]

| Path | What happens to the Fast text |
|---|---|
| `_append_event_serialized` (`runtime.py:913-926, 975-1007`) | Kept only as `CaseRuntimeState.last_fast_decision` (`:984`) and `RuntimeResult.fast_decision` (`:1004`). It is **not** recorded as a visible event: the snapshot gains only the consumer event (probe). |
| `current_result` (`runtime.py:336-356`) | Echoes `last_fast_decision` only for the APPEND_EVENT receipt that produced the current revision. A replayed receipt the Case has since moved past gets no `fast`. |
| `POST /cases/{id}/events` → `_result_payload` (`app.py:908-913`) | Emits `fast: {dialogue_act, response_text, created_at}`. **Nothing gates this text beyond pins and schema**: the probe's leaky adapter puts "Deal accepted … $61.00 … signed you up" into `fast.response_text` while the approval is created. In model mode that is a live, ungated model-text path. It is unexploited only because the Web never reads it. |
| `GET /cases/{id}` (`app.py:489-509`) | Builds a `RuntimeResult` without `fast_decision`, so the text is gone on every poll, restore, or reload. |
| Channel ingest (`runtime.py:446-470`) | The text is validated, compared to the constant, and discarded. The outbox always sends the constant. |
| Traces | The coordinator traces the Fast call (`coordinator.py:273-287`), carrying `output_ref=decision_id` and never the text. |

### 1.3 What the Web shows [O]

- `runtime-client.ts:49,64` types `snapshot.visible_events` and `fast` as `unknown`. `parsePayload`
  (`runtime-client.ts:313-363`) validates neither, and `conversation-workspace.tsx` reads neither
  (grep: no `fast` or `visible_events` reference).
- Every assistant bubble is Web-authored copy: `intakePrompt` and the literals in `submitMessage`
  (`conversation-workspace.tsx:1296-1333`), plus the TaskBrief, Progress, Offer, Approval, and Receipt
  artifacts. The eight-step wizard sends exactly one consumer event, the fixed `CONFIRMATION_EVENT`
  (`:72`, sent at `:1165-1222`). Free text after intake is refused with fixed copy (`:1318-1332`).
- Conclusion: no model output reaches any user-visible surface, and a model text path to the API exists
  ungated. A-4 / decision 7 is open.

### 1.4 Structural facts that constrain the design [O]

- **ML and evaluation consume the same coordinator methods.** `runner_v2.py:702-708` folds
  `validate_fast_result` reason codes into `failures`/`canonical`, and so do `runner_v2.py:1126`,
  `runner.py:273,787`, `run_phase_03a1_harness.py:1053-1313`, and `replay.py:151,263`.
  `project_fast_view` feeds `phase03c_prompt_set.py:300` and `phase03b_experiment.py:345`.
  `hosted-rescore-check` and `phase03c-rescore-check` re-score stored raw model outputs through the
  repository evaluator. Any new reason code in `validate_fast_result`, or any change to `project_fast_view` /
  `FastModelView` / `ScriptedFastAdapter`, can move committed bytes. [O for the call sites; I for which
  artifacts would move]
- `FastModelView` has no offers (`contracts.py:1325-1345`): goal, constraints, verified facts, strategy,
  last 8 events, latest Provider event, `pending_slow_work`, acts, and `allowed_disclosures`
  (strategy ∩ authority, `coordinator.py:356-364`).
- `allowed_disclosures` in the runtime Case = `("current_monthly_total", "required_features")`
  (`provider_simulator/episode.py:309`). The consumer's target price is **not** disclosable.
- The browser projection already carries `visible_events` with `{event_cursor, actor, event_type, content,
  occurred_at}` and drops only channel Provider events (`app.py:993-1004, 1055-1056`). `EventActor.SYSTEM`
  exists (`contracts.py:128-131`) and is already used for `approval_expired`
  (`test_phase_05a_temporal_workflow.py:728`).
- The planning basis excludes events and the event cursor (`contracts.py:910-962`), so an extra visible event
  does not invalidate the strategy.
- The API accepts only `event_type="consumer_message"` (`app.py:85`, `commands.py:43,153`).
- Any consumer event on a compliant offer creates the approval immediately (`runtime.py:928-955`): today the
  Web has exactly one consumer turn before approval.
- `_infer_adapter_mode` is an `isinstance` check (`runtime.py:2216-2218`). The probe's leaky
  `ScriptedFastAdapter` subclass reports `adapter_mode=scripted`, a pre-existing mislabel risk.

---

## 2. The disclosure gate

### 2.1 Placement: a pure `agent_core` function, invoked by an opt-in coordinator hook [P]

- New module `agent_core/disclosure_gate.py` exposes one function:

  ```python
  FAST_GATE_VERSION = "fast-gate-v1"
  def fast_disclosure_violations(
      decision: FastTurnDecision, snapshot: CaseContextSnapshot
  ) -> tuple[str, ...]:
      """Sorted unique fast_gate_* codes; () = the text may be shown. Pure, no I/O."""
  ```

- `CaseCoordinator.__init__(..., fast_gate: FastGate | None = None)`. When a gate is configured and
  `validate_fast_result` accepts, `advance` runs the gate. On a non-empty result it records the Fast audit as
  rejected with the gate codes, returns `fast_decision=None`, and sets the new
  `CoordinatorOutcome.fast_disclosure_rejected=True`. The Fast `ModelTrace` then carries `result=REJECTED`
  and the `fast_gate_*` codes.
- Only the runtime's `_coordinator()` passes `fast_gate=fast_disclosure_violations`. That is one line in
  `runtime.py`, and `_advance` (PR-7) is unchanged.

Rejected placements:

| Alternative | Why rejected |
|---|---|
| Inside `validate_fast_result` | It is the ML evaluator's validity function (§1.4). New codes change `canonical`/`failures` for stored hosted and 03C outputs, which contain numbers and "confirm"-style acts, so committed rescored artifacts move and decision 19's byte-identical rule breaks. [O call sites, I effect] |
| In `case_runtime` after the coordinator accepts | The trace would say `SUCCEEDED` for text that was withheld, which violates PR-7 I11 ("result is the coordinator's verdict"). Fixing that needs a second trace producer outside `_advance`, which breaks PR-7 I6. |
| In `app.py` at projection | Too late: the text is already persisted (`last_fast_decision`, events) and the Temporal path would bypass it. It would also touch PR-6's hot file. |
| A gate parameter on `advance(...)` | Every call site has to remember it. The constructor hook has exactly one construction site (`_coordinator`). |

Why `agent_core` and not `case_runtime`:

- The rules are pure policy over contracts, like `validate_fast_result`, and `agent_core` depends only on
  `proxyloop-contracts`.
- PR-9's parity re-measure can import the gate in `ml/evaluation` and report a gate-pass rate without importing
  the runtime.

### 2.2 What v1 checks, deterministically [P]

Normalisation first: NFKC, curly quotes → ASCII, lower-case for the phrase rules.

| Code | Rule |
|---|---|
| `fast_gate_number_not_allowed` | Every digit token (regex `[$]?\d[\d,]*(?:\.\d+)?%?`, Unicode digits included) must be in the **allowed-number set**. <br>Money set, compared in minor units after parsing "72", "72.00", "$72": \|amount\| of each current offer's `monthly_price`, `total_cost`, and every `fees[].amount`; `bill_snapshot.monthly_total` iff `"current_monthly_total"` is disclosed; `goal.target_monthly_total` iff `"target_monthly_total"` is disclosed (it is not today). <br>Integer set: each current offer's `term_months`. <br>Always rejected: any `%` token, any amount with more than 2 decimals, and any digit token matching neither set. |
| `fast_gate_number_word` | Closed list: ten…ninety, hundred, thousand, million, including hyphenated compounds. This catches "seventy-five dollars". |
| `fast_gate_date` | A month name or abbreviation followed by a digit, or an ISO date. Digits are already covered, but "December 12" with `term_months=12` would otherwise pass. |
| `fast_gate_identifier_or_link` | UUID pattern, `http`, `www.`, `@` email. |
| `fast_gate_commitment` | Closed, versioned phrase list. First-person (`i`/`we`, optional `'ll`/`will`/`have`/`am`/`are`) + {accept(ed), agree(d), approve(d), sign(ed), commit(ted), switch(ed), cancel(l)ed, upgrade, downgrade, purchase, pay, order, lock in}. Also the standalone words deal, guarantee(d/s), promise(d/s). |
| `fast_gate_completion` | {is, has been, have been, was, are} [now] + {complete(d), done, finali[sz]ed, applied, changed, switched, cancel(l)ed, activated, processed}. Also "all set" and "you're set". The structural `completion_claim.status == "candidate"` also maps here. |
| `fast_gate_authority` | "i am / i'm" + (the/a/an) + {account holder, customer, owner, subscriber}; "authori[sz]ed to". ("on behalf of" is explicitly **allowed**: it is the AI self-disclosure copy, proposal §7.) |
| `fast_gate_dialogue_act` | `dialogue_act ∉ {clarify, challenge, escalate}`. `confirm`, `close`, and `counter` are consequential in text form (root Q2). |
| `fast_gate_text_too_long` | `len(response_text) > 600`. The Fast budget is ≤ 200 output tokens (proposal §7). |

- **Allowed disclosures** = `strategy.allowed_disclosures ∩ case.delegated_authority.allowed_disclosures`,
  the same expression as `project_fast_view` (`coordinator.py:356-364`). What Fast is told it may disclose is
  exactly what the gate lets through (invariant I9).
- The gate is **addressee-agnostic and conservative**: it treats every line as if the Provider could read
  it. That is why the target price is refused even in the Web, where the consumer already knows it.
- v1 does **not** check, and records as known limits: paraphrased commitments, non-English text and non-Latin
  numerals, one…nine as words, feature or plan claims without digits ("unlimited data"), and non-numeric
  disclosure of constraints ("I won't touch device financing").
- It is a deterministic floor, not semantic safety. PR-14's Judge is advisory and cannot become authority.
  No side effect ever depends on Fast text: approvals are typed and pinned.

### 2.3 On a gate reject [P]

1. `_advance` appends the traces **before** the runtime acts (PR-7 I6): the Fast trace is `result=REJECTED`
   with `reason_codes=fast_gate_*`, and `output_ref` holds the decision id, never the text.
2. The runtime delivers the fixed fallback `FAST_FALLBACK_TEXT = BOUNDED_FAST_STATUS_TEXT` as the assistant
   line (§4). `last_fast_decision=None` and `RuntimeResult.fast_decision=None`, so the API emits no `fast`.
3. The command **is applied**: the consumer event, the approval if policy creates one, and the receipt. The
   rejected text is stored nowhere: not state, event, trace, log, or HTTP body (I4).
4. No error, no new error category, no 4xx. The content-free error rules of #82 are untouched because
   nothing new is refused.

### 2.4 Relation to the existing coordinator validation [P]

| | `validate_fast_result` (unchanged) | Disclosure gate (new) |
|---|---|---|
| Question | Is this output current and structurally permitted? (pins, case, strategy, `action_intent=None`, provenance, time, bounded) | May this validated text be shown? |
| Runs on | Every Fast call, product and ML | Product only: coordinator constructed with `fast_gate`. It runs only if validation accepted, so the two code sets never mix in one trace. |
| On failure | `ModelRuntimeError("fast")` → 409/`model_result_rejected`, no state change (unchanged) | Fallback line delivered, command applied |
| Trace | `REJECTED` + validation codes | `REJECTED` + `fast_gate_*` codes |

- The bounded `FAST_NOW_AND_SLOW_REFRESH` rule stays a stricter special case and is unreachable in the
  product event paths.
- The channel path keeps its equality check (§3.3), so a gate reject there still fails closed. Only
  non-scripted Fast could trigger that, and Temporal refuses model mode today.

---

## 3. The scripted Fast adapter

### 3.1 Design [P]

Add a new `ScriptedDialogueFastAdapter` in `agent_core/scripted.py`. `ScriptedFastAdapter` stays
byte-for-byte unchanged, because the harness, the ML runners, and every channel test depend on it.

- **Pure template selection, zero interpolation.** No snapshot text or number is ever spliced in, so the
  gate passes by construction:
  - **Latest event not consumer-authored** (Provider message, offer): `BOUNDED_FAST_STATUS_TEXT`. This
    preserves the channel invariant at `runtime.py:458-463` with no channel code change.
  - **Latest event is a consumer event:** index = number of consumer events among `recent_events` in
    `view` (capped at 8; use `pins.event_cursor` if the root prefers a pure cursor key), selecting from a
    frozen tuple `SCRIPTED_DIALOGUE_LINES` of about 4 number-free, id-free, commitment-free lines, for example:
    - "Thanks. I'm reviewing the fictional offer against your constraints now."
    - "Noted. I'll keep your required features and forbidden changes in view."
    - "Understood. Nothing changes without your explicit approval of exact terms."

    Once the tuple is exhausted, the last line repeats.
  - **`pending_slow_work`:** "I'm refreshing the plan before proposing anything."
- **Output fields.** `dialogue_act=CLARIFY`, `fact_updates=()`, `completion_claim=not_done`,
  `action_intent=None`, `created_at` = latest event time (as today),
  `decision_id=_stable_uuid4(f"scripted-dialogue-fast:{case_id}:{event_cursor}")`.
- **Identity.** `model_identity = ModelIdentity("scripted", "scripted_dialogue_fast", "dialogue-v1",
  "scripted-v1", "no-prompt")`. The report labels its backend from this.
- **Replay safety.**
  - The output is a pure function of (`case_id`, `event_cursor`, latest actor/type, consumer-event count,
    `pending_slow_work`).
  - A replayed command is deduplicated by command id before any coordinator run (`runtime.py:237-241`), so
    no second call happens. A retried *failed* command sees the same view and yields the same line.
  - Temporal replay does not re-execute activities.
- **Default.** `ThinAgentRuntime(fast=None)` becomes `ScriptedDialogueFastAdapter()`. This one change covers
  direct mode, the API scripted mode, and the Temporal worker (`activities.py:269`), matching "scripted by
  default" (DoD item 2).
- **Mode label.** `_infer_adapter_mode` must list the new class as scripted. Use an explicit
  `_SCRIPTED_FAST_TYPES` tuple; `type(fast) in ...` would also fix the subclass mislabel from §1.4, but it
  may break test subclasses (root: keep `isinstance`).

### 3.2 Committed `*-check` byte-identity [I, verifiable]

Every committed `*-check` stays byte-identical **by construction**. PR-8 does not change:

- `ScriptedFastAdapter`, `BOUNDED_FAST_STATUS_TEXT`, `validate_fast_result`, `project_fast_view`
- any contract or `FastModelView`, so there is no contracts regeneration
- `advance` behaviour with no gate (the default for every ML caller)
- the `CoordinatorOutcome` default (the new field defaults to `False`)

`phase04d-profile-check` uses `ThinAgentRuntime()` but pins only the shape and statuses, which stay 200
(`run_phase_04d_control_plane_profile.py:43-75`).

The only committed artifact PR-8 creates is new: `data/evaluation/fast-slow-split-scripted.json`.

Proof obligation in the PR log:

- `make test` passes (it includes every `*-check`).
- `git diff --stat main -- data/ contracts/ ml/` lists only the new report.
- `make phase04d-profile-check` passes once.

### 3.3 Channel path: unchanged in PR-8 [P]

- The outbound body stays the constant, the equality check stays, and no assistant event is added on channel
  ingest. The 06B1 fixtures pin the body and hash (`test_phase_06b1_workflow_worker.py:87…301`,
  `test_phase_06b1_connectors.py:77-119`) and the event count (`test_phase_06b1_temporal.py:263`).
- Model text on an outbound channel is a send under `SEND_MESSAGE` authority. That belongs to PR-11 (Fast
  under Temporal).

---

## 4. The API and Web surface

### 4.1 Carrier: `snapshot.visible_events`, not `fast` [P]

In `_append_event_serialized`, the delivered line becomes a canonical `VisibleCaseEvent`:

```
actor=SYSTEM, event_type="assistant_message", content=<gated model text | fallback>,
event_cursor=<trigger cursor>+1, occurred_at=<trigger occurred_at (runtime clock, never the model's created_at)>,
event_id=_stable_uuid(f"{case_id}:event:{cursor}:assistant_message")
```

- The event is appended **last**: after the policy/approval snapshot and after the routed `advance`, in the
  same write and at the same snapshot revision. `RouteRequest` requires the triggering event to be the
  latest visible event (`router.py:50-57`), so routing runs before the append.
- The transition receipt, `await_approval`'s intent, and the returned result use the final snapshot.
- Why this carrier:
  - It is durable across GET, poll, restore, reload, and Temporal.
  - It is multi-turn.
  - It feeds the next Fast and Slow views as real conversation.
  - It matches proposal §3 step 5.
  - It is already in the browser allow-list (`app.py:993-1004`) with no new field.
- **`app.py` needs no change**, which removes PR-8's conflict with PR-6's hot file. [O allow-list, P decision]
- `fast` stays as the transient per-command echo, with one strengthened invariant: it appears only for a
  gate-passed decision, and then `fast.response_text == ` the assistant event's `content`. The Web does not
  read it.
- `assistant_message` is reserved: `append_event` refuses it as a caller-supplied `event_type` (in-process
  callers only; the API already restricts to `consumer_message`).

### 4.2 Content-free errors and the allow-list [P]

- No new refusal, no new error category, no new response field.
- Gate reason codes live only in the trace log: never in an HTTP body, an operation record, or a log line.
  The rejected text is never logged.
- `test_browser_projection_allowlist.py`'s key sets are unchanged. Add one case asserting an assistant event
  projects with exactly the existing event keys.

### 4.3 Web (8b) [P]

- `runtime-client.ts` gains a pure `assistantLines(payload): {eventCursor: number; text: string}[]`.
  - It keeps entries with `actor === "system"`, `event_type === "assistant_message"`, a non-negative integer
    cursor, and a non-empty string content.
  - It sorts by cursor.
  - It ignores malformed entries: this is dialogue, not authority, so it does not block the Case.
- `conversation-workspace.tsx` renders them as `AssistantMessage` bubbles in a `DialogueArtifact`, as plain
  React text (no HTML), from the authoritative payload. A restored session re-renders them.
- No new fetch, no `fast` parsing, and no free-text consumer turns (root Q4).

---

## 5. Per-turn measurement

### 5.1 Definition of a turn [P]

- A **turn** is one applied Case command that appended a *triggering* visible event:
  `event_type ∈ TURN_TRIGGER_EVENT_TYPES = {"provider_offer", "consumer_message", "provider_message"}`.
  - Non-triggers: `assistant_message`, `approval_decision`, `approval_expired`, delivery-status events, and
    any other runtime-emitted type.
  - A test enumerates every event type the runtime emits across the scenarios and requires each to be
    classified, so a new type cannot silently fall through.
- The **turn key** is the trigger's `event_cursor`.
- **Joining traces.** `list_model_traces(case_id)` (PR-7) supplies the traces, joined by
  `trace.input_pins.event_cursor`. A Slow refresh and the following Fast call run on snapshots with the same
  visible events, and therefore the same cursor [O, `runtime.py:913-921, 1588-1647`].
  - Traces whose cursor is not an applied trigger are **unapplied attempts** (failed commands, CAS losers).
  - If several Fast traces share an applied cursor, the **last in log order** is the delivered attempt. This
    is sound because PR-7 I4 makes log order call order, and after a turn applies, the cursor has advanced by
    2, past the trigger and its assistant line.
  - An exact per-command join would need PR-7's optional `command_id` column. That is not needed now.

### 5.2 Per-turn classes and metrics [P]

- **Turn classes:**
  - `slow_only`: Case creation.
  - `fast_only`
  - `slow_then_fast`: a refresh on an expired or incompatible strategy, then Fast.
  - `no_model`: unused by definition, since non-trigger commands are not turns.
- **Per-turn record:** `{turn, trigger_event_type, class, slow_calls, fast_calls, fast_result, delivered:
  model|fallback|none, fast_reject_codes}`.
- **Aggregates (deterministic, committed):**
  - `turns`, `turns_by_class`
  - `fast_only_turn_share` = fast_only / turns
  - `slow_involved_turn_share` = turns with ≥ 1 Slow call / turns (the `slow_call_rate`)
  - `dialogue_turns` = turns with a Fast call
  - `fast_model_line_rate` = delivered model lines / dialogue turns
  - `fast_fallback_rate` = gate rejects / Fast calls
  - `calls_by_role_and_result`
  - `fast_reject_reason_histogram`
  - `unapplied_model_calls`
- **Measured block** (only for non-scripted backends, PR-9; recorded, not `--check`-replayed):
  - latency p50 and max per role
  - `time_to_line_ms` for `fast_only` turns vs `slow_then_fast` turns
  - tokens per role

  `time_to_line` must be reported because the runtime runs Slow **before** Fast on a refresh turn
  (`runtime.py:913-921`): the user waits for Slow. The Fast/Slow split is sequential, not duplex, and the
  report must show that rather than imply concurrency.

### 5.3 Report, target, committed file [P] (repo convention: `scripts/run_negotiation_ceiling.py:117-150`)

- **Pure computation:** `case_runtime/turn_split.py` exposes
  `fast_slow_split(traces, state) -> dict`. It is a deep module, table-testable, and reusable by PR-16's
  `ops-report`.
- **Driver:** `scripts/run_fast_slow_split_report.py --write|--check`. It runs in-process, with
  `ThinAgentRuntime(InMemoryCaseRepository(), clock=<fixed stepping clock>)` and the default scripted
  adapters. Commands go through `apply_command`, so receipts and dedup are real. Two frozen scenarios:
  - **S1 `demo_path`:** create ($92 → $75, compliant $72 offer) → confirmation consumer event → approve.
    That is 2 turns: `slow_only` + `fast_only`.
  - **S2 `dialogue_path`:** create ($92 → $70; the offer is non-compliant, so no approval) → 4 consumer
    messages at +1 min each (`fast_only`) → 1 message at +31 min (strategy expired → `slow_then_fast`) → 1 more
    (`fast_only`). This is the only runtime-reachable multi-turn shape today (§7 R4).
- **Output:** `data/evaluation/fast-slow-split-scripted.json`, canonical JSON with:
  - `schema_version: "fast-slow-split-v1"`, `fast_backend: "scripted_dialogue"`, `fast_gate_version`
  - `claim_boundary`: "scripted adapters; shares describe routing structure, not model quality or latency"
  - the per-scenario turns and aggregates, and `report_fingerprint`
  - no latency, because scripted latency is `perf_counter` noise (`runtime.py:1651`)
- **Make targets:** `make fast-slow-split-report` (`--write`) and `make fast-slow-split-check` (`--check`,
  appended to `make test`). Register the script in `PYTHON_PATHS` and the typecheck list, and the output in
  `validate_layout.py` `REQUIRED_PATHS` if that is the convention for new reports.
- **PR-9 extension:** add `--fast-backend http` and write `fast-slow-split-distilled.json` /
  `-untuned.json` as observed artifacts, integrity-checked only, never replayed. That covers DoD item 3.

---

## 6. Recommendation

### 6.1 Frozen interface sketch [P]

```python
# agent_core/disclosure_gate.py  (new)
FAST_GATE_VERSION: Final = "fast-gate-v1"
FAST_GATE_ALLOWED_ACTS: Final = frozenset({DialogueAct.CLARIFY, DialogueAct.CHALLENGE, DialogueAct.ESCALATE})
FastGate = Callable[[FastTurnDecision, CaseContextSnapshot], tuple[str, ...]]
def fast_disclosure_violations(decision: FastTurnDecision, snapshot: CaseContextSnapshot) -> tuple[str, ...]: ...

# agent_core/coordinator.py  (additive)
class CaseCoordinator:
    def __init__(self, router=None, snapshot=None, *, clock=None, monotonic=None,
                 fast_gate: FastGate | None = None) -> None: ...
@dataclass(frozen=True, slots=True)
class CoordinatorOutcome:
    ...                                   # unchanged fields
    fast_disclosure_rejected: bool = False  # validated, then withheld by the gate

# agent_core/scripted.py  (additive; ScriptedFastAdapter untouched)
SCRIPTED_DIALOGUE_LINES: Final[tuple[str, ...]]
class ScriptedDialogueFastAdapter:
    model_identity: ModelIdentity
    def decide(self, view: FastModelView) -> FastAdapterResult: ...

# case_runtime/runtime.py
ASSISTANT_MESSAGE_EVENT_TYPE: Final = "assistant_message"
FAST_FALLBACK_TEXT: Final = BOUNDED_FAST_STATUS_TEXT
def _coordinator(self, snapshot):  # + fast_gate=fast_disclosure_violations
# ThinAgentRuntime(fast=None) -> ScriptedDialogueFastAdapter()
# _append_event_serialized: fast_decision -> deliver model text; fast_disclosure_rejected -> deliver fallback;
#   else raise ModelRuntimeError("fast"); append the assistant event last, same revision.

# case_runtime/turn_split.py  (new)
TURN_TRIGGER_EVENT_TYPES: Final = frozenset({"provider_offer", "consumer_message", "provider_message"})
def fast_slow_split(traces: tuple[ModelTrace, ...], state: CaseRuntimeState) -> dict[str, object]: ...
```

```ts
// apps/web/lib/runtime-client.ts  (8b)
export type AssistantLine = { eventCursor: number; text: string };
export function assistantLines(payload: RuntimePayload): AssistantLine[];
```

### 6.2 Invariants [P]

- **I1.** Any Fast text on a user-visible surface (an `assistant_message` event, or `fast.response_text`) has
  passed `validate_fast_result` **and** the gate, or is `FAST_FALLBACK_TEXT`.
- **I2.** The gate is pure and deterministic, returning sorted unique codes. It has no I/O, clock, or model.
  Any rule change bumps `FAST_GATE_VERSION`.
- **I3.** A gate reject never fails the command. A validation reject always fails it, unchanged.
- **I4.** Gate-rejected text is persisted and emitted nowhere. Only its codes, in the trace.
- **I5.** The ML path is untouched: the default coordinator has no gate, and the listed symbols are
  unchanged. Every committed `*-check` is byte-identical.
- **I6.** Exactly one `assistant_message` per applied APPEND_EVENT. It sits at trigger cursor + 1, uses the
  trigger's time, has actor SYSTEM, and is appended last in the same write. PR-13 must preserve this.
- **I7.** The channel path is unchanged: constant body, no assistant event, the equality check stays.
- **I8.** The gate verdict lives in the Fast trace, appended by `_advance` before acting (PR-7 I6). The report
  reads only the log and the final state, and nothing on the decision path reads either (PR-7 I8).
- **I9.** Gate-allowed disclosures = strategy ∩ authority, the same as the Fast view.
- **I10.** The Web renders dialogue only from `snapshot.visible_events` (system + `assistant_message`), as
  text. It reads no `fast` and makes no new request.
- **I11.** `assistant_message` is runtime-authored only.
- **I12.** The gate reads contract fields directly and imports no status-block renderer (PR-10: the Status
  Bar must not become the Fast prompt).

### 6.3 Acceptance criteria

1. With the scripted default, every applied consumer event is followed by one `assistant_message` whose
   content is a `SCRIPTED_DIALOGUE_LINES` entry. It is visible in `GET /cases/{id}` in direct and Temporal
   mode.
2. A Fast adapter emitting an undisclosed number, a commitment, a completion claim, an authority claim, a
   forbidden act, an id or link, or over-long text gets the fallback delivered, and the command applies:
   - the Fast trace in `list_model_traces` is `REJECTED` with the matching `fast_gate_*` code;
   - `fast` is absent;
   - the rejected text appears nowhere in state, body, or logs.
3. A validation-rejected Fast (stale pins) behaves exactly as on `main`, plus its trace (PR-7).
4. The channel scenario, 06B1 fixtures, bodies, and hashes are unchanged.
5. `make fast-slow-split-check` passes, and the committed report shows S1 = {`slow_only`: 1, `fast_only`: 1}
   and S2 including ≥ 1 `slow_then_fast`, with `fast_fallback_rate` = 0 for scripted.
6. Every committed `*-check` is byte-identical (§3.2 proof obligation).
7. 8b: after the confirmation step, and after a page reload, the Web shows the assistant line as text.
8. Docs:
   - `docs/architecture.md`: the Fast section covers delivery, the gate v1 rules and their limits, and the
     sequential refresh.
   - `harness/context/audit-remediation-status.md`: §5 item 1 marked as stage 1a done (scripted only).
   - A PR log.

### 6.4 Red-first test list

**Red on `main` (write first; record the failing output):**

- **D1** `test_scripted_dialogue_line_is_a_visible_event`: after `append_event`, the snapshot has
  `(cursor+1, system, assistant_message)`. It fails on `main` (probe: no event).
- **D2** `test_gate_withholds_undisclosed_text_and_delivers_fallback`: the probe's leaky Fast through the
  direct API returns 200, no `fast`, the fallback event, the approval still created, and the trace
  `REJECTED`/`fast_gate_number_not_allowed` + `fast_gate_commitment`. It fails on `main` (the leaky text is
  in `fast`).

**Gate table** (`tests/integration/test_fast_disclosure_gate.py`, pure):

- **G1** Numbers:
  - "$72", "72.00", and "72" (offer) pass.
  - "$61", "7200", and "10%" are rejected.
  - "$92" (the bill) passes because `current_monthly_total` is disclosed; it is rejected when that disclosure
    is removed.
  - "$75" (the target) is always rejected.
- **G2** Full-width digits and number words ("seventy-five") are rejected.
- **G3** Date forms: "December 12" is rejected even with `term_months=12`.
- **G4** Commitment, completion, and authority phrases are rejected. "negotiating on behalf of the consumer"
  passes. `completion_claim=candidate` is rejected.
- **G5** The acts confirm, close, and counter are rejected; clarify, challenge, and escalate pass.
- **G6** UUID, URL, email, and a 601-character text are rejected.
- **G7** `BOUNDED_FAST_STATUS_TEXT` and every `SCRIPTED_DIALOGUE_LINES` entry pass on the S1 and S2
  snapshots.
- **G8** Determinism: repeated calls give an identical code tuple in fixed order.

**Coordinator:**

- **C1** A gate reject gives `fast_disclosure_rejected`, a `REJECTED` trace with gate codes, and
  `fast_decision=None`.
- **C2** No gate + numeric text gives an outcome equal to `main`'s (ML regression guard).
- **C3** Stale pins: the gate is not called and only validation codes appear.

**Runtime:**

- **D3** A validation reject is unchanged: `ModelRuntimeError`, a content-free 409 `model_result_rejected`,
  no state change.
- **D4** A dedup replay makes no new trace and returns the same receipt.
- **D5** Channel ingest with the default adapter keeps the constant body and adds no assistant event.
- **D6** The projection allow-list is unchanged; the assistant event carries exactly the existing keys.
- **D7** `append_event(event_type="assistant_message")` is refused.
- **D8** `adapter_mode == "scripted"` with the new default.
- **D9** PR-7's G8 guard (one `.advance(`) still holds.

**Report:**

- **S1** The pure `fast_slow_split` on synthetic traces handles classes, unapplied attempts, and
  last-Fast-wins.
- **S2** Every emitted event type is classified.
- **S3** `--check` passes, two runs are byte-identical, and there are no latency keys in the scripted file.

**Test updates:**

- `test_direct_mode_command_path.py:211` (`event_cursor == 2` → 3).
- Any other assertion that assumes the consumer event is the last event after an append. A grep found none
  besides that one; `test_phase_05a_case_runtime.py:362` reads the last event after *expiry*, which stays
  correct.

**Web (8b, vitest):**

- `assistantLines` filtering: Provider and consumer events, a wrong actor, and non-string content are all
  ignored, and order is by cursor.
- Render after `confirmConstraint` from the GET payload.
- Render on restore.
- `<script>` content renders as literal text.
- Nothing renders when there are no lines.

### 6.5 Owned files and split

- **8a, runtime + gate + report.** Starts only after PR-7 merges, because PR-7 owns `runtime.py` and
  `postgres_repository.py`. It does not touch `app.py`, so it is independent of PR-6 (the build plan's row
  lists `app.py`; this design removes it). It does not touch `postgres_repository.py`.
  - New: `agent_core/.../disclosure_gate.py`
  - Edited: `coordinator.py`, `scripted.py`, `agent_core/__init__.py`
  - Edited: `case_runtime/.../runtime.py`, plus `case_runtime/__init__.py` exports
  - New: `case_runtime/.../turn_split.py`
  - New: `scripts/run_fast_slow_split_report.py`
  - Edited: `Makefile`. PR-1 also edits it (the gated-skip pin). 8a adds no DB-gated test, so the pin is
    unaffected; merge `origin/main` after PR-1.
  - New: `data/evaluation/fast-slow-split-scripted.json`; `scripts/validate_layout.py` if required
  - Tests: new `test_fast_disclosure_gate.py`, `test_fast_dialogue_delivery.py`,
    `test_fast_slow_split_report.py`; edited `test_direct_mode_command_path.py`,
    `test_browser_projection_allowlist.py`
  - Docs: `docs/architecture.md`, `harness/context/audit-remediation-status.md`, `harness/log/<branch>.md`
- **8b, Web.** Can be written in parallel against the frozen event shape (fixtures) and merges after 8a.
  - Files: `apps/web/lib/runtime-client.ts`, `runtime-client.test.ts`, `conversation-workspace.tsx`,
    `conversation-workspace.test.tsx`
  - It is the single writer of `conversation-workspace.tsx` and must merge before PR-10 and PR-12 start on
    that file.
- **Fallback split** if 8a reviews too large:
  - 8a-i: gate + scripted adapter + delivery.
  - 8a-ii: report + Make targets + committed file. It touches no hot file, so it can run in parallel with 8b
    after 8a-i.
  - Decision 7 ("wired **with** a per-turn measurement") argues for keeping the report in the same wave, not
    for dropping it.
- **Not owned; escalate:** `app.py`, `workflow.py`, `activities.py`, `postgres_repository.py`, `contracts/`,
  `validate_fast_result`, `project_fast_view`, `ScriptedFastAdapter`, `BOUNDED_FAST_STATUS_TEXT`, and every
  committed artifact except the new report.

### 6.6 Gates

- **8a:**
  - focused pytest on the new and edited tests, plus `test_phase_04a/04b/05a_case_runtime`,
    `test_model_trace_producer`, `test_persisted_claim_and_traces`, and `test_phase_06b1_channel_runtime`
  - `make lint`, `make typecheck`, `make test` (all `*-check` byte-identical, §3.2)
  - `make phase04d-profile-check` once
  - `make preflight` once
  - the DB lane serially, because `runtime.py` changed: `postgres-check` → `phase05a-check` →
    `phase06b1-check`
  - an independent `reviewer`: the gate is a disclosure boundary, and `/security-review` as a quick scan
- **8b:**
  - `make web-check`, `make preflight`
  - Browser verification on `make portfolio-demo` (scripted): the line is visible after confirmation and
    after reload
  - `reviewer`

---

## 7. Risks

| # | Risk | Notes |
|---|---|---|
| R1 | **Lexical gate, false negatives.** | Paraphrase, other languages, and digit-free feature claims pass. Blast radius: misleading text shown; no side effect, because authority is typed. Stated as a limit in the docs. |
| R2 | **False positives.** | "I can't accept that" triggers `fast_gate_commitment`. That fails safe to the fallback, but it may make PR-9's distilled Fast mostly fallback. The report measures it (`fast_fallback_rate`, histogram); tune with a version bump, never silently. |
| R3 | **Sequential Slow-then-Fast.** | On refresh turns, time-to-line includes Slow, and `FAST_NOW_AND_SLOW_REFRESH` is unreachable. The report must not describe the split as concurrent. That is a PR-11/later architectural item, not PR-8. [O] |
| R4 | **One Web turn before approval.** | Any consumer event on a compliant offer creates the approval (`runtime.py:928-955`), so the demo shows one Fast line before approval until PR-13 lets Slow drive the intent. DoD item 2's "per-turn dialogue → … → approval" ordering therefore depends on PR-13. S2 demonstrates multi-turn at runtime level only. |
| R5 | **Event cursor shifts +1 per consumer turn.** | One known test update. The Web compares cursors only monotonically (`conversation-workspace.tsx:723`). Temporal replay is unaffected because the change is inside activities. |
| R6 | **Report join ambiguity.** | Failed attempts at a reused cursor are resolved by last-in-log; an exact join needs PR-7's optional `command_id`. It is irrelevant for scripted runs and matters for PR-9 only if validation rejects occur. |
| R7 | **Default-adapter change.** | Every `ThinAgentRuntime()` in tests changes Fast text. Observed assertions use the constant only in fakes and fixtures, not on runtime output, but expect small churn. |
| R8 | **Addressee ambiguity.** | Consumer vs Provider. The gate is conservative (it refuses the target), and scripted lines never state numbers, so the demo is unaffected. |
| R9 | **Pre-existing `adapter_mode` mislabel.** | Any `ScriptedFastAdapter` subclass reports `scripted` (probe). Not introduced by PR-8. |

## 8. Questions the root must decide

1. The carrier is `visible_events` `assistant_message`, and `fast` stays as an echo, unread by the Web and
   with `app.py` unchanged. **Recommend yes.**
2. The gate v1 rule set, especially the allowed acts {clarify, challenge, escalate} and the 600-character
   cap. **Recommend as written.**
3. How the fallback line is marked: the same `assistant_message` type (the verdict is only in the trace) or a
   distinct `assistant_fallback` the Web could label. **Recommend the same type.** This is a product
   transparency call.
4. **Product/scope:** no free-text consumer turns in the Web in PR-8; multi-turn Web dialogue waits for
   PR-13. This is a scope decision, not a technical one; the root must confirm.
5. The channel outbound body stays constant in PR-8, and PR-11 decides. **Recommend yes.**
6. Report placement: `case_runtime/turn_split.py` + `scripts/` + `data/evaluation/`, with
   `fast-slow-split-check` in `make test`. **Recommend yes.**
7. `CONTEXT.md`: add "Disclosure Gate" and "Assistant Message" now, via `domain-modeling`, or defer.
8. **Product copy** for the Web label of automated lines (AI disclosure wording).
9. For PR-9, not PR-8: should an adapter that *raises* or times out deliver the fallback with a `FAILED`
   trace? That is decision 18's "deterministic fallback", and it closes PR-7's recorded coordinator gap. It
   must stay distinct from the excluded "automatic fallback under load".
