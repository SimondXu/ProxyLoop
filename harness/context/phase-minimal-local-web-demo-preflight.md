# Minimal local Web demo preflight

Date: 2026-08-25

This file records activation, implementation, independent-review, PR-gate, and
post-merge closeout evidence. It does not claim a browser rerun after final
remediation.

## Boundaries observed

- Branch is `feat/minimal-local-web-demo`, based on `main@d2cda56`.
- Existing root untracked `findings.md`, `progress.md`, and `task_plan.md` are
  preserved and outside this slice.
- `apps/web` was empty except for `.gitkeep`; the old `b8d7ee5` snapshot was
  inspected read-only. Its visual shell and artifact language were reusable;
  its static `demo-case.ts` and `/cases/demo*` success flow were not.
- The Runtime API in `runtime/services/api/src/proxyloop_api/app.py` and
  `tests/integration/test_phase_04a_agent_runtime.py` are authoritative for
  create, event, approval, CAS pins, and completion payload shape. Backend
  files remain unchanged.
- The sole Web client seam is `apps/web/lib/runtime-client.ts`; no model,
  credential, `.env`, external Provider, or external network call is used.

## Initial red evidence

Before the Web package existed:

```text
pnpm --filter @proxyloop/web lint
No projects matched the filters in "/Users/edison/Desktop/projects/pine-clone"
```

## Dependency note

`pnpm install --lockfile-only --ignore-scripts --offline` updated the lockfile
without downloading. A later local dependency install was attempted only with
`--offline`; it was blocked because the pnpm store lacked the root tarball
`json-schema-to-typescript-15.0.4.tgz` (and then `@next/env-16.2.9.tgz`). No
network fallback was used. Focused checks were run against the existing local
dependency tree in the old worktree strictly as a read-only verification aid;
the old worktree was not edited.

## Scope exclusions

No backend, contracts, ML/evaluation, data, model, credential, authentication,
real Provider, channel, voice, deployment, release, or old-worktree branch
state was changed.

## Remediation verification evidence

After adding the narrow supported-intent gate and fixing the local Web scripts
to use Webpack, these commands exited 0 in the approved local dependency
environment:

- `pnpm --filter @proxyloop/web lint`
- `pnpm --filter @proxyloop/web typecheck`
- `pnpm --filter @proxyloop/web test` (`2 files / 20 tests passed`)
- `pnpm --filter @proxyloop/web exec next build --webpack` (static `/` and
  `/_not-found` generated)

This section records focused Web evidence only. It does not claim a browser
smoke, `make preflight` rerun, independent review, CI, merge, or phase
completion.

## Final verification evidence from Sol

Sol's final native commands exited 0:

- `pnpm --filter @proxyloop/web lint`
- `pnpm --filter @proxyloop/web test` (`2 files / 9 tests passed`)
- `pnpm --filter @proxyloop/web build` (`next build --webpack`, static `/` and
  `/_not-found`)
- Sequential `pnpm --filter @proxyloop/web typecheck`

The initial parallel build/typecheck attempt had a transient `TS6053` while
the build replaced `.next/types`; the sequential rerun passed. Sol's final
`make preflight` also exited 0 with Runtime `184`, ML `177`, and the repository
format/lint/mypy/contracts/artifacts/layout/uv-lock/offline-frozen-pnpm/
compile/Compose/diff gates passing.

The in-app Browser smoke used Runtime `127.0.0.1:8000` and Web
`127.0.0.1:3012`. It verified the unsupported vacation request stayed local,
the supported mobile-bill flow's Runtime-derived `$92` current / `$75` target
facts and constraints, one confirmation event, `$72` fictional offer, exact
approval boundary, local arbitrary-correction handling, and a Verified receipt
with one matching Evidence ID and execution count `1`. Console warning/error
output was empty; at `375x812`, `scrollWidth` was `375` with no horizontal
overflow. Servers, tab, viewport, and temporary dependency symlinks were
cleaned. No screenshot artifact was committed. This pre-PR evidence predates
the final PR gate recorded below.

## Terra remediation evidence

Terra's initial independent review returned `REQUEST_CHANGES` with four P1
findings covering the repository Web gate, malformed Runtime view validation,
the three-part intent boundary, and stale async responses after restart. Sol
accepted all four. The remediation added `make web-check` to `validate`,
explicit Money/Task Brief/pending Approval predicates, the independent intent
terms, and a monotonic session id that invalidates late responses and clears
busy state on restart.

Final `make web-check` exited 0 sequentially with `2 files / 20 tests passed`
and Webpack static `/` plus `/_not-found`. Final `make preflight` exited 0 with
Runtime `184`, ML `177`, and all repository gates including Web lint,
typecheck, test, and build passing. An earlier sandbox attempt hit the local
uv-cache permission boundary; an intermediate run without the temporary
dependency aid hit the existing root `tsc/json2ts` lookup failure. The final
run used the existing dependency tree read-only. The later PR gate is recorded
below.

The final five additional tests include empty and whitespace Evidence-ID
rejection in both payload parsing and receipt verification, plus an event
response with a valid pending offer/approval but a missing Task Brief; that
response remained blocked and never exposed Approval.

The intermediate failure was one escalated `make preflight` invocation. Its
Runtime pytest phase reported `182 passed, 2 failed`: `test_generated_types_accept_exact_representative_fixture`
failed because its `pnpm exec tsc --noEmit -p contracts/typescript/tsconfig.json`
subprocess reported `Command "tsc" not found`, and
`test_generated_artifacts_have_no_drift` failed because its
`scripts/generate_contracts.py --check` subprocess reported `Command "json2ts"
not found`. Make stopped at the nonzero `unit-test` phase; it did not proceed
to a separate later `contracts-check` command.

## Final Terra rereview

Terra's second rereview found no P0, P1, or P2 findings across six cumulative
remediations and returned `APPROVE_PHASE_GATE`. Browser smoke was not rerun
after the final remediation; the earlier complete journey/browser/mobile smoke
remains the recorded browser evidence. PR #18 passed CI/GitGuardian and Sol
approved it for squash merge.

## Final PR gate

PR #18 (`https://github.com/SimondXu/ProxyLoop/pull/18`) passed its fresh-install
phase gate in `2m29s`; GitGuardian Security Checks passed; head commit was
`9aa8869`. Sol reviewed the PR file scope, local final preflight, Terra's
`APPROVE_PHASE_GATE`, browser evidence, and PR checks, then decided
`APPROVE_FOR_SQUASH_MERGE`.

## Post-merge closeout

PR #18 was squash merged as `ef2ce53`. The post-merge
`main@ef2ce53` Repository checks passed in the recorded `2m27s`. The fully
merged `feat/minimal-local-web-demo` branch was safely removed locally and
remotely. The legacy UI worktree/branch remains local-only and preserved at
`b8d7ee5`, including its three untracked planning scratch files. No
implementation phase is active after this closeout.
