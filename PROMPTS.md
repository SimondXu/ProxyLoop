# ProxyLoop Harness Prompts

These prompts are reusable operator templates. Replace bracketed values with the active phase or owned slice. They do not activate a phase or expand scope. Once the user approves a bounded phase or change, root Sol follows `AGENTS.md` for delegation and routine Git integration; subagents never commit, push, review-submit, or merge.

## Orient the Root Orchestrator

```text
Read AGENTS.md, GOALS.md, CONTEXT.md, PLANS.md, the active harness/build phase file,
harness/build-log.md, and the relevant code/tests. Report the current phase, its gate,
dirty files, assumptions, and the smallest next action. Do not edit yet.
```

## Prepare a Phase

```text
Prepare [phase] as an executable build contract. Trace every acceptance criterion to the
product specification and current repository evidence. Define in-scope work, non-goals,
dependencies, red/green/refactor steps, focused and broad verification, review evidence,
and a stop condition. Do not implement the phase.
```

## Execute an Approved Phase

```text
Execute only [phase] from [phase file]. Follow AGENTS.md and karpathy-guidelines.
Start with preflight and the smallest failing check. Make the minimum implementation,
run focused then risk-proportionate verification, update the build log with real evidence,
and stop at the phase gate. Root Sol may complete the branch/commit/push/PR/review/merge
workflow after the gates pass. Do not deploy or begin the next phase.
```

## Delegate Implementation

Use when root Sol decides a bounded implementation slice materially benefits from delegation.
The default implementer is Luna xhigh. Override it to Luna max only for complex multi-file implementation whose architecture and acceptance criteria are already frozen.

```text
Assign the implementer exactly this owned slice: [files/responsibility]. You are not alone
in the repository: do not revert or overwrite other edits, and adapt to concurrent changes.
Read the active phase contract and relevant code/tests. Use the smallest verifiable change.
Do not touch shared architecture or contracts outside the owned slice. Do not commit or push.
Return changed files, commands run, results, assumptions, and remaining risks.
```

## Delegate a Narrow Mechanical Task

Use when root Sol identifies a narrow mechanical slice with exact file ownership and verification.

```text
Assign fast-worker this bounded mechanical task: [task and exact paths]. Do not redesign
interfaces, policy, authorization, or canonical contracts. You are not alone in the repository;
do not revert other edits. Run the named focused check and report only evidence. Do not commit.
```

## Independent Review

```text
Review the current diff against [phase file], AGENTS.md, and repository conventions.
Use code-reviewer discipline. Prioritize correctness, authorization/completion semantics,
contract compatibility, test gaps, and maintainability. Do not edit. Report actionable findings
with file and line evidence; explicitly say when there are no blocking findings and identify
verification that remains unrun. Return an Approve or Request Changes recommendation to Sol;
do not edit, commit, push, submit a GitHub review, or merge.
```

## Remediate Review Findings

```text
Evaluate each review finding against code and the active acceptance criteria. Fix accepted
findings with the smallest compatible patch, explain rejected findings with evidence, rerun
affected checks, and update harness/build-log.md. Do not expand phase scope.
```

## Phase Completion Check

```text
Audit [phase] for completion. Confirm every acceptance criterion with a file, test, or command
result; distinguish automated, manual, blocked, and unrun checks. Confirm independent review
and build-log evidence. If anything is missing, leave the phase incomplete. If complete, report
the recommendation to Sol. Sol owns the final integration review and merge decision. Stop without
starting the next phase.
```
