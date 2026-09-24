# Review: fix/r17-r5-channel-redrive (PR-3, R-17 + R-5)

Reviewer: independent `reviewer` agent, on the branch at `64ace73` + the
`origin/main` merge `3343609`. Findings and root decisions as relayed by the
root orchestrator; this artifact records them and their disposition.

**Verdict: Request Changes, no Blocking findings.** All findings accepted by
the root and applied on the branch (disposition below).

## Findings

| Id | Severity | Finding | Disposition |
|---|---|---|---|
| I-1 | Important | The R-17 main path sends twice when `record_delivery_observation` fails after a successful send: attempt 1 on a `pending` outbox sent without a lookup, and so did the re-drive (a new activity at attempt 1). Measured `{'send': 2, 'lookup': 4}` on the time-skipping test. | Root changed the frozen decision (dated note in the spec's Root decisions): the delivery activity always looks up before sending, every attempt and outbox state, and sends only when the lookup finds nothing. `docs/architecture.md` and §4a now state the residual as only a send not yet visible to lookup (TIMEOUT overlap). |
| I-2 | Important | The time-skipping test's set-of-ids assertion was vacuous (a stable id makes two sends indistinguishable). | `_CountingMailboxAdapter` counts `send` and `lookup` separately; the test asserts exactly 1 send. Red before I-1 (`assert 2 == 1`), green after. |
| I-3 | Important | The time-skipping test ran in `make test` and would start (and in CI download) the Temporal test server. | Gated with `skipif(not os.environ.get("PROXYLOOP_TEST_TEMPORAL_ADDRESS"))`; runs in `phase06b1-check`. After merging `main` @ `f4a2487` (#90), the per-file gated-skip pin is updated from the preflight failure output: `test_phase_06b1_channel_runtime.py` 1 → 2, `test_phase_06b1_temporal.py` 3 → 4 (R17-T3), total 53 → 55; `docs/development.md` updated. |
| M-1 | Minor | `docs/architecture.md` said R-5 retries only a lost route-read revision; it retries any `channel_conflict` while the Case moved and the event has no receipt. | Wording fixed. |
| M-2 | Minor | No test that an unavailable (non-conflict) first dispatch is not retried when the Case moved. | Added `test_local_mailbox_unavailable_dispatch_is_not_retried_after_case_moved` (1 dispatch, 503). |
| M-3 | Minor | A known race still returns 409 for an applied event (same as `main`); redelivery then gets 200. | Recorded in the log's risks. |
| M-4 | Minor | A duplicate now gets 503 on an outbox-read storage fault, and waits on an in-flight Update instead of returning 200 at once. | Recorded in the log's risks. |
| M-5 | Minor | The merge commit was unpushed and `main` had moved. | Pushed, then merged `origin/main` @ `f4a2487` (status-file conflict resolved per the status file's rule). |

Evidence and counts: `harness/log/fix-r17-r5-channel-redrive.md`.
