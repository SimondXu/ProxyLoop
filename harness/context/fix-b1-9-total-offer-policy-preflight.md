# Fix: the Case-vs-offer policy check is total (B1-9)

Audit remediation item B1-9, run under the 2026-09-22 standing authorization.
Branch `fix/b1-9-total-offer-policy` from `origin/main` @ 74e2073. Design is
the root-adopted architect proposal; this file freezes it for the implementer.

## Defect (observed on main)

- `LineItem.amount` may be negative by contract
  (`runtime/packages/contracts/src/proxyloop_contracts/contracts.py`
  `LineItem`/`Money`; `test_contracts.py` pins negative `Money` on purpose), and
  goal/offer tuples of `ExternalRef` may repeat a token.
- `OfferComplianceTerms.__post_init__` raises `ValueError` on a negative
  `fees_minor` and on duplicate `features`/`applied_changes`;
  `OfferComplianceContext.__post_init__` raises on duplicate
  `required_features`/`forbidden_changes`.
- So `verify_completion` (`proxyloop_telecom_domain/domain.py`) raises
  `ValueError: fees_minor must be a non-negative integer` for an offer with a
  -1000 CREDIT line, and the runtime's `offer_compliance_violations_for_case`
  (`proxyloop_case_runtime/runtime.py`, called from `append_event`) raises the
  same, turning a contract-valid Provider offer into an unhandled error.

## Frozen design

1. Add `case_offer_violations(case, offer, *, evaluated_at, applied_changes=())
   -> tuple[str, ...]` in `proxyloop_telecom_domain.domain`, exported from the
   package. It returns `("missing_bill_snapshot",)` when the Case has no bill,
   `("compliance_context_invalid",)` when building `OfferComplianceContext`
   raises `ValueError`, `("offer_terms_invalid",)` when building
   `OfferComplianceTerms` raises `ValueError`, else delegates to
   `offer_compliance_violations`. Only `ValueError` from those two
   constructors is caught; no bare `except Exception`.
   Root decision (amendment): a naive or non-UTC `evaluated_at` is a caller
   bug, not offer data. It is validated first, before the bill check and the
   first `try`, and raises `ValueError("evaluated_at must be timezone-aware
   UTC")`; only data-derived invalidity maps to a reason code.
2. `verify_completion` and `offer_compliance_violations_for_case` (kept, same
   exported name, now a one-line wrapper) both call it; the duplicated context
   construction is removed. `CompletionOutcome` has no REJECTED, so an invalid
   offer yields `NEEDS_REPLAN` with the reason code.
3. The helper name does not match the uniqueness regex
   `^def _?offer_compliance_violations\(` in
   `tests/integration/test_offer_policy_authority.py`.

## Non-goals and recorded limits

- No wire/contract change: non-negative fees at the wire is deferred to a
  future 1.2 contract set.
- No fee-netting rule change: a +1000/-1000 fee pair still nets to 0 and is
  evaluated as a zero fee sum.
- No `ml/` or `data/` change; no evaluator number or committed artifact moves.

## Acceptance

- Red on main: `verify_completion` with a negative-fee offer and with duplicate
  `offer.features` returns `NEEDS_REPLAN` containing `offer_terms_invalid`;
  runtime `append_event` on a Case whose offer has a -1000 credit returns
  normally with no approval and not `AWAITING_APPROVAL`.
- No regression: every input of the existing policy test tables, lifted into
  contract-valid Case and offer objects, yields exactly the reason codes
  `offer_compliance_violations` yields.
- Mutation: removing the catches makes the red tests fail.
- Verify: focused tests, `make format-check lint typecheck`,
  `make preflight-fast`, `make test` (no committed-artifact drift). DB and
  Temporal gates are scheduled by the root.
