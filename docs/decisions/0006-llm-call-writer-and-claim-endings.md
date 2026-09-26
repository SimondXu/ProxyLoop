# ADR-0006: `llm.call` single writer and claim endings

- **Status:** accepted
- **Date:** 2026-09-26
- **Task:** S0-ROOT-09
- **Related:** ADR-0004 (contract v1: `llm.call`, `session.ended`, `pl.bundle/1`), ADR-0005 (world models and the world structured-call policy).

## Context
S0-SYS-04 (#120) gives every adapter an `on_record` sink, S0-SYS-05 (#121) makes world calls through it, S0-SYS-03 (#118) checks bundles, and S0-SYS-06 adds the Fast and Slow lanes. Two rules were implicit in those PRs and need to hold for every later lane:
- **Who writes `llm.call`.** If a caller could also log the `LLMCallRecord` it gets back, a call could be written twice or not at all, and a cancelled generation could leave no record. The options were: callers log records (rejected: duplicates and missed cancellations), or the adapter's sink is the only writer (chosen).
- **Which endings a claim accepts, and what a pass means.** The #118 review found that a scripted bundle relabelled `real_http` still passes `--claim` (PLAN §0.9). A check over the bundle's own contents cannot detect that.

## Decision
1. **One writer for `llm.call`.** Every `llm.call` event is written only by the adapter's `on_record` sink (S0-SYS-04 `make_client(..., on_record=...)`). This holds for every lane: Fast, Slow and the world.
   - Callers cite a call by its `call_id`: in the payload (`fast.turn`, `rep.ear`) or through `cause_ids` to its `llm.call` events (`rep.mouth`, `user.sim`, …). They never log a returned record.
   - A cancelled call also produces its record through the sink.
2. **Claim endings.** `evidence-check --claim` accepts exactly these `session.ended` reasons: `completed`, `no_deal`, `info_only`, `escalate` and `abandoned` (the counterparty hung up). Every other ending fails a claim, including errors, timeouts, budget stops and `llm_unavailable`.
3. **What `--claim` proves.** Passing `--claim` proves that a bundle is internally consistent, not that it is authentic. Authenticity rests on root-run provenance: the root ran the command and committed the bundle.

## Evidence
This ADR records design rules, not measurements. The review findings behind Decision 3 are in PLAN §0.9 under #118. The sink is in `src/proxyloop/llm/factory.py` and `src/proxyloop/llm/http.py`; the world's sink is `World.record` (`src/proxyloop/env/world.py`).

## Consequences
- **Contract / fingerprint impact:** none. The fingerprints `pl_user_v1` and `pl_cp_v1` are unchanged.
- **Data invalidated:** none.
- **Migration:** S0-SYS-06 wires the kernel's Fast and Slow clients through `on_record` and cites `call_id`s. `ENDED_OK` in `src/proxyloop/evidence/check.py` (S0-SYS-03) already holds the list in Decision 2; any change to one changes the other.
- **Risks and what would make us revisit this:** a new ending that a claim should accept requires an amendment to this ADR. Decision 3 stays true until bundles carry a provenance attestation that `evidence-check` can verify.
