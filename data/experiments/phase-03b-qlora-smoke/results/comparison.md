# Phase 03B Qwen3-4B Untuned vs QLoRA Smoke

Status: `Complete; NO_GO_STOP_PHASE03B`; squash merged as PR #15
(`f441335` short).

This is a descriptive comparison of six development scenarios across three
scenario families. It is not a statistical significance test or a population
generalization claim. A zero observed failure count at this sample size does
not establish a low population failure rate.

## Evidence identity

- Arm A canonical result: `arm-a-untuned.json`; content fingerprint
  `d6b2f5e040ed4f759cce628418a530782c54d45d44a007ab13fe48b967ad5be2`.
- Arm B canonical result: `arm-b-qlora.json`; file SHA256
  `274e71e06f708d70a66bc6c30a148cab283b27350f62d4862339d838d8036f36`,
  content fingerprint
  `6a7e03a597ebafefb1748901a227b44784f1fe07b9869184f04a6340dcf1a634`.
- Shared evaluation-pipeline fingerprint:
  `c3a7a3bf91a775aba226f06d15e5fda28530502c92bbb813aeb52198148e881b`.
- Both results record `canonical/local_mlx/observed_local_files`. Arm B adapter
  fingerprint:
  `c3a4035d5735aa72687f2bd7507b3003a0622244856d5dc72dbefacb5a1f1651`.
- A's content fingerprint is the baseline content referenced by B. All frozen
  controls are equal except adapter identity.

## Comparable observations

| Metric | Arm A untuned | Arm B QLoRA |
|---|---:|---:|
| schema-valid count | 1/6 | 0/6 |
| canonical-valid count | 1/6 | 0/6 |
| end-to-end-valid count | 0/6 | 0/6 |
| dialogue-act accuracy | 0/6 | 0/6 |
| policy violations | 6/6 | 0/6, but `unassessable_due_to_6_of_6_invalid_json` |
| unsupported-response violations | 3/6 | 4/6; not a complete enumeration |
| false completion | 0/6 | 0/6 |
| PII / disclosure / stale / authority | 0/6 each | 0/6 each, with most safety checks unavailable on invalid JSON |
| input/output tokens | 4461 / 1765 | 4461 / 1442 |
| latency total / median (ms) | 28109 / 4515.5 | 27613 / 4908 |
| MLX peak / process RSS (bytes) | 3183546516 / 2436792320 | 3700787440 / 2655387648 |
| wall time (ms) | 29250.704 | 28726.628 |

Arm B produced invalid JSON in all six episodes. Therefore its apparent zero
counts for several safety detectors are not evidence of safety; the checks were
mostly unable to assess the invalid outputs. The policy counter of zero is
explicitly marked unassessable, and the unsupported count `4/6` is not a full
enumeration.

## Decision

- `arm_b_hard_gates_pass=false`. This is a necessary but not sufficient
  detector-based safety summary; it is not, by itself, an experiment Go,
  evaluability, task-quality, or promotion decision. Any future Go would also
  need independent schema, evaluability, and task-quality evidence.
- Arm A remains the honest baseline reference; its policy and unsupported
  failures are retained and not hidden.
- The No-Go is based on the combined evidence: Arm B schema-valid,
  canonical-valid, and end-to-end-valid were all `0/6`; all six outputs were
  `invalid_json`; apparent safety zeros were mostly unassessable; and
  unsupported was `4/6`, explicitly not a complete enumeration.
- The observed training loss decrease is not a task-quality conclusion.
- Final decision: `NO_GO_STOP_PHASE03B`.
- Do not expand data, train again, rerun either model, promote the adapter, or
  deploy it. Phase 03B is complete and squash merged as PR #15 (`f441335`
  short); no implementation phase is active.

## Review boundaries

Clean Terra's final review was an independent Agent review, not human review.
It accepted the closeout decision. One known P2 limitation remains: the
evaluator can miss duplicate keys inside fenced JSON. No post-hoc evaluator or
source change was made because the frozen result already yields No-Go and a
late change would contaminate the conclusion and over-engineer this bounded
demo.
