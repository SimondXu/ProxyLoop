# Fix: P2 hygiene — model adapter, completion verifier, executor claim, credit constant

Bounded P2 batch under the standing audit-remediation authorization
(`harness/context/audit-remediation-status.md` §4). Branch
`fix/p2-adapter-domain` from `main` @ `5bedcce`. Merged with
`origin/main` @ `c914c1b` on 2026-09-24 (see the log's "Update to
origin/main"); the runtime's persisted claim is now the canonical
`ExecutionClaim` 1.1 (#72), which does not change the design below.
Resolves audit findings **B1-6, B1-7, B1-8, B1-10, B1-11** (all Minor) from
`harness/code_review/repo-audit-B1.md`. Out of scope: B1-9 (negative fees,
a policy decision), B1-12.

## Defects (re-verified on main @ 5bedcce)

- B1-6 `openai_adapter/adapter.py` `_validate_response_model`: accepts any
  response model starting with `f"{requested}-"`, so `gpt-4o-mini` passes
  for a requested `gpt-4o`.
- B1-7 `adapter.py` `_request`: every exception raised inside
  `completions.parse()` is `TRANSPORT` (or `TIMEOUT`), including the
  pydantic `ValidationError` the SDK raises when the returned content does
  not match the schema.
- B1-8 `telecom_domain/domain.py` `verify_completion`: never compares
  `offer.case_id` with `case.case_id`; a foreign offer verifies `complete`.
- B1-10 `agent_core/capabilities.py`: the idempotency and approval records
  are written only after `commit()` returns; a commit that raises after
  mutating leaves no record and a retry through the same executor commits
  again.
- B1-11 `contracts/offer_policy.py` `_KNOWN_CREDITS_MINOR` (5_000) and
  `provider_simulator/scenarios.py` `PROMOTION_CREDIT_MINOR = 5_000` are two
  literals of one value (the audit's `scenarios.py:405` has since become a
  named constant at line 152).

## Frozen design

1. B1-6: accept the exact configured model, or the configured model plus a
   dated snapshot suffix `-YYYY-MM-DD` (the OpenAI alias → snapshot form,
   e.g. `gpt-4o` → `gpt-4o-2024-08-06`) or `-YYYYMMDD` (added after
   review). Any other suffix is
   `MODEL_METADATA`. Exact-only was rejected because it would fail every
   OpenAI alias request.
2. B1-7: `except pydantic.ValidationError` before the generic handler →
   `INVALID_OUTPUT`. Other SDK-side output failures (length / content
   filter finish reasons) are not in this finding and stay as they are.
3. B1-8: `verify_completion` rejects with the new reason code
   `offer_case_mismatch`. `verifier_version` stays `1.0`: no current path
   builds a foreign offer, so no committed decision changes.
4. B1-10: executor-local claim before commit. The executor marks the
   idempotency key and the approval as unresolved before `commit()` and
   clears them only after it returns. A request for an unresolved key or
   approval is `REJECTED ("execution_outcome_unknown",)`; the executor
   never fabricates `REUSED` Evidence for a commit it cannot confirm.
   Reconciliation belongs to the caller against the adapter's own state —
   the runtime already does this (persisted execution claim +
   `provider.confirmation` short-circuit, `fix-runtime-claim-receipt-retry`).
   No interface change; `interfaces.py` and `runtime.py` untouched.
5. B1-11: `offer_policy.py` owns `PREDEFINED_PROMOTION_CREDIT_MINOR`;
   `_KNOWN_CREDITS_MINOR` uses it. `scenarios.py` is a frozen V1 surface
   (`harness/context/d1-simulator-v2-design.md`, decision 1) and is not
   edited; a test pins `scenarios.PROMOTION_CREDIT_MINOR` to the policy
   constant instead.

## Acceptance

- One regression test per item, red on main, green after the fix.
- `make lint`, `make typecheck`, `make format-check`, `make preflight-fast`,
  `make test` pass; `data/` unchanged after `make test`.
