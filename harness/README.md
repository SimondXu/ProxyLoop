# ProxyLoop Development Harness

This directory is the development control surface used by Codex and human reviewers. It turns the product roadmap into bounded phase contracts, provides small phase-specific context, and records review and verification evidence.

It is deliberately separate from the product evaluation harness. Simulator scenarios, reward logic, model benchmarks, training data, and evaluation reports belong in the product directories described by `docs/architecture.md`.

## Layout

```text
harness/
├── build/          executable phase contracts and acceptance criteria
├── context/        small phase-specific evidence and decision inputs
├── code_review/    durable review artifacts for material phase gates
└── build-log.md    append-only execution and verification evidence
```

## Phase Lifecycle

1. Prepare one `build/phase-*.md` contract from the product specification.
2. Obtain human approval to activate that phase.
3. Create or update one Codex Goal for that phase only.
4. Execute preflight, red, green, justified refactor, and verification.
5. Obtain an independent review for material changes.
6. Record pre-merge verification and review evidence in `build-log.md`.
7. Sol may commit, push, and open the pull request for the approved scope without a separate user review.
8. Sol reconciles the final diff, independent findings, and CI, makes the final PR decision, and squash merges when the gate passes.
9. Report the merge result and prepare the next phase only after explicit user approval.

Subagent selection is an orchestration decision. Sol may assign bounded implementation, exploration, mechanical, or independent-review work whenever it materially improves execution or evidence quality. The user approves the phase and scope; the user does not need to approve each delegation or routine Git operation within that scope.

Status labels are exact:

- `Prepared, not started`: the contract exists but implementation is not authorized.
- `In progress`: the user approved the phase and implementation has begun.
- `Blocked`: a named dependency prevents meaningful progress.
- `At review`: implementation and developer verification are complete; independent review or Sol's final integration decision remains open.
- `Complete`: every acceptance criterion has evidence, required review is resolved, Sol's final integration gate passes, and the bounded change is merged when a repository remote is available.
