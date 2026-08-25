# ProxyLoop Agent Instructions

This file is the repository-level operating contract for Codex and delegated agents. Product requirements remain authoritative in the linked specification; this file controls how implementation work is prepared, executed, reviewed, and evidenced.

## Read Order

On first orientation, after a compacted/resumed session, or after a material
phase, branch, or repository-state change, read:

1. `AGENTS.md`
2. `GOALS.md`
3. `CONTEXT.md`
4. `PLANS.md`
5. the single active file under `harness/build/`
6. any phase-specific material under `harness/context/`
7. the `harness/build-log.md` phase-status table, entries named by the active
   phase or current bounded change, and the newest relevant entry blocks
8. the relevant source files and tests

Do not reread unchanged canonical documents for every delegated slice. Do not
scan the complete append-only build-log history unless an unresolved claim,
artifact, regression, or audit requires older evidence. Delegated agents follow
their task packet and read only the smallest evidence set needed for that task.

Do not treat a roadmap item as permission to implement it. Only an explicitly approved phase is active.

## Context and Evidence Routing

Sol owns the durable working context and final judgment. Keep these decisions
in the root context: shared architecture and interfaces, authorization and
completion policy, canonical contract or evaluator semantics, conflicting
evidence, scope changes, and phase-gate decisions. Sol must read the final diff
and the evidence used to make any approval or completion claim.

Delegate read-only exploration when a concrete question requires cross-directory
mapping, call-chain or data-lineage tracing, test-impact discovery, artifact
inventory, or noisy log inspection that can be summarized independently. Sol
should investigate directly when the answer is contained in one to three tightly
related files or when the question itself requires one of the retained decisions
above.

Prefer a fresh, bounded context for explorers and reviewers
(`fork_turns="none"` when the caller supports it). Pass the smallest self-contained
task packet: objective, constraints, known paths, exact questions, expected
evidence format, and escalation triggers. When a user decision cannot be
summarized safely, pass only the smallest recent context that contains it. Reuse
the same subagent for clarification before repeating the same discovery with a
new agent.

Explorers return evidence cards, not transcripts: a direct answer, precise
path/symbol or path/line support, checks run or unrun, conflicts and unknowns,
and a short "Sol must read" list. Escalate to Sol instead of resolving ambiguity
when evidence conflicts or the task reaches architecture, authorization,
canonical contracts, evaluator meaning, security boundaries, or a phase gate.

## Current State

- Repository foundation is complete.
- Phase 00B, canonical contracts and contract verification, was squash merged to `main` as `98a7514`.
- Phase 01A was independently reviewed and squash merged to `main` as `f7f3cf7`.
- Phase 01B simulator breadth and benchmark is complete, independently reviewed, and validated by the repository phase gate.
- Phase 02 Data Factory and trajectory pilot was independently reviewed, passed CI/GitGuardian, and was squash merged to `main` as `f45b1ea` through PR #6. Its human review sample remains `pending_human` and `training_ready=false`.
- Phase 03A0 Fast/Slow architecture and acceptance-criteria gate was independently reviewed, passed CI/GitGuardian, and was squash merged to `main` as `54afcb8` through PR #7.
- Phase 03A1-H deterministic multi-turn Harness was squash merged as `e08c9b6` through PR #8.
- Phase 03A1-B untuned Qwen/Terra baselines completed its frozen model matrix, independent review, and PR #9 CI/GitGuardian gates.
- Phase 03A1-E evaluation erratum and leakage-safe second run completed its local/independent gates with an honest terminal Provider blocker and passed PR #10 CI/GitGuardian. Its r3 report is a source-bound offline re-attribution of immutable r2 evidence, not a retry or training run.
- Phase 03A1-R hosted baseline reliability rerun completed its full corrected r4 matrix. The original unsupported `oneOf`/`discriminator` attempt is preserved separately; the canonical r4 uses OpenAI-supported `anyOf`, has complete usage accounting, and records `phase_completion_ready=true`.
- Phase 03A1-V evaluation-validity smoke completed its six-episode diagnostic. With the same Qwen/Terra models, prompt/input parity improved the selected baseline from 0/6 to 5/6 end-to-end valid; the remaining fee case exposes a hidden evaluator predicate. Its r5 artifact is diagnostic evidence, not a training or quality gate.
- The Phase 03A1-R/V closeout recorded `No implementation phase is active` before the explicit Phase 04A activation gate.
- Phase 03A1-R/V was squash merged through PR #11 as `e501e0f`; the CI phase-gate and GitGuardian checks passed.
- Phase 04A Thin Agent Runtime is complete and independently approved on the short-lived `feat/phase-04a-thin-agent-runtime` branch from `e501e0f`. Its executable contract is `harness/build/phase-04a-thin-agent-runtime.md`, its durable review is `harness/code_review/phase-04a-thin-agent-runtime.md`, and its activation baseline is `harness/context/phase-04a-preflight.md`.
- Phase 04A is limited to a local FastAPI, simulator-backed thin loop with an in-memory Case store interface, deterministic authorization/execution/completion, and one multi-turn integration path. More evaluation, training, PostgreSQL, Temporal, real tools or Providers, auth/channels/voice/UI, deployment, and release remain inactive.
- Phase 04B Model-backed Thin Agent Runtime was independently reviewed, passed both PR-head CI/GitGuardian gates, and was squash merged through PR #13 as `6daa1bc`. Its bounded scope is one runtime-owned OpenAI-compatible typed Fast/Slow adapter, mocked transport, fail-closed model errors, explicit opt-in configuration, a local server command, and a localhost black-box smoke while retaining the fictional Provider and deterministic authority boundaries.
- Phase 03B is complete and squash merged as PR #15 (`f441335` short) from `experiment/phase-03b-readiness-remediation`. Its executable contract is `harness/build/phase-03b-qwen-qlora-smoke.md`, its readiness evidence is `harness/context/phase-03b-readiness-preflight.md`, and its final comparison is `data/experiments/phase-03b-qlora-smoke/results/comparison.md`. The final decision is `NO_GO_STOP_PHASE03B`; no implementation phase is active.
- The one frozen QLoRA training run and one canonical Arm B evaluation are complete as descriptive evidence. The No-Go combines Arm B schema/canonical/E2E `0/6`, six invalid JSON outputs, mostly unassessable apparent safety zeros, unsupported `4/6`, and `arm_b_hard_gates_pass=false`. That boolean is only a necessary detector-based safety summary, not sufficient for Go, evaluability, task quality, or promotion. No data expansion, additional training, model rerun, adapter promotion, deployment, or next phase is authorized. Phase 03A1 continuation, r6/r7, PostgreSQL, Temporal, real tools or Providers, deployment, channels, voice, and UI remain inactive.
- Product services, model training, and external channels are not implemented.
  The bounded local Web demo was squash merged through PR #18 as `ef2ce53`;
  the post-merge Repository checks passed and its fully merged short-lived
  branch was safely removed locally and remotely. The legacy local-only UI
  worktree/branch remains preserved. The Local Conversation Intake UX was
  independently approved, passed final PR-head CI/GitGuardian, and was squash
  merged through PR #20 as `02466df`; post-merge Repository checks passed and
  its fully merged short-lived branch was removed locally and remotely. Its
  contract is `harness/build/phase-local-conversation-intake-ux.md`. It remains
  a bounded local fictional-telecom extension and does not activate production
  UI/channel/deployment boundaries. No implementation phase is active after
  this closeout.

## Working Rules

- Keep at most one implementation phase active.
- Use the smallest change that satisfies the active phase acceptance criteria.
- Do not begin the next phase automatically after completing the current one.
- Preserve existing user work and unrelated changes.
- Once the user approves a bounded phase or repository change, Sol may create its branch, commit, push, open and review its pull request, squash merge it, and clean up its fully merged short-lived branch without separate approval for each Git step.
- Explicit user approval is still required to expand scope, activate the next phase, deploy or publish a release, contact real external parties, use credentials, perform destructive operations, force-push, or rewrite shared history. Validated cleanup of a fully merged short-lived branch is the only branch-deletion exception.
- Never add real provider credentials, consumer PII, or production secrets.
- A model may propose an action or completion candidate; deterministic policy and evidence checks own authorization and completion.

## Development Loop

For an approved phase:

1. Preflight: inspect current state, assumptions, dependencies, and dirty files.
2. Red: add or identify the smallest failing check that represents the requirement.
3. Green: implement the minimum code needed to pass it.
4. Refactor: only when it removes demonstrated complexity or duplication.
5. Verify: run focused checks, then the broader checks justified by risk.
6. Review: use an independent reviewer for material code or contract changes; the reviewer supplies findings and a recommendation to Sol.
7. Remediate: fix accepted findings and rerun affected checks.
8. Evidence: append pre-merge commands and outcomes to `harness/build-log.md`.
9. Publish: for the approved scope, Sol may commit, push, and open the pull request.
10. Integrate: Sol reviews the final diff, verification, independent-review evidence, and CI, then makes the final approve or request-changes decision and squash merges when the gate passes.
11. Stop: report the phase gate; wait for approval before expanding scope.

Never report a check as passed if it was not run. Separate passed checks from blocked, skipped, manual, browser, cloud, GPU, voice, and external-channel checks.

## Skill Routing

- `karpathy-guidelines`: default discipline for implementation and refactoring.
- `codebase-design`: contract boundaries, deep modules, and interface placement.
- `domain-modeling`: changes to the ubiquitous language in `CONTEXT.md`.
- `code-reviewer`: independent local-diff or pull-request review.
- `diagnosing-bugs`: failures, regressions, and performance diagnosis.
- `vercel-react-best-practices`: React/Next.js implementation or review.
- `design-taste-frontend`: user-approved frontend product work.
- `update-docs` or `write-dev-spec`: documentation affected by code or design decisions.

The installed `fix` skill assumes Yarn commands that this pnpm/uv repository does not use. Do not invoke it automatically; use repository-native checks instead.

## Git Workflow

- Treat `main` as the last integrated, validated state; do not implement or commit directly on it.
- Use one short-lived branch per phase, feature, fix, documentation change, or experiment, following `CONTRIBUTING.md` naming rules.
- Keep one bounded concern per pull request and do not begin the next phase in the same branch.
- Run `make preflight`, review the complete diff, and obtain any required independent review before merge.
- Prefer squash merge so `main` keeps one clear commit per bounded change. Deleting the short-lived source branch is routine cleanup only after Sol confirms the PR is merged, the worktree is clean, the branch was pushed, and no unique unpushed work would be lost.
- For a user-approved bounded phase or change, Sol owns branch creation, commit, push, PR creation, final review, and merge. These routine Git steps do not require separate user review or authorization.
- Never deploy, publish a release, force-push, rewrite shared history, delete an unmerged branch, or perform another destructive Git operation unless the user explicitly requests that exact operation.

## Agent Roles

The root orchestrator uses Sol for architecture, integration, trade-offs, and final decisions. Sol decides when subagents materially improve implementation speed, independent evidence, or review quality; the user does not need to request delegation explicitly.

- `implementer`: Luna xhigh, write-enabled, one clearly owned and well-specified implementation slice.
- `reviewer`: Terra, read-only, independent acceptance-criteria and diff review.
- `fast-worker`: Luna, write-enabled, narrow mechanical or repetitive tasks only.
- `explorer`: Luna, read-only, bounded repository discovery.

Rules for delegated work:

- At most three subagents run concurrently.
- Delegate only concrete, bounded work with a useful independent execution path; Sol may work directly when delegation would add no value.
- Prefer fresh, bounded context and a self-contained task packet; do not pass the full root transcript by default.
- Reuse an existing subagent for follow-up questions before spawning another agent for the same discovery.
- Assign explicit, non-overlapping file ownership.
- Tell write-enabled agents they are not alone in the repository and must not revert other edits.
- The implementing subagent does not review or approve its own work.
- Independent reviewer conclusions are evidence and recommendations; they do not merge changes or replace Sol's judgment.
- The root Sol orchestrator reviews and integrates subagent output, owns the final verification statement, makes the PR approval decision, and executes merge when the gate passes.
- Luna max is an explicit per-task escalation for complex multi-file implementation after architecture and acceptance criteria are frozen; it is not a standing default.
- Sol retains decisions about shared architecture, authorization policy, canonical contract semantics, and phase completion. Luna may implement those decisions but must not invent them.

## Repository Verification

Use the checks that exist for the current phase:

```bash
make preflight
make check-layout
uv lock --project runtime --check
pnpm install --lockfile-only --ignore-scripts --offline
docker compose config --quiet
git diff --check
```

Phase 00B established repository-native lint, type-check, unit-test, schema-generation, and contract-drift commands. Later phases must extend the gate only for behavior they actually add.

## Harness Boundaries

- `harness/build/`: executable phase contracts, one file per phase or gate.
- `harness/context/`: small, phase-specific evidence that does not belong in product docs.
- `harness/code_review/`: durable review artifacts for material gates.
- `harness/build-log.md`: append-only execution evidence and phase status.

The Codex development harness is not the product evaluation harness. Simulator scenarios, model evaluations, reward logic, and benchmark artifacts belong under `ml/`, `runtime/`, `data/`, or `tests/` as defined by the architecture.
