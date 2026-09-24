# Fix log: the Case-vs-offer policy check is total (B1-9)

Spec: `harness/context/fix-b1-9-total-offer-policy-preflight.md`.
Branch `fix/b1-9-total-offer-policy` from `origin/main` @ `74e2073`.

## What changed

- `runtime/packages/telecom_domain/src/proxyloop_telecom_domain/domain.py`:
  new `case_offer_violations(case, offer, *, evaluated_at,
  applied_changes=())`. It returns `("missing_bill_snapshot",)`,
  `("compliance_context_invalid",)` or `("offer_terms_invalid",)` instead of
  raising (catches only the `ValueError` of the `OfferComplianceContext` /
  `OfferComplianceTerms` constructors), else delegates to
  `offer_compliance_violations`. `verify_completion` calls it with the
  confirmation's `applied_changes`; the inline context construction is gone.
  The `forbidden_change_present` -> `forbidden_change_applied` map is kept.
- `.../proxyloop_telecom_domain/__init__.py`: exports `case_offer_violations`.
- `runtime/packages/case_runtime/src/proxyloop_case_runtime/runtime.py`:
  `offer_compliance_violations_for_case` keeps its name and export and is now
  a one-line wrapper; the three now-unused policy imports are removed.
- Tests: `runtime/packages/telecom_domain/tests/test_offer_policy.py` (two
  `verify_completion` red tests, a direct helper test for each reason code,
  and a 14-row no-regression table lifting every existing policy-table input
  into wire-valid Case and offer objects);
  `tests/integration/test_b1_9_total_offer_policy.py` (runtime `append_event`
  with a Provider offer carrying a -1000 CREDIT line, injected by
  monkeypatching `runtime.FictionalMobileProvider`).

## Evidence

- Red (helper added, call sites still on the old path): 3 failed, 27 passed.
  The two verifier tests raised `ValueError: fees_minor must be a
  non-negative integer` and `ValueError: features cannot contain
  duplicates`; the runtime test raised the `fees_minor` error.
- Green: focused run of telecom_domain tests, the B1-9 test,
  `test_offer_policy_authority.py`, `test_phase_01a_simulator.py`,
  `test_phase_04a_agent_runtime.py`: 76 passed.
- Mutation: both `except ValueError` turned into `except LookupError`:
  4 failed (the 3 red tests plus the direct helper test), 26 passed; file
  restored.
- `make format-check lint typecheck`: exit 0 (ruff format and check clean,
  mypy no issues in 66 and 59 source files).
- `make preflight-fast`: exit 0.
- `make test` (after `pnpm install --frozen-lockfile`): exit 0; runtime
  1218 passed, 51 skipped; ml 397 passed, 1 skipped. The drift lines
  `drifted_since_r1`, `drifted_since_03b`, `drifted_since_bundle` are the
  pre-existing informational states. `git status` shows no committed
  artifact modified.
- Not run here: `make postgres-check`, `make phase05a-check`,
  `make phase06b1-check` (the root schedules the shared DB/Temporal gates).

## Limits

- The wire still admits a negative fee line; enforcing non-negative fees at
  the wire is deferred to a future 1.2 contract set.
- Fee netting is unchanged: a +1000/-1000 pair nets to 0 and is evaluated
  as a zero fee sum.
- `compliance_context_invalid` also covers a non-UTC `evaluated_at`, since
  the context constructor raises the same `ValueError` for it.
