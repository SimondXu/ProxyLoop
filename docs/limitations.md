# Limitations and negative results

This is the one place that lists what ProxyLoop does not do, what it tried
and failed at, and the known limits it ships with. Each item names the file
that records it. The list covers the programme that ran from the
2026-09-21 audit (`docs/research/2026-09-21-repository-audit.md`) through
Phase 07 (`harness/build/phase-07-portfolio-hardening.md`). A limit that a
later merged PR closed is not listed.

Why a separate page: the limits span the ML results, the Runtime, the
durable lane, the Web, the evaluation code and the operating gates. A README
section long enough to hold them would bury the overview, and
`docs/portfolio-demo.md` covers only the demo. The README links here and
keeps a short "not done" list of its own.

## Not done

Everything below is not done, except the one Web item marked as built
outside the phase. The sources are the Phase 07 contract ("Non-goals and hard
limits"), `harness/context/build-plan-to-complete.md` ("Blocked by the hard
limits", "Do not do") and decisions 16–21 in
`harness/context/audit-remediation-decisions.md`.

- **Production of any kind.** No production serving of the distilled
  adapter, no real-model load test, no p95, capacity, concurrency or OOM
  measurement, no automatic fallback under load, no production exactly-once
  effects, no production monitoring, no production-readiness claim
  (decision 18).
- **Deployment, hosting and release.** Nothing is deployed or published.
  The adapter and converted weights are not published (`ml/serving/README.md`).
- **Phase 06B2 and every real channel.** No real Provider, Gmail or OAuth,
  e-mail, MCP, SMS, or Voice (LiveKit, SIP, telephony), and no credential of
  any kind. The mailbox is a synthetic fixture (Phase 06B1).
- **V0, frontier-as-Fast, and a second-family Judge.** Not measured
  (budget): the relay keys are exhausted and no hosted budget is recorded
  (decision 17).
- **A model Judge.** The Judge is scripted (decision 17). No Judge verdict
  distribution is reported in any metric (decision 7, PR-14).
- **Further training, data expansion, reruns or promotion.** Phase 03C
  trained once; nothing is promoted. The Phase 03B decision
  `NO_GO_STOP_PHASE03B` is unchanged (decision 17).
- **Narrow contracts 1.2 (PR-15).** Dropped by decision 21. R-11b and B1-9b
  stay recorded limits (see "Contract and Runtime limits" below).
- **The build-plan "Do not do" list.** D3-5 and D3-6 (`qwen_mlx.py` is frozen
  by the r4 execution contract), D1-10 to D1-12 (the V1 simulator is frozen;
  V2 supersedes it), D2-7 to D2-9, D3-7 (field deletion), D3-8, D3-9, A-9b
  (dropped by decision 19), and a `SlowWorkRequest.revision_feedback` field
  (decision 20). Their content is under "Evaluation-code limits" below.
- **Web.** No free-text turn after Case creation, no Web view of channels or
  of the Judge, and no UI redesign. The Phase 07 contract also lists "a Web
  restore of a Case on a local backend after reload" as a non-goal, but #103
  (merged before PR-16) added that restore, and the PR-16 lane run observed
  it once on the distilled backend (contract amendment A2;
  `harness/log/phase-07-portfolio-hardening.md`). It works; it was built
  outside Phase 07.
- **Hosted spend.** None in Phase 07. The spend before it is in
  [Cost](#cost).

## Negative results

- **The distilled Fast model delivers no line through the product path.**
  On the 240 Phase 03C held-out rows rendered through the product path, the
  distilled backend delivers 0/240 lines: 40 rows (refusal-transfer, no
  offer) are refused before the model, and `fast-gate-v1` withholds all 200
  outputs that reach it. Product-path act agreement is 157/240 = 0.654
  (0.983 on the trained path). The untuned baseline delivers 8/240.
  (`data/experiments/phase-03c/local-parity/product-path-report.json`;
  `ml/serving/README.md`, "M2 result".) Details and causes are in
  [ML evidence](ml-evidence.md#the-product-path-a-negative-result).
- **Every local Fast call in the split runs was gate-withheld.** On both the
  distilled and the untuned backend, 8/8 Fast calls succeeded and were
  withheld by the gate, so `fast_model_line_rate` is 0.0
  (`data/evaluation/fast-slow-split-distilled.json`,
  `data/evaluation/fast-slow-split-untuned.json`). In the PR-16 Scene A-D
  run the consumer saw the fallback line
  (`harness/log/phase-07-portfolio-hardening.md`).
- **A third of distilled product-path calls would time out.** 64 of 200
  distilled product-path generations ran longer than 25 s by
  `generation_ms` (65 by `wall_ms`); p50 23.9 s, max 32.5 s. At the 25 s
  default each ends as `fast_adapter_timeout` and delivers the fallback
  line. One Apple M4 Pro, sequential, other work running on it: descriptive,
  not p95 (`harness/log/feat-pr9b-local-fast-gateway.md`,
  `ml/serving/README.md`). The committed M2 report carries only the maximum
  (32,544 ms) and the total; the p50 and the over-25 s count come from the
  git-ignored per-row run files and are recorded in the log.
- **The distilled model still names a restricted field** 4 times in 400
  in-family dev rows (untuned: 7). The held-out "zero policy violations"
  is partly untested: no held-out row can trip the disclosure detector
  (`docs/ml-evidence.md`, Phase 03C point 4).
- **Checkpoint selection had no resolving power.** The 60-row dev subset
  saturated at the first eval, so step 100 (0.22 of an epoch) was chosen by
  the tie-break. Eval loss rose 16.8 % after epoch 0.89
  (`harness/log/phase-03c-stage2-stage3.md`, `docs/ml-evidence.md`).
- **Phase 03B stopped at `NO_GO_STOP_PHASE03B`.** The one QLoRA smoke
  returned invalid structured output (A 1/6, B 0/6 schema-valid). A later
  review found the smoke's prompt, parser, data and scale were the causes, so
  it says nothing about the model or about QLoRA
  (`data/experiments/phase-03b-qlora-smoke/results/comparison.md`,
  `docs/research/2026-09-21-phase-03b-post-training-review.md`).
- **Hosted baselines were low.** Phase 03A1-R (r4): best condition 3/32 E2E
  under the r4-era evaluator; under the state-based verifier, 4 rows move and
  frontier-reference-high goes 1 → 2
  (`data/evaluation/phase-03a1-r4-rescored-report.json`). The r5 5/6 is
  rule-following with the oracle's rules in the prompt, not independent
  reasoning (audit D2-1).
- **The Judge never revises in the product.** On the default scripted Slow
  the scripted Judge always accepts; its revise-and-retry path runs only in
  tests (`harness/log/feat-pr14-judge-seam.md`).

## Measurement boundaries

- **One machine.** Every PR-9b local model number (M1, M2, the local split
  runs) comes from one Apple M4 Pro (48 GiB), sequential, with uncontrolled load on the machine. None is p95,
  capacity or production latency (`ml/serving/README.md`).
- **Two input paths.** The trained-path numbers (0.983, M1) use the prompt
  format the model was trained on; the product never produces that input
  (decision 18, E1). The product-path numbers (M2) use the training
  fixture's strategy text, not the product Slow's (D6), and the product
  prompt never contains the consumer's words (D5)
  (`harness/context/pr9-local-distilled-fast-design.md` §1).
- **Pre-Judge local reports.** The distilled and untuned split reports stay
  at `fast-slow-split-local-v1`, recorded before the Judge existed. They are
  never compared on Judge fields (Phase 07 decision D6).
- **Integrity, not provenance.** `phase03c-local-parity-check`,
  `phase03c-product-parity-check` and `fast-slow-split-check` verify that
  every derived field follows from the recorded fields. They cannot prove the
  raw outputs came from the model; that needs the git-ignored adapter and a
  rerun (`ml/serving/README.md`).
- **The local gate skips the database tests.** `make preflight` skips the
  tests that need PostgreSQL or Temporal (66 at PR-16's head, 67 on `main`
  after #104) and pins that count per file. A "preflight passed" covers none
  of them; `make postgres-check`, `make phase05a-check`
  and `make phase06b1-check` run them, one at a time (`docs/development.md`).
  The real-dependency gates do not themselves require zero gated skips
  (review Minor 5 of `harness/log/fix-gate-honesty-r15-g1.md`).
- **The demo's journey evidence is scripted only.**
  `data/evaluation/phase-07-demo-journey-scripted.json` is written for the
  scripted backend; the distilled scene is one manual run with no committed
  artifact (Phase 07 decision D7).
- **Hosted costs are estimates.** The relay exposes token usage but no
  billed cost; every relay figure is usage times a tariff, not an invoice
  (`data/evaluation/phase-03a1-r4-hosted-rerun-report.json`,
  `cost_accounting_note`).

## Product and Web limits

- **One consumer turn after creation.** The Web has one dialogue turn, the
  confirmation. Multi-turn dialogue is measured only by the split report's
  `dialogue_path` (`docs/portfolio-demo.md`).
- **No reject control.** The approval card offers only "Approve exact
  terms". The Runtime accepts a `rejected` decision, but the Web never sends
  one; declining means not approving (audit lane E, N5,
  `harness/code_review/repo-audit-E.md`).
- **The Judge is invisible in the Web.** It appears only as a `role=judge`
  Model Trace and in the split report's counts.
- **The Status Bar is hidden below 1120 px** with the rest of the context
  rail, and shows expiry as an ISO time with no countdown
  (`harness/log/feat-pr10-agent-status-bar.md`).
- **The intake parser is lexical and English only.** Unusual phrasing
  becomes a clarification the consumer answers. The $72 rule exists in four
  copies (`CreateCaseRequest`, `runtime.py`, the Web, the parser); only the
  parser's is pinned by a parity test. No model-backed intake is built
  (`harness/log/feat-pr12-stateless-intake.md`).
- **The demo uses one fixed Case id**, so Scenes A, J and B each need a stop,
  a reset and a fresh start (Phase 07 contract, K2).
- **Direct mode is in-process.** With the default memory store it holds one
  Case per process; a restart loses the Case and the approval-expiry timer
  (`harness/log/fix-direct-mode-apply-command.md`, `apps/README.md`). A Fast
  call can hold the direct-mode app lock for up to 25 s, and the lock is
  process-wide, not per Case (`harness/log/fix-b2-8-threadpool-runtime-calls.md`,
  `harness/log/feat-pr9a-fast-backend-seam.md`). Several direct-mode
  processes on one database can interleave a Case's clock guard and answer
  500 `internal_error` without storing anything (same B2-8 log).

## Contract and Runtime limits

- **R-11b: material terms exclude fees and applied changes.** An approval
  binds neither the fee breakdown nor the changes the Provider will apply; a
  forbidden applied change is caught only by the completion verifier after
  execution (`CONTEXT.md`, "Material Terms"; `docs/architecture.md`;
  decision 21).
- **B1-9b: the wire admits a negative fee line.** Fee netting is unchanged:
  a +1000/−1000 pair nets to zero (`harness/log/fix-b1-9-total-offer-policy.md`;
  decision 21).
- **A-3: the capability/action join is not on the wire.** On the Runtime
  path the coordinator's admission check and the executor both check it; on
  the ML evaluation path only the executor does
  (`harness/log/docs-contract-semantics-limits.md`, `docs/architecture.md`).
- **A-5 and A-9** are documented, not changed: `simulator_transition`
  Evidence hashes are producer-defined and `bill` Evidence has no producer;
  ephemeral values and write-once records keep `revision=1`
  (`harness/log/docs-contract-semantics-limits.md`).
- **The completion verifier produces two outcomes.** `verify_completion`
  returns only `complete` or `needs_replan`; `continue`, `needs_user` and
  `candidate_complete` exist in the contract enum but no producer emits them
  (audit A-7f; `runtime/packages/telecom_domain/src/proxyloop_telecom_domain/domain.py`).
- **R-6 residual: Cases persisted before #61 keep their one-day capability
  manifest** (no migration), so such a Case cannot execute after its first
  day. The other half of R-6, an injectable offer TTL, is closed by #104 on
  `main` (`harness/log/fix-r6-injectable-offer-ttl.md`); nothing in the
  product selects a non-default TTL, and a consistent multi-field forgery of
  the stored TTL and expiries within the nine-day bound is accepted (same
  log).
- **Model Trace log.** Retention is unbounded (R-13). An adapter that raises
  produces no trace, except a typed Fast or Judge failure. The A-3 check's
  version (`slow-proposal-v1`) is not stamped on traces
  (`docs/architecture.md`; `harness/log/feat-pr13-slow-drives-intent.md`).
- **Judge-retry paths not reachable today.** An exception in the retry call
  loses that run's traces; a retry the Runtime cannot use fails the command
  although the first result was usable. Neither is reachable while no
  product Slow implements the feedback protocol
  (`harness/log/feat-pr14-judge-seam.md`).
- **Model Slow timing (model mode only).** A channel refresh can yield a
  proposal whose offer expires before the next refresh; the re-consult
  trigger is deferred (`harness/log/feat-pr13-slow-drives-intent.md`, I1).
- **Error-category mismatch.** For a stale revision, direct mode returns
  `stale_cas` while real Temporal returns `case_conflict`
  (`harness/log/fix-p2-api-hygiene.md`). The `model` path's 409 still says
  "model execution is unavailable in Temporal mode"
  (`harness/log/feat-pr11-fast-under-temporal.md`).

## Durable lane and channel limits

- **Fast under Temporal.** Two queued 25 s Fast calls on one Case can push
  the second Web request past the 30 s proxy (the command still applies); a
  slow database plus a 25 s Fast call can exceed the activity
  start-to-close; the API labels `adapter_mode` from its own variables, not
  the worker's (`harness/log/feat-pr11-fast-under-temporal.md`).
- **Retries after exhaustion (R-1).** A retry of an exhausted Update gets
  the cached failure until the run rolls, and the roll waits until no handler
  is active. Every roll resets the run-local expiry state
  (`harness/log/fix-r1-retryable-update-continues-as-new.md`).
- **Runs in progress at deploy time (R-1, R-16)** keep the pre-patch
  behaviour for the rest of the run. History grows by one failed activity
  and timer per five minutes while an expiry keeps failing; there is no
  history-size Continue-As-New (`harness/log/fix-r16-expiry-classifier.md`).
- **Channel re-drive (R-17).** The only re-drive trigger is a sender
  redelivery; a sender that stops after one 503 leaves the outbox `pending`.
  A send whose effect `lookup` cannot yet see can still be duplicated
  (`harness/log/fix-r17-r5-channel-redrive.md`).
- **Callback pairing (R-18).** A consistent forged pair (a callback event
  and a `PROVIDER_EVENT` Evidence with equal times) is accepted, and a
  delivered/bounced swap is not detected
  (`harness/log/fix-r18-callback-evidence-pairing.md`).
- **The browser cursor counts channel events.** Gaps between visible events
  reveal channel activity (`harness/log/fix-browser-projection-allowlist.md`,
  R-8).
- **Demo supervisor (C-5).** A signal during the spawn loop or a failed
  `pids.json` write can orphan host services
  (`harness/log/fix-pr5-ops-tests.md`).
- **Shared test database (R-9).** The real-dependency gates share
  `proxyloop_test` and fixed ids, so they must run one at a time
  (`docs/development.md`).

## Evaluation-code limits

These live in files frozen by committed evidence, so a fix would move
committed bytes. They are recorded, not fixed.

- **D2-7:** `router_outcome_mismatch` is added to every episode whose Slow
  output failed validation (`runner_v2.py`, frozen).
- **D2-8:** `policy_violation_count` and `leakage_violation_count` are
  constants in the r2–r5 reports, and their leakage scan is key-name only.
- **D2-9:** `provider_config_ref` carries the configuration id, which is the
  provider-holdout split axis, in the frozen r2 views and the 03C pins.
- **D3-5, D3-6:** `qwen_mlx.py` accepts duplicate JSON keys as valid (no
  committed output has one) and reports unattested fingerprints when
  `model_path` is omitted (every real script passes it).
- **D3-7:** the dead `rejection_reasons` field stays in the committed
  trajectory schema; the pipeline's `_matches_environment` fallback still
  labels a non-regenerable row `invalid_verifier_outcome` (audit N1).
- **D3-8:** three copies of one Slow compiler and duplicated tariff
  literals.
- **D3-9:** the frontier adapter accepts any `gpt-5.6-terra-*` model id and
  writes `str(exc)` unbounded (latent; committed strings are at most 104
  characters).
- **D1-10 to D1-12:** V1 split membership is alphabetical, some V1
  docstrings are false, and small V1 defects remain. V1 is frozen; V2
  supersedes it.
- **R-4:** the ML Slow compiler resolves capabilities by exact id; it is
  consistent with every ML manifest today.
- **V1 and V2.** V1's two provider configurations change no outcome. No
  model has been evaluated on the V2 catalogue (`docs/ml-evidence.md`).

Sources for this group: `harness/code_review/repo-audit-D1.md`,
`repo-audit-D2.md`, `repo-audit-D3.md`, `harness/log/fix-p2-ml-eval-hygiene.md`,
`harness/log/fix-content-free-public-ids.md`,
`harness/context/audit-remediation-status.md` §4a.

## Cost

Every figure is from the file named. Relay figures are usage-accounted
estimates (token usage times a tariff), because the relay reports no billed
cost. Modal is a console reading, not a repository artifact.

| Item | Figure | Source |
|---|---|---|
| Phase 03A1-B (r1) hosted conditions | ≈ USD 1.58 (sum of `actual_cost_microusd` over conditions) | `data/evaluation/phase-03a1-baselines-report.json` |
| Phase 03A1-E (r2) | one hosted failure of unknown cost | `docs/ml-evidence.md`, `PLANS.md` |
| Phase 03A1-R (r4) | ≈ USD 3.11 | `data/evaluation/phase-03a1-r4-hosted-rerun-report.json` (`actual_cost_microusd` 3,114,128) |
| Phase 03A1-V (r5) | ≈ USD 0.117 | `data/evaluation/phase-03a1-r5-validity-smoke-report.json` |
| Phase 03C Stage 1b (teacher pilot) | ledger USD 9.55, plus ≈ USD 0.25 of transport smokes and probes | `harness/log/phase-03c-stage1b-teacher-pilot.md` |
| Phase 03C Stage 1c, v6 full run | USD 121.59 accounted (8,003 calls) | `harness/log/phase-03c-stage1c-full-generation.md`; `data/experiments/phase-03c/teacher-full-v6/phase-03c-teacher-generation-report.json` |
| Phase 03C Stage 1c, all runs | ≈ USD 132 accounted (the aborted v5 run's USD 125.84 phantom charge excluded; its real use ≈ USD 0.95) | `harness/log/phase-03c-stage1c-full-generation.md` |
| Phase 03C relay, Stages 1b and 1c | ≈ USD 146 real relay usage | `harness/log/phase-03c-stage1c-full-generation.md`; `harness/context/phase-03c-stage2-handoff.md` §5 |
| Phase 03C Stage 2 training (Modal) | USD 22.25 metered for the phase, of which ≈ USD 18.09 was the training run and USD 4.16 six smoke runs and three CPU probes; billed USD 0.00 (free credit) | `harness/log/phase-03c-stage2-stage3.md`; `harness/context/post-phase-03c-handoff.md` §4 |
| Local compute | one Apple M4 Pro; no dollar cost recorded | `data/experiments/phase-03c/local-parity/product-path-report.json` (`host`) |

Two sources disagree on the Stage 1b/1c relay figure.
`harness/context/post-phase-03c-handoff.md` §4 says "Real relay usage over
Stages 1b/1c was ≈ USD 121.59"; the primary log
(`harness/log/phase-03c-stage1c-full-generation.md`) gives USD 121.59 as the
v6 full run alone and ≈ USD 146 for all Stage 1b/1c runs, as does
`harness/context/phase-03c-stage2-handoff.md` §5. This page follows the
primary log. The ≈ USD 146 covers Phase 03C only; the Phase 03A1 runs above
also used the relay.
