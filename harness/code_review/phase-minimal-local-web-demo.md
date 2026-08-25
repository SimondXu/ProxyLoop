# Minimal local Web demo review

**Status**: Independent rereview complete; `APPROVE_PHASE_GATE`. PR #18 was
squash merged as `ef2ce53`; post-merge Repository checks passed and the fully
merged short-lived branch was safely removed locally and remotely.

## Initial Terra review

Terra independently reviewed the bounded Web slice and returned
`REQUEST_CHANGES`. Sol accepted all four P1 findings without expanding the
approved Web/runtime-client/docs ownership:

1. `P1.1` — the repository validation path did not include a sequential Web
   gate. Add `web-check` to `Makefile`, expose it in help, and make `validate`
   depend on it.
2. `P1.2` — malformed Task Brief and pending offer/approval facts could reach
   rendered artifacts without narrow Money, constraint, offer, and exact
   approval validation.
3. `P1.3` — the initial intent gate combined billing context with reduction
   words, allowing questions such as phone price or increased mobile cost.
4. `P1.4` — late create/event/approval responses could write stale state after
   restart.

## Remediation

- `Makefile` now runs Web lint, typecheck, test, and Webpack build in order via
  `web-check`, and `validate` includes that target.
- `runtime-client.ts` now exports small explicit Money, Task Brief, and pending
  Approval predicates. Missing or malformed facts block confirmation or
  approval rendering.
- The intent gate now requires independent telecom, billing-context, and
  explicit-reduction matches. Negative and positive cases are tested.
- `conversation-workspace.tsx` binds create/event/approval awaits to a
  monotonic session id; restart invalidates late responses and clears busy
  state. Deferred-promise tests cover create and approval restart races.

## Verification evidence

- `make web-check` passed sequentially: lint, typecheck, `2 files / 17 tests`,
  and `next build --webpack` with static `/` and `/_not-found`.
- `git diff --check` passed.
- Final `make preflight` exited 0 with Runtime `184`, ML `177`, and repository
  format/lint/mypy/contracts/artifacts/layout/uv-lock/offline-frozen-pnpm/
  compile/Compose/diff gates passing, including the Web gate.
- The first ordinary-sandbox preflight attempt hit the local uv-cache
  permission boundary; an intermediate escalated attempt without the temporary
  dependency aid hit the existing root `tsc/json2ts` lookup failure. The final
  run used the existing dependency tree read-only and passed. These are
  environment evidence, not source failures.

The intermediate result was one `make preflight` invocation whose Runtime
pytest phase reported `182 passed, 2 failed`. The failed contract tests were
`test_generated_types_accept_exact_representative_fixture` (`pnpm exec tsc ...`
reported `Command "tsc" not found`) and
`test_generated_artifacts_have_no_drift` (`scripts/generate_contracts.py
--check` reported `Command "json2ts" not found`). Make stopped at the
nonzero `unit-test` phase, so no later standalone `contracts-check` command ran.

## Final Terra rereview

Terra's second independent review found no remaining P0, P1, or P2 findings.
The cumulative six remediation findings passed: the four initial repository
gate/validation/intent/stale-response findings above, plus nonempty trimmed
Evidence ID validation and the requirement that an event response retain a
valid Task Brief before entering Approval. Terra's final recommendation is
`APPROVE_PHASE_GATE`.

Sol's final source verification recorded Web lint/typecheck, Vitest `2 files /
20 tests`, and a complete `make preflight` with Runtime `184`, ML `177`, the
Webpack build, and all repository gates passing. The earlier full journey,
Browser, and mobile smoke remains the browser evidence; Browser smoke was not
rerun after the final Evidence-ID/Task-Brief remediation.

PR #18 passed its fresh-install phase gate and GitGuardian checks, then was
squash merged as `ef2ce53`. Post-merge `main@ef2ce53` Repository checks passed
in the recorded `2m27s`; the fully merged implementation branch was safely
removed locally and remotely. The legacy local-only UI worktree/branch remains
preserved. No implementation phase is active after this closeout.
