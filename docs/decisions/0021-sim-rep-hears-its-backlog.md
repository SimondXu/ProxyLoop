# ADR-0021: The sim rep hears its whole backlog

- **Status:** proposed (main-root rulings (1)–(3) on S1-SYS-63, 2026-09-28, §0.5a; two open points below)
- **Date:** 2026-09-28
- **Task:** S1-SYS-63
- **Amends:** ADR-0005 Decision 5 ("one classify per utterance" becomes one classify call per heard block, one act per utterance).

## Context
`SimRep` ran one Ear → policy → Mouth round per agent turn, first in, first out, under one lock. A round takes world-model time, and the agent speaks faster than that, so the queue grew through the ungraded smoke `runs/20260928T041542Z-bdfcc0` (not committed). Read-back asks were still queued behind older discount asks when the session ended, and the rep kept answering stale turns. The Ear labelled every utterance it received correctly. A listener hears everything said while they compose, so the backlog is a simulator artefact, not caller behaviour.

## Decision
A world-semantics change, made before the battery (ruling 1):
- **D1 Backlog.** `SimRep` keeps the agent utterances it has heard but not yet taken. A turn appends its utterance, takes the lock, and takes the whole list, in delivery order, as one block. A call whose utterance an earlier turn already took returns an empty turn (no lines, no strike, `ended` = the policy is done) and makes no Ear or Mouth call.
- **D2 Ear.** One forced `classify` call per block. The prompt numbers the block's utterances in order (a block of one reads as before, numbered). The tool returns `acts`, one item per utterance, each the old act shape. Each item is checked against its own utterance's text (facts, price, offer_ref), and the count must match. It is still exactly one tool call per Ear call. An utterance that does several things takes the first of: accept, decline, provide_fact, ask_readback, then the levers, then the rest (one ordering in the system prompt, no phrase list).
- **D3 Policy.** The policy steps every act in order, each with its own utterance's `utt_id`, text and `t_ms`: the same `Policy.step` calls it would get one turn at a time. It stops once the call is over. `rep.policy`, `rep.commit_heard` and `ledger.write` are emitted as before, citing the committing utterance's `utt_id` and its own `rep.ear`.
- **D4 Voice.** The Mouth voices the decisions in order. A run of consecutive decisions with an equal `PublicIntent` and no commit is voiced once, at its last decision, with that utterance's heard text. A decision with a commit is always voiced, and `offer_expired` stays silent.
- **D5 `rep.ear`.** There is one event per utterance, citing its own `utt.delivered` and the block's `llm.call`s. It gains the additive optional key `heard_utt_ids` (the block's utt_ids, in order; ruling 2). `rep.ear` has no payload model in `_MODELS`, so there is no contract or fingerprint change. Obs and evidence readers must tolerate the key and several `rep.ear` events per `llm.call`.

**HARD CONDITION (I6).** Coalescing never drops an authority-bearing act. D3 meets it by construction: every act is stepped with the arguments a sequential run would pass, so commits, ledger writes, verified facts, declines, cancellations, levers and strikes are the ones a sequential run makes, given the same labels. FastC's extra turns stay in the log and stay measured (`speech_after_directive` etc.), so there is no rule-12 absorption. Fix B (defer FastC guidance while the rep composes) is deferred to §0.9 (ruling 3).

## Evidence
`tests/env/test_backlog.py`: T1 (the queued turns make one Ear call and the read-back is answered), T2 (an accept queued before a read-back commits, citing the accept's utterance and `rep.ear`), T3 (a queued disclosure is verified before a queued discount ask), T4 (a queued decline and cancellation), T5 (a table of 12 sequences: the policy state, decisions, commits, ledger writes and strikes equal one-turn-at-a-time stepping), T6 (voicing), T7 (`rep.ear`), T8 (the compound read-back plus best-and-final ask). `tests/concurrency/test_backlog.py` (T9): with the agent speaking faster than the rep, every turn reaches the Ear within one rep round. Stepping only a block's last act turns T2, T3 and T5 red (S1-SYS-63 PR).

## Consequences
- **Contract / fingerprint impact:** none (`rep.ear` gains an optional key; the Ear prompt and tool are world-side, not the renderer).
- **Data invalidated:** no graded battery exists, and the smokes are ungraded diagnostics. The battery runs only on post-0021 `main` and is never pooled with earlier runs.
- **Migration:** recorded bundles keep their old-format Ear responses as history; nothing replays them through the Ear.
- **Open (escalated with S1-SYS-63, root decision needed):**
  1. *An accept of an offer unlocked in the same block.* The Ear sees the offers made before the block. If a lever in a block unlocks a new offer and a later utterance in the same block accepts it by price, the Ear cannot name it (`offer_ref`), so the rep reads it back and asks for confirmation. One turn at a time, it would have committed. No utterance in the block could have heard that offer, so the sequential commit is itself a backlog artefact. It is still a commit that coalescing does not make. This case is pinned by `test_t5_an_accept_of_an_offer_unlocked_in_the_same_block` (`xfail`, strict).
  2. *`chan.strike` per turn.* `RepTurn.strike` is one flag, so a block with k identity strikes gives one `chan.strike`. The policy's counters and the hang-up are exact, but `obs` `identity.strikes.count` counts `chan.strike` events and undercounts. `h5_pass` is unaffected. Fixing this needs a kernel or obs change, which is outside this task.
- **Risks and what would make us revisit this.** The Ear must return a correctly sized `acts` array. A wrong count is a counted regeneration (ADR-0005 D5). A live Ear probe on the compound sentence and a live smoke are root-run. Revisit if the Ear audit (S2) shows per-utterance accuracy falls with block size.
