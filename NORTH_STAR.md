# ProxyLoop v3: North Star

**Goal.** A small but real Pine-AI-style agent. One self-hosted **Qwen3.5-9B Fast** (vLLM, the same weights on two lanes) chats asynchronously with the **user** and talks in real time to a **counterparty**, while **Claude Sonnet 5 Slow** plans from Fast's typed relays. The repo shows the whole ML cycle through the real serving path: teacher-in-harness distillation → BF16 LoRA SFT → held-out evaluation → vLLM serving. It also shows traceable records and, later, durability, voice, browser compilation and memory.

**Architecture in one sentence.** One asyncio kernel (`run_session`) appends typed, causally linked events to `events.jsonl`. It folds them into a blackboard split into **public** and **private** state, and renders three views from it: `FastView[user]` (public + private), `FastView[cp]` (public only) and a relay-only `SlowView`. Guard-minted capabilities release authority-bearing lines only after revalidation at release time, and only the evidence-bound verifier sets a `VERIFIED_*` status.

## Invariants (a PR that breaks one is rejected on sight)
- **I1 One execution path.** Demo, data generation, evaluation, teacher runs and pull-through all call `run_session(cfg, task)`. A condition or ablation is a `SessionConfig` value. There is no second runner.
- **I2 Events are truth, with causes.** `events.jsonl` is append-only with a single writer. Every derived event carries `cause_ids`. The blackboard is a pure fold of the log, and replay, metrics, spans and datasets are all derived from it.
- **I3 One renderer.** `proxyloop.contract.protocol` renders every Fast prompt: teacher, training, evaluation and serving. The golden token ids are pinned, vLLM `/tokenize` parity is checked at session start, and the label self-check (P5) runs before every training run. Any change to the renderer fingerprint re-runs `make pull-through`.
- **I4 Public/private separation.** `FastView[cp]` is a function of public state and the cp transcript only (the private-value counterfactual test keeps it byte-identical). A number enters public state only when it is source-bound: said by the counterparty, or an allow-listed shareable fact. GUIDE is an enum plus slot references and carries no free text.
- **I5 Relay-only Slow.** Slow learns conversational facts only through Fast's typed relays. Raw transcripts exist in the bundle, and reach Slow only in the `raw_transcript` ablation condition.
- **I6 Narrow, honest authority.** The claim is **guarded transactions + measured unauthorised speech + evidence-verified status**:
  - approvals come only from an authenticated UI button or the deterministic sim approver, bound to (approval id, terms hash, authority epoch);
  - authority-bearing lines are released only with an unconsumed capability, after an epoch, fence, TTL and terms revalidation;
  - Fast's own free speech is **measured**, not blocked;
  - models may restrict authority (revoke) but never grant it.
- **I7 Lanes with the right clocks.** The user lane is async chat, with latency measured and no patience or strikes. The counterparty lane is real time: speech timing, silence strikes, hold limits and offer TTL. The teacher runs on the wall clock, with no dilation.
- **I8 Real by default, with provenance.** Fakes live only under `tests/`, and live mode accepts only `real_http`. Every milestone claim rests on bundles that pass `make evidence-check`, which verifies the chain response → parse → state change → heard. With a model endpoint dead, the session fails loudly, and no fallback exists.
- **I9 Never train on evaluation.** Piloted families are train-only. Held-out families are drawn by salt from families never piloted, and the test seeds stay sealed until one unseal. TalkAct, PrincipalBench and τ² are never trained on.
- **I10 Numbers are generated.** README tables and résumé lines render from committed report JSON through `docs/claims.yaml`, and CI fails on drift. Failed attempts stay in every denominator.
- **I11 Honest disclosure.** The counterparty-lane opening is a deterministic AI-disclosure line. There are no fabricated competitor quotes, a cancellation lever is used only after user authorisation, and public replays are synthetic-only.

## Résumé lines per stage (wording fixed; numbers are filled in from reports only)
| Stage | Line (unlocked only when the stage's evidence exists) |
|---|---|
| S0 | "Audited my own v0 (trained path 0.542→0.983 act agreement, yet 0/240 lines delivered on the product path) and rebuilt it around one traceable execution path: self-hosted Qwen3.5-9B on vLLM and Claude Sonnet run concurrently, every delivered line traces from model response to what the listener heard, and a BF16 LoRA trains and serves through the same renderer." |
| S1 | "Concurrent dual-lane agent: one Qwen3.5-9B serves an async user chat and a real-time counterparty call while Sonnet plans from typed relays. Approvals are bound to read-back terms and authority epochs, and a user's 'stop' fences queued commitments; this is tested under concurrency and live." |
| S2 | "Built and human-audited the simulator instruments: a class-stratified Ear audit with precision/recall on rare harms, and repaired outcome metrics (blocked vs realised, generated vs heard). Reproduced TalkAct base rows in its original harness." |
| S3 | "Sized the talker's causal headroom with paired ablations, then ran an SFT learning curve of served LoRAs at 100/300/1,000 episodes, scored leave-one-family-out." Numbers, or the honest negative. |
| S4 | "Distilled a Sonnet 5 teacher, run under Fast-role constraints in the same harness, into a BF16 LoRA on Qwen3.5-9B. On never-piloted held-out families, safe success moved A→B (paired 95 % CI); the pre-registered bar {passed/failed}; the model is served through vLLM. TalkAct rows are our reproduction; PrincipalBench is a diagnostic subset." |
| S5+ | Voice (cp lane), durable cases, workflow compilation ("independently implemented"), memory: each line only after its own measured gate. |

## Non-goals
- RL, QLoRA, training on the Mac, or any headline number from a quantised or Metal artefact.
- An LLM judge on any headline metric. Sonnet never judges.
- "Deterministic code owns every commitment" or any other claim broader than I6.
- Real calls or channels, publishing, or a public non-synthetic replay without the user's release-scoped approval.
- Process documents beyond `PLAN.md`, `NORTH_STAR.md` and ADRs. No per-PR logs, phase contracts or status files.
- A second runner, a second renderer, fallback models, or "deprecated" code limbo.
- A "metric must rise every N PRs" tripwire.
