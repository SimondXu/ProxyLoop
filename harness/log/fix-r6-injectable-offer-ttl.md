# Fix log: injectable offer TTL, persisted in the envelope (R-6)

Finding: `harness/context/audit-remediation-status.md` §4a R-6 ("a runtime
> 24 h test needs an injectable offer TTL"). Investigation, proposed seam
and test plan: `harness/log/fix-pr5-ops-tests.md`, "R-6 deferred until after
PR-7". Root decision (2026-09-24): option (b), the TTL stored in the Provider
configuration as an optional `storage_version` 3 field, defaulting to 1 h,
no version bump, so the codec keeps detecting a tampered `expires_at`.
Branch `fix/r6-injectable-offer-ttl` from `main` @ `973258a`.

## What changed

- `provider_simulator/provider.py`: `DEFAULT_OFFER_TTL = timedelta(hours=1)`;
  `FictionalMobileProvider(*, offer_ttl=DEFAULT_OFFER_TTL)` refuses a
  non-positive TTL, exposes `offer_ttl`, and `issue_offer` uses it. Default
  output unchanged.
- `case_runtime/runtime.py`: `ThinAgentRuntime(..., offer_ttl=DEFAULT_OFFER_TTL)`
  refuses a TTL that is not positive, not whole seconds (storage keeps
  seconds), or longer than `_CASE_DEADLINE_WINDOW` (9 days, the constant
  `_case_at` now uses for the goal deadline). The offer is issued at
  creation, so this bound is the proposed "`offer.expires_at` not past the
  Case deadline" check done once, at construction, before any write; an
  approval therefore never outlives the manifest. `create_case` passes it to
  the Provider (its only Provider construction).
- `case_runtime/postgres_repository.py`: the envelope gains
  `provider_offer_ttl_seconds: int | None` (`gt=0`). The encoder sets it from
  `state.provider.offer_ttl` only when it is not the default and omits the key
  otherwise (the PR-13 `standing_proposal` precedent), so a default row is the
  document an earlier writer produced. A validator refuses the default stored
  by value (one document per Case). `_reconstruct_provider` builds the
  Provider with the stored TTL (default when absent) and still requires the
  regenerated offer to equal the stored one.
- `repository.py`: unchanged; the in-memory store keeps the Provider object,
  which carries the TTL.
- No contract, API, Workflow, or artifact change. `offer_ttl` is a
  constructor parameter only (no environment variable).

## Red → green

`tests/integration/test_r6_injectable_offer_ttl.py`, 20 items, DB-free. On
the tree before the implementation: 17 failed, 3 passed (the three that
already held: the default-TTL counter-control, the default stored by value,
a tampered default-TTL expiry). After: 20 passed.

- 48 h TTL: offer and approval expire at T+48 h, within the manifest.
- In-memory: approve at T+25 h → COMPLETE, `execution_count == 1`, one
  `confirmation` Evidence.
- Counter-control: default TTL, approve at T+25 h → `CaseConflictError`
  "approval expired", no execution, no completion.
- Through the codec (`_CodecChannelRepository`: every write is
  encode → JSON → decode, so the Runtime continues with the reconstructed
  Provider): approve at T+25 h → COMPLETE; the terminal state round-trips.
- Stored and read back: `provider_offer_ttl_seconds == 172800`; decoded
  Provider TTL 48 h; all non-Provider fields equal.
- Default row: no `provider_offer_ttl_seconds` key; key set equals the
  pre-change v3 document; decodes to the 1 h TTL.
- Rejected with "stored Case payload is invalid": tampered `expires_at`,
  tampered TTL, dropped TTL, TTL 0 (on a 48 h row); the default stored by
  value; a tampered `expires_at` on a default row.
- Runtime refuses TTL 0, −1 h, 1 h + 1 µs, 9 days + 1 s; 9 days is accepted
  and the approval ends exactly at the Case deadline and manifest expiry.
- Provider refuses 0 and −1 s.

DB-gated (written, **not run**; runs in `make postgres-check`):
`test_postgres_keeps_an_injected_offer_ttl_and_checks_the_offer_expiry` in
`tests/integration/test_phase_04c_persistent_case_store.py`: a 48 h Case
read by a fresh repository keeps the TTL; a default-TTL Runtime on another
fresh repository approves it at +25 h (the TTL comes from storage, not the
reading Runtime) → COMPLETE; the stored key is `172800`; a `jsonb_set` of
`snapshot.offers[0].expires_at` makes `get` fail closed.

## Gated-skip pin

`test_phase_04c_persistent_case_store.py` 29 → 30; total 66 → 67.
`EXPECTED_GATED_SKIPS_PER_FILE` in `scripts/check_gated_skips.py` and the
list in `docs/development.md` updated.

## Checks (on this branch, variables unset)

- `make lint`: passed.
- `make typecheck`: passed (mypy 78 and 70 source files, no issues).
- `make test`: passed; runtime 2091 passed, 67 skipped; ml 498 passed,
  1 skipped; contracts, 03A1-R execution contract, rescore, negotiation and
  Fast/Slow split checks all current. `git status` shows no committed
  artifact moved.
- `make preflight`: passed; web vitest 250 passed; gated skips 67, matching
  the per-file pin.
- Not run: `postgres-check`, `phase05a-check`, `phase06b1-check` (DB gates;
  `PROXYLOOP_TEST_*` not set, by instruction). Independent review not done.

## Known limits

- Persisted Cases keep the manifest they were minted with (no migration;
  A-11 log). Unchanged.
- A process from before this change cannot read a row that carries
  `provider_offer_ttl_seconds` (mixed versions unsupported, as for PR-13).
- Nothing in the product selects a non-default TTL; the seam is for tests
  and future configuration.
