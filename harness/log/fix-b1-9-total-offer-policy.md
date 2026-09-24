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

## Amendment: `evaluated_at` guard (root decision), merge, real gates

- `case_offer_violations` now validates `evaluated_at` first (before the
  bill check and the first `try`) and raises
  `ValueError("evaluated_at must be timezone-aware UTC")` for a naive or
  non-UTC value, so a caller bug is not masked as
  `compliance_context_invalid`. New test
  `test_case_offer_violations_raises_on_a_non_utc_evaluation_time`
  (naive, +02:00; with and without a bill). Mutation (raise -> `pass`):
  2 failed; restored.
- Merged `origin/main` @ `ff35dca` (docs-only: status and one log).
- Focused run: 78 passed. `make format-check lint typecheck`: exit 0.
  `make preflight-fast`: exit 0.
- Real-dependency gates, serial, shared test DB at `localhost:55432`,
  Temporal at `localhost:7233`, variables on the make command line only:
  `make postgres-check` 27 passed; `make phase05a-check` 42 passed;
  `make phase06b1-check` 35 passed. No `case_not_found` / `state_invalid`.
- `make preflight`: exit 0; runtime 1220 passed, 51 skipped; ml 397 passed,
  1 skipped; web 140 passed; Next build compiled. Same three pre-existing
  drift lines. A first `make preflight` run also exited 0 but its captured
  log contained NUL bytes and an inconsistent count (1203 passed vs 1271
  collected), so it was discarded and rerun into a fresh file.

## Independent review (Approve) and follow-ups

- Reviewer: Approve; differential fuzz of 20k inputs, 0 exceptions, 0
  differences on previously-returning inputs.
- Minor 1: the two `verify_completion` tests assert exact reason codes,
  order verified by running them: negative fee -> `("offer_terms_invalid",)`;
  duplicate features -> `("approval_binding_mismatch", "offer_terms_invalid",
  "confirmation_state_mismatch")`.
- Minor 2: the `case_offer_violations` docstring notes that an invalid
  `applied_changes` (e.g. a repeated confirmed change) also maps to
  `offer_terms_invalid`.
- Docs: `harness/context/audit-remediation-status.md` moves B1-9 to the §4
  closed table and adds backlog item R-19 (`SafeObservationAdapter.
  _adapt_offer` raises on the same inputs via `SafeOffer.__post_init__`;
  callers are `ml/` and `scripts/`, not the product runtime).
  `docs/architecture.md` and `CONTEXT.md` describe verifier outcomes and
  offer fields but not the raise-vs-reason-code behaviour or the fee sign,
  so they are unchanged.
- Merged `origin/main` @ `d23aff9` (#80, router precedence; clean, the
  status file untouched by it). At the root's request the status file also
  moves B1-12 and the grep -> Router precedence test replacement (audit §3,
  lane A) to the §4 closed table with #80 and `fix-p2-router-precedence.md`.
  DB gates not rerun (test/doc-only change since they passed above).

## Limits

- The wire still admits a negative fee line; enforcing non-negative fees at
  the wire is deferred to a future 1.2 contract set.
- Fee netting is unchanged: a +1000/-1000 pair nets to 0 and is evaluated
  as a zero fee sum.
