# Phase 03A1-V — Evaluation Validity Smoke

**Status**: Complete. Diagnostic gate closed; no next phase activated.

## Objective

Isolate whether r4 failures come from Provider transport, model capability,
model/oracle input mismatch, ambiguous structured-output semantics, or the
single-gold evaluator before any training decision.

## In scope

- preserve r2/r3/r4 byte-for-byte;
- select one frozen episode for each of the six simulator capabilities;
- compare the current raw r4 baseline with a separately versioned diagnostic;
- expose only the same public Provider state already supplied to the scripted
  oracle, never private reason codes or expected actions;
- clarify exact disclosure/preference semantics and non-completion guidance;
- run Terra medium through 29qg only after offline red/green tests pass;
- retain raw structured output, usage, returned model, and local validation.

## Out of scope

- full 32-episode rerun, high-reasoning rerun, prompt optimization loop,
  automatic output repair, SFT/QLoRA/DPO/RL, data expansion, serving, product
  services, UI, deployment, or release.

## Acceptance criteria

1. A test proves the current prompt omits public Provider state used by the
   oracle and leaves dynamic disclosure/preference semantics ambiguous.
2. The diagnostic prompt contains no oracle action, private reason code,
   expected outcome, split, family, or evaluator label.
3. The six selected episodes cover accept, decline, request clarification,
   request replan, escalate, and refuse disclosure exactly once.
4. The smoke artifact is new and source-bound; r2/r3/r4 hashes do not change.
5. Results distinguish schema validity, semantic validity, exact action match,
   safe outcome, and Fast completion behavior.
6. Focused tests and justified broader checks pass.

## Stop condition

Report the causal comparison and recommend the smallest permanent correction.
Do not run the full matrix or start Phase 03B automatically.

## Recorded outcome

- Source-bound artifact:
  `data/evaluation/phase-03a1-r5-validity-smoke-report.json`.
- Selected r4 baseline: 0/6 end-to-end valid, 2/6 Slow semantic valid, 2/6
  raw capability exact, and 1/6 Provider exact.
- Diagnostic: 5/6 end-to-end valid, 6/6 Slow semantic valid, 5/6 raw
  capability exact, 5/6 Provider exact, and 6/6 Fast non-completion.
- The remaining fee case is governed by a twelve-month-total predicate that is
  absent from the model-visible goal and constraints. It is evaluation-contract
  evidence, not an unambiguous model-quality failure.
- No full-matrix retry and no training activation is authorized by this smoke.
