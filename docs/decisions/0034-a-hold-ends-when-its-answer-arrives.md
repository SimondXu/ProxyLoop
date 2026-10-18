# ADR-0034: A cp hold ends when its answer arrives

- **Status:** proposed (the session, 2026-10-17; no contract change)
- **Date:** 2026-10-17
- **Task:** S1-SYS-128
- **Amends:** ADR-0026 "Hold semantics" (its last sentence). Carries out ADR-0029 "Kernel, not text" for the hold.

## Context
`bb.public.cp_hold` changed only through a FastC turn's `chan.hold` (`kernel/lanes.py` `_hold`, `core/fold.py` `_hold`). Two things that answer a hold never ended it, so FastC's prompt and Slow's `[STATUS]` kept a hold the case no longer waited on. ADR-0029's H4 rule ("a hold stands and the representative speaks: keep the same `@hold`") then asks FastC to keep stalling, and teacher labels built from those views teach the student a false state. From the tune set (`scripts/mod/cp_sets` `TUNE`, local bundles under `runs/`):
- **A Guard decline that was heard.** In 9a7dd3, `hold=offer` was set at seq 282. The decline was released at 388 and heard at 389 ("No, thank you: we will not take that offer."). FastC's request at 391 (turn 394) still showed `hold=offer`. 6ebdc0 is the same case (heard 423, turn 428). In `runs/b3-41313c3` the same thing follows Guard's accepts.
- **The user's facts, once recorded.** In 527345, `hold=fact_request` was set at seq 38. Both identity facts were recorded public at 166 and 168, and Slow guided `identify` at 170. FastC's request at 174 (turn 178, `rep_spoke`) still showed the hold.
- **Not stale: bdfcc0 turn 123.** FastC said `@hold fact_request` at seq 92 (its turn opened with "I'm not able to provide the account holder's personal details"), although both facts had been public since seq 67. No answer arrived after the hold began. The hold is FastC's own mistake, and the kernel must not repair it (AGENTS rule 12). It is a decision-table or label question, not state.

## Decision
FastC's `chan.hold` still sets and clears the hold. Two answers also end it. The kernel then emits `chan.hold{lane: cp, reason: null, ended: decided|answered}` (actor `kernel`, cause: the answering event). It does so inside the emit that answered, so no FastC request renders the old hold after it. The rule is one pure function, `guard/holds.py` `ended`; `kernel/calls.py` folds it from every event, next to the needs ledger.
1. **`decided`:** an `offer`, `decision` or `pressure` hold ends once a Guard `accept` or `decline` line is heard whole: its `utt.delivered`, not interrupted. Release alone ends nothing, because the rep has not heard the line yet. A cut line ends nothing, matching `accept_truncated`.
2. **`answered`:** a `fact_request` hold ends at a public `fact.recorded` from the user's message (`source: shareable`), once no readiness key is missing (`guard.readiness`) and no keyed need is `pending` or `replied` (`guard.needs`). This is ADR-0014's "answered", applied when no key list binds the hold.
3. **Ends nothing:**
   - a rep's own fact (`cp_utt`) or a private fact;
   - an `unclear` hold, which a decision line does not resolve;
   - a decline under a `fact_request` hold.
   FastC's next turn still ends any hold, as before.

## Evidence
Offline replay of the predicate over local bundles. The script is in the side-session notes and makes no model call. A request counts as stale when FastC's request rendered a hold that the rule had already ended:
- **Tune set:** 6 of 274 cp requests, in 4 of 13 runs (527345, afa368, 6ebdc0, 9a7dd3). 5 are `rep_spoke` (H4 applies) and 1 is `guidance`. bdfcc0 is not among them.
- **`runs/b3-41313c3`:** 13 of 671 cp requests, in 11 of 40 runs, all after an accept or a decline.
- Hold-out runs were not read.

## Consequences
- **Contract / fingerprint impact:** none. `chan.hold` has no payload model and no emitter restriction, so `ended` is an extra key and `kernel` an allowed actor. The views, renderer and profiles are unchanged. ADR-0026 said "a turn without `@hold` ends the hold". That still holds; the hold's answer now ends it too.
- **ADR-0014 hold counting:** `needs.Ledger.holds` counts holds *set*. The kernel only ends holds, so its ends are never counted. A FastC `@hold` after a kernel end is a new hold: it is counted, and it relays `HOLD` to Slow again instead of counting `hold_repeat`. Nothing reads `holds` today, since ADR-0029 descoped `defer_callback`.
- **World hold clock:** unchanged and independent. `SimRep` runs its hold clock on heard `hold_request` acts and resets it on progress (`env/counterparty/policy.py`), and it never reads `cp_hold`.
- **Training views:** bundles recorded before this change keep their stale holds when folded, because the log is the truth and is never rewritten. Sets built from them, such as `cp_sets` from the tune runs, should drop the rows that `guard.holds.ended` flags rather than re-render them. New runs render the hold correctly. bdfcc0-type rows stay; the decision table owns them.
- **Web:** `callHead` accepts the kernel's `chan.hold`, so the hold line clears with it.
- **Risks:** an answer that the user gives as a private fact last leaves a `fact_request` hold standing until FastC's next turn, which is the old behaviour. A FastC turn requested before the answer and said after it sets its `@hold` again, because the rep hears that stall: the hold follows what the rep last heard from FastC. A turn requested before a verbatim line is heard is cancelled anyway (S1-SYS-59). A turn with no speech, only `@hold` (`lanes.py`'s no-lines path has no floor check), sets the hold again although the rep heard nothing (review round 1; pre-existing, not fixed here). Keyless asks are not in the needs ledger: under a `fact_request` hold for a non-shareable answer, an unrelated shareable fact recorded meanwhile ends the hold early.
