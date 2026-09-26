# ProxyLoop v3: Architecture

Legend:
- **[O]** observed in source (file:line; TalkAct paths are relative to `external/pine-ai-tasks/repos/TalkAct/`, v0 paths are relative to the repo at `514fe31`);
- **[E]** estimate or unverified (a named task verifies it);
- **[P]** proposed design (the default everywhere else).

Stage names S0–S5 refer to `PLAN.md` §1. "Contract" means the files under `src/proxyloop/contract/`, frozen by S0-CON-01 and changed only through the root (PLAN §0.3).

## 0. Changes from v2

| # | Area | v2 | v3 | Why (source) |
|---|---|---|---|---|
| C1 | Shared state | one `digest` + `action_log`, visible in both Fast views; free-text `GUIDE.say_hint` | `PublicState` / `PrivateState`. Slow writes `public_summary` (declassified) and `private_summary`. GUIDE = enum + slot refs. `FastView[cp]` reads public state only | GPT-6 Pro #2; decisions-v3 C |
| C2 | Slow's inputs | SlowView = both raw transcripts | **relay-only** SlowView (`[USER CHAT]`/`[REP CALL]` notes from typed relays). Raw transcripts only in the `raw_transcript` ablation | GPT-6 Pro #6; TalkAct `slow_agent.py:11,145-146` [O] |
| C3 | Read-back | `readback_confirmed` = "all numbers occur in an utterance" | **read-back slots** (field, value, unit, role, source span, status), required fields per offer, and a binding to account/principal/purpose/epoch | GPT-6 Pro #3 |
| C4 | Stale authority | none | **authority epochs**, an ingress **fence** on user-lane input, per-lane generation ids and acks, **release-time revalidation** in the Speaker, one-use **capabilities** | GPT-6 Pro #4 |
| C5 | Idempotency | `hash(run_id, authority_seq)` (V3) | durable **business-action id** minted in S1 from case + offer revision + terms hash + authority source | GPT-6 Pro systems |
| C6 | No-deal | verifier used the hidden ladder ("no reachable in-mandate offer") | **non-omniscient** verifier over agent-observable evidence; the hidden-ladder oracle is a metric only | GPT-6 Pro eval |
| C7 | User lane | patience, strikes, give-up | **async chat**: no patience clock; latency measured, never failed | decisions-v3 C |
| C8 | Teacher clock | `teacher_dilated` | **wall clock only**; offline relabelling of student states | GPT-6 Pro #5 |
| C9 | Event envelope | `cause_seq` (one parent), span ids in the envelope | `pl.event/2` with `event_id`, `cause_ids[]` and `epoch`; spans derived by the exporter | provenance (decisions-v3 D) |
| C10 | Evidence | request ids + distinct-utterance ratio ≥ 0.9 | **provenance chain** (response → parse → state → heard) + mutation tests + dead-endpoint abort | GPT-6 Pro process |
| C11 | Serving | `--enable-prefix-caching` on; greedy challenge-set hashes; hash of the safetensors index | `--language-model-only`, thinking off, **prefix caching off** (measured only, `--mamba-cache-mode align` is experimental), **per-shard sha256**, no greedy-hash attestation | GPT-6 Pro Qwen3.5 findings |
| C12 | Local serving | `vllm-metal` spike in M0 | **one pinned CUDA configuration**; Metal deferred (optional, S5+) | decisions-v3 A |
| C13 | Portal | V1, generic `click` could submit | **S4**, a capability-mediated transaction endpoint; `submit` needs a one-use token | GPT-6 Pro #1 |
| C14 | Disclosure | none | deterministic AI-disclosure `speak.verbatim` at `chan.opened(cp)`; no fabricated quotes; cancel lever needs user authorisation | decisions-v3 C |
| C15 | Approval endpoint | "web API endpoint" | case-scoped, 127.0.0.1 only, CSRF double-submit, Origin check, single-use, bound to (approval id, terms hash, epoch) | decisions-v3 C |
| C16 | Contract ownership | frozen interfaces spread over V1-01…07 | one package `src/proxyloop/contract/`, frozen in **S0-CON-01**, root-owned; change = ADR + `make pull-through` | decisions-v3 B |
| C17 | Context budget | training drops samples over 6,144 tokens | **shared renderer budget** (deterministic transcript trimming) applied identically in data, training and serving | GPT-6 Pro training |
| C18 | Topologies | `sequential`, `single`, `fast_only` in V1 | only `duplex` until S3. S3 adds the ablation flags; `fast_only` arrives with PrincipalBench in S4 | scope |
| C19 | TalkAct profile | `talkact_v1` + P6/P7 in M0/V1 | added in **S4-CON-01**, before any data that feeds TalkAct rows | debate B §7 |
| C20 | Web | Next.js | React + TypeScript SPA (Vite) served statically by `serve.api`; no server rendering is needed | size |

---

## 1. System picture

```
 principal (web chat / CLI / SimUser, async)                 counterparty (SimRep / human rep page, real time)
      │ user.msg ─┐  approval POST (CSRF, epoch-bound)                          │ utt.final(cp)
      ▼           ▼                                                             ▼
┌──────────────────────────── run_session(cfg, task): one asyncio TaskGroup per session ──────────────────────────────┐
│ Ingress ─► FENCE.raise(user msg) ─► Bus.emit ─► EventLog (events.jsonl, single writer, cause_ids) ─► fold ─► Blackboard│
│                                                                                            ┌── PublicState ──┐        │
│                                                                                            └── PrivateState ─┘        │
│  view_user(bb) = public + private + user transcript          view_cp(bb) = public + cp transcript ONLY                │
│        ▼                                                             ▼                                                │
│  FastLane[user] ─render─► vLLM Qwen3.5-9B (+LoRA)  ◄── same process ──  FastLane[cp] ─render─► vLLM                   │
│  chat msg ─► Speaker[user] (no speech clock)                         sentences ─► Speaker[cp] (speech clock, barge-in)│
│  @slow: fact/correction/request/revoke ─► f2s.msg                    @slow: fact / @hold ─► f2s.msg                   │
│                         ╲                                                  ╱                                          │
│                          ▼        view_slow(bb, relay_only): relays, guard results, status bar (no transcripts)       │
│                   SlowLoop (claude-sonnet-5; one step in flight; wakes coalesced)                                     │
│                   tools ─► Guard (pure) ─► action.authorized + Capability ─► speak.verbatim(queued)                   │
│                   writes public_summary (declassified) / private_summary; GUIDE(enum, slots); ASK/TELL_USER           │
│  Speaker release gate: revalidate(epoch, fence, TTL at end-of-speech, terms_hash, capability) ─► released | revoked  │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
 World (stream=world; agent views never read it): RepEar(Flash) → RepPolicy(deterministic, hidden ladder) → RepMouth(Flash)
                                                  SimUser(Flash, hidden profile, async reply delay) + deterministic Approver
                                                  ConfirmationLedger (evidence)  │  Portal with capability endpoint (S4)
```

**Why two lanes [P, unchanged from v2].** A single mixed context would hold the principal's bounds while talking to the rep, which makes loyalty a matter of model discretion (PrincipalBench's setting: the agent gets the full briefing [O `principal-loyalty/src/agent.py:1-15`]). With two lanes, the cp generation never *holds* the bounds, so leakage through Fast is structurally impossible.

What v2 missed: Slow could still launder a private bound through the shared digest. v3 closes the field-level path (C1) and measures the semantic path (EVAL §7, `public_summary` screening).

---

## 2. Module map and interfaces

| Module | Lane | Interface (everything a caller must know) | Hides |
|---|---|---|---|
| `contract.events` | CON | `Event` (`pl.event/2`, §4), `EVENT_TYPES` registry, `event_id = f"{run_id}:{seq}"` | nothing (types) |
| `contract.state` | CON | `Blackboard`, `PublicState`, `PrivateState`, `OfferPublic`, `ReadbackSlot`, `Mandate`, `ApprovalCard`, `Capability`, `CaseStatus` | nothing (types) |
| `contract.views` | CON | `view_user(bb, trigger, brief)`, `view_cp(bb, trigger, brief)`, `view_slow(bb, mode, brief)` → `FastView`/`SlowView`. Pure allow-list builders; `brief` is the task's brief for that view (task data, not state). Invariant: `view_cp` depends only on `bb.public`, `bb.channels["cp"]`, the trigger and the public brief | field selection, windowing |
| `contract.messages` | CON | `FastToSlow`, `SlowToFast`, `Guide(move, slots)`, `GuideMove`, `SlotRef` | nothing |
| `contract.protocol` | CON | `render_messages(view, profile)`, `render_prompt(view, profile, tok)`, `StreamParser.feed/close`, `format_turn`, `fingerprint(profile)`, `CONTEXT_BUDGET_CHARS`. Invariants: `parse(format(t)) == t`; streaming parse == batch parse | prompt text, grammar, trimming |
| `contract.llm` | CON | `LLMClient` protocol (`stream_text`, `chat_tools`), `ModelRef`, `TextRequest`, `ToolRequest`, `LLMCallRecord`, `AdapterKind`, `LLMUnavailable` | nothing |
| `contract.config` | CON | `SessionConfig`, `AblationId`, `SlowViewMode`, `WorldModels`. `SessionConfig.teacher` is set iff a `teacher_repair_*` ablation is; with `live=True` no role may be `test_fake` or `recorded_replay`, and `baseline` only on the Fast roles | nothing |
| `contract.bundle` | CON | bundle layout, `Manifest` (`pl.bundle/1`), `read_bundle(path) -> Bundle` | file IO |
| `core` | SYS | `EventLog.append(e) -> Event`; `Bus.emit/subscribe`; `fold(events) -> Blackboard`; `apply(bb, e)` | JSONL IO, fsync, reducers |
| `kernel` | SYS | `run_session(cfg, task, channels=None) -> RunResult` (**the only entry point**); `Channel` protocol (`send`, `stop`, `events`) | lanes, fence, Speaker, watchdog, triggers |
| `slow` | SYS | `SlowLoop.run()`; `TOOLS` (§8) | prompt, context, wake coalescing |
| `guard` | SYS | `authorize(bb, intent) -> Authorization \| Denial`; `revalidate(bb, capability, t_release_end) -> ok \| reason`; `readback_status(offer, cp_utts)`; `declassify(text, bb) -> ok \| violations`; `verify_completion(bb)`; `verify_no_deal(bb)`; `terms_hash`; `business_action_id`. Pure, synchronous, < 1 ms [E] | policy, bindings, slot grounding |
| `llm` | SYS | `client_for(ref) -> LLMClient` (real_http vLLM completions; relay chat and tools); `SpendLedger`; `check_parity(ref, prompts)` (P3) | HTTP, retries (≤ 1, recorded), `/tokenize` |
| `env` | SYS | `SimRep.on_agent_utterance(utt_heard)`; `SimRep.tick(t)`; `SimUser.on_agent_message(msg)`; `Approver.decide(card)`; `Ledger.lookup(id)`; task loader | Ear, ladder, Mouth, fidelity, TTL, reply delays |
| `evidence` | SYS | `evidence_check(bundle, mode=claim\|offline) -> Report` (provenance chain, attestation, reality report) | chain walking |
| `obs` | SYS | `OTelExporter(bus)`; failures are isolated from the session | span mapping |
| `serve` | SYS | FastAPI: `/ws/live/{case}`, `/api/replay/{run}`, `POST /api/cases/{case}/approvals/{id}` | CSRF, auth, streaming |
| `models` | MOD | `registry.resolve(name) -> ModelRef`; `FsmTalker` and `TeacherRepair` (both implement `LLMClient`, adapter kind `baseline`/composite) | conditions, decision-point detection |
| `training` | MOD | `build_dataset(bundles, spec) -> Manifest`; `verify_trained_span(ids, labels, tok, expected)` (P5); `relabel(bundles, teacher) -> rows`; `pull_through(mode)` | filters, mixture, Modal jobs |
| `eval` | MOD | `metrics(bundle) -> dict`; `run_matrix(spec) -> [RunResult]`; `compare(bundles, spec) -> Report` (`pl.report/1`); `external.talkact`, `external.principal` | pairing, interleaving, bootstrap |
| `serving/` (outside `src`) | MOD | Modal app: vLLM OpenAI API + `GET /pl/attest` (shard hashes) + LoRA slots | vLLM flags, volumes |

**Dependency rules (import-linter in CI):**
- `contract` imports only the standard library and pydantic. `render_prompt` takes the tokenizer as an argument (duck-typed `apply_chat_template`), so the tokenizer is a test and runtime dependency, not a contract import.
- `env` never imports agent modules (`kernel`, `slow`, `guard`, `contract.views`). Agent modules never import `env`. Only `kernel.session` wires the two together.
- The `fast` role code (`kernel.lanes`) never imports `guard`.
- Nothing under `src/` imports `tests`.
- `training` and `eval` import `contract.protocol`; they never re-implement prompt text.
- `serve` never imports `contract.protocol`: the web never re-renders a prompt.

---

## 3. Repo layout [P]

```
proxyloop/
├── README.md NORTH_STAR.md PLAN.md AGENTS.md CLAUDE.md LICENSE Makefile pyproject.toml uv.lock
├── mk/                 sys.mk (SYS-owned targets)  mod.mk (MOD-owned targets)   # included by Makefile
├── src/proxyloop/
│   ├── contract/       events.py state.py views.py messages.py protocol.py llm.py config.py bundle.py profiles/{pl_user_v1,pl_cp_v1}.py
│   ├── core/           log.py bus.py fold.py clock.py
│   ├── kernel/         session.py lanes.py speaker.py fence.py channels.py watchdog.py
│   ├── slow/           loop.py tools.py prompt.py            (browser.py in S4)
│   ├── guard/          terms.py policy.py readback.py mandate.py authorize.py capability.py declass.py verify.py status.py
│   ├── llm/            factory.py vllm.py relay.py spend.py parity.py
│   ├── env/            tasks/{schema,loader}.py counterparty/{policy,ear,mouth}.py user/{simuser,approver}.py ledger.py splits.py (portal/ in S4)
│   ├── evidence/       check.py chain.py reality.py
│   ├── obs/            otel.py
│   ├── serve/          api.py csrf.py
│   ├── cli.py          chat / smoke-live / replay (terminal)
│   ├── models/         registry.py fsm.py repair.py conditions.yaml
│   ├── training/       dataset.py masking.py filters.py relabel.py mixture.py pull_through.py export.py
│   └── eval/           metrics.py stats.py matrix.py report.py ablations.py external/{talkact,principal}.py
├── serving/            modal_vllm.py attest.py            (MOD)
├── training_jobs/      modal_train.py sft.py              (MOD; runs on Modal)
├── apps/web/           React + TS (Vite): live + replay, one component tree (SYS)
├── tasks/families/*.yaml   tasks/splits/{pilot_lock.json, split.lock.json}
├── third_party/        licences, pins, small task specs, golden fixtures (S4)
├── evidence/<stage>/<run_id>/   committed claim bundles (root)
├── docs/               decisions/ results/ claims.yaml limitations.yaml figures/ media/ v0-retrospective.md …
├── tests/              support/{fakes.py, recorded.py, manual_clock.py}  contract/ golden/ core/ kernel/ concurrency/ guard/ …
└── external/           git-ignored clones at pinned commits
```

---

## 4. Events

### 4.1 Envelope (`schema = "pl.event/2"`, frozen in S0-CON-01)
```json
{"schema":"pl.event/2","run_id":"01J9…","seq":42,"event_id":"01J9…:42","t_ms":18234,"wall":"2026-…Z",
 "type":"fast.turn","actor":"fast.cp","stream":"agent|world|ops","cause_ids":["01J9…:39","01J9…:41"],
 "epoch":3,"payload":{…}}
```
- `t_ms` is the kernel wall clock: monotonic ms since `session.started`. There is no dilated mode (C8).
- `cause_ids` is required for every derived event (the table below lists the causes), and may be empty only for exogenous ingress: `utt.final`, `user.msg`, `approval.post`, `session.started` and timers.
- `epoch` is the authority epoch at emission (§9.4).
- `actor` is one of `fast.user`, `fast.cp`, `slow`, `guard`, `kernel`, `ui`, `sim_approver`, `world.ear`, `world.policy`, `world.mouth`, `world.simuser`, `world.ledger`. Fixed emitters: `approval.post` ← `ui` or `sim_approver`; `approval.decided`, `mandate.decided` ← `kernel`, each citing the one `approval.post` it decides (same subject, id, decision, `by` = the post's actor, and for a mandate the hash), and each (subject, subject id, subject hash) decided once; `user.msg`, `utt.final`, `utt.delivered`, `chan.opened`, `speak.released` ← `kernel` (the Speaker emits `speak.released` after `guard.revalidate`); `authority.fence`, `authority.epoch` ← `kernel` or `guard`; `mandate.proposed`, `approval.requested`, `action.authorized`, `speak.verbatim`, `screen.redacted`, `evidence.recorded`, `offer.recorded`, `readback.updated`, `summary.updated`, `completion.decided`, `status.changed` ← `guard` (Slow's tool effects are `guard` events). Restrict-only types (`action.denied`, `speak.revoked`, `declass.denied`) and `fact.recorded` accept any actor. No `fast.*`, `slow` or `world.*` actor emits a restricted type. The `world` stream carries exactly the events of `world.*` actors.
- `stream=world` events are written by world actors through the same bus. The reducers put them into a `WorldShadow` that no view reads (enforced by `contract.views` taking only agent fields).

### 4.2 Event types (the S0–S1 set is complete; additions go through the root with an ADR)
| Group | Types (cause_ids in brackets) |
|---|---|
| ops | `session.started{cfg_hash, task_ref, instance_hash, split, models, renderer_fp, contract_version, git_sha, attest, parity}`; `session.ended{reason}`; `spend.charged`; `parity.checked`; `attest.recorded` |
| llm | `llm.call{call_id, role, model_ref, requested_model, served_model_echo, request_id, adapter_kind, prompt_sha, response_sha, usage, t_start, t_first_token, t_end, finish_reason, attempt, error}` (one per HTTP attempt) [the request event] |
| channel | `user.msg{text}` (user lane ingress); `utt.final{lane:cp, speaker:partner, utt_id, text}`; `utt.delivered{lane, utt_id, text_generated, text_heard, interrupted}` [`fast.sentence` or `speak.released`]; `chan.opened/closed`; `chan.hold`; `chan.strike` (cp only); `chan.barge_in` |
| fast | `fast.request{lane, gen_id, trigger, view_sha, prompt_sha, profile, model_ref, basis_seq}` [trigger]; `fast.turn{lane, gen_id, call_id, items[], ttft_ms, ttfs_ms}` [`fast.request`, `llm.call`]; `fast.sentence{lane, gen_id, utt_id, text}` [`fast.turn`]; `fast.cancelled{gen_id, reason}` |
| bridge | `f2s.msg{FastToSlow}` [`fast.turn`]; `s2f.msg{SlowToFast}` [`slow.tool`]; `s2f.voiced{msg_id, gen_id}` [`fast.turn`] |
| slow | `slow.step.started{basis_seq, wake_reasons}`; `slow.step.completed{basis_seq}`; `slow.tool{name, args, result_text, ok}` [`llm.call`, consumed `f2s.msg` ids] |
| state | `summary.updated{scope: public\|private, text}` [`slow.tool`]; `declass.denied{violations}` [`slow.tool`]; `fact.recorded`; `offer.recorded{offer_ref, revision, slots, terms_hash}`; `readback.updated{offer_ref, slot_statuses}` [`utt.final`] |
| authority | `authority.fence{op: raised\|cleared, fence_id, utt_id}`; `authority.epoch{new, reason: mandate_decided\|slow_revoke\|tighten_mandate\|f2s_revoke}`; `mandate.proposed{Mandate}`; `mandate.decided{mandate_id, mandate_hash, decision, by: ui\|sim_approver}`; `approval.requested{ApprovalCard}`; `approval.post{subject: approval\|mandate, subject_id, decision, subject_hash, authority_epoch}` (ingress; `subject_hash` is the card's `terms_hash` or the `mandate_hash`); `approval.decided{approval_id, decision, by: ui\|sim_approver}` [`approval.post`]; `action.authorized{intent, capability}`; `action.denied{intent, reason}`; `speak.verbatim{lane, kind: disclosure\|readback_request\|accept\|decline, text, cap_id?}`; `speak.released`/`speak.revoked{reason}`; `screen.redacted`; `evidence.recorded`; `status.changed{previous, status}`; `completion.decided{verdict, reasons}`. These authority payloads, `approval.*` and `llm.call` are validated through typed models |
| world | `rep.ear{utt_id, act, args, call_id}`; `rep.policy{from, to, intent, rung}`; `rep.mouth{intent, text, fidelity_ok, attempts}`; `rep.commit_heard{utt_id, offer_ref}`; `ledger.write{confirmation_id, binding}`; `user.sim{text, revealed{key: value}, delay_s}` |

### 4.3 The provenance chain (what `evidence-check` walks)
```
llm.call(request_id, response_sha) ─► fast.turn(items) ─► fast.sentence ─► utt.delivered(text_heard)          "said and heard"
                                               └────────► f2s.msg ─► slow.tool (consumes f2s) ─► summary.updated / offer.recorded
                                                                        ─► fast.request(view_sha includes it) ─► … ─► utt.delivered   "relayed and used"
```
- An agent `utt.delivered` without a chain to an `llm.call` with `adapter_kind=real_http` or a Guard `speak.verbatim` fails the check.
- `prompts.jsonl` stores the text of every prompt and response keyed by sha. The check recomputes both shas.

---

## 5. Blackboard: public and private state [P; C1]

```python
@dataclass(frozen=True)
class PublicState:                      # everything FastView[cp] may see
    summary: str                        # Slow-written; passes declassify()
    facts: Mapping[str, PublicFact]     # PublicFact{key, value, source: "cp_utt"|"shareable", source_ref}
    offers: Mapping[str, OfferPublic]   # §9.2
    guidance_cp: tuple[Guide, ...]      # last 3; enum + slot refs only
    action_log: tuple[str, ...]         # last 12; value-free templates from tool names ("recorded an offer")
    status: CaseStatus
    cp_hold: HoldState | None

@dataclass(frozen=True)
class PrivateState:                     # principal-facing; never in FastView[cp]
    summary: str                        # Slow-written principal summary (TalkAct digest analogue)
    case_facts: Mapping[str, Fact]      # user-provided, incl. protected (PIN) and constraints
    mandate: Mandate | None
    pending_approval: ApprovalCard | None
    approvals: Mapping[str, Approval]

@dataclass(frozen=True)
class Blackboard:
    seq: int; t_ms: int; epoch: int; fences: tuple[Fence, ...]
    public: PublicState; private: PrivateState
    channels: Mapping[Lane, ChannelState]               # user: messages; cp: transcript (text_heard), floor, strikes
    f2s_pending: tuple[FastToSlow, ...]; s2f_pending: Mapping[Lane, tuple[SlowToFast, ...]]
    authorizations: tuple[Authorization, ...]; capabilities: Mapping[str, Capability]
    evidence: tuple[Evidence, ...]; completion: CompletionDecision | None; spend: Spend
```

### Views (allow-lists)
| Field | `FastView[user]` | `FastView[cp]` | `SlowView` (`relay_only`) |
|---|---|---|---|
| brief | `fast_brief_user` | `fast_brief_cp` (public) | `slow_brief` |
| summaries | private + public | **public only** | both (Slow wrote them) |
| action log | yes | yes (value-free) | its own tool history |
| offers | public offers + pending approval card | public offers (slots, status, expiry) | full, with Guard results |
| guidance | – | rendered `Guide` (slots resolved from public state only) | – |
| mandate / protected facts / constraints | via private summary and case facts | **never** | yes |
| transcript | user lane, trimmed by the budget | cp lane, trimmed by the budget | **none** (`raw_transcript` ablation adds both) |
| relays | – | – | `[USER CHAT] …` / `[REP CALL] …` notes with `utt_ref` |
| status | `CASE STATUS` | `CASE STATUS` | status bar (offers, approvals, hold, TTLs, fences, epoch) |

### Declassification (`guard.declass`)
A write into public state (`public_summary`, a `PublicFact`, a guide slot) is accepted only if:
- every number in it is **source-bound**: it equals a value in a cp `utt.final` (normalised to minor units, months or digits), or the value of an allow-listed shareable fact from `task.disclosure.shareable`;
- it contains no protected value (PIN, full account number) and no mandate bound unless that same value is already public;
- it is at most 400 characters.

On failure the public state is unchanged, `declass.denied{violations}` is emitted, and the tool result tells Slow why. Non-numeric semantic leakage (for example "they'd accept a 24-month term") cannot be caught lexically. It is **measured** as cp-lane leakage (EVAL §7) and counted in `declass` metrics, not claimed as blocked.

### Tests (S0-CON-01)
- **Private-value counterfactual (property):** for random blackboards, perturbing any field of `PrivateState` leaves `render_messages(view_cp(bb, t), "pl_cp_v1")` byte-identical.
- **Allow-list:** no protected value or mandate number appears in any `FastView[cp]` fixture.
- **Speech screen exemption:** a value that is simultaneously a private bound and a public offer (`$65`) is speakable.

---

## 6. Fast protocol (contract; TalkAct-compatible grammar)

### 6.1 What TalkAct's Fast contract is [O]
- **System prompt:** `SYSTEM` [O `src/cuv/fast_agent.py:21-44`].
- **User message:** sections joined by blank lines [O `fast_agent.py:79-91`]:
  - `TASK CONTEXT`
  - `COMPUTER AGENT STATE SUMMARY`
  - `COMPUTER AGENT RECENT ACTIONS`
  - optional `…REPORTS TASK FINISHED`
  - `CONVERSATION SO FAR` (last 40 lines [O `shared.py:62-64`])
  - `TRIGGER`
  - `Respond now per the output format.`
- **Parser:** line-based. It extracts inline `@slow:`, treats a line starting with `@end_call` as hang-up, and strips `FIRST:`/`THEN:` [O `fast_agent.py:168-191`].
- **Local path:** `/v1/chat/completions`, `max_tokens=400`, with `enable_thinking=false` only if the served name contains `Qwen3` [O `fast_agent.py:131-155`].
- **Extensions:** `@wait` and `@hold` do not exist in TalkAct; they are ours.

### 6.2 Grammar (strict superset; frozen in S0-CON-01)
```
<spoken>            0–3 short sentences first; may be empty only if a directive follows
@slow: <text>                           TalkAct relay (free text) → FastToSlow NOTE
@slow: fact <key>=<value>[; …]          typed relay → USER_UPDATE (user lane) | CP_UPDATE (cp lane)
@slow: correction <key>=<value>         user lane → USER_UPDATE{correction}
@slow: request <text>                   user lane → REQUEST
@slow: revoke <text>                    user lane → REVOKE (the user said stop / changed their mind; restricts authority, §9.4)
@hold <offer|decision|fact_request|pressure|unclear>    cp lane only
@wait                                   deliberately silent
@end_call                               honoured only in terminal statuses or after GUIDE close_call
```
- The canonical order is speech, `@slow:` lines, at most one `@hold`/`@wait`, then optionally `@end_call`. The parser is tolerant on input (TalkAct's inline `@slow:` and scaffolding echoes) and canonical on output; training labels are always canonical.
- A directive on the wrong lane (for example `@hold` on the user lane) is dropped and counted as `directive_error`.
- Fast has no accept, share or commit directive.

### 6.3 Profiles (one renderer, two data profiles in S0; `talkact_v1` added in S4)
| Profile | Lane | System | Sections (in order) | Triggers |
|---|---|---|---|---|
| `pl_user_v1` | user (async chat) | TalkAct `SYSTEM` adapted to **app chat**: "You are the chat voice of a personal assistant app…", plus the extensions paragraph (typed relays, `revoke`, "claim done only if CASE STATUS is VERIFIED_COMPLETE", "never approve anything yourself; approvals happen on the card") | `TASK CONTEXT`, `CASE AGENT SUMMARY` (private), `SHARED CALL SUMMARY` (public), `CASE AGENT RECENT ACTIONS`, `OFFERS ON THE TABLE`, `PENDING APPROVAL`, `CASE STATUS`, `CONVERSATION SO FAR` (`USER:`/`ASSISTANT:`), `TRIGGER`, `Respond now per the output format.` | `The user just sent a message (last USER line). Respond.` · `The case agent sent a message for the user ({kind}): "{text}". Convey it naturally.` · `An approval card is now shown to the user: {readback_text}. Explain it briefly and ask them to review it.` · `The session just started. Greet the user briefly.` |
| `pl_cp_v1` | cp (real time) | "You are the voice of an AI assistant on a live phone call with a company representative, calling on behalf of your customer. You have already said you are an AI assistant. Never agree to or accept anything yourself; stall with @hold at decisions. Say only facts in the context; never invent prices, quotes or personal data." | `TASK CONTEXT` (public brief), `CASE AGENT SUMMARY` (public), `CASE AGENT RECENT ACTIONS`, `OFFERS ON THE TABLE`, `CASE AGENT GUIDANCE`, `HOLD STATUS`, `CASE STATUS`, `CONVERSATION SO FAR` (`REP:`/`AGENT:`), `TRIGGER`, `Respond now per the output format.` | `The representative just spoke (last REP line). Respond.` · `You have kept the representative waiting for {n} seconds.` · `New guidance from the case agent.` · `The call connected and you introduced yourself as an AI assistant. Continue.` |

- **Every section exists from S0**, even when S0 renders it empty (`(none)`). This keeps the S1 Guard and approval work from changing the fingerprint.
- **The context budget [P; C17].** `CONTEXT_BUDGET_CHARS = 12_000` [E; P2 records the token count of the worst golden case]. When over budget, the renderer drops the oldest transcript lines and inserts `(earlier conversation omitted)`. If that is not enough, it truncates the action log. It never drops summaries, offers or the trigger. The same trimming happens in teacher prompts, training rows and serving.
- **Sampling [E]:** `temperature=0.3, top_p=0.9, max_tokens=160`, `seed = hash(run_seed, lane, gen_idx)`. The teacher uses temperature 0.7.

### 6.4 TalkAct compatibility
The grammar is a superset, so our parser returns TalkAct's `(spoken, to_slow, end_call)` on TalkAct outputs; P7 proves this in S4. The mapping stays as in v2: the digest becomes the summaries, `fast_to_slow` becomes typed `f2s.msg` rendered as notes, and `slow_to_fast{ask_user|tell_user}` becomes `SlowToFast{ASK_USER|TELL_USER}` with TalkAct's trigger string. Byte-identical `talkact_v1` rendering (P6) arrives in S4-CON-01.

---

## 7. Typed Fast↔Slow messages (contract)

```python
class FastToSlow(BaseModel):          # f2s.msg
    msg_id: str; lane: Lane; gen_id: str; utt_ref: str | None     # utt_ref: the partner utterance / user message it came from
    type: Literal["USER_UPDATE", "CP_UPDATE", "REQUEST", "REVOKE", "NOTE", "HOLD"]
    facts: tuple[tuple[str, str], ...] = ()                        # typed (key, value)
    correction: bool = False
    text: str = ""                                                 # ≤ 240 chars

class SlowToFast(BaseModel):          # s2f.msg; acked by s2f.voiced
    msg_id: str; lane: Lane
    type: Literal["ASK_USER", "TELL_USER", "GUIDE", "APPROVAL_NOTICE", "END"]
    text: str = ""                    # user lane only (ASK/TELL); empty on the cp lane
    guide: Guide | None = None        # cp lane only
    approval_id: str | None = None    # APPROVAL_NOTICE: the renderer shows ApprovalCard.readback_text (Guard-written)

class Guide(BaseModel):
    move: GuideMove   # open_call identify ask_discount cite_competitor mention_tenure cancel_lever ask_readback
                      # hold_for_decision decline_offer ask_final_offer deflect_fact_request close_call
    slots: tuple[SlotRef, ...] = ()   # "fact:<key>" | "offer:<ref>.<field>"; resolved against PublicState only
```
- A GUIDE whose slot does not resolve in public state is rejected (`action.denied{reason: guide_slot_not_public}`).
- `cite_competitor` requires `fact:competitor_quote` with `source=shareable`, so a fabricated quote is impossible.
- `cancel_lever` requires the public fact `authorization.cancel_lever=granted`, which the user must have given (C14).
- The cp lane never receives free text from Slow.

---

## 8. Slow tools and context [P]

Every tool requires `private_summary`, the principal-facing digest [O pattern from `slow_agent.py:47-64`]. `public_summary` is optional and passes `declassify()`. Results come back as text, so denials are recoverable. Parallel tool calls are allowed.

| Group | Tools | Stage |
|---|---|---|
| user bridge | `ask_user(question)`, `tell_user(text)`, `wait(seconds 1–15)` | S0 |
| cp steering | `guide_fast(move, slots[])` | S0 |
| facts | `record_fact(key, value, utt_ref)`: public iff shareable or cp-sourced | S0 |
| offers | `record_offer(offer_ref, slots[{field, value, unit, role, utt_ref, span}])` → `terms_hash`, slot statuses, violations | S0 (slot statuses checked from S1) |
| authority | `propose_mandate(envelope)` (loosening always needs a UI decision), `tighten_mandate(changes)` and `revoke(reason)` (restrict only; no approval needed), `request_approval(offer_ref)`, `accept_offer(offer_ref)`, `decline_offer(offer_ref, reason)`, `share_fact(key)` | S1 |
| evidence / close | `check_account()`, `finish(outcome ∈ {completed, no_deal, info_only, escalate}, summary)` | `info_only` S0; the rest S1 |
| browser | `observe/click/type_text/select_option/navigate/scroll` (TalkAct port, MIT) + `submit_transaction(form_id)` (capability) | S4 |

**Slow context.**
- a stable system prompt;
- `TASK: slow_brief`;
- the append-only tool history, with notes appended to tool results:
  - `[USER CHAT] <relay text> (utt u12)`;
  - `[REP CALL] <relay text> (utt c7)`;
  - `[APPROVAL] a17 granted`;
  - `[FENCE] user message pending`;
- the status bar (case status, epoch, offers with slot statuses and TTLs, approvals, hold time, strikes);
- one cache breakpoint on the newest tool result [O `slow_agent.py:160-171`].

There are no transcripts. In duplex, Slow has no free-speech tool.

---

## 9. Guard, authority and status (SYS lane; pure functions; types in the contract)

### 9.1 Terms (`pl.terms/2`)
The terms are:
- `monthly_price_minor`, `currency`, `term_months`, `features` (sorted);
- `fees` (sorted `{code, amount_minor}`) and `credits`;
- `applied_changes` (sorted);
- `total_cost_12m_minor` (derived);
- `offer_id`, `offer_revision`, `expires_at`.

`terms_hash` is the sha256 of canonical JSON, the same construction as v0 [O `material_terms.py:35-46`]. The v0 six-field hash is reproduced once in the port-fidelity fixture [O `material_terms.py:18-32`]; v0 left `applied_changes` unbound.

### 9.2 Read-back slots [C3]
```python
ReadbackSlot{field: "monthly_price"|"term_months"|"fee:<code>"|"fees_none"|"credit:<code>"|"applied_change:<code>"|"changes_none"|"feature:<id>"|"expires",
             value, unit: "usd_minor"|"months"|"bool"|"iso", role: "recurring"|"one_time"|"credit"|"change"|"feature"|"expiry",
             source_utt: str | None, span: (int, int) | None, status: "unknown"|"heard"|"confirmed"}
ReadbackBinding{offer_ref, revision, account_ref, principal_ref, purpose, authority_epoch}
```
- **Required fields per offer:**
  - `monthly_price` and `term_months`;
  - either at least one `fee:*` or `fees_none`;
  - either at least one `applied_change:*` or `changes_none`;
  - `expires` (or the rep's explicit "no expiry").
- **`heard`:** `source_utt` is a cp-partner `utt.final`, the span text normalises to `value`, a role cue from a fixed lexicon ("per month", "/mo" → recurring; "one-time", "activation", "fee" → one_time) occurs in the same clause, and no negation cue ("no", "without", "waived") sits within a 4-token window, unless the value is `*_none`.
- **`confirmed`:** heard in a rep utterance at or after the `guide(ask_readback, offer:ref)` for this revision, with no later rep utterance contradicting it (another value for the same field and role).
- **`readback_status`:** `confirmed` iff every required slot is confirmed. Role swaps, negations and omitted fields therefore stay unconfirmed.
- The lexicons are data in `guard/readback.py`. Their errors are measured by the Ear-audit sample (EVAL §9), not assumed away.

### 9.3 Rules (`authorize(bb, intent)`)
- **`propose_mandate(env)`:** authorised only after `mandate.decided{granted, by: ui|sim_approver}` binds `mandate_hash`. Mandate bounds live in `PrivateState` only.
- **`request_approval(offer)`:** requires an open, unexpired offer; `readback_status=confirmed`; policy violations empty, or exactly "outside mandate"; and no raised fence. It emits `approval.requested{ApprovalCard(approval_id, offer_ref, revision, terms_hash, readback_text, authority_epoch, expires_ms)}`.
- **`accept_offer(offer)`:** requires an open, unexpired, confirmed offer; no policy violations [O v0 `offer_compliance_violations`, `offer_policy.py:105`]; no raised fence; and either a granted, unexpired mandate that `covers(terms)`, or `approval.decided{granted}` with an equal `terms_hash`, the same `authority_epoch` and an unexpired card [O idea from `domain.py:132-182`]. The result is `action.authorized{capability}` plus `speak.verbatim{kind: accept, cap_id}`.
- **`share_fact(key)`:** allowed iff `key ∈ shareable`. Protected keys are always denied.
- **`submit_transaction(form)`** (S4): needs a granted approval over `action_hash(fields)` and mints a capability that the portal verifies.
- **`finish(completed)`:** goes to `verify_completion(bb)`, which requires exactly one released accept and ledger evidence bound to the authorised `terms_hash` (portal evidence additionally to `business_action_id`), with no forbidden change [O v0 I4 "the ledger decides", `domain.py:240-333`].
- **`finish(no_deal)`:** goes to `verify_no_deal(bb)` [C6]. It uses only agent-observable evidence:
  - (a) every recorded offer is declined, or denied at approval, or violates a hard constraint;
  - (b) a `guide(ask_final_offer)` was issued, and a later rep utterance matched the closing lexicon, or the rep ended or transferred;
  - (c) no accept was released.

  The hidden ladder is never consulted. The world oracle ("was an in-mandate offer reachable?") feeds only the `missed_deal` metric.
- **Speech screen (defence in depth):** an exact-match filter over protected values and mandate numbers *not already public* runs on cp-lane Fast sentences before release. It emits `screen.redacted`, and every redaction counts as a blocked harm (EVAL §7).

### 9.4 Epochs, fence, generations and release revalidation [C4]
- **Epoch.** `bb.epoch` increments only on events that **change or restrict** the principal's instructions:
  - `mandate.decided`;
  - a Slow `revoke` or `tighten_mandate`;
  - an f2s `REVOKE` (the kernel bumps it immediately: models may restrict, never grant).

  Approval decisions do **not** bump the epoch: they are grants *bound to* an epoch. An offer's new revision is covered by `terms_hash`, not by the epoch. Cards, approvals and capabilities carry the epoch at which they were minted, and every later check requires `minted_epoch == bb.epoch`.
- **Ingress fence.** Every user-lane `user.msg` raises `authority.fence{raised, fence_id}` synchronously, before any other processing. The fence clears at the first `slow.step.completed` whose `basis_seq` is at or after the seq of the FastU `fast.turn` produced for that message (Slow has seen whatever FastU relayed). While any fence is raised, `request_approval` and `accept_offer` are denied, and queued `speak.verbatim{accept}` lines are held. If FastU fails to relay a "stop", the fence still clears once Slow has processed FastU's turn. This is a **Fast failure**, and exactly the capability measured (EVAL §7 `revocation_honoured`).
- **Generations.** Each FastLane generation has a `gen_id`, `basis_seq` and `epoch`. A newer trigger on the lane cancels an older generation before its first sentence (`fast.cancelled`). `s2f.voiced{msg_id, gen_id}` acknowledges the message a generation voiced; unacknowledged `APPROVAL_NOTICE`s are re-triggered once.
- **Release revalidation (Speaker).** Before releasing a `speak.verbatim{accept}`, the Speaker calls `guard.revalidate(bb_now, cap, t_now + speech_duration(text))`, which checks:
  - the capability is unconsumed;
  - `cap.epoch == bb.epoch`;
  - no fence is raised;
  - `terms_hash` is unchanged;
  - the offer is still open;
  - `expires_ms > t_release_end`.

  On success it emits `speak.released`, and the capability is consumed; on failure, `speak.revoked{reason}`, and Slow is woken. A barge-in during a verbatim line truncates `text_heard`. The world acts only on what was heard, so a truncated accept is not a commitment, and the status stays `COMMIT_AUTHORIZED` → `NEEDS_REPLAN`.
- **Capability.** `Capability{cap_id, business_action_id, intent, terms_hash, epoch, expires_ms, consumed}`. On the cp lane it is a **release token for our own Speaker**: a human rep cannot verify it, so the claim is "guarded release", not complete mediation. In S4 the portal's transaction endpoint verifies and consumes it (complete mediation for portal transactions).
- **Business-action id [C5].** `business_action_id = sha256(case_id ‖ intent ‖ offer_id ‖ offer_revision ‖ terms_hash ‖ (approval_id | mandate_hash))`. It is stable across session restarts. The kernel refuses a second release for the same id (capability consumption), the S4 portal dedupes on it, and S5 Temporal activities key on it.

### 9.5 Status machine (`CaseStatus`)
```
INTAKE ──mandate.decided(granted)──► MANDATED ──chan.opened(cp)──► IN_CALL        (S0: INTAKE ─► IN_CALL ─► CLOSED_NO_ACTION)
IN_CALL ──approval.requested──► AWAITING_APPROVAL ──approval.decided──► IN_CALL
IN_CALL ──action.authorized(accept)──► COMMIT_AUTHORIZED ──speak.released + utt.delivered(full)──► COMMITTED
COMMIT_AUTHORIZED ──speak.revoked | truncated──► NEEDS_REPLAN
COMMITTED ──evidence.recorded──► EVIDENCE_PENDING ──completion.decided(ok)──► VERIFIED_COMPLETE
EVIDENCE_PENDING ──completion.decided(fail)──► NEEDS_REPLAN ──► IN_CALL | ESCALATED
IN_CALL ──finish(no_deal) ∧ verify_no_deal──► VERIFIED_NO_DEAL      any ──cp hang-up (strikes ≥ 3)──► ABANDONED
```
Only `completion.decided` sets a `VERIFIED_*` status. Fast sees the status in the `CASE STATUS` section.

### 9.6 Approval endpoint security [C15]
`POST /api/cases/{case_id}/approvals/{approval_id}` with the body `{decision, terms_hash, authority_epoch}`:
- the server binds to 127.0.0.1 only;
- a CSRF double-submit token is tied to the session cookie issued by `GET /live/{case_id}`;
- the `Origin` must equal the served origin;
- the endpoint is single-use: a second POST returns `409 already_decided`, and one `approval.decided` is emitted;
- it returns `409 stale` if `terms_hash` or `authority_epoch` differs from the current card (a user typing "yes" in chat does not bump the epoch; only authority events do, §9.4).

Voice confirmation (S5) is labelled "not authenticated consent".

---

## 10. Simulated world (SYS lane)

### 10.1 Counterparty = Ear → deterministic policy → Mouth
- **Ear** (`gemini-3.8-flash` via TeamRouter, ADR-0005; JSON schema, closed enum):
  - `ask_discount`, `cite_competitor{price}`, `cancel_intent`, `tenure`;
  - `ask_readback{offer_ref}`, `accept{offer_ref}`, `decline`;
  - `provide_fact{key, value}`, `refuse_fact{key}`, `ask_supervisor`, `hold_request`;
  - `smalltalk`, `injection`, `other`.

  It classifies what the rep **heard** (`text_heard`). Numeric arguments are cross-checked against the offers actually made, and an ambiguous `accept` makes the policy ask for confirmation. The Ear is audited in S2 and re-audited in S4 (EVAL §9).
- **Policy** (deterministic, per-family data): `GREET → IDENTIFY → DISCOVER → OFFER(k) → FINAL → CONFIRM → CONFIRMED | TRANSFER | ENDED`.
  - a lever ladder;
  - hidden terms revealed only on `ask_readback`;
  - identity (and PIN demands in hazard families);
  - offer TTL and withdrawal;
  - **cp patience:** silence over `P_silence` (6 s) → a strike; a hold over `P_hold` (20–60 s, per persona) → a strike; 3 strikes → hang-up;
  - on `accept` of a confirmed offer, `rep.commit_heard` plus a ledger write binding the heard terms (honest, misquote or absent mode). The rep cannot see our capabilities; whether a commitment was authorised is decided by metrics from the cause chain (was the heard accept a released `speak.verbatim`?).

  The ported pure parts are the ledger/binding, `offer_compliance_violations` [O `offer_policy.py:105`] and the salted split [O `negotiation_splits.py:81-119`]. The transition policy is written fresh.
- **Mouth** (`gemini-3.8-flash` via TeamRouter, ADR-0005) voices `PublicIntent`. A number-fidelity check allows at most 2 regenerations, then falls back to a template flagged `fidelity_fallback` (a metric).

### 10.2 Simulated user (async chat) [C7]
- An LLM (`gemini-3.8-flash` via TeamRouter, ADR-0005) plays a hidden profile. It returns JSON `{text, revealed: {key: value}}`, and a deterministic check verifies that every revealed value appears in `text`. This gives relay ground truth without an Ear (EVAL §7).
- **Reply delay:** sampled per persona, 2–20 s [E], on the wall clock. There is no patience, no strikes and no give-up.
- **Corrections and mind changes** come from the schema (`corrections`, `mind_change`, `stop: {trigger, text}`) for the `x-user-mind-change` family.
- **Approver (deterministic):** decides an `ApprovalCard` from the hidden constraints after a sampled 3–15 s delay, and posts it through the same endpoint semantics (`by: sim_approver`).
- **Human replacements:** the web chat (principal) and the "you play the rep" page. In S0 the CLI plays both roles.

### 10.3 Portal (S4)
A hermetic telecom account app with `/api/reset` and `/api/state` (the TalkAct pattern [O `envs/app.py:231-243`]). Consequential forms post to `/tx/{form_id}` with `X-PL-Capability: <cap_id>`. The portal verifies the capability against a kernel-signed token (HMAC with a per-session key) and the `action_hash` of the submitted fields, consumes it, and rejects replays. A generic `click` on a submit button calls the same endpoint without a token and receives `403`. The generic-click bypass test is part of S4-SYS-02.

---

## 11. Kernel concurrency (SYS lane)

- **Tasks per session:**
  - `Bus` (single writer);
  - `FastLane[user]`, `FastLane[cp]`;
  - `SlowLoop`;
  - `Speaker[user]` (instant delivery; chat) and `Speaker[cp]` (floor, speech clock `min(12 s, words/2.8)` [O TalkAct `runner.py:27-38`], barge-in, release gate);
  - `SimUser`/`SimRep` or human channels;
  - `Watchdog` (cp patience, holds, TTL, run budget);
  - `OTelExporter` (a subscriber; its crash is logged and isolated, and it never cancels the TaskGroup).
- **Triggers:**
  - `FastLane[user]` fires on `user.msg`, on a pending s2f for the user lane, and on `chan.opened`.
  - `FastLane[cp]` fires on `utt.final(cp)`, a pending GUIDE, a hold-filler timer (hold over 6 s) and `chan.opened`.
  - Slow wakes on `f2s.msg`, `approval.decided`, `mandate.decided`, `authority.fence`, `speak.revoked` and timers. Wakes that arrive during a step are coalesced into the next step, which is never cancelled.
- **Clocks:** the wall clock only. Tests inject a manual clock from `tests/support/manual_clock.py` through the `clock` constructor argument; `SessionConfig` has no manual-clock value, so production cannot select it.
- **Concurrency suite (`tests/concurrency/`, manual clock, S1-SYS-02):**
  1. the user says "stop" while an accept is queued;
  2. a correction arrives during acceptance;
  3. an offer is withdrawn or expires while speech is queued;
  4. the rep barges in during a verbatim accept;
  5. duplicate approvals (double click, replayed POST);
  6. the exporter fails in the middle of a session;
  7. a stale generation arrives after an epoch bump.

---

## 12. Renderer parity (CI unless marked live)
- **P1:** golden `render_messages` snapshots per profile.
- **P2:** HF tokenizer ids of the golden prompts (`apply_chat_template(…, add_generation_prompt=True, enable_thinking=False)`) equal the committed ids. This pins the tokenizer revision and the empty-think bytes. The v0 Qwen3 bytes were `<think>\n\n</think>\n\n` [O v0 `ml/training/phase03c_cloud/train.py:387-388`]; S0-CON-01 records the Qwen3.5 bytes [E].
- **P3 (live, at session start):** vLLM `/tokenize` with the same messages and `chat_template_kwargs={"enable_thinking": false}` returns the same ids as our pre-rendered prompt. The kernel refuses to start on a mismatch.
- **P4:** `parse(format(t)) == t`, and streaming parse equals batch parse for every prefix split.
- **P5 (training):** decoded trained-label tokens equal the canonical completion plus `<|im_end|>`, and the masked prefix ends with the generation prompt [O port of `verify_trained_span`, `train.py:359-393`].
- **P6/P7 (S4):** `talkact_v1` is byte-identical to TalkAct `_system()`+`_context()`, and the parser agrees with TalkAct's on 60 vectors.
- **The counterfactual view test** (§5) runs with P1.

`fingerprint(profile)` is the sha256 of the P2 ids plus the profile text. `make pull-through` records it, and every contract change re-runs pull-through (full if the fingerprint changed, verify-only otherwise).

---

## 13. Serving (MOD lane)

```
vllm serve Qwen/Qwen3.5-9B@<rev> --served-model-name Qwen3.5-9B --dtype bfloat16 --language-model-only \
  --enable-lora --max-lora-rank 32 --max-loras 4 --max-model-len 16384 --api-key $VLLM_KEY --port 8000
  # prefix caching OFF by default. S0-MOD-01 measures `--enable-prefix-caching --mamba-cache-mode align`
  # (experimental; 528-token block per GPT-6 Pro [E]) and records the TTFT delta only.
```
- **Thinking off:** our kernel pre-renders with `enable_thinking=False` and calls `/v1/completions`. TalkAct-harness runs pass `chat_template_kwargs` through `/v1/chat/completions` (the served names contain `Qwen3` [O `fast_agent.py:140`]). P3 proves both paths give the same ids.
- **One pinned configuration** (ADR-0002 serving, ADR-0003 training) covers the GPU class (default H100 [E]), vLLM version, image digest, HF revision, transformers, peft, trl, flash-linear-attention and causal-conv1d versions.
- **Attestation [C11]:** `GET /pl/attest` returns the sha256 of **every safetensors shard**, the tokenizer files, and every adapter file in the LoRA slots, computed at container start and cached per volume revision. It never uses the index file or greedy-output hashes. `session.started.attest` stores it, and `evidence-check` compares it with the adapter card.
- **Adapter liveness (replaces the challenge set):** at pull-through and on every adapter deploy, compare `prompt_logprobs` for 5 fixed prompt+completion pairs between the base and the adapter in the same process. They must differ by more than 1e-3 nats on average for a non-zero adapter, and be equal (at most 1e-4) for a zero-initialised one.
- **LoRA targets [E, verified by S0-MOD-02]:**
  - `self_attn.{q,k,v,o}_proj`;
  - GDN `linear_attn.{in_proj_qkv,in_proj_z,in_proj_b,in_proj_a,out_proj}`;
  - `mlp.{gate,up,down}_proj`;
  - never `visual.*`.

  The fallback ladder (ADR-0002): (1) all targets served by vLLM; (2) attention + MLP only (train = serve); (3) merged BF16 as a separate model process, with a merge-equivalence check.
- **Co-location:** the demo and development run the kernel on the Mac, and TTFS includes the network (GPT-6 Pro estimate p50 ≈ 0.4–1.2 s [E]). Latency claims use a Modal CPU container co-located with vLLM (OPEN_QUESTIONS Q3).

---

## 14. Tracing, replay and evidence (SYS lane)
- **OTel export:** as in v2, with `gen_ai.*` attributes; spans are derived from `event_id`/`cause_ids`; Phoenix is the viewer (no bake-off).
- **Run bundle** `runs/<run_id>/`:
  - `manifest.json` (`pl.bundle/1`): cfg and its hash, task and instance hash, split, git sha, contract version, renderer fingerprints, models per role with served name and adapter shard hashes, attestation, P3 result, reality (adapter kind per role), spend;
  - `events.jsonl`;
  - `prompts.jsonl` (`{sha, kind: view|prompt|messages|response, content}`). The `FastView` JSON is stored so that datasets **re-render** from views instead of trusting stored prompt text (TRAINING §6).
- **`evidence-check --claim`** fails unless all of these hold:
  - every agent `utt.delivered` has a complete chain (§4.3);
  - every `llm.call` for a claimed role is `real_http`, with a non-empty `request_id`, usage above zero, an echoed served model equal to the configured one, and a `response_sha` matching `prompts.jsonl`;
  - the attestation equals the adapter card when an adapter is configured;
  - the fingerprints equal the current contract;
  - P3 passed;
  - `seq` is dense and `t_ms` monotone;
  - no `recorded_replay`, `test_fake` or `baseline` kind appears in a role the claim names.

  It writes a **reality report** classifying each role as vLLM, hosted, baseline FSM, deterministic world or human.
- **Mutation tests (`tests/evidence/`, S0-SYS-03):** mutating one byte of a recorded response changes a parsed item and the delivered text, and the check fails when the bundle's `prompts.jsonl` disagrees. **Dead endpoint (live, root, S0-ROOT-05):** with the Fast URL pointing at a closed port, the session aborts with `session.ended{reason: llm_unavailable}`, exits non-zero, and delivers nothing after the failure.
- **Replay:** `apps/web` plays events on `t_ms` (1×/4×). It shows lanes (User chat, Rep, Fast-U, Fast-C, Slow, Guard) and a god-view (stream=world). It drills into prompts from `prompts.jsonl` and never re-renders. The live view is the same components over the WebSocket.

---

## 15. Plug-in points (S5+; no rewrites)
| Stage | Seam | Added | Unchanged |
|---|---|---|---|
| S5a voice (cp lane first) | `Channel` | `SimAudioChannel`, then `LiveAudioChannel`. TTS consumes `fast.sentence`, barge-in = `stop()`, and `text_heard` already exists. Voice confirmation is labelled "not authenticated consent" | kernel, renderer, Guard |
| S5b durability | `EventLog`, outer orchestration | `PostgresEventLog`; Temporal `CaseWorkflow` (approval = signal/update, call = activity, follow-up = timer); idempotency on **`business_action_id`** (§9.4) | kernel, Fast, Slow, Guard |
| S5c browser compilation | Slow `TOOLS`, portal | "independently implemented" (PreAct has no licence) trace recorder → compiled workflows with per-step assertions, verify-before-commit through the capability endpoint, fallback to the Slow loop | Fast, Guard, kernel |
| S5d memory + channels | Slow tools, `Channel` | `Memory` ≠ `KB` ≠ case state; email/SMS on the user lane (a new optional `MEMORY NOTES` section = a contract change) | kernel |

---

## 16. Size budget (Python under `src/`, excluding tests, web and `serving/`/`training_jobs/`) [E]

| Area | S0 | S1 adds | S0–S1 total |
|---|---|---|---|
| contract (types, views, protocol, profiles) | 1,900 | 0 | 1,900 |
| core + kernel (log, fold, lanes, speaker, fence, channels) | 700 | 350 | 1,050 |
| slow | 300 | 200 | 500 |
| guard (ported terms/policy + readback, authorize, capability, declass, verify) | 200 | 550 | 750 |
| llm | 300 | 50 | 350 |
| env (1 family → 4; SimRep, SimUser, approver) | 450 | 250 | 700 |
| evidence + obs + serve + cli | 300 | 300 | 600 |
| models + training + eval (MOD) | 300 | 450 | 750 |
| **Total** | **≈ 4,450** | **≈ 2,150** | **≈ 6,600** |

Tripwires (PLAN §0.6): `src/` over 3,700 at S0 close or over 5,800 at S1 close means stop and ask. The web app is capped at 1,500 TypeScript lines through S1, and `serving/` + `training_jobs/` at 700 lines.
