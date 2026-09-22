# Pine AI public architecture and TalkAct — reference card (2026-09-21)

Collected by a web-only research agent at the user's request during the
repository audit, then a follow-up pass on Pine's shipped SDK repositories.
Facts are cited; inferences are marked. Nothing here is authoritative for
ProxyLoop; it is input to the audit synthesis and to later phase decisions.

## TalkAct (github.com/19PINE-AI/TalkAct)

- Research system + benchmark: a fast/slow dual-model agent that holds a
  real-time phone conversation while operating a computer (Playwright).
  Python 3.12; `anthropic`, `openai`, `google-genai`; `faster-whisper` ASR,
  `kokoro` TTS, Silero VAD; Flask hermetic task environments. MIT.
- Created 2026-07-11, last push 2026-07-19, single author Bojie Li (Pine AI
  Chief Scientist per `01.me/whoami/`). `POSITIONING.md` never mentions
  Pine AI. **Verdict: research artifact, not Pine's production stack.**
- Abstractions: Fast Agent (voice I/O, `claude-haiku-4-5` / Gemini Flash,
  ≲1 s, sentence-streamed TTS) + Slow Agent (`claude-sonnet-5`, owns the
  browser, one tool call per cycle) coupled through a `SharedState`
  blackboard: transcript, a mandatory per-step `state_summary` digest the
  slow agent emits (no extra call), action log, async fast↔slow queues
  (`@slow:` directives, `tell_user()` / `ask_user()`). Text-mode
  (LLM-simulated caller) and audio-mode evaluation; metrics = latency
  percentiles, task success, LLM-judged correctness, cost.

## Pine AI — what is public

| Item | Known | Class | Source |
|---|---|---|---|
| Planning / execution | "built its own orchestration framework" for multi-step workflows; agents retry and adjust strategy | press interview | siliconangle.com/2026/05/06/… |
| Voice pipeline | proprietary voice models claimed; hour-long calls, IVR, hold, voicemail | Pine claim (no detail) | 19pine.ai, pineclaw.com |
| Human-in-the-loop | "You approve everything before we start"; call content not stored | Pine site | 19pine.ai |
| Success verification | only aggregate self-reported stats (93 % success, avg $400/negotiation); **no method disclosed** | Pine marketing | 19pine.ai |
| Safety / disclosure | agents identify themselves as virtual assistants; "trusted execution environment"; anti-abuse soft limits | press quote | siliconangle.com |
| Evaluation | nothing from Pine; TalkAct's simulated caller + hermetic envs is the closest public evidence | inferred | TalkAct |
| Models | OpenAI + Anthropic + Google APIs for reasoning; in-house models for voice/orchestration; RL + SFT roles hiring | interview + job posts | siliconangle.com, 19pine.ai/join-us |
| Memory | no product disclosure; Bojie Li's `user-as-code` (arXiv 2606.16707, MIT) is research-adjacent | inferred | github.com/19PINE-AI/user-as-code |
| Pricing | credit-based subscription; annual plans "credits only, no percentage success fee" | Pine site (third parties still say "success-based") | 19pine.ai |

## Borrowable for ProxyLoop (ideas and patterns; no code needed)

1. Fast/Slow digest-gated bridge (`state_summary` per slow step) — compare
   against `CaseContextSnapshot` + planning-basis fingerprint; ProxyLoop's
   is stricter; the digest idea is a cheap freshness signal for Fast.
2. Non-consequential concurrent acknowledgement (`tell_user()` while slow
   works) — validates `fast_now_and_slow_refresh`, which the audit found
   unreachable in the product runtime (A-8).
3. Hermetic task-environment benchmark with hidden state and an
   LLM-simulated counterpart — pattern for the simulator's next step past
   one-round "multi-turn" (D1-9).
4. Text-mode vs audio-mode dual evaluation — for the deferred Voice seam.
5. Approval-before-consequential-action and AI self-disclosure copy — for
   the Web and any future channel.
6. Concrete voice component list (VAD → streaming ASR → LLM → streaming TTS)
   and latency data points (hosted Haiku ~1.0 s vs local Qwen3-14B ~0.59 s)
   — reference for Fast-model latency targets.

## Do not borrow

- TalkAct's browser-automation slow agent (model executes tools directly —
  ProxyLoop's invariants forbid it).
- LLM-judged correctness as a completion metric (ProxyLoop commits to
  deterministic verification).
- Unverifiable claims (proprietary voice model, TEE), pricing model,
  cross-session user memory (out of Case scope).

## Unknowns

`01.me/research/TalkAct/` is JS-rendered; `REPORT.md`, `bench/`, `envs/`,
`src/` not read in depth; no Pine engineering blog or paper exists; whether
TalkAct's design is in Pine's production stack is not stated anywhere.
Follow-up pass on `pine-voice-python`, `pine-assistant-python`,
`pine-mcp-server` requested (appended below when it returns).

## Follow-up: Pine's shipped SDKs (2026-09-21, second pass)

| SDK (pip) | Surface | Maps to ProxyLoop | Missing vs ProxyLoop |
|---|---|---|---|
| `pine-voice` (last push 2026-02-18) | `calls.create(to, name, context, objective, instructions, …)` → `CallInitiated{call_id, status}`; `calls.get`; `create_and_wait` → `CallResult{status, transcript, summary, credits_charged}` | `objective/context/instructions` ≈ flattened, untyped `ConsumerGoal` + `StrategyPacket`; `transcript` ≈ raw material for Evidence | no approval gate, no typed Evidence, no completion decision, no versioning |
| `pine-assistant` (2026-09-20) | `sessions.create/list/get`, `chat(session_id, message)` streamed, `send_message` → `received|delivered|delivery_failed`, `end_task`, `submit_form_response`, `rebuild`; states `task_finished|task_cancelled|credits_exhausted|task_paused`; events `session:message|text|form_to_user|tool_status|task_finished` | `session` ≈ weak Case; `session:form_to_user` ≈ "ask the human" | delivery receipts are transport, not Evidence; no `ApprovalRequest`, `CapabilityManifest`, `ActionIntent` |
| `pine-mcp-server` / `pine` plugin (2026-09-21, most active) | `pine_session_*`, `pine_send_message`, `pine_send_form_response`, `pine_send_auth_confirmation` (OAuth), `pine_task_start/stop`, attachments, location, reminders | `pine_task_start/stop` ≈ coarse Case phase control; `pine_send_auth_confirmation` ≈ consent, but for account linking, not a priced action | no Evidence / CompletionDecision / FactLedger / ModelTrace |

Documented flow (field names verbatim): `sessions.create` → `pine_task_start`
→ streamed `session:message|text|tool_status`, `session:form_to_user` /
`pine_send_form_response`, `pine_send_auth_confirmation` → `task_finished`
(or `task_cancelled|credits_exhausted|task_paused`); for calls
`CallResult{status, transcript, summary, credits_charged}`. **No public
field is a pre-action approval pinned to an offer/version/expiry, and no
public field is post-action evidence.** ProxyLoop's `ApprovalRequest` and
`Evidence`/`CompletionDecision` are stricter than anything Pine documents.

TalkAct `src/cuv/`: `browser.py` (Playwright compact DOM + indexed actions),
`fast_agent.py` (streaming-text voice front end, no tool round trips),
`slow_agent.py` (Claude tool use; every action tool carries a required
`state_summary`), `shared.py` (`SharedState` blackboard), `runner.py`
(conditions `duplex|duplex-blind|duplex-noask|strawman|sequential|fast-only`),
`simuser.py` (LLM-simulated caller, different model family to reduce
same-model bias), `voice/{asr,tts,vad,pipeline}.py`.

Adjustments to the borrowable list: Pine's public approval surface is
weaker than ProxyLoop's (evidence for "keep ours", not a pattern to
import); one new idea — the assistant SDK's turn-completion heuristic
("two seconds of silence after text/form/document", configurable
`turn_timeout`) for the deferred Voice seam. The `runner.py` condition
matrix (`fast-only`, `sequential`, `duplex-noask`) is the cheapest external
template for finally *measuring* the Fast/Slow split the audit found
asserted, not measured (A-4).

## Third pass — user-supplied primary sources, verified (2026-09-21)

The user supplied a synthesis with sources the first two passes missed.
Each claim was checked against the primary page; status is verbatim /
paraphrase / contradicted.

| Claim | Status | Source |
|---|---|---|
| Fast/Slow = **Talker/Reasoner**, coordinated through shared memory | paraphrase ("store the planning results in a shared memory") | 01.me/en/2025/06/agent-learn-from-experience |
| Fast stalls naturally at high-impact decision points ("Can you explain more?") so Slow can decide | paraphrase; the "$10 upgrade" figure and "REJECT/counteroffer" wording are not in the retrieved text | same |
| Fast/Slow coordination trained with SFT + RL | verbatim | same |
| A **Judge model** reviews proposed actions before sending important information or executing irreversible actions; τ-bench success 56 % → 64 % | numbers verbatim; the term "Sequential Revision" not found verbatim | same |
| Three tiers of experience memory: parameters (SFT/RL), knowledge base (RAG), procedural (generated code / workflows) | paraphrase | same |
| PreAct: compile successful GUI trajectories into state-machine programs, replay with no per-step LLM call, fall back to the agent on state mismatch, 8.5–13× faster | verbatim; **no LICENSE file** (reuse rights unknown), pushed 2026-06-17 | github.com/19PINE-AI/PreAct |
| TalkAct REPORT: single-model ("strawman") voice latency p50 10.89 s / p90 17.98 s; duplex Fast/Slow p50 0.63 s; task success 100 % vs 100 % | verbatim | TalkAct/REPORT.md |
| TalkAct has a `bridge.py` | **contradicted** — coupling module is `src/cuv/shared.py` | TalkAct git tree |
| Production voice is full-duplex streaming; the agent hears its own speech to manage the floor (stop / continue / backchannel); production path = recognition + conversational + reasoning + synthesis models; "Fast thinking keeps the conversation moving. Slow thinking gets the job done."; models not fine-tuned for the benchmark | verbatim | 19pine.ai/blog/pine-takes-no-1-on-taubench-voice-leaderboard |
| Architecture in production since early 2025 | verbatim | 19pine.ai/blog/pine-ai-the-most-natural-human-computer-interface-is-your-voice |
| Tasks run for minutes, hours, or days; multiple agents run simultaneously | verbatim | 19pine.ai/blog/pine-launches-message-gateway |
| ai-agent-book ch. 2 "Agent Status Bar": deterministic code maintains a status block injected at the end of context, compensating for the model's inability to summarise implicit state | verbatim; chapters 2 Context Engineering, 6 Interaction, 7 Evaluation, 8 Post-Training, 9 Continuous Evolution, 10 Multi-Agent | github.com/bojieli/ai-agent-book |
| pine-voice-js request fields `to/name/context/objective/instructions/caller/voice` | verified; **`maxDuration` is `maxDurationMinutes`** | github.com/19PINE-AI/pine-voice-js |
| Stanley Wei: trains own voice model on own call data; tasks combine phone + email + chatbot + computer use + forms + human confirmation | paraphrase from a rough auto-transcript | podcast.futureventures.ca (FV podcast e37) |

### What this changes for ProxyLoop

1. **Judge before the deterministic gate.** Pine's Judge is an LLM
   reviewing an LLM; ProxyLoop's `offer_policy` + version-bound approval +
   executor is deterministic authority Pine does not document. The right
   composition is Slow proposal → Judge (quality: incomplete search,
   arithmetic, premature give-up) → retry → deterministic policy/approval.
   The Judge must never enter evaluation metrics (D2-1 shows what happens
   when the label function reaches the model).
2. **Agent Status Bar is what `CaseContextSnapshot` already is.** The audit
   found the deterministic state exists and the model never receives it in
   usable form (B1-N6: a three-sentence system prompt plus a JSON dump).
   Rendering the snapshot as a status block is the cheapest prompt fix.
3. **Experience memory and PreAct are later, gated stages.** `CONTEXT.md`
   scopes state to the Case; and the simulator's "multi-turn" is one round
   that ignores the consumer message (D1-9), so there are no trajectories
   worth learning from yet. PreAct additionally has no licence.
4. **A frontier-only V0 (no training) is consistent with the 03C contract's
   `GO_PROMPT_ONLY` outcome** and with the audit: the runtime cannot host it
   until the P0 fixes (B2-1/C-1 recovery, B2-3 Slow refresh, B1-3/B1-4
   capability id and hash, E-1/E-2 error surfacing) land.
5. **Measure the Fast/Slow split with TalkAct's condition matrix**
   (`fast-only | sequential | duplex`, `runner.py`) — the audit found the
   split asserted, not measured (A-4).
