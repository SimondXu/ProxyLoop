# Consumer Telecom Bill Optimization Agent

## Summary

Build a consumer agent that can analyze a mobile bill, plan a negotiation, conduct low-latency dialogue against a fictional provider, and continue until it obtains a verifiable bill-reduction outcome or a documented failure. The project demonstrates an end-to-end ML lifecycle by generating and curating consumer-agent trajectories, fine-tuning one Qwen3-4B Fast Response Model, evaluating it on leakage-safe held-out scenarios, serving it behind a typed interface, and integrating it into a durable agent workflow after the model gates pass. Home internet remains a later schema-compatible extension.

## Why This Vertical

Telecom bill optimization provides the strongest combined demonstration of:

- Pine-like consumer advocacy;
- strategic Slow reasoning and low-latency Fast dialogue;
- multi-dimensional offers and user constraints;
- measurable state transitions and savings;
- synthetic-data engineering and post-training;
- approval, evidence, follow-up, and durable workflow behavior.

Retail returns remain a lower-risk benchmark fallback. Car lease, insurance, medical bills, banking disputes, and real-provider automation are excluded from the first vertical because their data, compliance, identity, and outcome-verification costs are materially higher.

## Product Boundary

### Supported user goal

Reduce the recurring cost of one selected postpaid mobile line at a fictional provider without violating user-declared service requirements or contract constraints. An account may contain multiple lines, but the first case optimizes exactly one line.

### Supported provider actions

The first simulator supports exactly:

1. Change to an eligible lower-cost plan.
2. Remove an optional add-on such as insurance or a premium bundle.
3. Apply a predefined retention promotion or one-time credit.

### Required completion receipt

A successful case records:

- old and new recurring price;
- 12-month total cost comparison;
- plan ID/name and feature changes;
- removed add-ons;
- one-time fees or credits;
- contract term and promotion expiry;
- effective date;
- confirmation ID or simulator transition evidence;
- exact user approval version if the action is consequential.

### Non-goals

- Contacting or impersonating T-Mobile or any real provider in the research MVP.
- Storing real account passwords, PINs, payment credentials, or SSNs.
- Making payments, accepting financing, executing credit checks, or auto-signing contracts.
- Optimizing multiple lines in one case or handling device financing in v1.
- Training ASR, TTS, or a speech foundation model.
- Training the Slow Reasoner.
- Claiming that tau2 provider-side results prove consumer negotiation performance.
- Claiming production readiness, autonomous production retraining, or a complete Pine clone.
- GRPO before a stable SFT baseline and verifiable reward exist.

## Users and Primary Journey

1. User provides a redacted bill, current service, usage requirements, budget, forbidden changes, allowed disclosures, and approval policy.
2. System creates a normalized `BillSnapshot`, `ConsumerGoal`, and versioned constraints.
3. Slow Reasoner creates a strategy packet.
4. Fast Model conducts turn-level dialogue with a fictional provider representative.
5. Policy gate prevents unsupported claims, forbidden disclosure, stale strategy, and unauthorized acceptance.
6. Provider returns plan options, promotions, refusals, transfers, or clarification requests.
7. Agent compares total cost and feature impact, replans only when trigger rules require it, and asks the user when a decision exceeds delegated authority.
8. Verifier accepts completion only with sufficient external evidence.
9. Later portfolio phases persist and resume the case across email/call events.

## ML Hypothesis

Fine-tuning `Qwen/Qwen3-4B-Instruct-2507` on verified, consumer-side telecom negotiation decisions will improve local policy adherence and reduce latency/cost relative to the untuned 4B checkpoint, while a hosted frontier Slow Reasoner preserves strategic quality for infrequent complex decisions.

The hypothesis is rejected if the fine-tuned model does not improve family-held-out outcomes without worsening false completion, unsupported facts, PII disclosure, or serving latency.

The checkpoint is selected as the implementation default, not assumed to be successful. A pre-training spike must still record its license, context configuration, structured-output behavior, target hardware, and project-owned baseline before full data generation or training.

## Fast/Slow Coordination

### Authority and shared state

Fast and Slow are separate model interfaces coordinated by a deterministic Router. They never call one another, share hidden chain-of-thought or KV cache, mutate Case state, authorize side effects, or decide final completion.

Both receive allowlisted views derived from one immutable, model-external Case Context Snapshot. Fast receives a bounded recent-event window plus the current valid Strategy Packet and verified facts. Slow receives a broader safe Case view, relevant visible-event history or deterministic summary, domain policy, and the current simulator capability manifest. Every output echoes version and planning-basis pins so stale results can be traced and rejected.

One Case may have parallel Fast/Slow reads, but it has one serialized state-write and side-effect lane. The text research MVP may wait synchronously for mandatory Slow refresh; later voice work may use bounded concurrent Fast acknowledgement while Slow works.

### Deterministic routing and Slow triggers

The Router selects `fast_now`, `slow_refresh`, `fast_now_and_slow_refresh`, `wait_for_approval`, `verify_only`, or `terminal` with deterministic reason codes. A Fast `reasoner_request` is advisory and cannot bypass mandatory routing policy.

Outcomes are mutually exclusive and evaluated in order: an already verified terminal Case uses `terminal`; new Evidence or a completion candidate uses `verify_only`; a blocking current Approval Request uses `wait_for_approval`; mandatory Slow work uses `slow_refresh`, except that an explicitly permitted non-consequential acknowledgement may use `fast_now_and_slow_refresh`; an ordinary turn under a current compatible strategy uses `fast_now`. Deterministic handler results append a new event before the Router runs again.

- case initialization;
- changed user goal, hard constraint, or Delegated Authority;
- provider refusal or materially new offer structure;
- stalled dialogue or repeated turn;
- conflicting verified facts;
- accepted Fast Model low-confidence/high-risk request;
- proposed consequential action;
- verifier `needs_replan`, or candidate completion with missing, expired, or incompatible strategy/basis;
- expired or planning-basis-incompatible Strategy Packet;
- new Evidence that may change strategy or completion.

The initial target is for Slow calls to occur on no more than 20%–30% of dialogue turns. This is an evaluation target, not a hard product truth; the routing spike may revise it.

### Fast Model objective

Fast Model training covers:

- dialogue-act selection;
- fact-delta extraction with provenance;
- reasoner-trigger classification;
- candidate-completion classification;
- concise response generation conditioned on the strategy.

Fast Model training does not cover strategy generation, multi-step tool selection or argument planning, MCP/phone execution, long-term memory, approval, consequential acceptance, Evidence verification, final completion, credentials, or workflow durability. The existing optional `FastTurnDecision.action_intent` field remains wire-compatible, but Phase 03A1 Fast requests and accepted outputs require it to be `null`.

The training pipeline must measure whether response tokens dominate the loss. If necessary it uses field-aware examples, loss masks/weights, or separate auxiliary datasets so policy fields are not reduced to decorative JSON.

## Data Strategy

### Source classes

| Source | Role | Headline test eligibility |
|---|---|---|
| Project-owned fictional telecom scenarios | Primary task/environment source | Yes, if family/entity held out before derivation. |
| tau2 Telecom schemas/tasks | Structural seed and comparison reference | Not automatically; audit and contamination labels required. |
| Pine tau2 voice trajectories | Voice/dialogue research and optional auxiliary data | No for overlapping tau2 headline tasks after training exposure. |
| Licensed general spoken-dialogue data | Disfluency/repair auxiliary data | Only on separate robustness tests. |
| Teacher/provider simulator rollouts | Primary SFT candidates | Yes only when derived from training families. |
| Production/test-channel feedback | Later hard-negative source | Quarantine and human approval required; never automatic. |

### Dataset stages

```text
raw immutable source
  -> normalized schema
  -> generated executable trajectories
  -> validated and deduplicated candidates
  -> human-reviewed curated set
  -> immutable train/dev/test manifests
```

Each record stores source/license, base scenario family, entity cluster, derivation parent, teacher/provider/judge model snapshots, prompt/config hashes, simulator version, verifier result, review state, rejection reasons, and content hash.

The Phase 02 one-turn pilot validates the Data Factory interface only. Before any teacher-backed expansion or training-corpus claim, the project freezes the multi-turn evaluation protocol and held-out manifests, runs untuned Fast with Slow disabled/enabled, and records failure slices. Public-data SFT comes next only for learnable Fast-policy gaps; project-specific generation is targeted to gaps that remain.

### Leakage controls

- Freeze family/entity/provider-branch splits before teacher generation.
- Keep every derivative of a base scenario in the same split.
- Strip provider policy, DB, reference actions, evaluation criteria, and reward information from model observations.
- Run exact and semantic duplicate detection across splits.
- Maintain a contamination registry for tau2, Pine, and other public sources.
- Never use Pine's full public task set for training and then report the same tasks as unseen evaluation.

### Data sizing

Data volume is selected by learning curves rather than a fixed promise:

1. 100–200 trajectories to validate schema, simulator, filter rate, human review time, and cost.
2. 250/500/1,000 trajectory experiments across increasing family counts.
3. Expand toward 1,000–3,000 curated trajectories only while held-out family generalization continues to improve.

Ordinary examples receive random human sampling so false-negative quality rates can be estimated; high-risk completion, PII, disclosure, and escalation labels receive full or substantially higher review.

## Simulator Design

### Provider state

- account and line/service identities;
- current plan and plan catalog;
- usage and required capabilities;
- recurring bill line items and optional add-ons;
- contract/end date and plan-change eligibility;
- public offers and private retention ladder;
- offer expiry and one-time fees;
- annual credit budget and transfer state.

### Scenario families

- cheaper plan sacrifices a hard-required feature;
- promotion expires and produces higher 12-month cost;
- add-on removal produces the best valid outcome;
- retention credit requires an unacceptable new term;
- several plans have similar monthly price but different fees;
- provider refuses once but permits transfer/escalation;
- missing or conflicting bill information requires clarification;
- offer changes after user constraints are updated;
- old approval becomes stale after a revised offer;
- conversation includes adversarial instruction or irrelevant disclosure request.

### Provider ceiling

Before training, run a scripted/oracle consumer against the provider ensemble. If the provider cannot reliably execute valid outcomes, model training is premature because reward attribution would be dominated by the environment.

## Baselines and Experiments

### Required 2x2 comparison

| Fast Model | Slow Reasoner | Purpose |
|---|---|---|
| Untuned | Off | Small-model baseline. |
| Untuned | On | Measures routing/strategy value before training. |
| SFT | Off | Isolates fine-tuning value. |
| SFT | On | Target system. |

Also record a frontier-only upper-cost baseline and a scripted/oracle environment ceiling.

### Primary metrics

- family-held-out constraint-valid completion rate;
- false-completion rate;
- unsupported verified-fact rate;
- hard-constraint and disclosure violations;
- total 12-month savings and valid-offer utility;
- dialogue-act macro F1;
- fact-delta precision/recall;
- reasoner-request precision/recall and call rate;
- turns and model cost per successful episode;
- Fast Model p50/p95 TTFT and full-turn latency;
- provider-model and random-seed sensitivity.

### Statistical reporting

- paired-by-scenario comparisons where possible;
- bootstrap confidence intervals or an appropriate paired test;
- multiple provider models/seeds;
- results by scenario family and failure category, not only one average;
- all failed and negative training runs retained in the experiment record.

## Proposed Technical Stack

| Concern | Choice | Boundary |
|---|---|---|
| Web | Next.js + TypeScript | Approvals, timeline, input, receipt; no direct model/channel credentials. |
| API | FastAPI + Pydantic | Control plane and typed contracts. |
| Business database | PostgreSQL | Authoritative cases, facts, offers, approvals, evidence, outbox, audit. |
| Durable workflow | Temporal Python SDK | Added after ML gates; timers/signals/retries/approval waits. |
| Slow adapter | PydanticAI or small provider-neutral wrapper; OpenAI `gpt-5.6-terra` first | Structured hosted-model calls only; provider remains configurable. |
| Fast serving | vLLM on Linux/CUDA | OpenAI-compatible structured inference; local Apple serving is development-only. |
| Training | Transformers + PEFT/QLoRA + TRL/custom loss logic | Qwen3-4B only; 4-bit QLoRA, initial 8K sequence cap, one 24GB CUDA GPU. |
| Data | Parquet + Polars/DuckDB + Pydantic/Pandera | Versioned transformations and validation. |
| Artifacts | S3-compatible storage + immutable manifests | Datasets, checkpoints, audio, reports. |
| Experiment registry | MLflow OSS | Runs, metrics, datasets, artifacts, and promotion metadata; local first, database/object storage later. |
| Voice | LiveKit Agents + SIP provider | Later controlled channel only. |
| Observability | OpenTelemetry-compatible traces and metrics | Correlates case, model, workflow, and channel. |
| Local infrastructure | Docker Compose | Postgres, Temporal, object storage/telemetry as needed. |

## Delivery Plan

### Phase 0: Repository and Contracts — 3–5 days

Deliverables:

- monorepo skeleton and root commands;
- canonical Pydantic domain contracts and generated schemas;
- architecture tests preventing forbidden dependencies;
- CI for lint, type checks, unit tests, and contract drift;
- pinned initial dependency and Python/Node versions.

Gate: all packages install reproducibly and one sample contract round-trips through Python and generated TypeScript.

### Phase 1: Simulator and Benchmark — 1.5–2 weeks

Deliverables:

- fictional provider state machine and plan/offer schema;
- initial 15–20 scenario families;
- Safe Observation Adapter;
- deterministic business/safety verifier;
- custom family/entity split generator;
- scripted/oracle consumer and at least two provider configurations.

Gate: no leaked provider/gold fields; oracle/provider ceiling is high enough for useful attribution; simulator transitions and verifier pass adversarial unit tests.

### Phase 2: Data Factory — 1.5–2 weeks

Deliverables:

- normalized trajectory schema;
- teacher/provider rollout runner;
- lineage, licensing, PII, deduplication, leakage, and rejection pipelines;
- 100–200 trajectory pilot and cost/quality report;
- annotation guide and review sample.

Gate: provenance completeness is 100%; cross-split leakage scan is clean; pilot quality and cost justify expansion.

### Phase 3A0: Fast/Slow Architecture Gate

Deliverables:

- deterministic Router outcomes, priorities, and mandatory Slow triggers;
- model-external Case Context Snapshot and separate Fast/Slow Model Views;
- planning-basis, event-cursor, Slow-work, stale-result, and serialized-write semantics;
- capability, policy, approval, execution, Evidence, and completion ownership;
- bounded Qwen Fast training target and prohibited responsibilities;
- Phase 3A1 implementation prerequisites and acceptance criteria.

Gate: architecture responsibilities have one authority each; Pine public statements and ProxyLoop proposals are separated; no model, training, runtime service, external capability, or product implementation begins.

### Phase 3A1: Multi-Turn Evaluation Harness and Untuned Baselines

Deliverables:

- implemented Case coordinator, Router, Fast/Slow interfaces, and deterministic local adapters;
- simulator-only Capability Manifest and serialized capability executor;
- complete multi-turn episode/event export;
- frozen development, family/entity/provider-held-out, and safety manifests;
- untuned Fast with Slow disabled/enabled, scripted-oracle, and frontier-reference baselines;
- structured-output, policy, safety, end-to-end, latency, cost, and failure-slice reports.

Gate: the evaluation environment attributes failures to model behavior rather than routing, stale state, missing capabilities, or simulator defects; baseline evidence decides whether open-data SFT is justified.

### Phase 3B: Open-Data SFT, Gap Data, and Evaluation

Deliverables:

- base-model selection report;
- public-data source/license/role/contamination audit;
- open-data-only SFT baseline when Phase 3A1 shows learnable Fast gaps;
- project-specific generation only for measured residual failure slices;
- four required Fast/Slow baselines;
- QLoRA/SFT training and reproducible configs;
- learning curves across data/family sizes;
- policy, safety, end-to-end, latency, cost, and statistical reports;
- model and dataset cards.

Gate: practical family-held-out improvement over the frozen untuned baseline without safety regression; confidence interval, source ablation, and failure slices are reported. A provisional target is at least roughly 5 percentage points of useful improvement, but the final threshold is frozen before full training based on pilot power analysis.

### Phase 4: Serving and Control Plane — 1–2 weeks

Deliverables:

- one selected Fast inference runtime;
- typed model gateway;
- FastAPI case/episode API;
- PostgreSQL fact/evidence store;
- traces linking model/data/prompt/simulator versions;
- load, structured-output, OOM, timeout, and fallback tests.

Gate: structured output and semantic validation meet the frozen reliability target; serving p95 latency fits the target hardware budget; rollback to the prior adapter is proven.

### Phase 5: Durable Agent Loop — 1.5–2 weeks

Deliverables:

- Temporal case workflow;
- wait/replan/approval/completion states;
- idempotent activity/outbox design;
- duplicate-event and worker-crash fault injection;
- continue-as-new/history-growth policy.

Gate: repeated kills, retries, and duplicate callbacks produce no duplicate consequential side effects or stale approvals.

### Phase 6: Controlled Channels and UI — 2–3 weeks

Deliverables:

- Next.js case/approval/timeline/receipt UI;
- Gmail test-account integration, initially draft-only;
- optional LiveKit call to an owned/controlled number;
- segmented voice latency measurements and interruption tests;
- disclosure, recording, retention, and deletion controls appropriate for the demo.

Gate: all external sends/calls remain controlled and auditable; no real-provider automation is required for completion.

### Phase 7: Portfolio Hardening — 1 week

Deliverables:

- end-to-end demo script and failure-recovery demonstration;
- experiment and architecture reports;
- monitoring dashboard;
- resume bullets using only measured results;
- limitations, negative results, cost, and reproducibility notes.

Gate: a reviewer can reproduce the simulator benchmark and understand which results are observed versus proposed.

### Estimated duration

- Research ML MVP through Phase 3: approximately 6–8 focused weeks.
- Integrated portfolio demo through Phase 7: approximately 12–16 focused weeks.
- Part-time execution, data review, GPU debugging, or voice integration can extend the schedule materially.

## Budget Control

No fixed total should be promised before the 100–200 trajectory pilot. Track:

```text
generation cost =
raw trajectories
× teacher/provider/judge tokens per trajectory
× model rates
÷ accepted-sample rate
+ retries and human-review cost
```

Use hard stage budgets and stop/go reviews. A planning envelope of several hundred to roughly one thousand dollars is reasonable for a disciplined portfolio effort using rented compute and APIs, but synthetic generation, repeated evaluation, and failed GPU runs can exceed it. Voice minutes are normally a smaller demo cost than teacher rollouts, human review, and training iteration.

## CI and Verification Strategy

Required CI lanes:

- docs and schema validation;
- Python formatting, lint, typing, and unit tests;
- web lint, typing, component tests, and build;
- contract-generation drift check;
- simulator deterministic and property-based tests;
- leakage and dataset-manifest tests;
- CPU smoke tests for data/training code;
- API/workflow/Postgres integration tests;
- manually triggered GPU benchmark/training jobs;
- manually approved external email/voice smoke tests.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Synthetic teacher/provider/judge share one bias | Cross-family roles, deterministic checks, blind/random human review. |
| Simulator is too cooperative | Provider ensemble, refusal/ambiguity families, oracle ceiling and human role-play gap tests. |
| Fast Model learns NLG rather than policy | Explicit policy fields, counterfactual pairs, field-aware loss/evaluation, ablations. |
| Data count hides low family diversity | Learning curves by family count and derivative clustering. |
| tau2/Pine contamination inflates results | Project-owned benchmark and contamination registry. |
| Slow calls erase latency/cost gains | Frozen triggers, call-rate metric, value-added ablation, budget gate. |
| Temporal retries duplicate external actions | Outbox/idempotency/provider-event keys and fault injection. |
| Real channel compliance derails project | Simulator and owned test channels satisfy portfolio completion; real providers remain out of scope. |
| CUDA/audio dependencies destabilize runtime | Separate ML and voice locks inside one monorepo. |
| Scope expands into multiple domains or RL | One telecom vertical; GRPO and other domains require explicit post-gate decisions. |

## Implementation Defaults Before Scaffolding

1. Project identity: `ProxyLoop`; GitHub repository `ProxyLoop-A-Durable-Consumer-Negotiation-Task-Completion-Agent`.
2. First account type: one selected postpaid mobile line. Keep `service_type` and provider contracts extensible for home internet, but do not build home-internet scenarios in the first benchmark.
3. Fast checkpoint: `Qwen/Qwen3-4B-Instruct-2507`, non-thinking-only. Run the base-model smoke benchmark before full training.
4. Training hardware: local MLX-LM smoke runs on the M4 Pro; canonical 4-bit QLoRA targets one 24GB CUDA GPU with an 8K sequence cap. Escalate to 48GB only after measured OOM or unacceptable throughput.
5. Slow provider: OpenAI `gpt-5.6-terra` with structured outputs and medium reasoning effort as the initial setting. Preserve a provider-neutral interface and use a second model family for selected evaluation/teacher checks when budget permits.
6. Experiment system: MLflow OSS. Start with local SQLite/artifacts; use a database-backed registry and S3-compatible artifacts when the integrated stack needs shared state.
7. Fast serving: vLLM is the promoted Linux/CUDA runtime. SGLang is out of v1 unless vLLM fails a frozen structured-output or latency gate. Apple-local serving stays behind the same OpenAI-compatible gateway but is not the deployment reference.

## Remaining Operational Decisions

1. Exact rented GPU provider and stage budget; choose the vendor immediately before the training spike because availability and prices change.
2. Exact object-store deployment: local filesystem first, MinIO for integrated local infrastructure, and an S3-compatible interface in code.
3. Weekly hours available; this determines whether the 12–16 week integrated-demo estimate is realistic.
