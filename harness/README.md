# ProxyLoop Development Harness

This directory is the development control surface used by Codex and human reviewers. It turns the product roadmap into bounded contracts, exposes one canonical current state, and records concise review and verification evidence.

It is separate from the product evaluation Harness. Simulator scenarios, reward logic, model benchmarks, training data, and evaluation reports belong in the product directories described by `docs/architecture.md`.

## Layout

```text
harness/
├── status.toml     canonical current phase and authorization state
├── build/          executable phase contracts and acceptance criteria
├── context/        small phase-specific evidence and decision inputs
├── code_review/    durable review artifacts for material gates
├── log/            one concise execution log per bounded change
└── build-log.md    historical evidence through the Harness v2 migration
```

## Phase Lifecycle

1. Prepare one `build/phase-*.md` contract from the product specification.
2. Obtain human approval to activate that phase and update `status.toml`.
3. Execute preflight, red, green, justified refactor, and focused verification.
4. Stabilize the diff, then obtain independent review for material changes.
5. Batch accepted remediation and rerun affected checks.
6. Run final manual or Browser checks when applicable, followed by one final `make preflight`.
7. Record concise pre-merge evidence in one file under `log/`.
8. Sol may commit, push, open the pull request, reconcile CI and independent findings, squash merge, and perform validated merged-branch cleanup for the approved scope.
9. Return `status.toml` to idle and stop. Another product phase still requires explicit user approval.

Create or update a Codex Goal only when the user explicitly requests Goal tracking. A normal bounded phase is governed by `status.toml`, its phase contract, and its change log.

Subagent selection is an orchestration decision. Sol may proactively delegate bounded work according to `AGENTS.md`; the user approves phase and scope rather than every delegation. The configured concurrency value is a ceiling, not a required team size or total task budget.

Status labels are exact:

- `prepared`: a contract exists but implementation is not authorized;
- `in_progress`: the user approved the phase and implementation began;
- `blocked`: a named dependency prevents meaningful progress;
- `at_review`: implementation and developer verification are complete, but review or final integration remains;
- `complete`: every acceptance criterion has evidence, required review is resolved, the final gate passes, and the bounded change is merged when a remote is available;
- `idle`: no product phase is active.
