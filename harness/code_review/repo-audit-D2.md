# Repo audit — Lane D2: evaluation harness and evidence chain

Reviewer: `reviewer` (Opus, high), read-only; 88 tool uses, ~382K tokens.
Recorded by the root orchestrator from the lane's report; root verification
at the end. Scratch probes under the session scratchpad `laneD2/`
(`q1_leak.py`, inline probes for Q4–Q7, `tamper/`). No hosted call;
`PROXYLOOP_FRONTIER_API_KEY` absent; no adapter constructed with a key.

Read completely: `runner.py`, `runner_v2.py`, `hosted_rerun.py`, `replay.py`,
`replay_v2.py`, `artifacts.py`, `artifacts_v2.py`, `fresh_fixtures.py`,
`models.py`, `validity_smoke.py`; the six 03A1 scripts;
`run_phase_01b_benchmark.py:100-275`; nine `ml/tests` files;
`tests/integration/test_phase_03a1_harness.py`; the five 03A1 contracts;
`docs/ml-evidence.md`; `PLANS.md:15-38, 86-110`.

## 1. Verdict per module

| Module | Verdict | Why |
|---|---|---|
| `runner.py` (r1) | rewrite or delete as superseded | Slow prompt carried the oracle's APPROVED `accept_offer` on 10/32 episodes (D2-4); Fast "done" text counted as `false_completion`; hosted labels not replayable (D2-5). |
| `runner_v2.py` | refactor | Stage separation real and replayable, but `end_to_end_valid` is scripted-label equality for 22/32 scenarios (D2-3); `router_outcome_mismatch` double-counts every Slow failure (D2-7); `policy_violation_count` / `leakage_violation_count` are constants (D2-8). |
| `hosted_rerun.py` | keep | Strongest link: r2/r3 fingerprint + timestamp binding, execution-contract file hashes, dispatch/cost reconciliation, semantic replay on `--check` (tamper caught). |
| `replay_v2.py` | keep | r3 re-derivation byte-identical to the committed r3. |
| `replay.py`, `artifacts.py` (r1) | refactor | Replays prompts and "does it recompile", never `valid_outcome`/`completed` (D2-5). |
| `artifacts_v2.py` | keep (minor) | Skips r2 semantic replay once r3 exists (D2-6); leakage scan key-name only (D2-8). |
| `fresh_fixtures.py` | keep | No label reaches the snapshot; `provider_config_ref` reveals the provider-holdout axis (D2-9). |
| `models.py` | keep | `policy_violation_count` is a dead field. |
| `validity_smoke.py` | rewrite | The r5 system prompt contains the oracle's decision procedure (D2-1). |
| `scripts/run_phase_03a1_validity_smoke.py` | refactor | `--check` re-derives nothing label-bearing from raw outputs (D2-2). |
| other 03A1 scripts | keep / refactor (harness per D1; its `build_phase03a1_model_fixtures` is the r1 approval-leak source) | — |

## 2. Findings

**D2-1 — reported Important, root: Blocking (evidence claim) — the r5 "5/6 after input parity" prompt contains the scripted oracle's decision procedure, not just its inputs**
- `validity_smoke.py:140-146`: the system prompt ends with "Interpret the public Provider state with this precedence: needs_clarification -> request_clarification; a requested disclosure outside the allowed set -> refuse_disclosure; approval_current=false -> request_replan; transfer_available=true -> escalate; confirmation_evidence_available=false -> request_replan; otherwise accept a compliant visible offer or decline a noncompliant offer." — `observation.py:352-386` transcribed. `validity_smoke.py:84-109` appends the five oracle booleans as JSON to the Provider message.
- Claims: `docs/ml-evidence.md:31, 36-38` ("after giving model and oracle the same public inputs … 5/6"); `PLANS.md:101-103`; `phase-03a1-evaluation-validity-smoke.md` AC#2 ("diagnostic prompt contains no oracle action … or evaluator label") in substance; `phase-03a1-baselines.md` isolation rule (held-out/safety families may never shape a prompt; 5 of the 6 r5 episodes are held-out/safety and the rule table encodes the safety-family rules).
- Repro (`q1_leak.py`): the five r5 successes are exactly the five one-boolean rules in the prompt (clarification, disclosure, absent-evidence, multi-hazard, add-on-removal); the one case needing arithmetic (fee trap) failed. `EXPECTED_DIAGNOSTIC_CHANGES` names this `explicit_dynamic_field_semantics` (`run_phase_03a1_validity_smoke.py:60-64`). `test_validity_smoke.py:207` tests only that the string `"oracle"` is absent.
- Direction: document r5 as "rule-following under oracle-flag parity", not as evidence about the harness or the model; future parity experiments add inputs only; a leakage test must scan for the oracle's rule vocabulary.

**D2-2 — Important — r5 `--check` does not re-derive any label from stored raw outputs; an edited 5/6 → 6/6 passes `validity-smoke-check`**
- `run_phase_03a1_validity_smoke.py:301-500`: counts and metrics recomputed from the report's own row booleans; only `raw_capability_exact_count` derives from `slow_raw_output`; `_expected_prompt_provenance` (`:216-278`) replays but discards the outcome; `replay_v2.replay_condition_v2` is not called.
- Repro (probe (c), scratch copy): flip the fee-trap row to valid, recompute counts and `report_fingerprint` with the script's own helpers → `_check_report(...)` returns `(True, ())` with `end_to_end_valid_count: 6`. `test_validity_smoke.py:53-111` bumps counts without editing rows.
- Direction: `_check_report` must replay through `replay_condition_v2` with a smoke replay path; regression = the probe.

**D2-3 — Important — hosted `end_to_end_valid` / `provider_outcome_valid` is "agrees with the scripted answer" for every non-accept scenario; 03A1-E decision 6 is not honoured by the evaluator**
- `runner_v2.py:317-324` sets `provider_outcome_valid = transition.verification.valid_outcome` → `multi_turn.py:282-320` → Phase 01B verifier label equality (D1-3); `:1159-1168` folds it into E2E. `reference_match` (`:549-571`) is reported "separately" but is implied by E2E for 22/32 scenarios.
- Claims: `phase-03a1-evaluation-erratum.md` decision 6 ("Exact reference action/offer match … cannot turn a safe executable alternative into a … failure"); `docs/ml-evidence.md:13-15, 30`.
- Repro (queued-completions probe): `fee-total-cost-trap ← request_replan`, `expired-approval ← decline`, `absent-evidence ← escalate`, `required-feature-loss ← request_clarification`, `refusal-transfer ← decline` all give `slow_canonical=True auth=True exec=True provider_valid=False e2e=False ('invalid_provider_outcome',)`. In the committed r4, of the 36 semantic-valid Slow outputs across the four hosted conditions, 0 accept, 0 false-complete, and 28 are safe non-completions scored `invalid_provider_outcome`. "3/32" is an exact-match-with-script number. `test_phase03a1_erratum_metrics.py:128-132` asserts `reference_match=False, end_to_end_valid=True` on a hand-built row the runner never produces.
- Direction: E2E = stage validity ∧ ¬false_completion ∧ (accept ⇒ Provider-verified); expose `reference_match` as the scripted-agreement number; docs state which one every figure is. Depends on D1-3.

**D2-4 — Important — the r1 hosted Slow prompts contained the oracle's label as an APPROVED `accept_offer` approval on exactly the 10 accept scenarios; 03A1-B AC#4/#8 are contradicted while `PLANS.md:23` records "full gate passed"**
- `run_phase_03a1_harness.py:704-717` derives `attempt` from the oracle and `_episode_execution_context` (`:530-552, 596-597`) puts an `ApprovalRequest(action_type=ACCEPT_OFFER, decision=APPROVED)` into `snapshot.approval_requests` iff the oracle accepts; `runner.py:609-618` → `coordinator.project_slow_view` (`coordinator.py:282`) copies it into `SlowReasonerView`; `legacy_slow_output.py:168-188` dumps the whole request into the user message.
- Repro (`q1_leak.py`): 10/32 r1 Slow requests carry `"decision": "approved", "action_type": "accept_offer"`; the committed `phase-03a1-baselines-report.json` `frontier_reference` prompt fingerprints equal `build_legacy_slow_prompt` of the request **with** the approval for 10/10 accept episodes and 0/10 without — the dispatched prompts provably contained the label. Secondary: `runner.py:280, 808` count a Fast `completion_claim != not_done` as `false_completion` (r1 `false_completion_count=28` is Fast text, not Provider-verified).
- The 03A1-E contract (decision 4) acknowledges the defect; `PLANS.md:23` and the 03A1-B status line still say the gate passed.
- Direction: amend `PLANS.md:23` / `phase-03a1-baselines.md` status to "superseded; AC#4/#8 failed, corrected in 03A1-E"; keep r1 as calibration only.

**D2-5 — Important — `baselines-check` (r1) does not re-derive hosted labels; a tampered `valid_outcome`/`completed` passes**
- `artifacts.py:85, 33-38` self-computed fingerprint; `replay.py:191-439` never checks `valid_outcome`, `completed`, `false_completion`, `failure_codes` for hosted rows.
- Repro (probe (a)): flip one `frontier_reference` episode to `valid_outcome=True, completed=True`, recompute counts and fingerprint → `check_baseline_artifacts(scratch)` returns `(True, ())`.
- Direction: retire r1 from `make test` with an explicit "historical, not replayable" marker, or add `replay_v2`-style semantic replay.

**D2-6 — Minor — r2 report labels are not replayed once r3 exists** (`artifacts_v2.py:550-557`); repo-level chain still catches it via `hosted-rerun-check`.

**D2-7 — Minor — `router_outcome_mismatch` is added to every episode whose Slow output failed validation** (`runner_v2.py:1142-1147`); in r4 it equals `slow_semantic_invalid` in every condition.

**D2-8 — Minor — reported metrics that are constants or key-name scans**: `policy_violation_count` never set (→ 0 in every r2–r5 row); `leakage_violation_count` hard-coded `0` per row (`runner_v2.py:636, 746, 836, 1224`); the only measurement is `artifacts_v2.py:115-186` key-name/substring (`"reference_"` matches `"preference_"`; family words not in the token set).

**D2-9 — Minor — `provider_config_ref` in every prompt is the provider-holdout split axis** (`fresh_fixtures.py:645`; `run_phase_03a1_harness.py:573, 602`); no family/hazard/`expected_*`/split label reaches any r2–r5 prompt.

**D2-10 — Note — the fee-trap oracle input is invisible to the model in every run**: the oracle reads `case.bill_snapshot.monthly_total` (`observation.py:265`); neither view carries `bill_snapshot`. Under the shared policy the decline follows from the visible target, so the r5 "predicate the model could not see" holds only for the legacy oracle.

**D2-11 — Note — "actual cost" is tariff × usage**, tariffs duplicated in three places (`openai_frontier.py:50-51, 886-889`; `replay.py:258`; `runner.py:1141, 1151`); ledger consistent (220 hosted calls, 0 mismatches). `docs/ml-evidence.md:31` "USD 0.117 hosted spend" should read "usage-accounted estimate".

**D2-12 — Note** — `runner.py:59` `HOST_CLASS` literal; `report_fingerprint_v2` depends on `model_fields_set` (false-positive drift on re-serialisation); r1 `schema_valid` conflates stages.

**D2-13 — Note — untested acceptance criteria**: 03A1-V AC#1 (no test proves the prompt omits public Provider state); 03A1-E AC#5 rejection branches absent from `ml/tests`.

## 3. Field reachability (Q1) and artifact → oracle (Q2)

| Field | r1 | r2–r4 | r5 | Reaches model? |
|---|---|---|---|---|
| family id / hazard / scenario id | hashed only | hashed | same | no (0 hits over 38 prompts) |
| `expected_*`, split, `reference_*` | fixture wrapper only | wrapper only | same | no |
| oracle action as APPROVED approval | **yes** (`harness.py:530-552, 596-597`) | `approval_requests=()` | same | **r1 only, 10/32 (D2-4)** |
| oracle decision rules | no | no | **yes, system prompt** | **r5 (D2-1)** |
| oracle input flags | no | no | yes, event content JSON (declared) | r5 |
| `provider_config_ref` | `configuration_id` | `configuration_id@2.0` | same | yes = provider split (D2-9) |
| event `content` | Provider message | "Fresh Provider update: …" | + state JSON | natural-language hazard by design |
| offer ids / evidence ids | UUIDs | UUIDs | same | content-free |
| `current_monthly_total` (oracle input) | absent | absent | absent | no (D2-10) |

| Artifact | Oracle path |
|---|---|
| `phase-01b-ceiling-report.json` | legacy (`run_phase_01b_benchmark.py:131`) |
| `phase-03a1-{manifest,episodes,ceiling-report}.json`, `phase-03a1-baselines-report.json` r1 references | legacy (`run_phase_03a1_harness.py:704, 1135`) |
| r2/r3/r4 ceilings and `reference_match`; r5 `reference_capabilities` | legacy (`fresh_fixtures.py:755`, `artifacts_v2.py:159`) |
| 03B/03C experiments | shared policy injected |

No evaluation artifact in scope was labelled by the shared policy; root's 0/32 disagreement result makes the labels stand today.

## 4. Metric definitions (from code)

| Metric | runner_v2 / r2–r5 | r1 |
|---|---|---|
| `slow_json/schema/semantic_valid` | adapter stage did not raise | `schema_valid` = Slow canonical ∧ Fast schema |
| `canonical` | `validate_slow_result(...).accepted` (pins/basis echo) | same |
| `authorization_valid` / `execution_valid` | executor did not REJECT; commit happened | folded into `valid_outcome` |
| `provider_outcome_valid` | `verification.valid_outcome` = label equality for non-accept, state check for accept | same |
| `end_to_end_valid` | canonical ∧ fast_canonical ∧ auth ∧ exec ∧ provider_valid ∧ ¬false_completion ∧ ¬unsupported_completion ∧ no failure code | exec ∧ Slow ∧ Fast schema ∧ no failures |
| `reference_match` | capability == reference ∧ offer maps to reference offer; diagnostic but implied by E2E for non-accept | gating failure code |
| `false_completion` | Provider rejected an executed `accept_offer` | that **or** Fast `completion_claim != not_done` |
| `policy_violation_count` | never set → 0 | number of distinct failure codes |

"3/32 E2E" is an agrees-with-script number; the model-quality signal that survives is `false_completion_count = 0` across hosted runs (except the r5 fee trap) and the stage counts.

## 5. Acceptance criteria (summary)

| Contract | Verified | Attested only | Contradicted / weaker |
|---|---|---|---|
| 03A1-H | #10 gate arithmetic, #11 Make targets, #12 | #1, #14, #15 | #3 leakage probes key-name only; #9 test asserts `safety ⊆ safety`; #10 "100 % valid" = label equality for 22/32 |
| 03A1-B | #3, #6, #7, #9, #10 fingerprints | #1, #2, #12 | **#4, #8 (D2-4)**; #5 Fast text as `false_completion`; #10/#11 labels not replayed (D2-5) |
| 03A1-E | #3, #4, #5 happy path, #6, #7, #8, #10, #11; r3 byte-reproducible | #1, #2, #9, #12, #13 | decision 6 not honoured (D2-3); #5 rejection untested |
| 03A1-R | #3, #4, #5 (tamper caught by replay), #7, #8 | #1, #2, #6, #9, #10 | — |
| 03A1-V | #3, #4, #6 | #1 (no test) | **#2 in substance (D2-1)**; #5 labels self-attested (D2-2) |

## 6. Test quality
Load-bearing: `test_runner_v2_frontier.py` (stage separation, replay tamper, statuses), `test_hosted_rerun.py` (all), `test_phase03a1_erratum_artifacts.py` (determinism, drift, source tamper), `test_baseline_artifacts.py` (drift gate, prompt/cost tamper), `test_slow_output_erratum.py`. Gaps/tautologies: no safe-alternative runner case; `test_reference_match_is_diagnostic…` hand-builds a row the runner never emits; `test_fresh_phase03a1_fixtures.py:95-97` `safety ⊆ safety`; `test_validity_smoke.py` tampers bump counts without rows and leakage = `"oracle" not in prompt`; no hosted-label tamper for r1; no value-level leakage test on rendered prompts.

## 7. Checks run / not run
Run: 9 `ml/tests` files → 82 passed; `make harness-check baselines-check errata-check hosted-rerun-check validity-smoke-check` → all passed; `q1_leak.py`; r3 re-derivation byte-compare (True); tamper probes (a) r1 pass, (b) r4 caught, (c) r5 pass, r2-with-r3 pass; cost-ledger audit; split cross-tab; fee-trap view probe; safe-alternative runner probe. Not run: `make preflight/lint/typecheck`, `benchmark-check` (root baseline); hosted calls; Qwen checkpoint load.

## 8. Open questions
1. D2-1 severity (answered by root below).
2. Keep r1 in `make test` as a non-replayable historical gate, or mark superseded?
3. Which number should the docs carry for r4 — `reference_match` (3/32) or a state-based E2E once D1-3 is fixed?
4. `provider_config_ref`: opaque it, or drop the "held-out" claim (D1-5)?

Lane recommendation: **Request Changes**.

## Root verification (2026-09-21)

Root read `validity_smoke.py:136-148` and `observation.py:352-362`
(the prompt is the oracle's rule order, verbatim), and re-ran `q1_leak.py`
(r1: 10/32 Slow views carry an APPROVED `accept_offer` approval; r5 system
prompt and event JSON as quoted).

| Id | Verdict | Root note |
|---|---|---|
| D2-1 | **confirmed; raised to Blocking (evidence claim)** | The 5/6 number is genuine, but the published cause ("same public inputs") is not what the prompt does: it hands the model the label-generating procedure. `README`/`ml-evidence.md`/`PLANS.md` present r5 as proof that the harness is valid and the model can do the task under parity; neither follows. Under the audit's severity table this is a documented result whose evidence does not support it. |
| D2-2 | confirmed, Important | Tamper probe accepted by the lane's method; consistent with G-4. |
| D2-3 | confirmed, Important | Same root cause as D1-3; every hosted E2E figure is a scripted-agreement number. |
| D2-4 | confirmed, Important | Leak is real and provable from committed fingerprints; already acknowledged by 03A1-E, but `PLANS.md:23` still records the gate as passed. |
| D2-5 … D2-13 | accepted as reported | Probes under `laneD2/`. |
