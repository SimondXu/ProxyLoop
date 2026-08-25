# ProxyLoop Harness Prompts

These are optional operator templates. They do not activate a phase, require delegation, or expand scope. Root Sol follows `AGENTS.md` and `harness/status.toml`; subagents never commit, push, review-submit, or merge.

## Orient Root Sol

```text
Read harness/status.toml first. Read the active contract only if one exists. Select GOALS,
CONTEXT, or PLANS only when the task concerns product outcome, domain semantics, or phase
history. Inspect dirty files and the relevant code/tests. Report current authorization,
assumptions, risks, and the smallest next action before editing.
```

## Decide Delegation

```text
Before spawning, identify independent lanes and compare their value with coordination cost.
Delegate only bounded work that isolates noisy context, runs independently, benefits from a
specialized role, or provides independent review. Work directly when the task is small, tightly
coupled, ambiguous, or concerns architecture, authorization, canonical contracts/evaluators,
security, scope, or a phase gate. Start with the smallest useful team; the configured concurrency
is a ceiling, not a target.
```

## Prepare a Phase

```text
Prepare [phase] as one executable contract. Trace acceptance criteria to the product
specification and current repository evidence. Define scope, non-goals, dependencies,
red/green steps, focused and final verification, independent review, evidence location,
and the stop condition. Do not implement or activate the phase.
```

## Execute an Approved Phase

```text
Execute only [phase] from [phase file]. Start with the smallest failing check, implement the
minimum compatible behavior, and use focused checks until the diff is stable. Obtain material
independent review, batch accepted remediation, perform final Browser/manual verification when
applicable, then run one final make preflight. Record concise evidence in one harness/log file.
Do not deploy or begin the next phase.
```

## Delegate Exploration

Use for a bounded cross-directory map, call-chain or data-lineage trace, test-impact search, artifact inventory, or noisy log analysis.

```text
Investigate exactly: [question]. Scope/non-goals: [bounds]. Known paths: [paths or unknown].
Work read-only in a fresh bounded context. Return the explorer evidence card required by
.codex/agents/explorer.toml. Escalate conflicts or decisions involving architecture,
authorization, canonical contracts/evaluators, security, scope, or phase completion to Sol.
```

## Delegate Implementation

Use after Sol freezes interfaces, behavior, ownership, acceptance criteria, and verification.

Multiple implementers may run in parallel when they own independent requirements and non-overlapping files or modules. Give each writer a separate packet. Sol must assign every shared file to exactly one writer, freeze shared interfaces first, and define the integration order and final cross-slice verification.

```text
Own only [files/responsibility]. Preserve user and concurrent edits. Implement [frozen behavior]
with the smallest compatible patch and run [focused checks]. Do not redesign interfaces or
change contracts outside the owned slice. Return files changed, commands and exact results,
assumptions, and remaining risks. Do not commit or push.
```

## Delegate Mechanical Work

```text
Apply this already-specified mechanical change: [task], only in [paths]. Preserve other edits,
do not infer new behavior, and run [exact check]. Stop on ambiguity and return concise evidence.
```

## Independent Review

```text
Review the stable complete diff against [contract/requirements]. Work read-only and defect-first.
Check correctness, authorization/completion semantics, contract compatibility, adjacent same-class
cases, security, test gaps, and scope. Return all actionable findings in one pass where practical,
with precise file references and an Approve or Request Changes recommendation. Identify blocked,
manual, skipped, and unrun verification. Root Sol owns the final integration decision.
```

## Remediate Review

```text
Evaluate all findings against primary code and acceptance criteria. Batch accepted fixes, explain
rejected findings with evidence, and rerun only affected checks. Request re-review only for material
semantic changes or unresolved findings. Do not expand scope or update evidence after every tiny fix.
```

## Completion Check

```text
Confirm every acceptance criterion with a file, test, command, review, or explicitly manual result.
Distinguish passed, blocked, skipped, and unrun checks. Confirm final preflight and concise change-log
evidence. Leave the change incomplete if any required item is missing. Stop without activating the
next phase.
```
