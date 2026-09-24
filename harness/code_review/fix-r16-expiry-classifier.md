# Review: fix/r16-expiry-classifier (PR-2, R-16)

**Target**: `fix/r16-expiry-classifier` into `main`

**Reviewer**: independent `reviewer` agent; written by the implementer at the root orchestrator's direction.

**Verdict**: Approve. Three Minor findings, all accepted and applied before
the PR.

## Minor 1: in-flight runs stay on the old path longer than stated

The spec's risk said a pre-deploy run is retried "until the run rolls". That
understates it: the SDK caches `patched("expiry-failure-outermost-cause") ==
False` for the rest of a run that replays a pre-deploy expiry failure, so a
chained non-retryable failure in it retries indefinitely (backoff capped at 5
minutes) until an Update adopts a newer transition (`_adopt_transition` →
`_reset_expiry_backoff`) or the run rolls, and the history grows by about one
failed activity per 5 minutes meanwhile. The growth predates this fix (no
history-size Continue-As-New).

**Resolution**: the risk is restated with the full mechanism in
`harness/context/fix-r16-expiry-classifier-preflight.md` and under "Known
limits" in `harness/log/fix-r16-expiry-classifier.md`.

## Minor 2: no DB-free test of the classifier

The classifier was covered only by DB/Temporal-gated time-skipping tests and
the replay test.

**Resolution**: `test_outermost_failure_category_classifies_the_raised_failure`
in `tests/integration/test_phase_05a_temporal_workflow.py`, parametrized over
eight shapes, runs in `make test` without the DB. Expected values are what the
classifier returns today (checked against the reviewer's shape table):

| Shape | Result |
|---|---|
| chained `case_conflict` (flagged, listed) | `("case_conflict", True)`, abandon |
| chained `storage_unavailable`, `MAXIMUM_ATTEMPTS_REACHED` | `("storage_unavailable", False)`, retry |
| `channel_conflict` flagged, not listed | `("channel_conflict", True)`, abandon |
| `case_not_found` listed, not flagged | `("case_not_found", True)`, abandon |
| timeout wrapping the last `ApplicationError` | `("activity_timeout", False)`, retry |
| cancelled | `("activity_failed", False)`, retry |
| untyped `ApplicationError`, `non_retryable=True` | `("activity_failed", True)`, abandon |
| Workflow-raised `state_invalid` from `ValueError` | `("state_invalid", True)`, abandon |

## Minor 3: no recorder script for the replay fixture

`temporal_history.case-workflow-expiry-chained-conflict.pre-r16.json` was
recorded by hand; no script regenerates it.

**Resolution**: recorded as a known limit in the log, consistent with the R-1
fixture. No script added.

## Final gate

After the Minors, with no `PROXYLOOP_TEST_*` set: `make lint`,
`make typecheck`, `make format-check` passed; `make test` passed (runtime
1260 passed, 53 skipped; ml 397 passed, 1 skipped). The real-dependency gates and `make preflight` ran green
before the Minors (log); the Minors change a test and docs only.
