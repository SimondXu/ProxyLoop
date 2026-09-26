# ADR-NNNN: <title>

- **Status:** proposed | accepted | superseded by ADR-NNNN
- **Date:** YYYY-MM-DD
- **Task:** <TASK-ID> (the PR that implements or records this decision)

## Context
What forces the decision: the constraint, the observed evidence (link `docs/decisions/data/<…>.json` or `evidence/<stage>/<run_id>/`), and the options that were on the table.

## Decision
What we do, stated so that a reviewer can check a diff against it.

## Evidence
The measurements behind the decision, each with its raw artefact and the command that produced it. No number without a committed source.

## Consequences
- **Contract / fingerprint impact:** none | the renderer fingerprint changes (old → new) and `make pull-through MODE=full` must pass.
- **Data invalidated:** none | the datasets and adapters built under the old fingerprint.
- **Migration:** what in-flight worktrees, bundles and goldens must do.
- **Risks and what would make us revisit this.**
