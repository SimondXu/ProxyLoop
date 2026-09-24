# Feature log: scripted Fast dialogue, the disclosure gate, and the per-turn split (PR-8a)

Spec (frozen by the root, 2026-09-24): `harness/context/pr8-fast-dialogue-design.md`,
with the root's dated §5.2 amendment (`fast_result`, `fallback_cause`). Build-plan
item PR-8a (A-4, decision 7, stage 1a). Branch `feat/pr8a-fast-dialogue` from
`main` @ `1573a42` (PR-7's trace log and PR-6's `app.py` included).

Non-goals, per the spec: no change to `app.py`, `workflow.py`, `activities.py`,
`postgres_repository.py`, `contracts/`, `validate_fast_result`,
`project_fast_view`, `ScriptedFastAdapter`, or `BOUNDED_FAST_STATUS_TEXT`; no Web
change (PR-8b); the channel outbound body stays constant (PR-11); no
model-backed measurement (PR-9).

## What changed

- `agent_core/disclosure_gate.py` (new): `fast_disclosure_violations`,
  `FAST_GATE_VERSION = "fast-gate-v1"`, `FAST_GATE_ALLOWED_ACTS`, `FastGate`.
  Pure; sorted unique `fast_gate_*` codes; rules as in spec §2.2. Allowed
  disclosures are strategy ∩ authority, as in `project_fast_view` (I9).
- `agent_core/coordinator.py`: `CaseCoordinator(..., fast_gate=None)`; the gate
  runs only after `validate_fast_result` accepts; a non-empty verdict rejects
  the Fast audit with the gate codes, withholds the decision, and sets
  `CoordinatorOutcome.fast_disclosure_rejected` (default `False`). No gate: no
  change.
- `agent_core/scripted.py`: `ScriptedDialogueFastAdapter`,
  `SCRIPTED_DIALOGUE_LINES` (4 lines), `SCRIPTED_PENDING_SLOW_LINE`.
  `ScriptedFastAdapter` is byte-for-byte unchanged.
- `case_runtime/runtime.py`: the default Fast adapter is
  `ScriptedDialogueFastAdapter`; `_coordinator` passes
  `fast_gate=fast_disclosure_violations` (the single construction site, `_advance`
  unchanged); `_append_event_serialized` delivers gate-passed text or
  `FAST_FALLBACK_TEXT` as an `assistant_message` event (actor system, trigger
  cursor + 1, trigger time, same revision, appended last); a validation reject
  still raises `ModelRuntimeError("fast")`; `append_event` refuses a caller
  `assistant_message`; `_infer_adapter_mode` lists both scripted Fast types.
- `case_runtime/turn_split.py` (new): `fast_slow_split(traces, state)`,
  `TURN_TRIGGER_EVENT_TYPES`, `NON_TURN_EVENT_TYPES` (an unclassified event type
  raises). Join rule: by input cursor; the last Fast trace at a cursor is the
  delivered attempt, with the Slow trace immediately before it; a turn without
  Fast (creation) takes the first succeeded Slow trace, so a repeated
  `create_case` (M7) is an unapplied attempt.
- `scripts/run_fast_slow_split_report.py` (new, `--write|--check`),
  `data/evaluation/fast-slow-split-scripted.json` (new), `make
  fast-slow-split-report`, `make fast-slow-split-check` (in `make test`), the
  script in `PYTHON_PATHS` and the typecheck list. `validate_layout.py` is not
  changed: the newest committed report (`negotiation-v1-ceiling.json`) is not
  registered either, and `--check` fails on a missing file.
- Tests: new `test_fast_disclosure_gate.py` (G1–G8, C1–C3),
  `test_fast_dialogue_delivery.py` (D1–D9, AC1 in direct and fake-Temporal
  mode, AC2 per gate code), `test_fast_slow_split_report.py` (S1–S3, AC5).
  Edited `test_direct_mode_command_path.py` (cursor 2 → 3),
  `test_browser_projection_allowlist.py` (assistant event keys), and
  `test_api_event_loop.py` (strictly increasing times now exclude the
  assistant line, which shares its trigger's time by I6; not listed in the
  spec's test updates).
- Docs: `docs/architecture.md` (Fast delivery, gate v1 rules and limits,
  sequential refresh), `CONTEXT.md` ("Disclosure Gate", "Assistant Message"),
  `harness/context/audit-remediation-status.md` (§0 row, §5 item 1).

## Red (on `main` sources, before any production edit)

`uv run --project runtime --all-packages pytest -c runtime/pyproject.toml -q
tests/integration/test_fast_dialogue_delivery.py` with only D1 and D2:
`2 failed in 1.92s`.

| Test | Red failure |
|---|---|
| D1 `test_scripted_dialogue_line_is_a_visible_event` | `:76` `assert (1, provider, 'provider_offer') == (2, consumer, 'consumer_message')`: the consumer event was the last event; no assistant event existed |
| D2 `test_gate_withholds_undisclosed_text_and_delivers_fallback` | `:114` `assert 'fast' not in {...}`: the leaky text was in the response's `fast` |

## Scenario S2 (dated spec amendment, 2026-09-24)

Found during implementation and confirmed by the root from the PR-13 design
review; recorded as a dated amendment in the spec copy. Spec §5.3 defined S2 as "create ($92 → $70; the offer is non-compliant)". Intake
refuses that: `_case_with_intake` raises `target_monthly_total is incompatible
with the fixed offer` for any target below 7200 cents, so every valid Case has a
compliant $72 offer and the first consumer event opens the approval. The only
runtime-reachable non-compliant offer is an expired one (60 minutes; a
strategy lives 30). `dialogue_path` therefore creates $92 → $75 and talks after
the offer expired: +61 min (refresh), +62…+65 (four `fast_only`), +92 (31
minutes after the refresh: a second refresh), +93. Result: 1 `slow_only`, 2
`slow_then_fast`, 5 `fast_only`. `demo_path` follows the spec and adds one
repeated `create_case` (M7), counted as 1 unapplied model call.

## Byte identity (spec §3.2, I5)

- `make test`: exit 0. Every `*-check` passed; the drift lines
  `drifted_since_r1`, `drifted_since_03b`, `drifted_since_bundle` are the
  pre-existing informational states.
- `git diff --stat origin/main -- data/ contracts/ ml/`: empty for tracked
  files; `git status` under those paths lists only the new
  `data/evaluation/fast-slow-split-scripted.json`.

## Verification

| Check | Result |
|---|---|
| focused: the three new test files | 47 + 19 + 13 passed |
| runtime pytest (in `make test`) | 1373 passed, 59 skipped |
| ml pytest (in `make test`) | 397 passed, 1 skipped |
| `make lint` | passed |
| `make typecheck` | passed (70 and 59 source files) |
| `make test` | passed (exit 0), including `fast-slow-split-check` |
| `make phase04d-profile-check` | passed (exit 0) |
| `make preflight` | passed (exit 0); gated-skip counts match the pinned 59 per file |
| `postgres-check`, `phase05a-check`, `phase06b1-check` | see "After merging `main` @ `df733f7`" |

No DB-gated test was added: the gated-skip pin is unchanged.

### After merging `main` @ `df733f7` (#92: channel re-drive, `app.py`, `activities.py`)

The merge was clean (no conflicts). On the merge commit:

| Check | Result |
|---|---|
| `make test` | passed (exit 0); runtime pytest 1390 passed, 61 skipped; ml 397 passed, 1 skipped; `Fast/Slow split report is current.` |
| byte identity | `git diff --stat origin/main -- data/ contracts/ ml/` lists only `data/evaluation/fast-slow-split-scripted.json` (new) |
| `make preflight` | passed (exit 0); gated-skip counts match the pinned 61 per file (#92's pin) |
| `make postgres-check` | 35 passed |
| `make phase05a-check` | 53 passed |
| `make phase06b1-check` | 54 passed (includes #92's channel re-drive with the assistant-line delivery) |

The gates ran serially from this worktree against the Compose `postgres-test`
(`127.0.0.1:55432/proxyloop_test`) and `temporal` (`127.0.0.1:7233`)
services, with the variables on the make command line only.

## Known limits

- The gate is lexical (spec §2.2, R1/R2). "I can't accept that" passes v1:
  the commitment rule needs the verb right after the first-person subject and
  optional auxiliary. "12 December" passes when 12 is an allowed integer
  (only month-then-digit is a date in v1).
- The turn join has no command id (R6): attempts at one cursor are resolved
  by log order. A refresh turn whose failed attempt left a Slow trace is
  resolved correctly only because each attempt re-runs its own refresh.
- The report carries no latency and no model text; it describes routing
  structure of the scripted adapters only.

## After the review fixes (Request Changes; `harness/code_review/feat-pr8a-fast-dialogue.md`)

The fixes are B1 (`fast_gate_non_ascii_text`), I1 (completion and commitment
phrasings), M1 (percent, signed amounts), M2 (schemes, scheme-less domains), M3
(`gate_fallback_rate` over applied Fast turns, unapplied attempts reported
apart), M4 (log order is call order only within one process, R6), M5 (status
table), and M6 (channel gate-reject test), plus the optional assistant-time
assertion. The gate stays `fast-gate-v1`, and spec §2.2, §5.1, and §5.2 carry a
dated amendment. `runtime.py` is unchanged, so the DB gates were not rerun.

Refusals that pass: "I can't accept that.", "I won't accept that.", "I will not
accept that.", "I cannot sign that.", and "We don't agree to that." The passive
"That can't be accepted." is refused (`fast_gate_completion`); this is a safe
false positive.

| Check | Result |
|---|---|
| `make lint` | passed |
| `make typecheck` | passed (70 and 59 source files) |
| `make test` | passed (exit 0); runtime pytest 1443 passed, 61 skipped; ml 397 passed, 1 skipped; `Fast/Slow split report is current.` |
| byte identity | `git diff --stat origin/main -- data/ contracts/ ml/` lists only `data/evaluation/fast-slow-split-scripted.json` (new, regenerated for M3) |
| `make preflight` | passed (exit 0); gated-skip counts match the pinned 61 per file |
| DB gates | not rerun (no `runtime.py` change since the green run at 35 / 53 / 54) |

The regenerated report still meets AC 5. `demo_path` is {`slow_only` 1,
`fast_only` 1} with 1 unapplied Slow call (the repeated create). `dialogue_path`
has 2 `slow_then_fast` turns. `gate_fallback_rate` is 0 in both.

## Final additions after the re-review (Approve) and merge of `main` @ `a3a429f` (#93)

The root's final decisions are recorded in the review artifact and in a dated
spec amendment:
- bare completion participles;
- non-ASCII symbols (S*);
- dash-like, parenthesised, and "minus" amounts;
- "account owner";
- `FAST_GATE_UNICODE_DATA_VERSION = "15.0.0"`, with a test, and
  `unicode_data_version` in the report.

The report was regenerated because of that new field. The gate stays
`fast-gate-v1`, and G7 still passes.

The merge conflicted only in the status table; both rows were kept. The
gated-skip pin is main's 63; this branch adds no gated test.

| Check | Result |
|---|---|
| `make lint` | passed |
| `make typecheck` | passed (70 and 59 source files) |
| `make test` | passed (exit 0); runtime pytest 1467 passed, 63 skipped; ml 397 passed, 1 skipped; `Fast/Slow split report is current.` |
| byte identity | `git diff --stat origin/main -- data/ contracts/ ml/` lists only `data/evaluation/fast-slow-split-scripted.json` (new) |
| `make preflight` | passed (exit 0); gated-skip counts match the pinned 63 per file |
| DB gates | 35 / 53 / 54 on `23e1b5d`. Since then `runtime.py` is unchanged (`git diff --stat 23e1b5d HEAD -- runtime/` lists only `agent_core` and `turn_split.py`); the branch-side changes are the pure gate, the split, the report, and tests, so the gates were not rerun |
