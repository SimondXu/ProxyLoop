# ProxyLoop Agent Instructions

This file is the repository-level operating contract for Codex and delegated agents. Product requirements remain authoritative in the linked specification. This file contains durable operating rules; volatile phase state lives in `harness/status.toml`.

## Orientation and Context

On first orientation, after resume or compaction, or after material repository drift:

1. Read `harness/status.toml`.
2. If a product phase is active, read its single contract under `harness/build/` and only the phase-specific evidence it names.
3. Read `GOALS.md` for product-outcome questions, `CONTEXT.md` for domain-language or contract-semantics questions, and `PLANS.md` for roadmap or phase-gate questions. Do not load all three by default when the task does not need them.
4. Read the relevant source files and tests.
5. Read historical contracts, reviews, or build-log entries only when a current claim, regression, or audit requires them.

Do not treat a roadmap item as permission to implement it. Only a user-approved phase or bounded repository change is active.

## Authority and Safety

- Keep at most one product implementation phase active.
- Use the smallest change that satisfies the approved acceptance criteria; do not begin the next phase automatically.
- Preserve user work and unrelated changes.
- Once the user approves a bounded ProxyLoop phase or repository change, root Sol may create a branch, commit, push, open and review the pull request, squash merge it, and clean up its fully merged short-lived branch without separate approval for each routine Git step.
- A new explicit user decision is required to expand scope, activate another phase, deploy, publish a release, contact real external parties, use credentials, perform destructive operations, force-push, rewrite shared history, or delete unmerged work.
- Never add real Provider credentials, consumer PII, production secrets, or unreviewed generated model artifacts.
- Models may propose actions or completion candidates; deterministic policy and evidence checks own authorization and completion.

## Sol-Retained Decisions

Root Sol owns shared architecture and interfaces, authorization and completion policy, canonical contract and evaluator semantics, security boundaries, conflicting evidence, scope changes, phase gates, final diff review, and every completion or integration claim.

Sol must inspect the primary evidence for those decisions. Subagent output is navigation, implementation, or independent review evidence; it does not replace Sol's judgment.

## Adaptive Delegation

Sol may proactively use subagents when doing so materially improves quality, latency, or context isolation. The user does not need to request delegation separately.

Delegate when at least one of these is true:

- the work contains two or more independent evidence or implementation lanes;
- exploration, logs, test output, artifact inventories, or large-file analysis would pollute the root context;
- a bounded mechanical slice has exact ownership and a verification command;
- a specialized model, tool surface, or independent reviewer provides distinct value;
- parallel execution shortens a real critical path without overlapping writes.

Sol should work directly when the answer is in one to three tightly related files, the task is small or highly coupled, boundaries are still ambiguous, delegation would duplicate the same reads, or the task concerns a Sol-retained decision.

Start with the smallest useful team and expand only after finding an evidence gap or an additional independent lane. `max_concurrent_threads_per_session` is a safety ceiling, not a target or a per-task agent budget:

- normal discovery: zero to two explorers;
- broad independent inventory: burst up to the configured ceiling after Sol defines non-overlapping questions;
- implementation: allow multiple writers for independent requirements when file or module ownership is non-overlapping, shared interfaces are frozen, and Sol defines shared-file ownership plus the integration order; otherwise keep one writer until those boundaries are clear;
- review: one independent reviewer after the diff and acceptance criteria are stable.

Use these project roles:

- `explorer`: Luna medium, read-only repository mapping and evidence cards;
- `fast-worker`: Luna medium, mechanical generation, formatting, fixtures, or exact repetitive edits that require no behavior or interface judgment;
- `implementer`: Luna xhigh, a well-specified implementation slice after interfaces and acceptance criteria are frozen;
- `reviewer`: Terra high, read-only defect-first review and adversarial checks.

Prefer fresh bounded subagent contexts (`fork_turns="none"` when supported). Every task packet must contain the objective, scope and non-goals, known paths, exact questions or owned files, expected output, verification, and escalation triggers. Reuse an existing subagent for clarification before repeating the same discovery.

Explorers return an evidence card rather than a transcript: direct answer, precise path and symbol or line support, checks run or unrun, conflicts and unknowns, and a short `Sol must read` list. Escalate instead of resolving ambiguity involving architecture, authorization, canonical contracts or evaluators, security, scope, or a phase gate.

## Skill Routing

Skills are on-demand procedures, while custom agents are delegated roles with separate context, model, tools, or permissions. Do not substitute one mechanism for the other.

- Use a Skill when the user names it or the task clearly matches its description; explicit mention is not required for a clear match.
- At task start and whenever the work changes phase or shape, scan the available Skill descriptions again so a newly relevant Skill is not missed.
- Choose the most specific workflow Skill that covers the current stage. Add a complementary domain Skill only when it contributes a distinct procedure or body of knowledge. There is no hard Skill-count limit, but do not stack overlapping workflows for ceremony.
- If two Skills overlap, prefer the narrower repository-compatible one. If neither fits cleanly, follow repository-native commands directly and state the mismatch.
- Use progressive disclosure: read the selected `SKILL.md` completely, then load only the references or assets it routes to for the current variant.
- Do not suppress a useful Skill merely to save tokens. Control cost through precise triggering, non-overlap, and on-demand references.

Repository-specific routing:

- `karpathy-guidelines`: implementation and refactoring discipline.
- `diagnosing-bugs`: reported failures, regressions, or performance diagnosis.
- `codebase-design`: interface placement, module depth, and architecture seams.
- `domain-modeling`: deliberate changes to the ubiquitous language in `CONTEXT.md`.
- `vercel-react-best-practices`: React and Next.js implementation or performance review.
- `design-taste-frontend`: landing pages, portfolios, or an explicitly approved visual redesign; not ordinary ProxyLoop product-flow changes.
- `write-dev-spec`: architecture, ADR, runbook, or developer-spec work. The installed `update-docs` Skill targets the Next.js documentation repository and is not a default ProxyLoop docs workflow.

The installed `fix` Skill assumes Yarn and is not repository-compatible. Use pnpm/uv targets from this repository. Project reviewer instructions already contain the required defect-first workflow; do not load a second generic review Skill unless the user explicitly requests it or the review target needs its distinct remote-PR procedure.

## Development and Verification Loop

For an approved phase or bounded change:

1. Preflight: inspect status, scope, dependencies, dirty files, and the smallest relevant checks.
2. Red: add or identify the smallest failing check when practical.
3. Green: implement the minimum compatible change.
4. Refactor only to remove demonstrated complexity or duplication.
5. Run focused checks while the behavior is changing.
6. When the diff is stable, obtain independent review for material code, contract, authorization, security, workflow, or external-channel changes.
7. Batch accepted findings, rerun affected checks, and request re-review only for material semantic changes or unresolved findings.
8. Run Browser or manual verification only after the affected behavior is stable.
9. Run `make preflight` once as the final local repository gate; rerun it only after a material change to covered behavior or artifacts.
10. Record concise pre-merge evidence in one bounded-change log under `harness/log/`, then integrate and stop at the gate.

Never report a check as passed if it was not run. Separate passed checks from blocked, skipped, manual, Browser, cloud, GPU, voice, and external-channel work.

## Git Workflow

- Treat `main` as the last integrated validated state; do not implement or commit directly on it.
- Use one short-lived branch per phase, feature, fix, docs change, or experiment, following `CONTRIBUTING.md`.
- Keep one bounded concern per pull request.
- Sol reviews the complete final diff, verification, independent-review evidence, and CI before merge.
- Prefer squash merge. Delete a fully merged short-lived branch only after confirming the worktree is clean, the branch was pushed, and no unique unpushed work would be lost.

## Harness Boundaries

- `harness/status.toml`: single current-state source.
- `harness/build/`: executable phase contracts.
- `harness/context/`: small phase-specific evidence and decision inputs.
- `harness/code_review/`: durable material review artifacts.
- `harness/log/`: one concise execution log per bounded change.
- `harness/build-log.md`: historical evidence through the Harness v2 migration; do not scan or append it by default.

The Codex development Harness is not the product evaluation Harness. Simulator scenarios, model evaluations, reward logic, benchmarks, and training artifacts belong under `ml/`, `runtime/`, `data/`, or `tests/` as defined by the architecture.
