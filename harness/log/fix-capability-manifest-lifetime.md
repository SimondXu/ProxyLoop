# Fix log: the runtime capability manifest lives until the Case deadline (A-11)

Spec: `harness/context/fix-capability-manifest-lifetime-preflight.md`.
Programme: `harness/context/audit-remediation-status.md` (row A-11); design
frozen by the root orchestrator on 2026-09-23 (D1/A-11 design, slice P-A).
Branch `fix/capability-manifest-lifetime` from `main` @ `383d1fa`.

## What was wrong

The runtime minted each Case's only capability manifest with
`expires_at = issued_at + 1 day` and reused it for every later snapshot. The
executor rejects execution at or after that instant
(`capability_manifest_expired`, `capability_expired`). The 1 h simulator
offer masked this. Any approval window longer than 24 h would have failed
to execute even while the offer and approval were still valid.

## What changed

- `case_runtime/runtime.py`:
  - `_manifest(case)` sets `issued_at = case.created_at` (unchanged instant)
    and `expires_at = case.goal.deadline` on both the manifest and its
    capability definition. A Case without a deadline raises `RuntimeError`.
    Both call sites (`create_case`, the `_snapshot` fallback) pass the Case.
  - `_build_approval(..., manifest=...)` refuses to return an approval with
    `expires_at > manifest.expires_at` (I9). The one caller passes the event
    snapshot's manifest. This guard is unreachable today.
- `tests/integration/test_offer_policy_authority.py`: the one external
  caller of `runtime._manifest` now passes `Phase01AEpisode.success().case`.
  It was previously a bare datetime. The test only compiles against the
  manifest's capability ids, and its assertions are unchanged.
- No other file mints the runtime manifest. `postgres_repository.py` only
  persists snapshots. The harness, benchmark, ML and fixture manifests are
  independent. `phase-04a-runtime-v1` appears in no committed artifact.

## Red → green (`tests/integration/test_capability_manifest_lifetime.py`)

| Test | Pre-fix (`main` sources) | Post-fix |
|---|---|---|
| 48 h approval executes at T+25 h | REJECTED `('capability_manifest_expired', 'capability_expired')` | passes |
| counter-control: same with the old 1-day manifest | passes | passes |
| execution at deadline − 1 min succeeds | REJECTED, same reasons | passes |
| execution at deadline / deadline + 1 h rejected (`capability_manifest_expired`) | passes | passes |
| new Case: manifest and capability expire at `goal.deadline`; manifest unchanged after the next event; approval ≤ manifest | `2026-09-02 12:00 != 2026-09-10 12:00` | passes |
| `_build_approval` refuses an approval one second past the manifest | `TypeError` (no `manifest` kwarg) | passes |

Pre-fix run: 4 failed, 3 passed. Post-fix run: 7 passed.

## Known limits

- Persisted Cases keep the 1-day manifest they were minted with. There is no
  migration, and such a Case still cannot execute after its first day.
- The runtime-level long-window path is exercised only at the executor
  seam. A runtime end-to-end test of a > 24 h approval needs an injectable
  Provider offer TTL (`provider.py` fixes `issued_at + 1 h`).
- The executor still does not gate on the Case deadline directly; the
  manifest expiry now carries that bound.

## Checks

- Implementer: the new module + 05a/04a/slow-refresh/offer-policy suites 63
  passed; `make lint`, `make typecheck`, `make preflight-fast`,
  `make harness-check`, `make benchmark-check` passed.
- Review (`reviewer`, Opus): **Approve**, no Blocking/Important. Minor 1
  (make `_snapshot`'s `manifest` required) deferred to the 1.1 PR2, which
  rewrites `_snapshot`; Minor 4 (the guard raises after the Fast decision if
  it ever becomes reachable) recorded for the offer-TTL slice.
- Root, final diff (serial, Compose profiles up, `PROXYLOOP_TEST_DATABASE_URL`
  and `PROXYLOOP_TEST_TEMPORAL_ADDRESS` set): `make preflight` exit 0 (runtime 754 passed incl. DB-gated tests, ML and web green);
  `postgres-check` 27, `phase05a-check` 31, `phase06b1-check` 32 — all passed.
  An earlier run failed intermittently (`case_not_found`, `state_invalid`)
  because another worktree's Temporal tests truncated the shared
  `proxyloop_test` database at the same time; rerun serially, all green.
