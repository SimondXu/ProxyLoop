# Phase 03B final clean Terra review

Date: 2026-08-25

## Recommendation

`NO_GO_STOP_PHASE03B`

Clean Terra returned this recommendation after independently reviewing the
frozen Phase 03B smoke evidence. Sol accepted it. This is an independent Agent
review, not human review; the Phase 02 human review fields remain unchanged.

## Evidence reviewed

- Canonical Arm A and Arm B result identities, shared pipeline fingerprint,
  canonical/local MLX provenance, adapter identity, and Arm B's reference to
  Arm A content.
- The six-scenario / three-family descriptive comparison in
  `data/experiments/phase-03b-qlora-smoke/results/comparison.md`.
- The frozen QLoRA config/data/base identity and recorded adapter hashes.

## Findings and disposition

### Important 1 — stale status documentation

The prior status documents still described training or evaluation as pending.
This closeout updates the current status and the durable evidence links. It
does not rewrite historical build-log entries.

Disposition: fixed by this closeout.

### Important 2 — policy-zero is not a safety result

Arm B's policy counter is zero, but all six Arm B outputs are invalid JSON.
The policy result is therefore recorded as
`unassessable_due_to_6_of_6_invalid_json`, not as a safety success. The same
boundary applies to the apparent zero counts for most other safety detectors.

Disposition: recorded explicitly in the comparison and closeout evidence.

### Important 3 — hard gate failure

Arm B is schema-valid and canonical-valid in `0/6` episodes and its final hard
gate is false. The gate is a necessary but not sufficient detector-based safety
summary; it is not an experiment Go, evaluability, task-quality, or promotion
decision by itself. The No-Go also rests on Arm B end-to-end validity `0/6`,
`invalid_json` in all six episodes, mostly unassessable apparent safety zeros,
and unsupported `4/6`, which is not a complete enumeration. It does not justify
another training run or a post-hoc change to the evaluator.

Disposition: final decision is `NO_GO_STOP_PHASE03B`.

### P1 — detector hard-gate boundary

Terra reproduced the field-boundary issue with an injected `{}` output: the
runner can report schema-valid `0`, end-to-end-valid `0`, while
`arm_b_hard_gates_pass=true` when the detector counters happen to be zero. This
shows that the boolean is only a detector-based safety summary and cannot stand
in for evaluability or task quality.

Sol accepted a documentation-only remediation. The evaluator, pipeline
fingerprint, frozen A/B results, and model evidence are not changed or rerun:
changing them after the No-Go would contaminate the frozen conclusion and
over-engineer this portfolio demo. Any future Go must independently satisfy
schema, evaluability, task-quality, and promotion criteria.

### P2 — fenced-JSON duplicate-key limitation

The evaluator can miss duplicate keys inside fenced JSON. This remains a known
evaluator limitation. No post-hoc source or evaluator change is made: it does
not affect the No-Go conclusion, and changing the frozen evaluator after the
run would contaminate the conclusion and over-engineer the portfolio demo.

## Final boundary

No data expansion, additional training, model rerun, adapter promotion,
deployment, or next phase is authorized. Phase 03B is closeout-only. CI and
merge have not occurred; this artifact must not be described as a merged or
complete phase.

## Final closeout rereview

After the documentation-only P1 remediation, clean Terra returned
`APPROVE_CLOSEOUT`. No blocking finding remains. The fenced-JSON duplicate-key
limitation remains P2 and non-blocking. Terra recommends retaining the final
`NO_GO_STOP_PHASE03B` decision and the frozen evaluator/results; no rerun or
post-hoc implementation change is recommended.
