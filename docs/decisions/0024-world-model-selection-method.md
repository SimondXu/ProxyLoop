# ADR-0024: World-model selection method (S1-MOD-09)

- **Status:** proposed
- **Date:** 2026-09-28
- **Task:** S1-MOD-09 (#246, #252)

## Context
The world (Ear, Mouth, SimUser) runs on `gemini-3.8-flash`, the same family as Slow, which violates EVAL §9.7. The user will decide whether to switch. This ADR fixes the method before any candidate call. It is an internal instrument choice: nothing from it goes into `docs/claims.yaml` or the README, and it is not S2 truth (the S2 human Ear audit still applies).

## Decision
1. **Arms** (TeamRouter, each role at `reasoning_effort` low): `gemini-3.8-flash` (incumbent), `deepseek-flash`, `glm-5.3-flash`. `deepseek-flash` is an alias echoing `deepseek-v4-1-flash-260910`; TeamRouter rejects the dated id with HTTP 400. Gate 0 (20 forced calls each): DeepSeek 20/20, GLM 19/20. One model would serve all three roles.
2. **Items:** frozen, root hash `471a0a91…41cc` (`docs/decisions/data/world-select-items.json`). Sources: 51 `real_http` train bundles, plus 232 blind-authored constructed items, reported separately. Off-distribution items (29 Ear) are reported apart. Five bundles fail the offline evidence-check; they are disclosed, not filtered.
3. **Replay** (`scripts/mod/world_select_run.py`): every arm makes fresh calls, with no reuse. Requests come from the production builders (#244), are checked by the production validators (`check_act`, `fidelity_ok`, `check_reply`), and use the production regeneration bound and timeouts. The 13 constructed SimUser items are not replayable; the closed loop covers them. **Exception to AGENTS rule 3 / I1** (root decision): this is a component-level, open-loop replay of single world calls, not an agent evaluation and not a session runner, and it never drives Fast or Slow. Precedents: S0-ROOT-12, S1-MOD-08.
4. **Ear gold:** labelled blind by an Opus xhigh annotator under codebook v1.2 (attached as data; its boundary rulings were made by the model root under the user's delegation). The annotator scored 98.3 % (176/179) on constructed items with known gold, with 0 harm-class false positives. Hard cases were re-adjudicated blind under v1.2; the 26 items still uncertain were decided by the user. Isolation was instruction-based (the annotators were told to read only the codebook and their batch), not sandboxed.
5. **Metrics.** Ear: consequence-class accuracy is primary (`smalltalk`, `other`, `injection` and `refuse_fact` form one class); exact accuracy, per-class recall/precision, harm-class false positives, first-attempt validity, exhausted/timeout and block array size are also reported. Mouth: `fidelity_ok`, fallback, and judged M1–M5 (blind, by Opus). SimUser: validity, invented numbers, undeclared reveals. Latency and cost are secondary. Paired bootstrap by episode cluster: X − Gemini with a 95 % CI.
6. **Decision:** the user decides on the data. There is no automatic switch rule. A closed-loop sanity run of 8 episodes follows for the chosen model, counting only world failures, not success.

## Consequences
If the world model changes, bundles before and after the change cannot be pooled, and the S1 battery (held for this, user decision) runs on the chosen world. A world swap is a model-role change (the user's decision) plus an update to ADR-0005.
