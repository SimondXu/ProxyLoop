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
6. Record evidence in `build-log.md` and stop at the gate.
7. Prepare the next phase only after explicit approval.

Status labels are exact:

- `Prepared, not started`: the contract exists but implementation is not authorized.
- `In progress`: the user approved the phase and implementation has begun.
- `Blocked`: a named dependency prevents meaningful progress.
- `At review`: implementation and developer verification are complete.
- `Complete`: every acceptance criterion has evidence and required review is resolved.
