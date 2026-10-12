# ADR-0022: Training labels from hosted models

- **Status:** accepted (**a user risk decision**, 2026-09-28, recorded by the main root; not a legal opinion)
- **Date:** 2026-09-28
- **Task:** S1-ROOT-17 (records it); S1-MOD-07 builds the pull-through label-source selector

## Context
- **No served base Qwen during development.** The user decided on 2026-09-28 that development runs on Luna (OpenRouter `openai/gpt-6-luna`) everywhere, and that Qwen enters only after fine-tuning. The base-Qwen serving runs were cancelled, so there are no base-9B turns to label pull-through with (TRAINING §9, PLAN §9 E1: base-9B turns in S0, teacher turns from S1 on).
- **The planned teacher is a hosted model.** TRAINING §2.1's teacher is `claude-sonnet-5` acting as Fast in the harness; its outputs are the SFT labels.
- **Provider terms.** Anthropic's Commercial Terms (section D.4) restrict using the services to train competing AI models. OpenAI's terms are believed to carry a similar restriction; this is **not verified**. This ADR does not interpret either.
- **Options on the table** (main root's log, 2026-09-28): (a) FSM labels for pull-through (no terms risk, plumbing only; the root's first ruling); (b) base-9B turns (needs a served base Qwen, cancelled); (c) an open-weight teacher; (d) hosted-model outputs as labels. The root held (d) for the user, because it is a legal-risk question.

## Decision
The user accepts the risk: **hosted-model outputs may be used as SFT labels.**
- Real SFT (S3/S4): the Sonnet teacher's turns in the harness, as TRAINING §2 describes. The teacher choice is still pending with the user (a Gemini teacher was raised on 2026-09-28; main root's log).
- Development: Luna Fast turns from real sessions. Pull-through (plumbing, `claim: "none"`) takes its labels from them (`PT_SOURCE=hosted`, S1-MOD-07); the three train-split label bundles are in `evidence/s1/pull-through/`. `base_9b` stays a selectable source.
- **The user's rationale:** a personal research and demo project; a narrow small model that learns protocol discipline for this harness; not a competing product.
- **Constraint:** adapters trained on hosted-model outputs are **not published** (the root's proposed default; the user did not object). Any publishing still needs the user's release-scoped approval (NORTH_STAR non-goals).
- Unchanged: labels come only from train-split families (I9); every row keeps its provenance (TRAINING §3), so the source of each label stays visible in the dataset and the adapter card.

## Evidence
None measured. This is a risk decision, recorded from the main root's log (2026-09-28): the user's decision on training labels, and the root's rulings on the pull-through label source before it.

## Consequences
- **Contract / fingerprint impact:** none.
- **Data invalidated:** none. No dataset or adapter has been built from hosted outputs before this decision.
- **Migration:** S0-MOD-03's label step no longer needs a Qwen@vllm bundle; TRAINING §9 points here. The root runs pull-through (`MODE=full`, G) on the committed Luna bundles.
- **Risks and what would make us revisit this.** The provider may read its terms differently from the user; the user bears that risk, and this ADR is not legal advice. Revisit if the project's purpose changes (a product, publishing an adapter), if the providers' terms change, or if the user asks.

## Amendment (2026-09-29, user decision)
- **The teacher for SFT labels is DeepSeek** (TeamRouter `deepseek-flash`, served echo `deepseek-v4-1-flash-260910`; S1-MOD-10). This replaces the pending Sonnet teacher above.
- **Opus filters and rewrites.** In distillation, Opus subagents filter the teacher's labels (the hard checks and the judged T1–T6) and rewrite the labels they judge wrong. The user explicitly allows Opus-rewritten text as SFT labels and accepts the Anthropic Commercial Terms D.4 risk this ADR already names.
- **Safeguards:** every row carries provenance `teacher_raw | opus_rewrite` (TRAINING §3); each dataset reports its rewrite share; the no-publish constraint on adapters is unchanged.
- Unchanged: the rest of this ADR. It is a risk decision, not legal advice.

## Amendment 2 (2026-10-12, user decisions)
- **The reviewer is Sonnet 5.5**, replacing the Opus subagents above (NORTH_STAR now allows Sonnet to judge outside headline metrics). Provenance becomes `teacher_raw | reviewer_edit | reviewer_rewrite` (TRAINING §3).
- **Two independent, blind reviewers per row.** A row is kept only if both keep it, or both fix it with the same directive signature (hold and reason, relay keys, `@end_call`/`@wait`); then the fix closest to the teacher's text (edit distance) is used. Any disagreement or any drop drops the row.
- **How rows are fixed.** Directive errors by edit operations applied mechanically (add or remove `@hold <reason>`, repair or split a relay line, delete a sentence), so the teacher's speech is kept; a free rewrite only for speech errors (T1–T3). Shorter speech is acceptable. Every fixed row is re-checked by the filters that gate the data (TRAINING §4).
- **One specification.** The reviewer brief quotes the cp profile's decision table (the next profile's ADR) and adds nothing; where the table does not decide, the reviewer drops the row with `ambiguous:<rule>`.
- **Calibration and bias.** During pilot rounds, 8 blind rows built from the table go into every 40; a class below 90 % accuracy means the brief is fixed before the data counts. Kept, fixed and dropped rows are reported by lane, trigger, hold state, guidance, status and family; a class with more than 25 % dropped goes back to the table instead of out of the data.
- **Where it runs.** Small rounds (brief tuning, calibration, spot checks) in Claude Code on the plan quota; full scale through the Anthropic Message Batches API on the monthly credit, each row keeping its request id.
- **Teacher sampling:** temperature 0.3, the live Fast sampling (TRAINING §2.1).
- **Pilot evidence** (`runs/label-review-pilot-1012`, git-ignored; DeepSeek medium on `pl_cp_v3`, 40 rows): all 20 mechanically known errors were caught and all 28 fixes passed the deterministic checks; two reviewers agreed on wrong-vs-keep in 19 of 20 rows and on the exact verdict in 14 of 20. The pilot brief contradicted ADR-0026's sticky hold ("not otherwise"), so its hold verdicts are void (principal-architect review, 2026-10-12).
