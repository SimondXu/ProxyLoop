# Fix log: the event paths refresh an expired strategy through Slow (P1 B2-3, B2-5)

Spec: `harness/context/fix-slow-refresh-strategy-expiry-preflight.md`.
Programme: `harness/context/audit-remediation-decisions.md` (decision 10).
Branch `fix/slow-refresh-strategy-expiry` from `main` @ `dcc2b43`.

## What was wrong

`_append_event_serialized` and `ingest_channel_event` called
`CaseCoordinator.advance(..., fast=...)` without a Slow adapter. Every
strategy expires 30 minutes after it is written, after which the Router
returns `SLOW_REFRESH(strategy_expired)`, `advance` returns
`SLOW_UNAVAILABLE`, and the runtime raised `ModelRuntimeError("fast")`:
every consumer message and every mailbox message after T+30 min was
refused while the offer was still valid for another 30 minutes.

## What changed

- `case_runtime/runtime.py`: `_refresh_strategy_if_required(event_snapshot,
  event, occurred_at)`, called by both event paths before their unchanged
  Fast step. It calls `advance(..., slow=self._slow)` only; any route other
  than `SLOW_REFRESH` returns the snapshot unchanged without a model call.
  On `SLOW_REFRESH` it requires an accepted Slow result with a strategy that
  is new — a different id, or the same id with a higher revision — else
  `ModelRuntimeError("slow")` with nothing persisted; it installs the
  strategy at `revision + 1`. The approval, intent and channel outbox then
  pin the refreshed strategy. `FAST_NOW_AND_SLOW_REFRESH` is deliberately
  not handled: the event paths never set `bounded_acknowledgement_allowed`.
- `agent_core/scripted.py`: a refresh of the same scripted strategy returns
  `revision = prior + 1`; the first strategy is byte-identical to before
  (`make harness-check` unchanged).
- B2-5: no execution gate on `strategy.expires_at` was added; T3 pins that
  an approval decided after strategy expiry still executes once.

## Red → green (`tests/integration/test_slow_refresh_strategy_expiry.py`)

| Test | Pre-fix | Post-fix |
|---|---|---|
| T1 message at T0+31 m → new strategy, approval pins it, Fast present | `ModelRuntimeError` (`runtime.py:893`) | passes |
| T2 T1 then approve at T0+40 m → executed once, complete | same | passes |
| T3 approve at T0+45 m under the expired T0 strategy (B2-5) | passes | passes (pin) |
| T4 channel message at T0+31 m → outbox pins new strategy | `ModelRuntimeError` (`runtime.py:449`) | passes |
| T5 Slow rejected (same id+rev / expired) → nothing persisted | raised `fast`, not `slow` | passes |
| T5-channel (+ revision regression at T0+62 m) → no outbox, inbox `reserved` | — | passes; fails if `<=` is weakened to `==` |
| T6 / T6-channel before expiry → no Slow call | passes | passes |
| scripted refresh bumps revision | `1 == 2` | passes |

## Review

Independent review (`reviewer`, Opus): **Approve**, no Blocking/Important.
The reviewer re-ran the new tests against `main` sources (T1, T2, T4, T5 fail
for the stated reasons), ran `make test`, `postgres-check` 27,
`phase05a-check` 31, `phase06b1-check` 32, and a Postgres round-trip probe
(refreshed strategy rev 2 read back identically; a new runtime instance
approves at T0+40 m and executes once). Minors applied: M1 helper handles
`SLOW_REFRESH` only; M2 reject a same-id revision regression; M3
channel-path T5/T6.

## Known limits

- In model mode the first message after expiry costs a Slow call plus a Fast
  call while the Case lane is held (worst case about twice
  `PROXYLOOP_MODEL_TIMEOUT`). This is the price of decision 10.
- A Slow failure on the channel path leaves the inbox reservation
  `reserved`, the same state a Fast failure already left.
- Slow action proposals from the refresh are ignored; the approval is still
  built by the offer-policy path (A-4, proposal stage 1).
- A Temporal end-to-end run across a real 30-minute gap is not exercised;
  the Temporal tests use short clocks.

## Checks

See the PR body for the final `make preflight` and real-dependency gate output.
