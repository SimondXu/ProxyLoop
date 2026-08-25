# Harness v2 Agent and Skill Routing

Date: 2026-08-25

## Scope

- Allow the global Sol root agent to delegate dynamically within the user's scope while keeping global commit, push, and PR actions explicitly user-authorized.
- Give ProxyLoop Sol routine Git and PR integration authority only for an already approved bounded change.
- Replace the fixed three-subagent policy with adaptive routing, a concurrency safety ceiling, fresh bounded task packets, and safe multi-writer coordination for independent non-overlapping slices.
- Reduce always-loaded context, overlapping Skill workflows, repeated full verification, and evidence-only commits without weakening the final gate or independent review.

## Changes

- Installed the backed-up global Codex routing update under `~/.codex`; backup: `~/.codex/backups/agent-harness-v2-20260825-165736`.
- Replaced duplicated phase history in `AGENTS.md` with durable rules and the canonical `harness/status.toml` pointer.
- Added explicit custom-agent metadata, adaptive role descriptions, a six-thread safety ceiling, and focused-versus-final verification guidance.
- Clarified the role ladder as Sol high root, Luna medium read-only exploration, Luna xhigh behavior implementation, Terra high independent review, and medium workers only for judgment-free mechanical edits.
- Allowed multiple implementation writers when requirements and file or module ownership are independent, shared interfaces are frozen, and Sol owns integration order and shared files.
- Added strict Harness status validation, including active contract existence, path containment, symlink containment, and schema type checks.
- Added `preflight-fast`, a one-log-per-change policy, and status contract tests; froze `harness/build-log.md` as legacy history.
- Updated lifecycle, prompts, contribution guidance, status tests, and README pointers to the new routing model.

## Independent review

One Terra stable-diff review requested changes. Accepted remediations:

- Removed a historical Phase 03A1 test's coupling to the current Harness idle state.
- Required every non-idle state to name a phase and an existing Markdown contract under `harness/build/`.
- Rejected contract paths that resolve outside `harness/build/` and schema versions with non-integer TOML types.
- Added positive and negative contract tests for those invariants.

The same reviewer rechecked the remediations and returned **Approve** with no remaining blocking findings.

## Verification

- Live global and project TOML parsing: passed.
- `codex features list`: passed; multi-agent remains enabled.
- Focused Ruff, mypy, status/architecture tests, and `make preflight-fast`: passed.
- Final `make preflight`: passed after review remediation.
  - Runtime tests: 214 passed.
  - ML tests: 177 passed.
  - Web tests: 29 passed; lint, typecheck, and production build passed.
  - Contract drift, phase artifact checks, layout, locks, compileall, and Compose validation passed.
- `git diff --check` and `git diff --cached --check`: passed.

Not run: Browser/manual product testing and remote CI, because this change does not alter product behavior and no PR was opened. No commit, push, PR, merge, deployment, or release was performed.
