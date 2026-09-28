# ADR-0021: The sim rep hears its whole backlog

- **Status:** accepted (root, 2026-09-28, §0.5a: rulings (1)–(3) on S1-SYS-63, then the review rulings on the same-block accept, the `chan.strike` count and causes, and the accept gate)
- **Date:** 2026-09-28
- **Task:** S1-SYS-63
- **Amends:** ADR-0005 Decision 5 ("one classify per utterance" becomes one classify call per heard block, one act per utterance).

## Context
`SimRep` ran one Ear → policy → Mouth round per agent turn, first in, first out, under one lock. A round takes world-model time, and the agent speaks faster than that, so the queue grew through the ungraded smoke `runs/20260928T041542Z-bdfcc0` (not committed). Read-back asks were still queued behind older discount asks when the session ended, and the rep kept answering stale turns. The Ear labelled every utterance it received correctly. A listener hears everything said while they compose, so the backlog is a simulator artefact, not caller behaviour.

## Decision
A world-semantics change, made before the battery (ruling 1):
- **D1 Backlog.** `SimRep` keeps the agent utterances it has heard but not yet taken. A turn appends its utterance, takes the lock, and takes the whole list, in delivery order, as one block. A call whose utterance an earlier turn already took returns an empty turn (no lines, no strike, no end) and makes no Ear or Mouth call.
- **D2 Ear.** One forced `classify` call per block. The prompt numbers the block's utterances in order and marks each offer made as open or no longer open. The tool returns `acts`, one item per utterance, each the old act shape. Each item is checked against its own utterance's text (facts, price, offer_ref), and the count must match. It is still exactly one tool call per Ear call. An utterance that does several things takes the first of: accept (only of an offer the rep made), decline, provide_fact, ask_readback, then the levers, then the rest (one ordering in the system prompt, no phrase list).
- **D2a Accept needs an offer made.** An accept must name an offer the caller could have heard: one the rep made before this Ear call, open or not. With none (identifying, or before any offer), the tool's `act` enum has no `accept`, and an `accept` is invalid, a counted regeneration. "Sure, yes, it's Dana Reyes, 4821" while identifying is a disclosure, never an accept. An accept of an offer that has lapsed is an accept; the rep says the offer is unavailable.
- **D3 Policy.** The policy steps every act in order, each with its own utterance's `utt_id`, text and `t_ms`: the same `Policy.step` calls it would get one turn at a time. It stops once the call is over. `rep.policy`, `rep.commit_heard` and `ledger.write` are emitted as before, citing the committing utterance's `utt_id` and its own `rep.ear`.
- **D4 Voice.** The Mouth voices the decisions in order. A run of consecutive decisions with an equal `PublicIntent` and no commit is voiced once, at its last decision, with that utterance's heard text. A decision with a commit is always voiced, and `offer_expired` stays silent.
- **D5 `rep.ear`.** There is one event per utterance, citing its own `utt.delivered` and the block's `llm.call`s. It gains the additive optional key `heard_utt_ids` (the block's utt_ids, in order; ruling 2). `rep.ear` has no payload model in `_MODELS`, so there is no contract or fingerprint change. Obs and evidence readers must tolerate the key and several `rep.ear` events per `llm.call`.
- **D6 What the kernel gets.** A rep turn carries its end kind and its strike count. The end is `hangup` only when the turn's terminal decision is the strike-out `hang_up`; any other end (confirmed, transferred) is `closed`. The count is the block's identity strikes, or the tick's one timer strike. The kernel emits one `chan.strike` per strike, each citing its own decision's event: its voiced line's `rep.mouth`, or its `rep.policy` when D4 voiced it once with the next equal intent. A turn of one decision cites what it always did, its first line's `rep.mouth`. So a strike followed by a transfer in one block closes the call (`chan.closed`), and is not an abandonment. The strike count reaches Slow's STATUS line (fold `cp.strikes` → `views.cp_strikes`) exactly, and obs `identity.strikes.count` is exact too: both equal the sequential run.

**HARD CONDITION (I6).** Coalescing never drops an authority-bearing act. D3 meets it by construction: every act is stepped with the arguments a sequential run would pass, so commits, ledger writes, verified facts, declines, cancellations, levers and strikes are the ones a sequential run makes, given the same labels.

**Documented world semantics (ruling 1).** An accept that names an offer the rep unlocked in the same block was spoken before the caller could have heard that offer. So the sequential commit there is a backlog artefact. The Ear lists only the offers made before the block. When offers were already made, the Ear may say accept, the named offer is not one it lists, so the rep reads the terms back and asks to confirm, and a following confirm commits. When the block makes the first offer, `accept` is not in the enum, so the utterance gets another act and the rep asks what the caller means (`clarify`). The accept stays in the log and is measured. FastC's extra turns stay in the log and stay measured (`speech_after_directive` etc.), so there is no rule-12 absorption. Fix B (defer FastC guidance while the rep composes) is deferred to §0.9 (ruling 3).

## Evidence
- `tests/env/test_backlog.py`: T1–T4 and T6–T8 (the queued turns, the HARD CONDITION negatives, voicing, `rep.ear`, the compound read-back ask).
- T5: 15 sequences plus the strike rows. The policy state, decisions, commits, ledger, strikes, `chan.strike` count and end kind equal one-turn-at-a-time stepping.
- The same-block accept: read back, then committed on the confirm; clarified when the block makes the first offer.
- F4: each act is checked against its own utterance.
- D2a: the enum before and after an offer is made, the disclosure path, and the accept of a lapsed offer.
- `tests/kernel/test_rep_block.py`: rep-chat sessions whose block ends and strikes like the turns one at a time (reason, `chan.strike`, fold `cp.strikes`, obs `identity.strikes`, `chan.closed`); each block strike cites its own decision; a one-decision turn's identity or timer strike cites its first line, as before.
- `tests/concurrency/test_backlog.py` (T9): a bounded backlog.

## Consequences
- **Contract / fingerprint impact:** none (`rep.ear` gains an optional key; the Ear prompt and tool are world-side, not the renderer).
- **Data invalidated:** no graded battery exists, and the smokes are ungraded diagnostics. The battery runs only on post-0021 `main` and is never pooled with earlier runs.
- **Migration:** recorded bundles keep their old-format Ear responses as history; nothing replays them through the Ear.
- **Risks and what would make us revisit this.** The Ear must return a correctly sized `acts` array. A wrong count is a counted regeneration (ADR-0005 D5). Live Ear probes (the compound sentence, the disclosure-plus-yes) and a live smoke are root-run. Revisit if the Ear audit (S2) shows per-utterance accuracy falls with block size.
