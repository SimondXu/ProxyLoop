# PR-14 Judge seam review

**Target**: `feat/pr14-judge-seam` at head `2400ff2` (code at `2db340b`), on
`main` @ `37f6bab`. Spec: `harness/context/pr14-judge-seam-preflight.md`
(frozen, root answers 1–9).

**Reviewer**: an independent read-only `reviewer` subagent. Its probe is
`scratchpad/rev-pr14/repro_split.py`.

**Recommendation**: Request Changes, with no Blocking finding; every
boundary held (no contract change, no committed artifact other than the
scripted split report moved, the Judge unreachable from `ml/`, metrics, the
executor and approvals). The root accepted every finding below and passed its
decisions to the implementer. The implementer wrote this file from the root's
messages, not from the reviewer's own text.

## Findings and disposition

| # | Finding | Disposition |
|---|---|---|
| I1 (Important) | `turn_split._attempts` read any Slow call directly after a `judge_revise` trace as that group's retry. With a Slow adapter that has no feedback protocol (revise, no retry), a repeated create logs `S J(revise) S J`: the second `S` was taken as the retry and its `J` raised "orphan judge trace". Reproduced by `repro_split.py`. | Applied. A Slow call after a revise is the retry only if no Judge trace follows it: a retry is never judged, so a judged Slow call there starts a new attempt (one-trace lookahead in `_attempts`). The remaining ambiguity is recorded as a known limit in the `turn_split` docstring and `docs/architecture.md`: a new attempt's Slow call that the coordinator rejects, logged right after an unretried revise, is not judged either and is counted as a rejected retry. Tests: `test_s4_a_judged_slow_after_a_revise_is_a_new_attempt` (`[S J(revise) S J]`), `test_s4_a_rejected_slow_after_a_revise_is_read_as_the_retry` (`[S J(revise) S(REJECTED)]`, pinning the limit), and the reviewer's repro as the Runtime-level `test_a_repeated_create_after_an_unretried_revise_splits_cleanly`. Both I1 tests failed on `2db340b` (`ValueError: orphan judge trace`) and pass on the fix; `repro_split.py` on the fix splits into one turn with `slow_calls 1, judge_calls 1, slow_retry None`. |
| M1 | A Judge returning something that is not a `JudgeVerdict` crashed the coordinator (`AttributeError`) instead of being recorded and ignored like a non-binding verdict. | Applied. `_judge` returns `object`; a non-verdict return gives a `REJECTED` Judge trace and audit with `judge_verdict_invalid`, and the first admitted result is used. Test: `test_a_return_that_is_not_a_verdict_is_rejected_and_the_first_result_used`, red on `2db340b` (`AttributeError: 'dict' object has no attribute 'request_id'`). |
| M2 | The G1 source guard did not pin how the Runtime touches the outcome's `audits` and `traces`, where the Judge's codes live; `docs/architecture.md` said the outcome "carries no Judge output". | Applied. G1 asserts `source.count(".audits") == 0`, `source.count(".traces") == 2`, and that the two uses are `_advance`'s log append. The architecture text now says the outcome has no Judge field, the Judge's codes appear only in its `audits` and `traces`, and the Runtime never reads `audits` and only appends `traces`. |
| M3 | The boundary test did not catch indirect access: a `judge=` passed to a coordinator, or an evaluation source constructing a Runtime (whose coordinator has the Judge by default). | Applied. `test_b1_no_evaluation_source_reaches_the_judge_through_a_runtime` flags any `CaseCoordinator(..., judge=...)` and any `ThinAgentRuntime(...)` call under `ml/` and `scripts/`, except the named product-Runtime drivers (`run_fast_slow_split_report.py`, `run_phase_04d_control_plane_profile.py`, `run_phase_07a_portfolio_demo.py`); a probe test proves the scan detects both forms. The module docstring states that dynamic imports (`importlib`, `__import__`) and run-time names are out of scope. PR-9b's new scripts construct neither (checked on `origin/feat/pr9b-local-fast-gateway`). |
| M4 | The Judge paragraph was inserted inside the standing-proposal paragraph, so the OpenAI 5-minute proposal-expiry limit (and the closing sentences) ended up under the Judge. | Applied. That text is back at the end of the standing-proposal paragraph, which is now byte-identical to `main`; the Judge paragraph follows it. |
| M5 | No split test covered `FAILED` or `REJECTED` Judge traces. | Applied. `test_s4_a_failed_or_rejected_judge_call_is_counted_apart[FAILED\|REJECTED]`: each is counted in `judge_calls_by_result`, never in the Fast/Slow counts, and, not being a revise, a later Slow call starts a new attempt. |
| M6 | Follow-up after PR-9b merges. | Done after PR-9b (#100) merged (`51cf629`). The local mode refuses a Judge trace that is not the scripted Judge's. The committed local reports are not regenerated: the integrity check still accepts them because it compares only the Fast/Slow structure, which v2 leaves unchanged; they stay at `fast-slow-split-local-v1` as pre-Judge observed artifacts, pinned by a test. A local report written now is `fast-slow-split-local-v2` (it carries Judge calls); the check accepts v1 and v2. `docs/architecture.md` and `ml/serving/README.md` say the local reports predate the Judge. |

## Verification after the fixes

See `harness/log/feat-pr14-judge-seam.md`, "Review fixes" and "Checks on the
final merged tree": on `760541a` (merged with PR-9b and PR-12) `make lint`,
`typecheck`, `test`, `preflight` passed, and the DB lane passed
(`postgres-check` 38, `phase05a-check` 73, `phase06b1-check` 56).
