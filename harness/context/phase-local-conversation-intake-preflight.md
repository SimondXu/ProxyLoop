# Local conversation intake UX preflight

Date: 2026-08-25

## Activation baseline

- User gate: execute the bounded Local Conversation Intake UX only after an
  independent PR #18 docs closeout; all current-phase exclusions remain on the
  long-term roadmap.
- PR #19 completed that docs-only closeout and was squash merged as
  `0d0acb37aec1dfad6e566523a772f7bb455ac570`; post-merge Repository checks
  passed in `2m37s`.
- Branch `feat/local-conversation-intake-ux` was created from synchronized
  `main@0d0acb3` after Gate 0 completed.
- Root `task_plan.md`, `findings.md`, and `progress.md` are untracked planning
  scratch. They are excluded from product commits and will be removed only
  after the complete phase closes.
- `/private/tmp/proxyloop-ui-worktree` remains read-only on local branch
  `feat/pine-inspired-ui-prototype` at snapshot `b8d7ee5`, including its three
  preserved untracked planning files.

## Read-only Gate 0 evidence

- Canonical read order completed on the post-closeout baseline. `.codegraph/`
  is absent, so bounded `rg` and direct source/test reads were used.
- Current `POST /cases` has no request body and calls the fixed deterministic
  `ThinAgentRuntime.create_case()` fixture.
- The four intake facts already map to canonical `BillSnapshot.monthly_total`,
  `ConsumerGoal.target_monthly_total`, `required_features`,
  `forbidden_changes`, and the hard constraint `Do not change device
  financing.`
- The fictional Provider's single `$72` offer, existing event immutability,
  exact approval pins, Evidence checks, and completion verifier were inspected.
  The frozen request validations preserve those semantics without Provider or
  public-contract changes.
- The existing Web client/workspace and all current Web tests were read. The
  current create call is empty and immediate after the lexical intent gate;
  session-generation protection already rejects late create/approval results.
- An independent bounded read-only explorer returned the same API/data-lineage
  mapping. Sol reconciled it against `app.py`, `runtime.py`, `episode.py`,
  canonical contracts, `runtime-client.ts`, the complete conversation
  workspace, and their tests.
- Focused baseline:

```text
tests/integration/test_phase_04a_agent_runtime.py
tests/integration/test_phase_04b_model_runtime.py
29 passed in 1.80s
```

## Gate decision

`GO_NARROW_SEAM`: the four facts fit existing canonical types and one strict
API-local request. No material contract, authority, security, Provider,
completion, or roadmap conflict was found. Fixed fixture IDs remain an honest
process-bound limitation; post-create correction requires Runtime restart and
New task.

## Ownership

- Sol: architecture, API/canonical/safety semantics, frozen contract,
  acceptance criteria, source/diff review, commands, Browser evidence,
  independent-review reconciliation, PR/CI/merge, and final gate.
- One Luna xhigh implementer: the bounded API/Runtime/Web/tests/docs slice from
  the frozen contract; no commit, push, PR, review, merge, or reinterpretation
  of canonical/safety boundaries.
- One fresh Terra reviewer: final diff and acceptance-criteria review only;
  no edits or integration actions.

## Pre-implementation scope guard

Stop and return to Sol before editing beyond the contract if implementation
would require a canonical schema change, Provider change, new identity/storage
strategy, mutable intake, dynamic pricing, general NLP/state framework,
credentials/network model, auth, persistence, Temporal, channels/voice,
deployment/release, training/evaluation, or a second journey/vertical.

## Implementation and focused verification

One Luna xhigh implementer changed only the frozen API/Runtime/Web/test/UI-doc
ownership. Sol read every changed source file and the complete diff. The
implementation adds no package, lockfile, canonical schema, Provider,
repository, auth, model, channel, deployment, or infrastructure change.

Exact focused commands after the final review remediation:

```text
UV_CACHE_DIR=/tmp/proxyloop-intake-uv-cache uv run --project runtime pytest -q \
  tests/integration/test_phase_04a_agent_runtime.py \
  tests/integration/test_phase_04b_model_runtime.py \
  -k 'not localhost_server_black_box'
45 passed, 1 deselected in 0.89s

UV_CACHE_DIR=/tmp/proxyloop-intake-uv-cache uv run --project runtime pytest \
  --collect-only -q tests/integration/test_phase_04a_agent_runtime.py \
  tests/integration/test_phase_04b_model_runtime.py \
  -k 'not localhost_server_black_box'
45/46 tests collected (1 deselected)

pnpm --filter @proxyloop/web lint
exit 0

pnpm --filter @proxyloop/web test
2 files / 29 tests passed

pnpm --filter @proxyloop/web typecheck
exit 0

pnpm --filter @proxyloop/web build
Next 16.2.9 Webpack production build passed; `/` and `/_not-found` static
```

The ordinary-sandbox full preflight reached Runtime `200 passed, 1 failed`;
the sole failure was `PermissionError` when the existing localhost black-box
test tried to bind `127.0.0.1`. The same full command was rerun outside that
socket restriction. The final post-remediation run exited 0 with Runtime
`201 passed`, ML `177 passed`, Web `2 files / 29 tests`, and all Ruff, mypy,
contracts, generated TypeScript, Phase artifact, layout, uv-lock, frozen
offline pnpm, compile, Compose, build, and diff gates passing.

## Browser evidence

The in-app Browser used real Runtime `127.0.0.1:8000` and Web
`127.0.0.1:3012`.

- Unsupported vacation input stayed local and exposed no create action.
- The four facts filled the local Draft Task Brief progressively. No create
  occurred before the explicit action. Editing current disabled create;
  `$74` was rejected against the `$75` target; `$100` was accepted locally.
- Create returned and displayed a verified `$100` current / `$75` target
  Runtime Task Brief with hotspot and financing facts. A post-create correction
  named the Runtime-restart/New-task boundary. Exact approval of the `$72`
  fictional offer produced one matching Evidence ID, execution count `1`, and
  a Verified receipt.
- A temporary non-production HTTP stub returned a structurally valid create
  response whose root Case was `$92` and snapshot Case was `$93`. The UI showed
  `Runtime state not verified`, with zero verified Task Briefs and zero Approval
  actions.
- After Terra remediation, a final real-Runtime Browser regression rejected
  `no change, but I want to change device financing` locally with create
  disabled. Explicit `yes` then enabled create and completed the verified
  `$92 -> $72` journey.
- After the first rereview, the exact Terra sentence `no change, but please
  modify device financing` was also exercised in Browser against the final
  whole-answer allowlist. Create remained disabled, no verified Task Brief was
  present, the input stayed local, and console warning/error output was empty.
- After the second rereview, the exact hotspot sentence `yes, remove mobile
  hotspot` was exercised against the final whole-answer allowlist. The hotspot
  fact remained missing, create remained disabled, only the local fixed-
  constraint alert was shown, no verified Task Brief was present, and console
  warning/error output was empty.
- Desktop and `375x812` Draft/receipt checks reported document/body
  `scrollWidth=375` and zero overflowing visible elements. Browser console
  warning/error output was empty.

Browser tabs, explicit viewport, Runtime/Web processes, temporary fault stub,
and both current-worktree dependency symlinks were removed. Next's generated
`next-env.d.ts` dev-path noise was restored to the tracked build-path value.
The legacy worktree remained at `b8d7ee5` with exactly its three original
untracked planning files.

## Independent-review status

Initial Terra review returned `REQUEST_CHANGES` with one substantive P1 for
contradictory financing language, one P1 combining a durable evidence gap with
an incorrect static test-count calculation, and two P2 findings for missing
event stale-response coverage and inaccurate Retry documentation. Sol accepted
the substantive parser, evidence-record, event-test, and documentation work.

The same implementer made the bounded remediations. Exact pytest collection
proved `45/46 collected (1 deselected)`, and actual Vitest output was
`25 passed` before the first two Terra regressions and `27 passed` afterward.
Terra's first rereview found one remaining P1 because a negative-synonym list
could still miss `modify`. The financing parser now uses a normalized
whole-answer confirmation allowlist; the exact `modify` sentence has unit and
Browser fail-closed evidence. Terra's second rereview found the analogous
hotspot free-text match; both fixed booleans now use normalized whole-answer
allowlists, and the exact `yes, remove mobile hotspot` sentence has unit and
Browser fail-closed evidence. Final Vitest reports `29 passed`; final full
preflight again reports Runtime `201`, ML `177`, and Web `29`.

The same Terra reviewer inspected the current complete diff after final
remediation, found no P0/P1/P2 findings, and returned
`APPROVE_PHASE_GATE`. The reviewer did not rerun commands or Browser in the
final pass.

PR #20's initial head `d432975` passed GitGuardian Security Checks in `1s` and
the Repository `phase-gate` in `2m16s` (Actions run `32883127501`). Sol's
integration decision is `APPROVE_FOR_SQUASH_MERGE` after this evidence commit
passes its own fresh PR-head checks. Merge, branch cleanup, and post-merge
`main` checks remain pending.
