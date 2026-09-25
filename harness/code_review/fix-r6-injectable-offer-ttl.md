# R-6 injectable offer TTL Independent Review

**Date**: 2026-09-24
**Branch**: `fix/r6-injectable-offer-ttl` (R-6 follow-up, root decision (b))
**Reviewer**: independent read-only `reviewer`
**Recommendation**: Request Changes, no Blocking finding

## Scope reviewed

The Provider and Runtime `offer_ttl` seam, the optional `storage_version` 3
field `provider_offer_ttl_seconds` in the PostgreSQL codec
(`_encode_state`, `_decode_state`, `_reconstruct_provider`), the DB-free
tests in `tests/integration/test_r6_injectable_offer_ttl.py`, the DB-gated
04C test, the gated-skip pin, and the docs. Reviewed at `5b48935`.

The reviewer probed the codec without a database: default-row byte identity
(`bytes.py`), payload tampering including type confusion, null, and huge TTLs
(`tamper.py`), and a consistent 30-day forgery built by bypassing the
Runtime's bound and the approval-time manifest guard (`forge30.py`). The
probes are in the session scratchpad (`rev-r6/`), not committed.

## Findings and disposition

This records the findings as the root relayed them, with the root's decisions
and the implementer's disposition.

| Finding | Disposition |
| --- | --- |
| Important I-1: the stored TTL has no upper bound on read (the field had only `gt=0`). A huge TTL raised an uncaught `OverflowError` (`10**12`: date out of range in `issue_offer`; `10**15`: `timedelta` overflow in `_reconstruct_provider`) instead of "stored Case payload is invalid", so the worker would not see the non-retryable `state_invalid`. A consistent 30-day row (offer, Evidence, intent and approval agreeing, manifest guard bypassed) decoded with an approval that outlives the manifest; the probe then tried to approve it on day 10. | Fixed per root decision. `MAX_OFFER_TTL = timedelta(days=9)` now lives in `provider.py` and is the single source for the Runtime constructor bound, the Runtime Case deadline window (`_CASE_DEADLINE_WINDOW = MAX_OFFER_TTL`), and the envelope field's `le=`. `_reconstruct_provider` also refuses `offer.expires_at > snapshot.capability_manifest.expires_at`. `_decode_state` catches `OverflowError` alongside the existing wrapper (defense in depth: with `le=` pydantic refuses these values first). Regression tests: `10**12` and `10**15` → invalid payload; `MAX + 1` → invalid; a consistent 30-day row is refused on write and on read; a 48 h offer on a Case with a one-day manifest (in-range TTL) is refused on write and on read, which isolates the manifest check. |
| Minor M-1: an explicit `"provider_offer_ttl_seconds": null` decoded as the default, so a Case had two encodings. | Fixed: the envelope validator refuses a null that is in `model_fields_set`; the encoder passes the field only when it is not the default, so its own write is unaffected. Test on a default row. `standing_proposal` has the same gap (explicit null accepted); per the root it is not changed in this PR and is recorded as a follow-up in the log. |
| Minor M-2: missing tests for a TTL added to a default row, out-of-range values, overflow, and the explicit null. | Fixed: `test_the_codec_rejects_a_ttl_key_on_a_default_row` (default by value, null, 7200, `10**15`) and the 48 h tamper list extended (−5, null, `MAX + 1`, `10**12`, `10**15`, float, string, bool). |
| Minor M-3: a consistent multi-field forgery (TTL, `expires_at`, offer Evidence, intent and approval expiry together) is accepted. | Recorded as a known limit in the log and in `docs/architecture.md`: the codec's integrity comes from simulator replay, with no authentication, the same class as R-18's consistent-forgery limit. The 9-day bound and the manifest check cap the window. |

## Verification after the fixes

Merged `main` @ `e543d64` (#103) first; clean, gated-skip pin unchanged at
67. On the pre-review codec (`runtime.py` and `postgres_repository.py` from
`2ace7fb`), 6 of the 34 R-6 test items fail: `10**12` and `10**15` raise
`OverflowError`, null on a default row and the 30-day and one-day-manifest
forgeries do not raise. After the fixes all 34 pass.

- `make lint`, `make typecheck`: passed.
- `make preflight` (runs `make test`): passed; runtime 2105 passed,
  67 skipped; ml 498 passed, 1 skipped; vitest 256 passed; committed checks
  current; gated skips 67, matching the per-file pin.
- `make postgres-check`: not yet rerun after the codec change (needs the DB
  lane). Before the fixes, on `4442472`: `postgres-check` 39,
  `phase05a-check` 73, `phase06b1-check` 56 passed.

Re-review: the root decides whether the I-1 change warrants one.
