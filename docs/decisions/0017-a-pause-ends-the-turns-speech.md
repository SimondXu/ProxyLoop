# ADR-0017: A pause ends the turn's speech (profile `pl_cp_v3`)

- **Status:** accepted (root decision under PLAN §0.5a, 2026-09-27, from the agent-reliability review)
- **Date:** 2026-09-27
- **Task:** S1-CON-09
- **Amends:** ARCHITECTURE §6.2 (the parser enforces the canonical order's pause boundary under `pl_cp_v3`) and §6.3 (a `pl_cp_v3` row; the root's doc sync writes both); ADR-0014 (its profile becomes `pl_cp_v4`).

## Context
- In real runs FastC (`openai/gpt-6-luna`) degenerated after `@hold` into garbage lines ("રી", ")", "}", "天天中彩票买", a repeated stall sentence), and the parser voiced every one: 4 turns and 87 `Speech` items after the turn's `Hold`, all delivered to the rep. They are `fast.turn` seq 207 in `runs/20260927T081031Z-93f96b` and seq 249, 518 and 770 in `runs/20260927T091443Z-289b86` (the main checkout's git-ignored `runs/`). Two of the four calls ended with `finish_reason` `length`, two with `stop`.
- ARCHITECTURE §6.2 fixes the canonical turn order: speech, then `@slow:` lines, then at most one `@hold`/`@wait`, then optionally `@end_call`. The cp system text already tells Fast this order ("Speak first, directives after"). The parser enforced "at most one pause" (`duplicate_pause`) but not "speech first".

## Decision
- `Profile` gains the grammar flag `pause_ends_speech` (default `False`). New cp profile `pl_cp_v3` (`contract/profiles/pl_cp_v3.py`) = `pl_cp_v2` + `pause_ends_speech=True`; its rendering is byte-identical to `pl_cp_v2`'s.
- `StreamParser(lane, profile=None)` and `parse_turn(text, lane, profile=None)` take the profile name. Under a `pause_ends_speech` profile, once the parser has emitted a `Hold` or a `Wait`, every later non-directive line (a non-blank line not starting with `@`) becomes one `ParseIssue(reason="speech_after_pause", text=<the stripped line>)`. It is never a `Speech`, so it is never voiced, and it is counted like every issue. A partial such line emits nothing until it closes, so streaming parse == batch parse.
- Directive lines after the pause are unchanged: `@slow:` lines still relay, `@end_call` still ends, a second pause is still `duplicate_pause`. The rule does not fire after `@slow:` or `@end_call`, nor after a refused pause (`bad_hold_reason`, `wrong_lane`) (TalkAct P7 compatibility).
- Without a profile, and under `pl_user_v1`, `pl_cp_v1` and `pl_cp_v2`, the grammar is exactly the old one. `fingerprint()` hashes the flag only when it is set, so those three fingerprints are unchanged.
- The evidence chain re-parses each `fast.turn` under the profile its `fast.request` names; an unknown or other-lane profile is a chain failure. The kernel's cp lane and Slow's `CP_PROFILE` move to `pl_cp_v3`, and the kernel parses with its lane's profile.

## Rule-12 analysis (anti-absorption)
Stricter, never more lenient: the rule only turns `Speech` into issues. It applies to every Fast condition on the cp lane (base Qwen, the LoRA, hosted Fast, the teacher), because it lives in the one parser and keys on the profile, not on a model. Its reason is semantic (§6.2's canonical order: after a pause the agent is silent), not a Luna quirk. Base Qwen may pay more for it (more issues, less speech); that is the intended direction.

## Evidence
- The four raw responses above, trimmed, are the parser fixtures in `tests/contract/test_pause_ends_speech.py`: under `pl_cp_v2` they parse as the recorded turns did (the pre-change parser gives the same items), under `pl_cp_v3` every post-hold line is `speech_after_pause`.
- Twenty canonical "speech then pause" turns, the P4 corpus and the tolerant vectors parse identically under v2 and v3. `fingerprint("pl_cp_v3")` is recorded in `tests/contract/snapshots/fingerprints.json`; the other three are unchanged. Goldens `c10_v3_empty` and `c11_v3_hold_for_fact` bind `pl_cp_v3.p2_ids_sha256`; their token ids equal `c08_v2_empty`/`c09_v2_hold_for_fact`'s.

## Consequences
- **Contract / fingerprint impact:** a new cp profile and fingerprint, and a new `IssueReason` value; `pl_user_v1`, `pl_cp_v1`, `pl_cp_v2` and every existing golden are unchanged. `CONTRACT_VERSION` stays `v1` (additive).
- **Data invalidated:** none; no training data exists yet. Old bundles verify under their own profile (the four `evidence/s0` bundles still pass `make evidence-check`).
- **Migration:** root runs `make pull-through MODE=verify` (pending). S1-CON-06's `defer_callback` profile becomes `pl_cp_v4` (built on `pl_cp_v3`). MOD callers that parse with the lane only (`training/dataset.py`, `training/pull_through.py`, `models/repair.py`, `models/fsm.py`) keep the old grammar until they pass the profile.
- **Alternatives rejected:** a filter for Luna only (a model-specific path, rule 12); a charset filter (misses the repeated English stall sentence and would be a heuristic in the parser); a rule keyed on `finish_reason=length` (misses the two `stop` turns, half the cases).
- **Revisit** if a real model voices meaningful speech after a pause that a principal would want heard.
