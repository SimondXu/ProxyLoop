# PR-11 Fast under Temporal review

**Target**: `feat/pr11-fast-under-temporal` @ `f017bc5` against `main` @ `a8fdf5b`
(spec `harness/context/pr11-fast-under-temporal-preflight.md`).

**Reviewer**: independent read-only `reviewer` subagent, with scratch probes
(`rev-pr11/interleave.py`, `retry_race*.py`, `run_gated.py`) run against the
branch.

**Recommendation**: Approve. There is no Blocking finding. The root accepted
one Important finding and five Minors and passed them to the implementer, who
wrote this file from the root's message. D5 option A (channel commands keep
scripted Fast; the outbound body stays constant) stands.

## Findings and disposition

| # | Finding | Disposition |
|---|---|---|
| I-1 | The two-Runtime layout (D5-A) gives the Case Runtime and the channel Runtime separate in-process Case lanes. Nothing tested what happens when a consumer turn and a channel ingest run at the same revision. The reviewer's `interleave.py` showed repository compare-and-swap admits one and the other fails `case_conflict`. | Applied. New non-gated `test_two_runtimes_admit_one_commit_at_one_revision`: a blocking scripted-subclass Fast on `adapter.runtime` holds a consumer turn while a channel ingest commits on `adapter.channel_runtime` at the same `expected_revision`. After release it asserts `case_conflict` (non-retryable), exactly one `provider_message`, no consumer or assistant event, one outbox row, and the ingest's revision as final. |
| M-1 | Operation records and `/health` show the Case-command backend, not the channel path. | Applied in `docs/architecture.md` (and spec D2). |
| M-2 | The worker leaves no record of its own selection. | Applied. `activity_adapter_from_environment` logs `worker Fast backend: <label>` once, label only; the composition test asserts the single line. `docs/architecture.md` and spec D2 state the disagreement direction: worker `distilled` + API `scripted` under-claims (`/health` says scripted, traces name the local model), and the reverse over-claims. |
| M-3 | The spec's D4 overstated same-worker retry protection. | Applied in the spec (D4) and `docs/architecture.md`. The per-Case lock plus the stored receipt protect a racing retry only when `expected_revision` is sent. Without it, protection is incidental: the scripted first consumer turn opens an approval, so the retry fails "awaiting approval" and resolves to the receipt. Recorded gap: `_append_event_serialized` does not re-check the receipt after taking the lock. PR-13 fixes this in `runtime.py`, which is not edited here. |
| M-4 | The API bootstraps PostgreSQL before its gateway probe (the worker probes first). | Documented in `docs/architecture.md` and spec D2. Not reordered: in `config.py` the repository is built before the mode branches, so moving the probe is not a trivial one-line change. |
| M-5 | `activities.runtime_from_environment` is a footgun with a local backend; the test module imported the private `_ChannelRepository` from another test module; the launcher docstring said "every child process". | Applied. A docstring warning: wrapping that Runtime alone sends channel commands to the local model. The test module now has its own minimal channel repository. The launcher docstring, spec D6/T7/AC6, the log, and the test name now say the flag reaches the worker and the API; the Web build and recovery check use the scripted default. |

## Verification after the follow-up

See `harness/log/feat-pr11-fast-under-temporal.md`, "After review".
