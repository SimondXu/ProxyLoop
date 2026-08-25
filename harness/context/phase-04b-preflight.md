# Phase 04B Preflight

Date: 2026-08-25

This file records activation-time observations and frozen decisions. It does
not claim Phase 04B implementation, focused tests, review, CI, or merge success.

## Activation evidence

- `git fetch --prune origin` completed before activation.
- Local and remote `main` are synchronized at `75974da`, the Phase 04A squash
  merge from PR #12.
- The worktree was clean. The active branch is
  `feat/phase-04b-model-backed-runtime`, created from that exact `main`.
- One preserved stash remains from the old Phase 03A1 validity-smoke work and
  is not part of this phase.
- The separate pushed `docs/agent-architecture-alignment` branch at `2ed4a90`
  contains only `PLANS.md` and `docs/architecture.md`; it is not merged into or
  used as the Phase 04B base.
- The user explicitly approved Phase 04B as the single active bounded
  implementation phase and separately prohibited external model calls without
  additional confirmation.

## Baseline verification

- Unmodified `make preflight` passed on the Phase 04B branch.
- Runtime/contract/integration tests: 162 passed.
- ML tests: 115 passed.
- Runtime and ML Ruff, strict mypy, contract/TypeScript drift, Phase
  01B/02/03A1 artifact checks, repository layout, both uv locks, frozen offline
  pnpm, script compilation, Docker Compose, and Git diff checks passed.
- No external model/API call was made and no credential or `.env` was read.

## Observed implementation boundary

- `FastAdapter` and `SlowAdapter` are typed protocols in `agent_core` and are
  already constructor-injected into `ThinAgentRuntime`; scripted adapters are
  the current default.
- `CaseCoordinator` independently validates Fast/Slow pins, Case/strategy
  identity, planning basis, expiry, and forbidden Fast `action_intent`.
- `ThinAgentRuntime` owns deterministic policy, approval creation,
  fictional-Provider execution, Evidence capture, and completion verification.
- The API currently has only an importable ASGI app. There is no committed
  runtime server command, uvicorn dependency, OpenAI SDK dependency, model-mode
  configuration, or localhost black-box test.
- A rejected Fast result currently needs an explicit fail-closed Runtime path
  before policy derives an approval; Phase 04B must not silently continue after
  a model failure or stale result.
- No `.codegraph/` directory exists, so source navigation used `rg` and direct
  reads.

## Evaluation adapter reuse decision

`ml/evaluation/openai_frontier.py` is not suitable for Runtime reuse. It freezes
Terra/29qg identifiers, evaluation cost ceilings and call caps, provenance,
error history, artifact replay, and ML-private semantic compilers. Importing it
would make Runtime depend on `ml/evaluation` and couple product behavior to
historical experiment evidence. Copying the whole file would also bring
evaluation-only machinery into the product path.

The minimal shared seam is therefore the existing typed adapter protocols and
canonical contracts. Phase 04B may implement only the small runtime-facing
Structured Outputs DTO/compiler needed for one OpenAI-compatible path while the
historical evaluation implementation and artifacts remain untouched.

## Frozen ownership

- Sol owns phase architecture, this contract/context, status/build-log updates,
  integration decisions, durable review evidence, Git publication, and final
  merge/cleanup. Sol does not implement product code.
- One Luna xhigh implementer owns the new runtime adapter package, API runtime
  failure/configuration/server wiring, runtime dependencies/lock, Make/README
  command surface, layout gate updates, and all Phase 04B code/tests. No other
  write-enabled agent may overlap these files.
- One Terra high reviewer later owns read-only independent review and may run
  verification, but does not edit, commit, push, or merge.

## Scope boundary

No external model smoke, further evaluation, r6/r7, training, database,
Temporal, real tool/Provider, authentication, channel, voice, UI, deployment,
release, credential, or PII work is active.
