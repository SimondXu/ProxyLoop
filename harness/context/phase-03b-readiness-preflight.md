# Phase 03B Gate 0 Preflight

Date: 2026-08-25

This file separates observed readiness evidence from Sol's frozen decisions.
It does not claim human review or canonical Arm B evaluation success.

## Activation evidence

- The user explicitly approved the bounded, conditional Phase 03B experiment
  and directed Sol to retain final decision authority.
- The user further constrained the result to a meaningful, working portfolio
  demo and rejected unnecessary platform or infrastructure work.
- Local `main`, local `origin/main`, and fetched remote `main` were verified at
  `600c18b2f5e987d0727edab6d59549d1e8045215` with a clean worktree before the
  experiment branch was created.
- Phase 04B is merged and no other implementation phase was active.
- One historical Phase 03A1 stash remains untouched.
- Baseline `make preflight` passed with Runtime 184 and ML 115 tests plus all
  repository-native gates.

## Observed data readiness

- Phase 02 has 128 accepted source records split 80 train / 24 dev / 24 test;
  automated PII, exact-duplicate, and recorded cross-split leakage counts are
  zero.
- The 80 train records represent 20 distinct scenarios and the 24 dev records
  represent six; each scenario has four response-text variants. The dev set has
  only three family clusters.
- The Phase 02 16-record review remains `pending_human` and its quality report
  remains `training_ready=false`.
- The historical review sample contains three test records and does not expose
  enough public observation detail to review the proposed Phase 03B Fast
  mapping. It remains immutable historical evidence, not the Phase 03B review
  packet.
- On 2026-08-25 the project owner explicitly waived personal review for the
  bounded portfolio smoke and directed a clean-context Agent review with Sol as
  final decision maker. This is recorded as `independent_agent_review`; it does
  not change Phase 02 historical human-review fields.
- Source records declare project-owned synthetic provenance and
  `LicenseRef-ProxyLoop-Synthetic-1.0`; no separate license grant was found.
  The project owner's explicit instruction authorizes only this local bounded
  smoke, not redistribution or a broader license claim.

## Observed contract mismatch

- Phase 02 targets are `SafeObservation + OracleAction`; some contain
  `accept_offer` and completion candidates owned by the Slow/capability path.
- The Fast contract requires proposal-only `FastModelOutput` and rejects
  non-null `action_intent`.
- Therefore Phase 02 records are source lineage, not directly trainable Fast
  examples. A deterministic, human-reviewed Phase 03B mapping is required.

## Observed evaluator and causal-control gaps

- Phase 03A1 r5 is a six-episode diagnostic and not Arm A for this experiment.
- The existing end-to-end runner invokes Slow separately for each condition,
  so it cannot guarantee identical Fast inputs between A and B.
- The remaining r5 fee case depends on the shared twelve-month total-cost
  predicate, which was absent from the model-visible diagnostic goal.
- Existing evaluation records do not derive all required PII, stale-pin, and
  Fast-authority safety metrics from executed detectors.
- The Qwen MLX adapter does not yet load an adapter and does not explicitly
  attest all decoding settings.

## Local model and compute evidence

- Cached model:
  `mlx-community/Qwen3-4B-Instruct-2507-4bit` at revision
  `50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b`, derived from
  `Qwen/Qwen3-4B-Instruct-2507` revision
  `cdbee75f17c01a7cc42f958dc650907174af0554`.
- Checkpoint fingerprint:
  `941705797578fb931fdef40b55c03ae60274b48fe03f1626f01197b52394de50`.
- Tokenizer fingerprint:
  `5b06e759eb78534dbbf01b5ffc3faa43c9607921494151f7ca758b352f08722b`.
- Chat-template fingerprint:
  `40c21f34cf67d8c760ef72f8ad3ae5afad514299d4b06e91dd9a8d705af7b541`.
- Host: Apple M4 Pro with 48 GB unified memory. Installed ML environment
  includes MLX 0.32.1 and MLX-LM 0.31.3; MLX-LM contains LoRA/QLoRA and adapter
  loading support.
- Earlier sandbox inspection could not expose a Metal device. The later
  canonical Arm A run is the only recorded local execution evidence; no
  dependency or model was downloaded.

## Current Gate 1 pretraining remediation

- Clean-context Terra returned `PRETRAIN_BLOCK`. Sol accepted the three
  findings: unsupported numeric relations were not observation-bound, result
  evidence lacked fail-closed provenance, and Arm B had no required canonical
  Arm A baseline/control-parity gate before generation.
- A third clean Terra `PRETRAIN_BLOCK` found that Arm B did not persist the
  canonical Arm A false-completion count/content fingerprint for a relative
  gate, and that an output path could alias the baseline path under overwrite.
  Sol accepted the bounded fix; the runner now records A/B counts and
  `arm_b_hard_gates_pass`, and rejects the alias before generation.
- A fourth clean Terra review raised two Important findings: a canonical
  `not_done` structured claim could still pass completion quality when response
  text asserted completion, and a baseline aggregate count was trusted without
  recomputing the six episode booleans. Sol accepted both fixes; the evaluator
  now fails closed on either signal and the validator requires exact episode
  count/type/recomputed-count parity before generation.
- A fifth clean Terra review raised one Important finding: Phase 03B reviewed
  targets all require `fact_updates=[]`, while non-empty structured or raw fact
  updates were not classified as unsupported. Sol accepted the narrow
  Phase03B-only fail-closed check; the historical Fast contract is unchanged
  and no generic fact-grounding component is added.
- A sixth clean Terra review raised two Important findings: duplicate JSON
  members could be silently accepted and output/baseline hard-link aliases were
  not rejected. Sol accepted the Phase03B-local recursive object-pair guard and
  `os.path.samefile` check; both fail closed before trusting output or writing.
- The canonical Arm A provenance review returned `STOP_AFTER_ARM_A` with one
  Important finding: an injected adapter path could produce evidence labeled
  canonical without an observed local checkpoint attestation. Sol accepted the
  finding. Injected runs are now diagnostic with `injected_test` provenance;
  canonical Arm A validation requires exact `local_mlx` and
  `observed_local_files`; at that checkpoint only a fresh production local Arm
  A rerun was permitted. The resulting canonical run and current authorization
  are recorded below.
- The old Arm A evaluator exposed the real public-number claims `7200 exceeds
  7500` and `81,400 exceeds 90,000`. The remediation now evaluates only the
  nearest comparison numbers when both values are present in the same public
  observation or its public target annual cap. The underlying model output
  remains diagnostic evidence and is not rewritten.
- The actual offline token-fit invocation used the frozen local snapshot with
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` and produced
  `phase03b token fit: verified`; observed full-train token range was 752--850
  and eval-prompt range was 688--775 across 26 rows, with no truncation.
  This is recorded evidence, not human review.
- The remediation was independently reviewed, the fresh canonical Arm A rerun
  passed its provenance gate, and the complete repository preflight passed.
  The one frozen QLoRA training run then exited 0. Clean Terra returned
  `APPROVE_CANONICAL_ARM_B_EVAL`, accepted by Sol; exactly one canonical Arm B
  evaluation is now authorized, with no further training or data expansion.
  Phase 02's historical 16-sample review remains `pending_human` /
  `training_ready=false`.

## Sol's minimal decision

- Use the exact cached 4-bit MLX checkpoint as both A and B base; do not request
  the missing official full checkpoint.
- Use train/dev only. Never read or use Phase 02 test records in this phase.
- Treat results as a descriptive six-scenario smoke, not significance or
  generalization evidence.
- Stage implementation to avoid waste: first create and validate the new human
  review packet and deterministic mapping. The 80/24 source records compile to
  20/6 distinct scenario-level examples; historical response variants remain
  reviewer evidence rather than independent examples. Stop for human decisions
  before adding or running the model/training path.
- Do not build reusable training infrastructure. One narrow compiler, one
  fixed manifest, one local A/B runner, and small evidence files are the entire
  intended implementation surface.

## Frozen ownership

- Sol owns this context, the executable contract, target semantics, acceptance
  criteria, Gate decisions, integration, review remediation decisions, Git
  publication, and merge/cleanup.
- Stage 0A uses one Luna xhigh implementer with exclusive ownership of the new
  Phase 03B compiler, review-packet generator/artifact, focused tests, and
  required command/layout wiring. The implementer is not alone in the
  repository and may not revert or overwrite others' work.
- A later Stage 0B implementer, if human review passes, may own the minimal
  adapter/decode/A-B path. It must not overlap active Stage 0A ownership.
- Terra performs independent read-only review and advises Sol; Terra never
  edits, approves in Sol's place, publishes, or merges.

Stage 0A is now qualified under the owner-directed independent-Agent-review
waiver. One new Luna xhigh implementer may own Stage 0B only:

- one new Phase 03B experiment/compiler/evaluator module and focused tests;
- the existing Qwen MLX adapter plus its existing tests, limited to explicit
  greedy decoding and optional local adapter loading/attestation;
- one preparation/check script, one Make target, and small train/dev-only
  JSON/JSONL experiment artifacts.

It may reuse existing deterministic fixture helpers without changing Phase
03A1 code. It may not modify Stage 0A code/artifacts, Runtime, historical
artifacts, dependencies/locks, or any test-split content.

## Fresh canonical Arm A evidence

- Canonical result:
  `data/experiments/phase-03b-qlora-smoke/results/arm-a-untuned.json`, SHA256
  `b2a994d1eea6989cadbcf9873d8c7bdc7722ed0b4764807fd1245c4a87d3b0f0`;
  content fingerprint
  `d6b2f5e040ed4f759cce628418a530782c54d45d44a007ab13fe48b967ad5be2`;
  evaluation-pipeline fingerprint
  `c3a7a3bf91a775aba226f06d15e5fda28530502c92bbb813aeb52198148e881b`.
- Execution is canonical/local_mlx/observed_local_files over six episodes.
  Observed counts: schema-valid 1, canonical-valid 1, end-to-end-valid 0,
  dialogue-act 0, policy violations 6, unsupported-response violations 3,
  and false-completion, PII, disclosure, stale-pin, and authority violations
  all 0. Wall time `29250.704 ms`; latency total/median
  `28109 ms`/`4515.5 ms`; tokens `4461`/`1765`; MLX peak memory
  `3183546516` bytes; process RSS `2436792320` bytes.
- Raw hashes matched the pre-provenance run. The retained pre-provenance,
  pre-remediation, and detector-diagnostic files have hashes
  `636c1f...`, `bd7647...`, and `2a6929...` respectively.

## Frozen QLoRA training evidence

- Sol executed the frozen native MLX-LM config against the local snapshot in
  offline mode, writing the adapter only to
  `/private/tmp/proxyloop-phase03b-adapter.<ephemeral>`; the command exited 0.
  No network fallback or external model API was used.
- The executed command, with the local snapshot path redacted, was:
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --project ml python -m mlx_lm lora -c data/experiments/phase-03b-qlora-smoke/qlora-smoke.yaml --model <frozen-local-snapshot> --train --data data/experiments/phase-03b-qlora-smoke --adapter-path /private/tmp/proxyloop-phase03b-adapter.<ephemeral>`.
- Sol's observed training log recorded trainable parameters
  `3.670M/4022.468M` (`0.091%`); validation loss `3.886` at iteration 1,
  `3.441` at 10, `2.744` at 20, `1.997` at 30, and `1.706` at 40; training
  loss `3.850` at 5, `3.602` at 10, `3.163` at 15, `2.687` at 20, `2.087` at
  25, `2.135` at 30, `1.699` at 35, and `1.574` at 40. Trained tokens were
  `2780`; peak memory `5.412 GB`; observed session wall time approximately
  `128.4 s` from accumulated tool waits.
- Final weights were `14692068` bytes with SHA256
  `801d2d96908dbb49df146d568b496f2d831c68ac128be14a33c50211cf76813c`.
  `adapter_config.json` was `1160` bytes with SHA256
  `070c605ed52337d57fcc676dc919d20d14507c47c8c4eb78622dd5d01a57e903`.
  These binaries remain ephemeral and are not committed repository artifacts.
- Clean Terra independently verified config, data, base identity, and hashes,
  but did not see the original stdout. Loss and timing are Sol execution
  evidence, not an independent quality result; loss decrease is not a task-
  quality conclusion.

## Final canonical Arm B evidence and closeout

- Arm B result `data/experiments/phase-03b-qlora-smoke/results/arm-b-qlora.json`
  has SHA256 `274e71e06f708d70a66bc6c30a148cab283b27350f62d4862339d838d8036f36`,
  content fingerprint
  `6a7e03a597ebafefb1748901a227b44784f1fe07b9869184f04a6340dcf1a634`,
  pipeline fingerprint `c3a7a3bf91a775aba226f06d15e5fda28530502c92bbb813aeb52198148e881b`,
  canonical/local_mlx/observed_local_files provenance, and adapter fingerprint
  `c3a4035d5735aa72687f2bd7507b3003a0622244856d5dc72dbefacb5a1f1651`.
- Shared controls matched except adapter identity. A recorded schema/canonical
  `1/1`, E2E `0`, dialogue `0`, policy `6`, unsupported `3`, false completion
  `0`, and PII/disclosure/stale/authority `0`; input/output `4461/1765`,
  latency total/median `28109/4515.5 ms`, MLX/RSS
  `3183546516/2436792320 bytes`, wall `29250.704 ms`. B recorded
  schema/canonical `0/0`, E2E `0`, dialogue `0`, policy counter `0` but
  `unassessable_due_to_6_of_6_invalid_json`, unsupported `4`, false completion
  `0`, and detected PII/disclosure/stale/authority `0` with most safety checks
  unavailable; input/output `4461/1442`, latency total/median `27613/4908 ms`,
  MLX/RSS `3700787440/2655387648 bytes`, wall `28726.628 ms`.
- All six B episodes failed `invalid_json`; unsupported `4/6` is not a complete
  enumeration. `arm_b_hard_gates_pass=false` is a necessary but not sufficient
  detector-based safety summary, not an experiment Go, evaluability,
  task-quality, or promotion decision. The No-Go also rests on schema,
  canonical, and E2E `0/6` plus mostly unassessable apparent safety zeros. See
  the compact comparison at
  `data/experiments/phase-03b-qlora-smoke/results/comparison.md`.
- Final decision is `NO_GO_STOP_PHASE03B`. No data expansion, additional
  training, model rerun, adapter promotion, deployment, or next phase is
  authorized. Any future Go would independently require schema, evaluability,
  and task-quality evidence. Loss decrease is not a task-quality conclusion.
- Clean Terra's final review is independent Agent evidence, not human review.
  The stale-document finding is fixed here; policy zero is not treated as a
  safety result; the hard-gate failure is retained. The known fenced-JSON
  duplicate-key limitation is recorded without a post-hoc evaluator change.

## Current pretraining verdict

Gate 0 previously reached `READY_FOR_QLORA_SMOKE` after Stage 0A/0B
remediation and independent review. The fresh canonical Arm A rerun recorded
the real evaluator gaps and the complete repository preflight passed. The
current state is closeout-only: the one frozen QLoRA run and one canonical Arm B
evaluation are complete as descriptive evidence. Clean Terra returned
`NO_GO_STOP_PHASE03B`, accepted by Sol, from the combined schema/canonical/E2E
`0/6`, six invalid JSON outputs, mostly unassessable apparent safety zeros,
unsupported `4/6`, and `arm_b_hard_gates_pass=false`. This does not authorize
additional training, data expansion, model reruns, promotion, deployment, or a
wider model matrix.
The Phase 02 historical review remains `pending_human` /
`training_ready=false`; no Agent review is human review.

No model execution is active; Phase 03B is closeout-only and is not yet merged
or CI-complete.
