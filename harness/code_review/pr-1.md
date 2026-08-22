# Pull Request 1 Review

**Target**: `chore/development-harness` into `main`

**Decision before remediation**: Request changes

**Decision after local remediation review**: Approved, subject to required GitHub checks on the updated commit

## Finding 1 — Custom roles were not registered

**Severity**: Blocking

The repository added four role configuration files under `.codex/agents/`, but `.codex/config.toml` did not declare the corresponding `[agents.<role>]` tables. Codex requires each custom role declaration to provide a `description` and `config_file`; merely placing TOML files in that directory does not register the roles.

**Impact**: The documented implementer, reviewer, fast-worker, and explorer routing could appear validated while remaining unavailable to Codex as named roles.

**Resolution**: Added explicit declarations for all four roles and extended the repository validator to reject missing or mismatched declarations.

## Finding 2 — CI checked only the final commit

**Severity**: Improvement

The committed-diff whitespace command used `git diff --check HEAD^`, which checks only the final commit. A multi-commit pull request could introduce whitespace errors in an earlier commit without failing this step.

**Resolution**: CI now fetches full history and checks the complete pull-request or push commit range.

## Final Gate

The remediation diff was reviewed and `make preflight` passed locally. Merge still requires all GitHub checks to pass on the updated pull request commit.
