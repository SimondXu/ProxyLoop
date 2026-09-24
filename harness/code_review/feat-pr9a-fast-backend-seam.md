# PR-9a Fast backend seam review

**Target**: `feat/pr9a-fast-backend-seam` as pushed during the review (head
`1b063a6`, `main` @ `c018390` merged), spec
`harness/context/pr9-local-distilled-fast-design.md` (9a part).

**Reviewer**: independent read-only `reviewer` subagent. Probes:
`scratchpad/rev-pr9a/` (`probe_wire.py`, `probe_e2e.py`, `probe_trickle.py`,
`probe_url.py`).

**Recommendation**: Request Changes, with no Blocking finding. The root accepted
I1 and M1–M4 as below and passed them to the implementer, who wrote this file
from the root's messages. The root also added one decision of its own: the
default timeout goes to 25 s, following PR-9b's measurement.

## Findings and disposition

| # | Finding | Disposition |
|---|---|---|
| I1 (Important) | Some malformed gateway bodies escaped the Fast call as a raw exception: 500 `internal_error`, command not applied, only the Slow trace written (reproduced with `{"status":"invalid_output","detail_code":["x"],...}`). Causes: allow-list membership tests on unhashable values (`TypeError`) and integers past Python's 4300-digit conversion limit (`ValueError` outside the caught set). | Applied in `local_fast_wire.py`. `_load` maps every `ValueError` (JSON, UTF-8, int digit limit) and `RecursionError` to `WireError("body_not_json")`, and re-raises its own `WireError`s unchanged. The status, detail and backend membership tests are guarded with `isinstance(x, str)`; a non-text value is `body_shape_invalid`. Tests: `test_malformed_bodies_are_wire_errors` (deep nesting, huge int in usage, huge int in output), `test_a_decide_response_is_strict` (status `[]`/`{}`, detail list or dict), transport-matrix row `detail_not_text` (200, fallback, command applied, `FAILED` with `fast_adapter_protocol_error`/`body_shape_invalid`), `test_a_bad_identity_body_refuses_to_start` (list backend, dict label, huge int, deep nesting all give `LocalFastStartupError`). |
| M1 | The timeout bounded each socket read, not the call. A gateway trickling one byte at a time held the call, and the B2-8 app lock, far past `PROXYLOOP_FAST_TIMEOUT_S` (`probe_trickle.py`: 2.5 s wall at a 0.3 s timeout). | Applied as a fix, not a doc correction. `_exchange` uses a connection whose socket wrapper sets the socket timeout to the remaining whole-call budget before every read and write, and raises `TimeoutError` once the budget is spent. Connect is bounded by the same deadline. The wrapper's close is a no-op and `_exchange` closes the real socket, because `http.client` closes the connection before it reads a `Connection: close` body. Tests: transport-matrix rows `trickle_head` and `trickle_body` (a byte every 0.1 s at a 0.3 s timeout) give `FAILED` with `fast_adapter_timeout`, with trace latency under 1.5 s against a 4 s trickle. |
| M2 | Identity text fields were only length-checked, so a control character or a long value could push the composed trace identity past 256 characters, where the trace silently falls back to "unversioned". `connect` did not pin the served prompt or model. | Applied. Identity fields (text fields, adapter fingerprint, mlx names and versions) must be tokens: printable ASCII without spaces, at most 128 characters. `connect` refuses unless `prompt_version == "v6"` and `base_model == "Qwen/Qwen3-8B-MLX-bf16"` (`SERVED_*` constants that mirror the frozen ml `QWEN3_8B_BF16_SPEC`; the runtime cannot import ml). Tests: `test_identity_fields_are_tokens`, `test_connect_pins_the_served_prompt_and_base_model`. |
| M3 | `_infer_adapter_mode` reported an unrecognised `LabelledFastBackend` label as `model`. | Applied in `runtime.py`: an unknown label raises `ValueError` at Runtime construction. Test: `test_an_unknown_backend_label_is_refused`. |
| M4 | Two different `BACKEND_LABELS` (the wire's human labels and the adapter's `adapter_mode` values) were easy to confuse. | Applied: the adapter's map is now `proxyloop_local_fast.ADAPTER_MODE_BY_BACKEND`. The wire keeps `BACKEND_LABELS`, the name PR-9b's gateway also uses. |
| Root decision | PR-9b measured distilled latency locally: p50 21.3 s, max 26.9 s, 134/240 calls over 20 s and 15/240 over 25 s. | `DEFAULT_TIMEOUT_S` is now 25 s, the cap, and the cap stays 25 s (30 s Temporal and proxy limits). A timeout fallback is expected on about 6% of held-out-like calls, and the app lock can be held for up to 25 s. Recorded in the spec (dated amendment), `docs/architecture.md`, `docs/development.md` and the log. Test: `test_the_default_timeout_is_the_25_second_cap`. |

## Verification after the follow-up

- Red first: the new cases failed on the reviewed tree, 21 failed and 66 passed
  in the two files (`test_local_fast_adapter.py`, `test_local_fast_config.py`).
  The reviewer's probes reproduced I1 (`TypeError` and `ValueError` escapes, and
  a 500 with no Fast trace) and M1 (2.5 s wall at a 0.3 s timeout).
- After the fixes, the four PR-9a test files pass. `probe_wire.py` gives a
  `WireError` for every case. `probe_e2e.py` gives 200 plus a `FAILED` Fast
  trace. `probe_trickle.py` ends in `fast_adapter_timeout`.
- The repository checks are in the log, `harness/log/feat-pr9a-fast-backend-seam.md`.
- `runtime.py` changed (M3), so the DB gates were rerun on `8b9adae`:
  `postgres-check` 38, `phase05a-check` 53, `phase06b1-check` 56 passed.

## Focused re-review

**Target**: `8b9adae` (the I1/M1–M4 fixes and the 25 s timeout).
**Recommendation**: Approve, with one Minor that the root accepted.

| # | Finding | Disposition |
|---|---|---|
| N1 (Minor) | A near-zero timeout (for example `PROXYLOOP_FAST_TIMEOUT_S=1e-300`) passed validation. `_exchange` built `_DeadlineConnection` before its `try`, so the expired deadline raised an untyped `TimeoutError` and the server crashed at start with a traceback. | Fixed both ways, in `proxyloop_local_fast` only (no `runtime.py`; the DB gates are unaffected). (a) `validate_timeout`, which the environment parse now also uses, refuses anything below `MIN_TIMEOUT_S = 0.1`. (b) `_exchange` builds the connection inside the `try`, so any deadline expiry becomes `fast_adapter_timeout`. Red first: 5 failed on `8b9adae`, all an untyped `TimeoutError` or a failed startup. Tests: `1e-300` and `0.09` in the environment refusal matrix, `test_connect_refuses_a_timeout_below_the_floor`, `test_an_expired_deadline_is_a_typed_timeout`. Docs now state the range as [0.1, 25]. |
