# ADR-0013: Superseded cp speech and guidance recency

- **Status:** accepted (root decisions under PLAN §0.5a, 2026-09-27, adopting the architect's design §2.2a and the principal-architect review's R2 option A)
- **Date:** 2026-09-27
- **Task:** S1-ROOT-05 (records); S1-SYS-22 (superseded speech) and S1-SYS-27 (guidance recency) build it
- **Amends:** ARCHITECTURE §5 (`guidance_cp`), §9.4 (generations); narrows the full "newer trigger cancels an older generation" rule left open by #156 (7c).

## Context
- **Stale in-flight speech.** `FastLane.run` awaits the whole spoken turn, and the Speaker never asks whether a line is still current. In `evidence/s0/20260927T011721Z-dcb1a6` a line generated before the user's answer was still being spoken after the facts became public and the `identify` GUIDE arrived; the rep heard a refusal.
- **Ambiguous guidance.** FastC's view lists the last three cp guides, oldest first, with no "current" marker (`core/fold.py`, `guidance_cp`). After `identify` was guided, the older `hold_for_fact` guide was still listed first, and FastC kept saying "please hold" after the facts were public (smoke #1: the main checkout's git-ignored `runs/20260927T051033Z-dd5094`, `runs/20260927T051648Z-d04021`, `runs/20260927T050729Z-723c8f`; review F6, F7).
- **The base rule (#156, 7c).** For S1 a generation is cancelled only when it is epoch-stale, before its first sentence (`fast.cancelled{reason: epoch}`), and its trigger re-runs. Whole-generation cancellation on any newer trigger was rejected because it loses relays that #144 protects.
- **Options for guidance.** (A) the fold keeps only the newest cp guide; (B) a new profile renders "CURRENT GUIDANCE" and "EARLIER (superseded)" (a contract change, pull-through); (C) FastC role text that asks it to prefer the newest guide (rejected: prompt tuning for one Fast, rule 12).

## Decision
- **Superseded cp speech (S1-SYS-22).** Before each cp line starts, the Speaker drops the line and the rest of its generation when the generation's `basis_seq` is older than either:
  - a public `fact.recorded`, or
  - a cp GUIDE `s2f.msg` that differs from the newest guide in that generation's view (identical re-sent guides never cut speech).

  The kernel emits `fast.cancelled{gen_id, reason: "superseded", utt_ids, by}` (causes: the turn and the superseding event) and re-queues the generation's trigger, coalesced by kind. **Relays are kept**: `fast.turn` and `f2s.msg` are emitted before speech, as today. The line already being spoken finishes. The user lane is never superseded, and a newer rep line supersedes nothing (barge-in handles it).
- **Invariant S1 (test).** No cp `utt.delivered` starts after a superseding event whose seq exceeds its generation's `basis_seq`, and every `f2s.msg` of a superseded generation still exists.
- **Guidance recency (S1-SYS-27, option A).** The fold keeps only the newest cp guide (`guidance_cp = guides[-1:]`). The contract's bound (`MAX_GUIDES = 3`) and the renderer are unchanged, so the section renders one guide. Option B is the fallback, taken only if smoke evidence shows A losing needed context (e.g. fewer confirmed read-backs when a hold follows `ask_readback`); it would be a CON task with its own ADR.
- **Why this is not absorption (rule 12).** Both changes apply to every Fast condition alike and remove an ambiguity in what the agent is told; neither repairs a model's output.

## Evidence
No measured value backs this ADR. The runs above are the failure cases; S1-MOD-05's `superseded_lines`, `stale_line_after_public` and `holds_after_identify` (EVAL §7) measure the effect on smoke #2.

## Consequences
- **Contract / fingerprint impact:** none. No new event type (`fast.cancelled` gains the reason `superseded` and untyped keys); no renderer or profile change.
- **Data invalidated:** none. Bundles store every `FastView` by sha in `prompts.jsonl`; `evidence-check` checks each `view_sha` against what was stored and replays the fold, which a shorter `guidance_cp` does not make reject any event. So the committed `evidence/s0` bundles should still verify; S1-SYS-27's acceptance re-runs `make evidence-check` on all four.
- **Migration:** S1-SYS-22 after S1-SYS-23 (`kernel/speaker.py` overlap, serial); S1-SYS-27 after S1-SYS-26.
- **Risks.** It would not have saved dcb1a6: that stale line was already being spoken when the facts landed; readiness (ADR-0012) is the fix there. A slower Fast loses more lines, so `superseded_lines` is reported per condition. Option A may drop read-back context; watch confirmed read-backs.
