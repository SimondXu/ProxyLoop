# 1.1 PR3: the ModelTrace producer (P1 A-2)

Design: `harness/context/schema-1.1-design.md` (PR3 row; decision 12 of
`audit-remediation-decisions.md`: `ModelTrace` is emitted with a `role`, not
deleted). Contracts are final (PR1, #65); the seam
`CoordinatorOutcome.traces: tuple[ModelTrace, ...] = ()` was frozen in PR2.
Branch `feat/model-trace-producer` from `main` (after PR2).

## Defect (audit A-2)

`ModelTrace` has no producer: no model call made by the runtime is recorded
anywhere a later judge, latency measurement (Stage 6) or audit could read.

## Frozen design

1. `agent_core/interfaces.py`: an optional traced-adapter protocol — an
   adapter may expose a stable identity (`provider`, `model`, prompt version)
   and, per call, usage/latency. Adapters that do not implement it still
   work (the coordinator records what it knows).
2. `CaseCoordinator.advance` emits **one 1.1 `ModelTrace` per adapter call,
   including rejected results** (`role` = `fast` | `slow`; `reason_codes` =
   the audit's reason codes; `input_pins` = the request pins; `request_id`
   where one exists; result status accepted/rejected), **only for 1.1
   snapshots** (1.0 snapshots emit nothing — the ML/evaluation world is
   untouched). Timestamps come from an injected clock (no wall-clock reads
   inside the coordinator); latency measured with an injected monotonic
   source. Traces go in `CoordinatorOutcome.traces`; nothing else changes.
3. `scripted.py`: the scripted adapters expose identity (`provider="scripted"`,
   deterministic, zero tokens).
4. `openai_adapter/adapter.py`: tokens from `response.usage` when present;
   provider/model from the adapter config; latency measured around the call.
   A model call that raises produces no trace in this PR (known limit, as the
   design records).
5. No persistence here (PR4 appends `outcome.traces` to runtime state), no
   snapshot/view/browser field: a test scans snapshot, Fast/Slow views and
   the API projection and finds no trace id.
6. Never touch `ml/`, frozen modules, `data/`, contracts, `runtime.py`,
   `repository.py`, `postgres_repository.py`, `commands.py`.

## Tests

One trace with the right `role` per adapter call (Fast only, Slow only,
Fast + Slow refresh), including a rejected result (`accepted=False`,
reason codes present); none for a 1.0 snapshot; deterministic timestamps
with the injected clock; token counts from a fake `response.usage`; no trace
id in snapshot, views or `_result_payload`; ML evidence gates unchanged.

## Verification

Focused tests; `make lint`, `make typecheck`, `make format-check`,
`make preflight-fast`, `make test` (`data/` clean). No Compose (root runs it).
