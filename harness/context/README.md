# Harness Context

Store only small, phase-specific evidence that helps an implementation or review agent execute a prepared phase without rediscovering the same facts.

Each context file must identify:

- the phase and question it supports;
- source files or official external sources;
- what is observed, inferred, proposed, or still unverified;
- the date when drift-prone information was checked.

Do not copy the PRD, architecture document, source code, hidden chain-of-thought, secrets, PII, large generated output, or model datasets into this directory. Durable product decisions belong in `docs/decisions/`; domain language belongs in `CONTEXT.md`; execution evidence belongs in `harness/build-log.md`.

Active context:

- `phase-00b-preflight.md`: observed contract-package baseline and the six decisions that must be resolved before domain model implementation.
