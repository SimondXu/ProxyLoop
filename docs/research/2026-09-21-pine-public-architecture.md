# Pine's public architecture, mapped onto ProxyLoop (2026-09-21)

## Purpose and provenance

This note records what Pine AI's public materials say about its
architecture and maps each claim onto ProxyLoop's existing components and
the active Phase 03C decisions. It adds no scope: no new phase is proposed,
`harness/status.toml` is unchanged.

Claims originate from a user-supplied research pass
(`pine-research-user-notes.md`, 2026-09-21) naming eight sources. Every
claim is attributed, never stated as fact; every source was re-fetched on
2026-09-21 except `pine-voice-js` and the Stanley Wei podcast, marked
unverified below. Correction from verification: the user notes labeled
`ai-agent-book` chapter 2 "the Agent Status Bar" chapter; the fetched
chapter is titled "Context Engineering," and the Status Bar is one
subsection within it.

## Pine's public architecture, as described by its authors

**Full-duplex voice.** The system "streams audio continuously in both
directions" and can "listen while it speaks, react before you've finished a
sentence, handle interruptions, and adapt continuously." Pine reports first
place on the τ-Voice leaderboard at 75.4% (a separate 80.2% figure uses a
non-standard simulator, itself called "not comparable to the standard
entries").

**Fast/Slow split.** Both blog posts and Li's article describe two
concurrent models: "a fast model answers on time but can't think; a
reasoning model thinks but can't answer on time." Li names them the
"Talker" (fast) and "Reasoner" (slow), coordinating through shared context;
the user notes' worked example (Fast stalls with a clarifying question
while Slow evaluates and returns a reject-plus-counteroffer) matches this.
Neither fetched blog post states Fast/Slow coordination is trained with
SFT+RL — that specific claim is **not verified on 2026-09-21**.

**Sequential Revision.** Li describes an actor-judge-retry loop before
"irreversible operations": a judge model catches "insufficiently researched
options" and "policy violations," raising a τ-bench airline score from 56%
to 64% (+8 points).

**Three-layer experience memory.** Li separates parameter memory (SFT/RL,
"muscle memory"), knowledge memory (a lessons knowledge base), and
procedural memory (generated automation), stating the three are "not
substitutes for each other but complementary."

**PreAct.** It "compiles the run into a small state-machine program... that
check[s] the screen," reporting "8.5–13× faster, with no per-step
language-model calls" on replay; it verifies the screen before each action
and falls back to the agent "the moment something is off," and a compiled
program joins the library only if "an independent evaluator confirms it
actually solved the task."

**TalkAct's public numbers.** A fast conversational tier (Claude Haiku) and
a slow Playwright browser tier (Claude Opus) coordinate through a state
digest and a bidirectional channel (`@slow:`; `ask_user`/`tell_user`).
`REPORT.md`: p50 voice latency 10.89 s single-model versus 0.63 s Fast/Slow
("17× reduction"), both arms at 100% task success.

**Durable multi-channel tasks and the Message Gateway.** "One assistant
that can manage many tasks and agents behind the scenes" across "WhatsApp,
Telegram, Slack, voice notes, phone calls, or the Pine mobile app," where
"tasks can run for minutes, hours, or even days" and the system "tracks
everything and reports back... or if it needs a quick confirmation."

**Agent Status Bar.** An "independent mechanism that injects dynamic
meta-information... at the end of the context, compensating for the
model's inability to actively summarize implicit states," analogized to a
phone's status bar — and flagged for a related risk: "the model places
substantial trust in status information. If that information comes from a
source an attacker can manipulate... the attacker can exploit that trust."

**Data-flywheel claim.** Per the user notes, Stanley Wei's podcast states
Pine trains its own voice model on its own call data and treats that
flywheel, not telephony or prompting, as the moat. Not re-verified (audio,
not fetched).

## Mapping table

| Pine concept | ProxyLoop counterpart today | Gap / decision |
|---|---|---|
| Fast/Slow split | `FastTurnDecision` + `SlowWorkResult`, scheduled by the deterministic Router (`fast_now`, `slow_refresh`, `fast_now_and_slow_refresh`) | Pine's split is reportedly jointly trained; ProxyLoop's is code-enforced, Fast prompted not trained. No decision needed. |
| Judge / Sequential Revision | Policy gate + detectors (`disclosure`, `false_completion`, `stale_pin_violation`) before `ActionIntent` execution | No LLM judge exists or is planned. A plausibility check could sit ahead of the gate — see open questions. |
| Blackboard / state digest | `CaseContextSnapshot`, version-pinned, feeding separate Fast/Slow Model Views | Pine's is agent-authored (`state_summary`); ProxyLoop's is coordinator-derived, never model-authored. Deliberate difference. |
| Agent Status Bar | Fast View's structured fields (fact ledger, pending Slow status); `apps/web`'s compact view/pins for users | Not named or positioned as one block; functionally similar. No change proposed. |
| Experience memory (3 layers) | Parameter layer only, as a Phase 03C distillation target. No knowledge-base or procedural layer | Not implemented; out of scope per `GOALS.md`. |
| PreAct trajectory compilation | None; closest analog is the hand-written scripted Temporal `CaseWorkflow` | Not implemented, not planned. |
| Durable multi-channel / Message Gateway | Phase 05A `CaseWorkflow` + Phase 06B1 `local_mailbox` (one credential-free channel) | Pine spans real channels under one identity; ProxyLoop has one synthetic channel, correctly deferred. |
| Data flywheel | `ml/data_pipeline` + Phase 02 Data Factory, a fictional simulator | Different in kind, not scale: no real-call data exists or is planned. |

## What this changes for Phase 03C

The v4 `DECISION_CONVENTION` block added in Stage 1b
(`phase03c_experiment.py`) is a prompt-level version of "the harness
computes the decision rule deterministically": seven ordered conditions map
Provider/offer state to `dialogue_act` and `reasoner_request`, instead of
letting the model invent the mapping. It is weaker than ProxyLoop's code
gates (prompt text the model must follow, not enforced code), but the same
instinct: push the decision out of free-form model judgment wherever it can
be made explicit.

Pine's stall-and-defer example is structurally the same shape as rule 6:
when an offer passes every check, Fast emits `confirm` with
`reasoner_request.needed: true` and `reason_code:
offer_candidate_requires_slow_review` — "a confirm is a proposal for Slow
review, never an acceptance." Fast fills the turn without claiming
authority Slow has not yet granted, the same pattern Pine describes for its
stall.

The Stage 1b pilot's fee-trap failure argues for keeping that authority in
deterministic code rather than any judge, taught or prompted.
`claude-sonnet-5` as teacher wrote the right numbers and the wrong
comparison ("$1,127 is under the $816 cap") in 59 of 60 fee-trap samples —
the class of error Li's judge is described as catching. ProxyLoop's policy
gate already checks `total_cost_12_months_minor <= target*12` in code,
independent of model reasoning. The result argues the gate must stay in
code and that teacher-generated fee-trap data needs that same check applied
to it — not that ProxyLoop needs a new LLM-judge component.

The untuned `Qwen/Qwen3-8B` v4 smoke scored 6/6 on strict JSON, schema, act,
reasoner-request, and end-to-end correctness (`arm-a-untuned-8b-v4.json`),
with no SFT/RL, against Li's claim that Fast/Slow coordination "requires
SFT+RL." Not a contradiction: n=6 is drawn from the episodes used to
sanity-check the prompt, not the fee-trap/forbidden-term families where the
pilot's 200-prompt run already shows the convention failing (F2 0.02 and
0.00). Prompt-plus-convention looks viable on easy families and an open
failure on hard ones — the outcome space the project's pre-registered
Go/No-Go already allows for (`docs/ml-evidence.md`).

## Open questions

- Does the untuned 6/6 smoke hold against the larger held-out family
  evaluation (n ≥ 100/family), or degrade like fee-trap/forbidden-term did
  at 200 prompts?
- Is Li's SFT+RL claim specific to voice turn-taking (no ProxyLoop analog
  absent a voice channel), or does it also cover the dialogue-act decision
  v4 targets? The fetched sources do not distinguish these.
- Is there a role for an LLM-judge-style check ahead of the policy gate, for
  proposal quality rather than authorization, or does that duplicate the
  existing gate and detectors?
- The Agent Status Bar chapter flags prompt-injection risk when status
  content is attacker-influenced; `docs/architecture.md` already treats
  external text as untrusted — does the Fast View's status fields need
  explicit review against that threat model?
- Would experience memory, PreAct-style compilation, or a multi-channel
  gateway change the non-goals in `GOALS.md`, or are they correctly out of
  scope here?

## Sources

| Source | URL | Verification |
|---|---|---|
| Pine blog, τ-Voice leaderboard | https://www.19pine.ai/blog/pine-takes-no-1-on-taubench-voice-leaderboard | Fetched 2026-09-21; confirmed. |
| Pine blog, "most natural human-computer interface" | https://www.19pine.ai/blog/pine-ai-the-most-natural-human-computer-interface-is-your-voice | Fetched; full-duplex/Fast-Slow confirmed. Sequential Revision, memory, Status Bar **not mentioned** here. |
| Pine blog, Message Gateway launch | https://www.19pine.ai/blog/pine-launches-message-gateway | Fetched 2026-09-21; confirmed. |
| Bojie Li, "Effective Agents" | https://01.me/en/2025/06/agent-learn-from-experience/ | Fetched; Talker/Reasoner, 56%→64%, three-layer memory confirmed. |
| Bojie Li, `ai-agent-book` ch. 2 | https://github.com/bojieli/ai-agent-book | Fetched; Status Bar section confirmed. Chapter title is "Context Engineering," correcting the user notes. |
| `19PINE-AI/TalkAct` | https://github.com/19PINE-AI/TalkAct | Fetched (README + REPORT.md); blackboard, channel, models, latency (10.89 s → 0.63 s, 17×) confirmed. |
| `19PINE-AI/PreAct` | https://github.com/19PINE-AI/PreAct | Fetched; state-machine compile, 8.5–13×, verification gate confirmed. |
| `19PINE-AI/pine-voice-js` | https://github.com/19PINE-AI/pine-voice-js | Not fetched; request-shape claim **not verified on 2026-09-21**. |
| Stanley Wei podcast | https://podcast.futureventures.ca/2606607/episodes/19208387-stanley-wei-ai-that-actually-gets-things-done-the-future-of-autonomous-agents-fv-podcast-e-37 | Not fetched (audio); data-flywheel claim **not verified on 2026-09-21**. |
