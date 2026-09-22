# Repository Audit — independent review of the Codex-built codebase and docs

## Authorization

Approved by the user on 2026-09-21 as a bounded, read-only repository
change. It runs in the worktree `.claude/worktrees/phase-03c-parallel` on
branch `worktree-phase-03c-parallel` from `main` at `aaae134`, in parallel
with the active Phase 03C Stage 1a session. It does not change
`harness/status.toml`, product code, tests, or artifacts. Its only writes are
the audit artifacts named below.

## Why

Every phase through 07A was implemented by one model family (Codex/Luna) and
independently reviewed by the same family (Terra). The user has not read the
code. The defects that mattered so far (03B evaluator `json.loads`, dropped
schema in the 03B prompt, model/oracle input mismatch in 03A1, module-global
compliance constants in `environment.py`) were found only when code was
reused for a new purpose, never by a phase-gate review. Before building
further agent-side work on this base, the user wants one structured,
adversarial audit of the whole repository with the strongest available
models, producing a trust rating per module and a prioritized remediation
backlog.

## Objective

1. Decide, per module, **keep / refactor / rewrite**, with evidence.
2. Produce a remediation backlog where every item has a reproduction.
3. Map every "Complete / passed / approved / verified" claim in the docs to
   the code, test, artifact, or harness record that supports it, and list
   the claims that nothing supports.

## Rules

- **No reproduction, no finding.** A `Blocking` or `Important` finding must
  name `path:line` and give a concrete failure scenario: a command, an
  input, or a failing test that could be written today. Anything without one
  is a `Note`.
- **Docs claims are hypotheses.** A statement in `README.md`, `PLANS.md`,
  `docs/**`, or a harness log is evidence only after it is traced to code,
  a test, or an artifact.
- **Read the tests of the area.** Every code lane judges whether the tests
  are tautological (verify generated output against itself, assert on
  mocks that encode the expected answer, or never exercise the failure
  branch). "Green tests" is not evidence until the tests are read.
- **Do not fix during the audit.** Findings go to the backlog. Fixes are
  separate PRs, each starting with a failing regression test.
- **The root orchestrator verifies primary evidence** for every `Blocking`
  and `Important` finding before it enters the backlog, marking it
  `confirmed`, `plausible`, or `rejected`.
- Reviewers state which checks they ran and which they did not.

## Severity

| Level | Meaning |
|---|---|
| Blocking | A safety, authorization, money, idempotency, or completion-truth invariant that the docs claim can be violated; or a documented "passed" result that the evidence does not support. |
| Important | A defect with a reproduction that affects correctness, durability, evaluation validity, or a stated contract, but not a safety invariant. |
| Minor | A defect with a reproduction that affects maintainability, edge cases, or a non-critical path. |
| Note | Design concern, over-engineering, unclear docs, or a suspicion without reproduction. |

## Lanes

Sizes are source bytes measured on 2026-09-21. Each lane reads the tests of
its area in addition to the paths listed.

| Lane | Scope | Size | Role / model |
|---|---|---|---|
| A — Architecture and contracts | `docs/architecture.md`; `docs/decisions/2026-08-22-implementation-defaults.md`; `docs/decisions/2026-08-23-fast-slow-orchestration.md`; `CONTEXT.md`; `GOALS.md`; the "system boundaries / safety invariants / non-goals" sections of `docs/specs/2026-08-21-telecom-bill-optimization-agent.md`; `runtime/packages/contracts/src/proxyloop_contracts/contracts.py` and `_base.py` | ~110 KB | `architect` (Fable, high) |
| B1 — Decision and authority core | `runtime/packages/agent_core/src/**`; `runtime/packages/telecom_domain/src/**`; `runtime/packages/openai_adapter/src/**` (`outputs.py` compiler and `adapter.py`) | ~90 KB | `reviewer` (Opus, high) |
| B2 — Case runtime and API | `runtime/packages/case_runtime/src/{runtime,commands,repository}.py`; `runtime/services/api/src/**` | ~130 KB | `reviewer` (Opus, high) |
| C — Persistence, workflow, channel, supervisor | `runtime/packages/case_runtime/src/postgres_repository.py`; `runtime/services/workflow_worker/src/**`; `runtime/packages/connectors/src/**`; `scripts/run_phase_07a_portfolio_demo.py`; `compose.yaml` | ~150 KB | `reviewer` (Opus, high) |
| D1 — Simulator and oracle | `runtime/packages/provider_simulator/src/**` (the `main` version, not the Stage 1a working tree); `tests/contract/**` | ~100 KB | `reviewer` (Opus, high) |
| D2 — Evaluation harness and evidence chain | `ml/evaluation/src/proxyloop_evaluation/{runner,runner_v2,hosted_rerun,replay,replay_v2,artifacts,artifacts_v2,fresh_fixtures,models}.py`; `scripts/run_phase_01b_benchmark.py`; `scripts/run_phase_03a1_*.py`; `data/` checked through the existing `make *-check` targets and spot-checked against `docs/ml-evidence.md` numbers | ~330 KB | `reviewer` (Opus, high); may be split into D2a (runner/runner_v2/models) and D2b (replay/artifacts/fixtures/scripts) |
| D3 — Data factory and model adapters | `ml/data_pipeline/src/**`; `ml/evaluation/src/proxyloop_evaluation/{qwen_mlx,qwen_spec,openai_frontier,fast_output,fast_parse,slow_output,legacy_slow_output,validity_smoke,phase03b_readiness}.py`; `scripts/run_phase_02_data_pilot.py`; `scripts/prepare_phase03b_readiness.py` | ~120 KB | `reviewer` (Opus, high) |
| E — Web and projection boundary | `apps/web/**` (source and tests); `docs/ui/*.md` checked against the implementation; the browser-facing projection in `runtime/services/api/src/proxyloop_api/app.py` | ~150 KB | `reviewer` (Opus, high) |
| F — Documentation claims | All 19 files under `docs/`, `README.md`, `PLANS.md`, `CONTRIBUTING.md`, `PROMPTS.md`, `harness/README.md`, `infra/README.md`, `data/README.md`, `ml/README.md`, `apps/README.md`, `tests/README.md`, `voice/README.md`, `contracts/README.md`. Every completion, pass, approval, or measurement claim is traced to its support; harness contracts, reviews, and logs are opened only as targets of a trace | ~190 KB + traces | `explorer` (Sonnet, medium) builds the claim table; root verifies |
| G — Build, gates, scripts | `Makefile`; `.github/workflows/ci.yml`; `compose.yaml`; `scripts/validate_layout.py`; `scripts/generate_contracts.py`; `contracts/` generated outputs; `scripts/run_phase_04d_control_plane_profile.py`; every `--check` path in `scripts/*.py`; `pyproject.toml` / lock files | ~70 KB | `explorer` (Sonnet, medium) |

Batches: **1** A, B1, B2, G. **2** C, D1, E, F. **3** D2, D3. At most four
lanes in flight; at most three on Opus/Fable at once.

## Baseline before the lanes start

`make preflight` in the audit worktree, then the three real-dependency gates
(`make postgres-check`, `make phase05a-check`, `make phase06b1-check`) if the
Compose profiles can run without colliding with the Stage 1a session.
Results recorded in the audit log so every lane compares against the
observed state, not the documented one.

## Lane output

Each lane writes `harness/code_review/repo-audit-<lane>.md`:

1. Verdict per module in scope: keep / refactor / rewrite, one sentence why.
2. Findings, most severe first, each with: id (`<lane>-<n>`), severity,
   `path:line`, claim being violated (doc or contract reference when one
   exists), reproduction, and suggested fix direction (not a patch).
3. Test-quality assessment: which test files are load-bearing, which are
   tautological or never exercise failure branches.
4. Checks run / not run.
5. Open questions for the root orchestrator.

## Root orchestrator output

- `harness/log/repo-audit.md`: baseline results, batch timeline, per-finding
  verification verdicts, what was not audited and why.
- `docs/research/2026-09-21-repository-audit.md`: trust rating per module,
  the confirmed backlog in priority order, unsupported doc claims, and the
  cross-lane synthesis. The synthesis is produced by `architect` (Fable)
  from the confirmed findings; the root orchestrator and the user own the
  keep / refactor / rewrite decisions.

## Explicitly not audited

- `harness/build-log.md` (144 KB historical log through the Harness v2
  migration).
- `ml/evaluation/src/proxyloop_evaluation/{phase03b_experiment,phase03c_experiment}.py`,
  `scripts/run_phase03b_smoke.py`, `scripts/run_phase03c_smoke.py`,
  `scripts/prepare_phase03b_experiment.py`, `scripts/prepare_phase03c_errata.py`:
  covered by the 2026-09-21 Phase 03B post-training review and the Phase 03C
  Stage 0 review, and under active change by the Stage 1a session.
- Full reads of `data/**` artifacts; they are checked through the existing
  drift targets and spot-checked by D2 and F.
- The Stage 1a working tree in the main checkout; D1 audits `main`, and the
  Stage 1a diff is reviewed at its own gate.

## Non-goals

No code, test, artifact, or doc changes; no fixes; no new phases activated;
no hosted model calls; no credential use; no change to `harness/status.toml`.

## Stop

After `docs/research/2026-09-21-repository-audit.md` is written and the
user has read the backlog. Remediation is a new user decision, item by item.
