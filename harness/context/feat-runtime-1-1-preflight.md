# Feat: runtime produces contract set 1.1 (PR2: A-1, A-10, A-6 producer)

Slice PR2 of `harness/context/schema-1.1-design.md`, which holds the root
decisions and is authoritative (decisions 1 to 5, including the tightened
decision 3). PR1 (#65, the 1.1 contract set) is on `main` and final. Branch
`feat/runtime-1-1` from `main` @ `69924fe`.

## Scope (owned files)

- `runtime/packages/case_runtime/src/proxyloop_case_runtime/runtime.py`:
  - `_basis` and `_snapshot` produce 1.1 snapshots with the narrowed formula;
  - `_snapshot`'s `manifest` becomes a required argument (deferred A-11
    review minor);
  - on completion, a `CompletionReceipt` built from the approved approval,
    the executed offer, and the CONFIRMATION Evidence the runtime already
    writes;
  - `_record_rejection` records the Router's route instead of the
    hard-coded `fast_now`.
- `runtime/packages/agent_core/src/proxyloop_agent_core/router.py`:
  `strategy_basis_incompatible` when a 1.1 snapshot's strategy binding
  differs from its pins. A 1.0 strategy (no binding) inside a 1.1 snapshot
  is incompatible, so the next event refreshes it once through the existing
  `_refresh_strategy_if_required`.
- `runtime/packages/agent_core/src/proxyloop_agent_core/coordinator.py`:
  `slow_strategy_basis_mismatch` at 1.1; `CoordinatorOutcome.traces = ()`
  freezes the PR3 seam (nothing populates it).
- `runtime/packages/agent_core/src/proxyloop_agent_core/scripted.py`,
  `runtime/packages/openai_adapter/src/proxyloop_openai_adapter/outputs.py`:
  stamp strategies with `strategy_basis_binding`, through construction,
  never `model_copy(update=...)`.
- New `tests/integration/test_strategy_basis_binding.py`.
- `docs/architecture.md` (~line 189) and `CONTEXT.md` materiality wording.
- Existing tests only where they assert a 1.0 runtime snapshot; each edit is
  listed in the log as an intended consequence.

## Non-goals

- No contract change (PR1 is final), no `ml/`, `data/`, or frozen module.
- No `ModelTrace` producer (PR3), no persisted `ExecutionClaim` or envelope
  change (PR4).
- `expire_approval` records the Router's decision instead of a hard-coded
  `fast_now` (root decision 2, added during the slice). An expired approval
  is not material at 1.1, so this is `fast_now` while the strategy is
  current.
- The 1.0 ML/evaluation world stays 1.0: producers stamp whatever version
  the planning basis they receive carries.

## Frozen acceptance (written first where possible)

1. A-1: an offer revision change under a still-valid strategy routes
   `slow_refresh` with `strategy_basis_incompatible` (on `main`: `fast_now`).
2. An expired approval routes `fast_now` and makes no Slow call.
3. A rejected approval routes `slow_refresh`.
4. A stored 1.0 Case (in-memory state built at 1.0, and a 1.0 Postgres
   storage envelope decoded without a database) refreshes its strategy on the
   next event and continues.
5. A full approved flow ends in a 1.1 COMPLETE snapshot whose receipt is
   bound (approval, offer, CONFIRMATION Evidence, COMPLETE decision) and
   validates.
6. `_record_rejection`'s route follows the Router.
7. Every ML evidence gate is unchanged: `make test` green and
   `git status --porcelain data/` empty (prompt-set, hosted-rescore,
   validity-smoke, phase03c-rescore, harness).

## Verification

New and affected runtime tests; `make lint`, `make typecheck`,
`make format-check`, `make preflight-fast`, `make test` (after
`pnpm install --frozen-lockfile`). No `PROXYLOOP_TEST_*` variable and no
Compose gate: the root runs `postgres-check`, `phase05a-check`, and
`phase06b1-check` serially.

## Escalate

Stop and report if a contract rule blocks a legitimate runtime shape, a
stored 1.0 Postgres row cannot load, or the A-1 route change breaks the
channel path or the workflow in a way the design does not cover.
