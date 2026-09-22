# Progress Log

Concise chronological record of what has been delivered, keyed to merged PRs.
Live authorization state is `harness/status.toml`; the phase index and gate
artifacts are `PLANS.md`; per-phase verification evidence is `harness/log/`
(Phase 04C onward) and `harness/build-log.md` (earlier phases). This file does
not restate those; it answers "where are we and how did we get here".

## Current state (checked 2026-09-21)

- Harness: `idle`. Last completed bounded phase: **07A Reproducible Local
  Portfolio Demo** (PR #29, `763a1a9`, 2026-08-26).
- Integrated on `main`: canonical contracts, deterministic fictional-Provider
  simulator and benchmark, Phase 02 data pilot, Fast/Slow routing, multi-turn
  evaluation Harness with untuned baselines, one closed QLoRA experiment
  (`NO_GO_STOP_PHASE03B`), FastAPI Thin Agent Runtime (scripted and explicit
  model mode), PostgreSQL Case store, control-plane operations, Temporal
  `CaseWorkflow`, Next.js conversation intake with durable resume, synthetic
  `local_mailbox` channel, and one credential-free `make portfolio-demo` stack.
- Not started / unauthorized: Phase 06B2 (real Provider/email/MCP/credential
  channels), full Phase 07 hardening, voice, authentication, production UI,
  promoted-model serving, deployment, and any further training or rerun.
- Known placeholders: `runtime/services/model_gateway/`, `voice/worker/`, and
  `infra/{compose,migrations,observability,temporal}/` contain only
  `.gitkeep`; real infra wiring is the root `compose.yaml`.
- Test surface at the last gate (2026-09-22, after audit Group 1 and
  Phase 03C Stage 1c): Runtime 316 passed + 39 guarded infrastructure
  skips, ML 318 passed + 1 skipped, Web 51 vitest tests,
  plus contract/artifact drift checks (`make preflight`).

## 2026-08-21 — Planning

- Consolidated research, chose the fictional-provider telecom vertical, wrote
  the specification, architecture, monorepo ADR, and initial plan. Details in
  `docs/planning/initial-project-plan.md`.

## 2026-08-22 — Repository foundation and contracts

- Selected the `ProxyLoop` identity and implementation defaults
  (`docs/decisions/2026-08-22-implementation-defaults.md`).
- Phase 00A: monorepo skeleton, dependency zones, layout CI (`81d28b3`, PR #1).
- Phase 00B: 13 canonical Pydantic contracts with generated JSON Schema and
  TypeScript, fixtures, and drift checks (`98a7514`, PR #2).

## 2026-08-23 — Simulator, benchmark, data pilot, Fast/Slow freeze

- Phase 01A: deterministic Provider loop, exact approval gate,
  content-addressed Evidence, `ConfirmationAuthority` forgery guard (PR #3).
- Sol-governed delegation/merge workflow adopted (PR #4).
- Phase 01B: 16 scenario families × 2 configurations, Safe Observation
  boundary, split manifest, 32-scenario scripted ceiling (PR #5).
- Phase 02: normalized trajectory schema, one-turn pilot with quality and
  quarantine reports, annotation guide (PR #6).
- Phase 03A0: Fast/Slow orchestration and shared Case context frozen as
  `docs/decisions/2026-08-23-fast-slow-orchestration.md` (PR #7).
- Phase 03A1-H: deterministic multi-turn evaluation Harness (PR #8).

## 2026-08-24 — Baselines, erratum, hosted rerun, validity smoke, Runtime 04A

- Phase 03A1-B: untuned Qwen/Terra baselines (PR #9).
- Phase 03A1-E: evaluation erratum and leakage-safe r2/r3 with a terminal
  Provider blocker recorded honestly (PR #10).
- Phase 03A1-R/V: Slow output union corrected to `anyOf`, full hosted r4
  matrix completed, six-episode r5 validity smoke improved the baseline from
  0/6 to 5/6 after prompt/input parity; the remaining fee case is an
  evaluation-contract mismatch (PR #11).
- Phase 04A: Thin Agent Runtime — FastAPI service, in-memory Case repository,
  typed Fast/Slow routing, deterministic offer policy shared with the oracle,
  version-bound approvals, at-most-once fictional execution, Evidence, and
  completion verification (PR #12).

## 2026-08-25 — Model adapter, QLoRA closeout, Web demo, persistence

- Phase 04B: OpenAI-compatible Fast/Slow adapter, explicit `--mode model`,
  mocked-transport failure gates, localhost black-box smoke (PR #13).
- Phase 03B: one frozen six-scenario 40-iteration QLoRA smoke and one
  canonical Arm B evaluation; clean Terra review returned
  `NO_GO_STOP_PHASE03B` (Arm B 0/6 valid, `arm_b_hard_gates_pass=false`); no
  expansion or promotion authorized (PR #15, closeout PR #16).
- Minimal local Web demo: Runtime-backed Next.js conversation UI (PR #18).
- Local Conversation Intake UX: four confirmed fictional-telecom facts, one
  Runtime-owned Case, exact Web snapshot verification (PR #20).
- Harness v2 agent/skill routing tightened (PRs #17, #22).
- Phase 04C: opt-in PostgreSQL aggregate persistence with revision CAS,
  strict decode, and restart/recovery evidence (PR #23).

## 2026-08-26 — Control plane, Temporal, durable Web, mailbox, demo

- Phase 04D: correlated JSON operation records, liveness/readiness, redacted
  failure categories, credential-free diagnostic profile, fake-model to
  scripted/PostgreSQL switch proof (PR #24, docs PR #25).
- Phase 05A: Temporal `CaseWorkflow` in `runtime/services/workflow_worker`
  with command ordering, retries, and recovery over PostgreSQL (PR #26).
- Phase 06A: durable Web Case resume — strict browser locator, one exact
  pending-command retry via `Idempotency-Key` (honoured in the durable
  Temporal profile; direct mode ignores the header), readiness plus GET-first
  recovery, monotonic projection guard, bounded polling, truthful
  expired/finalizing/reconnect states (PR #27).
- Phase 06B1: synthetic `local_mailbox` in `runtime/packages/connectors` —
  SHA-256-fingerprinted raw-byte fixtures (unkeyed; integrity, not
  authentication), PostgreSQL inbox/outbox authority, Temporal
  dispatch, delivered callback, two channel Evidence records (PR #28).
- Phase 07A: `make portfolio-demo` / `-stop` / `-reset` / `-channel` /
  `-recovery` supervising Compose PostgreSQL + Temporal, worker, Runtime, and
  production Web; two separate demo scenes; portfolio narrative in
  `docs/portfolio-demo.md` (PR #29). Harness returned to `idle`.

## Reboot check

| Question | Answer |
|---|---|
| Where am I? | Harness idle after Phase 07A; all bounded phases through 07A merged on `main`. |
| Where am I going? | Nothing is authorized. The next candidates are Phase 06B2 (real controlled integration) or the remainder of Phase 07 hardening; each needs an explicit user gate and a new `harness/build/phase-*.md` contract. |
| What's the goal? | A portfolio-grade, simulator-first durable consumer negotiation agent with verifiable completion; no production or real-carrier claim. |
| What have I learned? | Untuned hosted Slow reasoning reaches 5/6 once model and oracle see the same public inputs; the bounded 4B QLoRA smoke did not produce valid structured output and was stopped. See `harness/build/phase-03a1-evaluation-validity-smoke.md` and `harness/build/phase-03b-qwen-qlora-smoke.md`. |
