# 1.1 PR4: the canonical execution claim and model traces are persisted (P1 B2-1 contract half, A-2 storage)

Design: `harness/context/schema-1.1-design.md` (PR4 row; decision 2: the
claim lives on runtime state, not on the snapshot). Contracts are final
(PR1, #65: `ExecutionClaim` 1.1, `ModelTrace` 1.1); the seam
`CoordinatorOutcome.traces` was frozen in PR2 (PR3 populates it; PR4 must
work whether it is empty or not). Branch `feat/persisted-claim-and-traces`
from `main` (after PR2).

## Frozen design

1. `case_runtime/commands.py`: delete the runtime-local
   `ExecutionClaimRecord`; the runtime state carries the canonical
   `ExecutionClaim` (1.1): `case_id, approval_id, action_intent_id,
   idempotency_key, before_revision, claimed_at, command_id?,
   command_fingerprint?` (both or neither — direct mode now always has a
   command id since #66; keep the contract's optionality).
2. `repository.py`: `CaseRuntimeState.execution_claim: ExecutionClaim | None`
   and `model_traces: tuple[ModelTrace, ...] = ()`; the existing
   claim/pending consistency invariant keeps holding.
3. `postgres_repository.py`: envelope `storage_version` 2 carrying the
   canonical claim and `model_traces`; **v1 rows load and upgrade on read**
   (`case_id`, `action_intent_id`, `idempotency_key` recovered losslessly from
   `execution_intent`; `model_traces=()`); writes are always v2; no table
   schema change (jsonb payload). A v1 row with a pending claim must load,
   complete and write back as v2.
4. `runtime.py`: the claim write builds the canonical `ExecutionClaim`;
   every path that runs the coordinator appends `outcome.traces` to
   `model_traces` in the same state write (no separate write); traces are
   never copied into the snapshot, views, transitions or the API projection.
   Retention: unbounded in this PR (known limit, recorded).
5. Never touch `ml/`, frozen modules, `data/`, contracts, `coordinator.py`,
   `interfaces.py`, adapters (PR3's files).

## Tests

A stored v1 row (encode with the v1 codec shape) with a pending claim loads,
upgrades, completes and round-trips as v2; a v1 row without a claim loads;
the claim/pending invariant rejects inconsistent states; traces placed in
`CoordinatorOutcome.traces` (use a stub coordinator outcome or a fake adapter
that returns traces if PR3 has not landed) are persisted in the same write
and absent from snapshot/API payload; the P0-1 claim-retry path (#38) still
passes with the canonical claim.

## Verification

Focused tests incl. the Postgres codec tests that run without a database;
`make lint`, `make typecheck`, `make format-check`, `make preflight-fast`,
`make test` (`data/` clean). The root runs `postgres-check`,
`phase05a-check`, `phase06b1-check` serially — do NOT set PROXYLOOP_TEST_*.
