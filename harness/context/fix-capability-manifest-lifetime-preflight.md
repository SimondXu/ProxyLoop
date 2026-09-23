# Fix: the runtime capability manifest lives until the Case deadline (A-11)

Bounded change under the audit-remediation programme
(`harness/context/audit-remediation-status.md`, row A-11). The design was frozen
by the root orchestrator on 2026-09-23 from an `architect` (Opus) proposal
(the D1/A-11 design note, slice P-A). Audit source:
`harness/code_review/repo-audit-A.md` §A-11.
Branch `fix/capability-manifest-lifetime` from `main` @ `383d1fa`.

## Defect (observed on main)

`ThinAgentRuntime.create_case` mints the Case's only capability manifest with
`_manifest(created_at)`; `_snapshot` falls back to `_manifest(case.created_at)`.
Both the manifest and its one `CapabilityDefinition` get
`expires_at = issued_at + 1 day`. Every later snapshot reuses that manifest, and
`CapabilityExecutor._validate` (`agent_core/capabilities.py`) rejects execution
at or after it with `capability_manifest_expired` (and `capability_expired`).
Nothing outside the executor handles that reason.

Today the simulator offer lives one hour (`provider.py` `issued_at + 1 h`), so
the approval and intent built from it also expire long before the manifest,
which hides the problem. Once an offer or approval window runs past 24 h, a
valid approval can't execute. `GOALS.md` ("survive waits") and
`architecture.md` ("wait across days") both name that as the target. On
`main`, a 48 h offer approved and executed at T+25 h is rejected with
`('capability_manifest_expired', 'capability_expired')`.

## Frozen design

1. **Mint once per Case, expiring at the Case deadline.**
   `_manifest(case: Case)` sets `issued_at = case.created_at` (same instant
   as today at both call sites) and `expires_at = case.goal.deadline` on
   both the manifest and its capability definition. The runtime always sets
   the deadline (`_case_at`: `created_at + 9 days`); a Case without one
   raises `RuntimeError`. Both call sites (`create_case`, `_snapshot`
   fallback) pass the Case.
2. **Invariant I9: every approval the runtime builds satisfies
   `approval.expires_at <= manifest.expires_at`.** `_build_approval` takes
   the snapshot's manifest and raises `RuntimeError` instead of returning an
   approval that outlives it. The guard is defensive and unreachable today:
   offers are issued only at Case creation with a 1 h lifetime, and an
   approval is built only while the offer is compliant (unexpired).
3. Rejected alternatives (root decision): a manifest per snapshot (the
   manifest fingerprint is a planning-basis component, so every snapshot
   would trigger a refresh under A-1); a manifest per execution (the
   executor would then validate what it just minted); no expiry
   (`CapabilityManifest.expires_at` is a required canonical field).
4. Out of scope: persisted Cases (they keep their 1-day manifest), an
   injectable Provider offer TTL, and any contract, executor, or
   `postgres_repository.py` change. `postgres_repository.py` doesn't mint a
   manifest; it only persists the snapshot.

## Tests (`tests/integration/test_capability_manifest_lifetime.py`)

These run at the executor seam. Each snapshot is built with the runtime's
`_snapshot` from a real runtime-created Case, with a hand-built APPROVED
intent and approval.

1. A 48 h offer and approval, using the Case's manifest, executes at T+25 h
   (`EXECUTED`). Counter-control: the same scenario with the old 1-day
   manifest is rejected with exactly `{capability_manifest_expired,
   capability_expired}`.
2. With an offer that lives until the deadline, execution one minute before
   the deadline succeeds. At the deadline and one hour after it, execution is
   rejected with `capability_manifest_expired`.
3. A new runtime Case has `manifest.issued_at == case.created_at` and
   `manifest.expires_at == capability.expires_at == case.goal.deadline`. After
   the next event the manifest is unchanged (minted once), and the built
   approval satisfies I9.
4. `_build_approval` accepts an offer that expires exactly at the manifest
   expiry and refuses one second past it.

Artifact impact: `make harness-check` and `make benchmark-check` mint their own
manifests (`scripts/run_phase_03a1_harness.py` `_probe_capability_manifest`)
and don't import `proxyloop_case_runtime`, so no committed artifact changes.
