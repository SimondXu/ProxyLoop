# Repository audit — synthesis (2026-09-21)

Contract: `harness/build/repo-audit.md`. Inputs: `harness/log/repo-audit.md`
(baseline), the ten lane reports `harness/code_review/repo-audit-{A,B1,B2,C,D1,D2,D3,E,F,G}.md`
(only findings marked confirmed/accepted in each "Root verification" table
are used), `harness/context/pine-ai-reference.md`, `GOALS.md`,
`docs/architecture.md` §Research MVP / §Integrated Portfolio Demo. Base
`main` @ `aaae134`. Severities are root's; one disagreement is stated inline
and root's verdict is kept in every table. Statements about the future plan
are marked *proposed*; everything else is observed by a lane and re-verified
by root.

## 1. Verdict

Today this codebase is a strictly typed, deterministic Case state machine
with a four-field wizard in front of it. Contracts, approval binding, CAS
persistence, the accept-path verifier, and the fail-closed model adapters are
real and tested. The things the docs sell on top of that are not: no model
output ever changes product state (A-4, B1-3, E §5), "multi-turn" is one
round of a scripted follow-up (D1-9), "at-most-once" recovery cannot be
finished by the retry the Web and Temporal actually send (B2-1/C-1), the
verifier and evaluator score agreement with a script for 22/32 scenarios
(D1-3, D2-3), "zero leakage" and "5/6 after input parity" are measurements
that cannot detect what they claim to rule out (D1-1, D2-1). Every defect
that mattered was found by reuse, never by the same-family phase-gate review
(`repo-audit.md:14-19`). Decision: **keep the core, refactor the seams, rewrite
four units** (`environment.py` verifier, r1 `runner.py`, `validity_smoke.py`,
the leakage/label measurement) and the docs. Not a whole rewrite: the deep
modules survived ten adversarial lanes; the defects live where modules meet.

## 2. What the evidence still supports

- Baseline: `make preflight` 72 s green; 291+220+47 tests; `postgres-check` 24, `phase05a-check` 24, `phase06b1-check` 31 passed (`harness/log/repo-audit.md:13-26`).
- 22 of 23 canonical contracts are produced and consumed in `runtime/`; `_base.py` enforces the wire-format ADR exactly; `ApprovalRequest` binding is enforced at executor, domain, and router (A §1, A Q4).
- `telecom_domain/domain.py` is the strongest runtime module; `offer_policy.py` arithmetic is correct at every boundary tried (B1 §1); `verify_completion` adversarial tests (expiry, forged hash, mismatched confirmation) are real (D1 §4, `test_phase_01a_simulator.py`).
- PostgreSQL revision CAS is correct across connections and OS processes (8/8 rounds, one winner); receipts live in the same transaction as state; tamper matrix real (C §1, c6).
- `hosted_rerun.py` + `replay_v2.py`: r3 re-derives byte-identical; a tampered r4 is caught (D2 §1, probe (b)).
- `openai_adapter` and `openai_frontier` fail closed; `max_retries=0` on every production client; budget checked before the call (B1 §1, D3 §1).
- `apps/web/lib/runtime-client.ts` validates a narrow envelope strictly (E §1); `local_mailbox.py` matches its own contract (C §1).
- Router precedence text matches ADR :95-104 (A-8, B1 §1).
- No committed hosted number is contaminated by the family-id leak: r2–r5 views use UUID offer ids; 03C Stage 0 prompts 0/6 hits (D1 root, D3-2 root); legacy and shared oracle agree on all 32 committed scenarios, so committed labels stand (B1-5 root, D1-2 root).
- `false_completion_count = 0` across every hosted run except the r5 fee trap is the one model-quality signal that survives the evaluator critique (D2 §4).
- CI `phase-gate` is a superset of local preflight; gates are honest about what they compare (G, G-4).
- Every number in `docs/ml-evidence.md` except F-1 traces to a committed artifact (F-6).

## 3. What is wrong — the structural findings

**(a) Approval→execution recovery is not retryable, and "at-most-once" rests on a discarded Python object.**
The claim write persists no receipt, the Provider commit happens before the final write, and `_check_expected_revision` runs before the pending-execution branch; so the documented exact retry (same key, same body with `expected_revision`) gets 409, and in Temporal it is classified `case_conflict`/non-retryable. On the real worker the cached executor returns `REUSED` and the reconstructed Provider has no confirmation → `state_invalid`; only a replaced worker plus a pin-less approval (a request the Web never sends) converges, by re-committing a Provider reconstructed as `awaiting_approval`. The executor itself keys idempotency on the intent's key, never on the approval, and never derives terms from the current offer — the invariants are held by a hard-coded key string and the simulator's state machine. Late recovery re-verifies at "now", yields `needs_replan`, which the Postgres envelope refuses to persist, so the Case is stuck forever. Direct mode drops `Idempotency-Key` entirely.
Subsumes: B2-1, C-1 (Blocking); B2-2, C-2, B2-4, B1-1, B1-2 (Important); B1-10, C-4, B2-7, B2-9 (Minor); B2-N7.
Falsifies: `README.md:87` "At-most-once execution"; `docs/architecture.md:54`, `:243`, `:272`; `docs/ui/state-matrix.md:13`; `docs/ui/user-flows.md:19-22`; `docs/planning/progress.md:93-94`; `phase-05a` fault rows.
Why it matters: this is the one safety/money invariant the product exists to demonstrate; with any Provider whose state is not an in-memory object this is at-least-once with amnesia.

**(b) The product runtime never uses model output; the model seams are evaluation-only.**
`runtime.py:443-448` rejects any Fast `response_text` except a constant; the approval is derived from `offers[0]` + compliance policy regardless of the Fast decision; `advance()` is never handed a Slow adapter on the event path, so after the 30-minute strategy expiry every Case is dead with error `model_result_rejected`. The runtime Slow compiler cannot compile the only advertised capability (`simulator.accept_offer` ≠ `simulator.accept_fictional_offer`) and its intent hash matches neither verifier, so a model-compiled intent is dead on arrival. `FactLedger` is never written; `ModelTrace` has no producer; `pending_slow_work` and the concurrent route are dead. The Web renders only string literals and never reads `fast`, strategy, or `visible_events` — in model mode it would look identical.
Subsumes: A-4 (Minor as defect, central for the demo claim), B1-3, B1-4, B2-3 (Important), A-2 (Important), A-8, A-1's "Router not the authority" half, E §5, A FactLedger row.
Falsifies: `docs/architecture.md:5`, `:124-170`, `:185`, `:211`, `:276`; spec:65, :107; `README.md:112` "model-backed" reading of 04B.
Why it matters: there is no agent in the demo; the Fast-model programme (03B, 03C) has no product consumer to be promoted into.

**(c) The verifier and the evaluator score agreement with a script, not Provider state.**
For every non-accept action `environment.py:160-171` returns `unexpected_action` on label inequality; only `ACCEPT_OFFER` is checked against turn state, and against module constants rather than the scenario's Case. `runner_v2` folds that label into `end_to_end_valid`, so 22/32 "valid outcomes" and every hosted E2E figure (r4 3/32) are exact-match-with-script numbers; in r4, 28 of 36 semantically valid Slow outputs were safe non-completions scored `invalid_provider_outcome`. The environment also completes a change the oracle forbids (two unsupported-change lists).
Subsumes: D1-3, D1-4, D1-7, D2-3 (Important); D2-7 (Minor); D3-N3.
Falsifies: `docs/ml-evidence.md:13-15`, `:30`; `phase-01b:34`; `phase-03a1-evaluation-erratum.md` decision 6.
Why it matters: the product's differentiator is deterministic verification by state; the benchmark that is supposed to prove it does not do it, and no training signal built on it can be trusted.

**(d) Leakage is measured by key names; family ids are in every public id and in Phase 02 rows.**
`offer_id`, `turn_id`, `evidence_ref` embed the full scenario id; 28/32 `SafeObservation.to_json()` outputs and the committed episodes manifest carry the family while `leaked_public_keys == []`. Phase 02 `learning_content` carries it in 104/128 rows; the 03B readiness packet in 12/16 records; both Fast prompt guards stop at `str`, so 20/26 03B example views render the family into the prompt. Hosted r2–r5 views are UUID-mapped, so no committed number is affected.
Subsumes: D1-1 (Important; root downgraded from Blocking), D3-1, D3-2 (Important; Blocking for Stage 1b/1c), D2-8, D2-9, D1-11 (Minor).
Disagreement, one line: I would hold D1-1 at Blocking under the severity table's "documented passed result the evidence does not support" clause, because the *measurement* cannot detect the leak it certifies; root's Important verdict stands in every table below.
Falsifies: `docs/ml-evidence.md:20`; `phase-01b:32-33, 60`; `phase-03a1-harness.md:22, 66`; `phase-02:34-35` AC6.
Why it matters: the next phase renders training rows from exactly these objects.

**(e) Two headline evidence claims are not supported by their artifacts.**
The r5 system prompt transcribes the oracle's decision precedence and appends its five booleans; the five successes are exactly the five one-boolean rules; the arithmetic case failed. r1 Slow prompts contained the oracle's label as an APPROVED `accept_offer` on exactly the 10 accept episodes (provable from committed fingerprints) while `PLANS.md:23` still records "full gate passed". `baselines-check` and `validity-smoke-check` recompute fingerprints over the report's own rows, so an edited 5/6 → 6/6 passes. The oracle ceiling is described as "completes all 32" when it completes 10.
Subsumes: D2-1 (Blocking, raised by root), D3-3; D2-4, D2-5, D2-2, F-1 (Important); D3-4 (Minor); G-4.
Falsifies: `docs/ml-evidence.md:19-22`, `:31`, `:36-38`; `PLANS.md:23`, `:101-104`; `phase-03a1-evaluation-validity-smoke.md` AC2 in substance.
Why it matters: these are the two numbers the README uses to argue the harness works and the model can do the task.

**(f) Duplicated authority: two oracles, three hash functions, two unsupported-change lists, two `content_hash` meanings.**
`ScriptedOracleConsumer()` defaults to the frozen 01B predicate at six evaluation call sites; the shared policy runs only when injected (03B/03C). `material_terms_hash` has three implementations (runtime compiler unsorted 3-term; executor sorted; domain 6-term). `Evidence.content_hash` means "artifact hash" in one producer and "hash of our idempotency key, minted before execution" in another. Credit constant and tariffs are literals in several files.
Subsumes: B1-5/D1-2, B1-4, D1-7 (Important); D3-8, B1-11, A-5, D2-11 (Minor/Note).
Falsifies: `PLANS.md:179-183`; `CONTEXT.md:87-89`.
Why it matters: labels, authorization, and evidence each have two definitions; the parity tests compare the ones nobody runs.

**(g) Durability edge cases that strand a Case permanently.**
Expiry-timer activity failure fails the workflow run; `REJECT_DUPLICATE` prevents recreation; the approval never expires and the API reports a healthy Temporal as unavailable. One Case per process plus a restore path that refuses non-durable profiles dead-ends direct mode after any reload. Direct mode never expires an approval. The manifest is minted once with a 24 h expiry against a "wait across days" goal. 30-minute strategy expiry with no refresh (b).
Subsumes: C-3 (Important), E-4 (Important), B2-3, C-4, E-11 (Minor), A-11, B2-N6.
Falsifies: `phase-05a` "PostgreSQL unavailable through retry exhaustion → Workflow remains available"; `apps/README.md:12-16`; `GOALS.md:5`.
Why it matters: "survive waits and retries" is a stated success condition.

**(h) The Web hides failure.**
409 after event/approval POST is swallowed with no message and the button re-enabled; Finalizing polling stops after five reads and goes silent; the exact pending-approval retry is discarded precisely in the `approved + pending_execution` state the runtime writes; a `blocked` response re-offers the confirm action; the 06A review records tests that do not exist. With (a), the user's experience of a stuck runtime is silence.
Subsumes: E-1, E-2, E-3, E-5, E-6 (Important); E-7, E-8 (Minor).
Falsifies: `docs/ui/state-matrix.md:13, 15, 18`; `phase-06a` AC 6/11/12; `harness/code_review/phase-06a-durable-web-resume.md:36-39`.
Why it matters: a Pine-style surface is judged on truthful state; fixing (a) without (h) leaves the user uninformed.

**(i) The benchmark's breadth is overstated.**
Configurations change no outcome (32 = 16 duplicated; the "provider held-out" split measures nothing); `forged-evidence` ≡ `absent-evidence`; `multi-hazard` and `refusal-transfer` are one boolean the oracle checks before looking at any offer; five success families are one offer with a different token; "multi-turn" is one round that ignores the consumer message; the disclosure hazard is injected by the script.
Subsumes: D1-5, D1-6, D1-8 (Important); D1-9, D1-10, D1-12 (Minor); D1-13, D1-14.
Falsifies: `docs/ml-evidence.md:17`; `phase-03a1-harness.md:23, 55`; `phase-03a1-ceiling-report.json` `provider_holdout_episode_count: 16`.
Why it matters: three independent hazards and one round cannot train or evaluate a negotiator.

**(j) Contracts and docs describe things that do not exist or contradict each other.**
Strategy is never invalidated by a planning-basis change (no field, route unchanged after a material offer); `ModelTrace` has no producer; the spec's completion receipt is a plain dataclass outside the contract seam; Research MVP says "no Temporal" beside an "Implemented: Temporal" status block; five verifier outcomes documented, two produced; Qwen3-4B vs 8B; "HMAC-signed" with no key; `contracts/openapi` is a `.gitkeep`; `tests/README.md` says DB/workflow tests are deferred; `make preflight` silently skips 36 real-dependency tests.
Subsumes: A-1, A-2, C-6 (Important); A-3, A-6, A-7a–g, F-2, F-3, G-1, G-2, G-3 (Minor); A-9, A-10, E-N3.
Falsifies: listed per row in §7.
Why it matters: a reviewer cannot tell built from planned; the project's own success condition (`GOALS.md:19`) is that reported results distinguish the two.

## 4. Module trust table

| Unit | Verdict | Why (one clause) | Lanes |
|---|---|---|---|
| `contracts.py` (19 of 23) + `_base.py` | keep | produced and consumed; strict base matches ADR | A |
| `FactLedger`, `StrategyPacket`, `ActionIntent`, `Evidence` contracts | refactor | never written / no basis binding / no capability ref / undefined hash referent | A-1, A-3, A-5 |
| `ModelTrace` contract | rewrite or delete | zero producers | A-2 |
| `agent_core/router.py`, `coordinator.py`, `scripted.py`, `interfaces.py` | keep | precedence real; small fixes (B1-12, N8, A-1 reasons) | B1, A |
| `agent_core/capabilities.py` | refactor | approval not consumed, terms not derived | B1-1, B1-2, B1-10 |
| `agent_core/observation.py` | refactor | legacy oracle default; duplicate context | B1-5, D1-2 |
| `telecom_domain/domain.py`, `offer_policy.py` | keep | strongest runtime modules; B1-8/9/11 minor | B1, D1 |
| `openai_adapter/outputs.py` | refactor | cannot compile advertised capability; third hash | B1-3, B1-4 |
| `openai_adapter/adapter.py`, `errors.py` | keep | fail-closed; B1-6/7 minor | B1 |
| `case_runtime/runtime.py` | refactor | recovery, time basis, no Slow refresh | B2-1/2/3, C-1 |
| `case_runtime/commands.py`, `repository.py` | keep | correct; validators under-tested | B2 |
| `case_runtime/postgres_repository.py` | keep (one fix) | CAS correct; envelope refuses non-COMPLETE | C-2 |
| `api/app.py` | refactor | header ignored in direct mode; blocking handlers; full snapshot to browser | B2-4/6/8, E-N1 |
| `api/config.py`, `operations.py`, `readiness.py` | keep | fail closed | B2 |
| `workflow_worker/workflow.py` | refactor | timer path fails the run | C-3 |
| `workflow_worker/{activities,client,models,config,readiness,worker}.py` | keep | taxonomy matches; C-4 minor | C |
| `connectors/local_mailbox.py` | keep | matches its contract; docs wrong | C-6 |
| `scripts/run_phase_07a_portfolio_demo.py`, `compose.yaml` | keep (one fix) | refused-start orphans processes | C-5 |
| `provider_simulator/environment.py` | **rewrite** | label equality, module constants, divergent list | D1-3/4/7 |
| `provider_simulator/scenarios.py`, `multi_turn.py`, `splits.py` | refactor | ids leak; one round; decorative configs | D1-1/5/6/8/9/10 |
| `provider_simulator/episode.py`, `provider.py` | keep | real verifier tests | D1, A |
| `scripts/run_phase_01b_benchmark.py` | refactor | key-name leak probe; injected hazard | D1-1, D1-13 |
| `ml/evaluation/runner.py` (r1) + `replay.py`, `artifacts.py` | rewrite or retire as historical | label in prompt; not replayable | D2-4, D2-5 |
| `runner_v2.py` | refactor | E2E = script agreement; constant metrics | D2-3/7/8 |
| `hosted_rerun.py`, `replay_v2.py`, `fresh_fixtures.py`, `artifacts_v2.py`, ml `models.py` | keep | strongest evidence chain; D2-6/9 minor | D2 |
| `validity_smoke.py` | **rewrite** (D2) over "re-document" (D3): the builder's only purpose is the contaminated diagnostic; wording fixes the doc, not the module | D2-1, D3-3 |
| `scripts/run_phase_03a1_validity_smoke.py` | refactor | `--check` re-derives nothing | D2-2 |
| `scripts/run_phase_03a1_harness.py` | refactor | r1 approval-leak source; key-name probe | D2-4, D1-1 |
| `ml/data_pipeline/pipeline.py` | refactor | family id in model-facing rows; regeneration-equality curation | D3-1, D3-N1 |
| data `models.py`, `run_phase_02_data_pilot.py` | keep | — | D3 |
| `qwen_mlx.py` | keep frozen, wrap | r4 execution contract; D3-5/6 latent | D3 |
| `qwen_spec.py`, `fast_output.py`, `fast_parse.py`, `slow_output.py`, `legacy_slow_output.py` | keep | tested; hash executor-compatible | D3 |
| `openai_frontier.py` | keep with fixes | value-blind guard; loose prefix | D3-2, D3-9 |
| `phase03b_readiness.py` | refactor | constants echoed as fingerprints | D3-4 |
| `apps/web/lib/runtime-client.ts` | keep | narrow, strict | E |
| `apps/web/.../conversation-workspace.tsx` | refactor | 1287 lines; swallows 409; silent poll cap | E-1/2/3/5 |
| other `apps/web` files | keep | trivial | E |
| Web tests | keep, extend | zero coverage of 409/poll/blocked paths | E-6 |
| `Makefile`, `ci.yml`, gate scripts | keep | honest gates; G-1/2/3 minor | G |
| `tests/contract/*` import-graph files | keep | real | D1, A |
| `test_phase_03a0/03a1/baselines/hosted_rerun_architecture.py` (grep tests) | rewrite or delete | markdown substring greps | A §3, D1 §4, B1-N2 |
| `runtime/packages/contracts/tests/test_contracts.py` | refactor | no negative tests for 03A1 validators | A §3 |
| `GOALS.md`, ADR implementation-defaults, spec boundary sections | keep (line fixes) | A-7a | A |
| `CONTEXT.md`, `docs/architecture.md`, ADR fast-slow | refactor | built/planned/stale unmarked | A-1/2/7 |
| `docs/ui/*.md`, `docs/ml-evidence.md`, `PLANS.md` status rows, `README.md` invariants | refactor | §7 | E, F, D2, C-6 |
| `tests/README.md`, `contracts/README.md` | rewrite | describe a repo that does not exist | F-3, G-2 |

## 5. Path to a runnable Pine-style demo

**What "Pine-style" means here** (from `pine-ai-reference.md`). Pine publicly
promises: the user states a goal in their own words; the agent negotiates
with a third party over a live channel while identifying itself as an AI;
the user "approves everything before we start"; an outcome is reported
(`CallResult{status, transcript, summary}`). Pine discloses no verification
method, no typed approval pinned to terms, and no post-action evidence. So
the Pine-style surface to reach is: free-text goal → visible model-driven
multi-turn negotiation → proposed action → approval → execution → reported
outcome. The ProxyLoop differentiator to keep is everything Pine does not
show: `ApprovalRequest` pinned to offer revision, terms hash, and expiry;
at-most-once execution; `Evidence` + deterministic `CompletionDecision`
verified against Provider state. The card's third pass (Bojie Li's primary
sources) adds three Pine patterns and their placement: a **Judge** model that
reviews Slow proposals (τ-bench 56 % → 64 %) — a quality step *before*
ProxyLoop's deterministic policy/approval gate, never a replacement, and
never part of an evaluation metric (D2-1 is what happens when a label
function reaches the model); the **Agent Status Bar** — a deterministic state
block injected into context, which is what `CaseContextSnapshot` already is
and what the model never receives in usable form (A-4, B1-N6: a two-sentence
system prompt plus a JSON dump); and **experience memory / PreAct** — later,
gated stages (Case-scoped state per `CONTEXT.md`; no trajectories worth
learning from while multi-turn is one round, D1-9; PreAct has no licence).
Do not borrow: TalkAct's browser-automation slow agent (the model executes
tools directly), LLM-judged correctness or a Judge verdict as a completion
metric or authority, PreAct code, unverifiable TEE/voice claims,
cross-session memory.

Ordering rule (*proposed*): nothing model-driven is wired into the product
until (a) is fixed, because a model that proposes actions will hit the
recovery bug on the first transient failure; nothing is trained until (c)
and (d) are fixed, because the labels and rows are the defect. Sizes:
S ≤ 1 day, M ≤ 1 week, L > 1 week.

**Stage 1 — Recovery a retry can finish (L).**
Persist a claim receipt (`command_id`, `before_revision`, `evaluated_at`) in
the claim write; `apply_command`/`approve` recognise a retry of the same
command and re-drive `_execute_claim` regardless of `expected_revision`;
drop the process-local executor cache; executor records `approval_id →
evidence` and rejects `approval_already_consumed`; executor derives terms
from the snapshot offer; recovery verifies with the persisted time basis;
envelope accepts the full `CompletionOutcome` set; timer path catches
activity failure and re-arms. Web: `pendingResolved` keeps the approval
command while `pending_execution`; 409 and poll exhaustion show a category.
Removes: B2-1/C-1, B2-2/C-2, C-3, B1-1, B1-2, B1-10, E-1, E-2, E-3.
Touches: `runtime.py`, `postgres_repository.py`, `capabilities.py`,
`workflow.py`, `conversation-workspace.tsx`. Depends on decisions 1, 2.
Evidence: lane C `c2` ends `terminal=True` on activity attempt 2 with one
confirmation Evidence; `c1` scenario D persists; `c3` leaves the workflow
running; Web repros R1–R3 pass; the same `CaseCommand` applied twice around
an injected final-write failure returns a terminal receipt.

**Stage 2 — Verifier by state, one oracle, content-free ids (L).**
Rewrite `environment.py`: per-action state predicates (a safe non-completion
is valid when the Provider state shows no side effect and the offer is
non-compliant/expired/unclear), constraints carried by the scenario's Case,
one unsupported-change list from `offer_policy`; delete the legacy oracle
predicate; one `material_terms_hash`; E2E = stage validity ∧ ¬false_completion
∧ (accept ⇒ Provider-verified), `reference_match` reported separately;
UUID/hash public ids; value-level leakage scan (JSON-in-string aware) in the
benchmark probe, both prompt guards, and the pipeline; regenerate 01B/02/03A1
artifacts with `DEFAULT_PARAMS` preserving ids where required by the 03C
contract. Removes: D1-3, D1-4, D1-7, D2-3, D2-7, B1-5/D1-2, B1-4, D1-1, D3-1,
D3-2, D2-8, D2-9. Touches: `provider_simulator/*`, `observation.py`,
`runner_v2.py`, `pipeline.py`, `openai_frontier.py`, a wrapper around
`qwen_mlx.py`, `outputs.py`, `capabilities.py`. Depends on decisions 3, 4;
runs inside 03C Stage 1a (see reorder note). Evidence: D2's safe-alternative
probe yields `e2e=True`; D1 `divergence.py` A–H all agree with the shared
policy; `leak.py` 0/32 value hits; `b03_leak2.py` 0/26; oracle/verifier
agreement over ≥1,000 seeds (03C Stage 1 acceptance).

**Stage 3 — Model output reaches the product runtime (L).**
Capability id resolved through the manifest (B1-3); `append_event` routes
`slow_refresh` to `self._slow` and passes `fast=`; the action intent is
derived from the accepted `SlowWorkResult` proposal, not from `offers[0]`;
Fast `response_text` is delivered as dialogue under the disclosure policy
(AI self-disclosure copy included); `StrategyPacket` bound to
`planning_basis_fingerprint` so the Router, not hand-coded control flow,
triggers Slow; `ModelTrace` emitted per adapter call or deleted (decision 11);
browser projection becomes an allow-list that includes `visible_events` and
assistant text. Two third-pass additions: the prompt renders the snapshot as
a deterministic status block (goal, constraints, current offer with the six
material terms, approval state, allowed capability ids, disclosure policy)
instead of the current two sentences (B1-N6) — the same renderer serves the
runtime `adapter.py` and the ml prompt builders; and an optional Judge pass
sits between the accepted `SlowWorkResult` and the deterministic gate (Slow
proposal → Judge: incomplete search / arithmetic / premature give-up → one
retry → `offer_policy` + approval), recorded in the trace, excluded from
every metric. Removes: B1-3, B1-4, B2-3, B2-5, A-1, A-2, A-8, A-4's
"asserted not exercised", B1-N6, E-N1. Touches: `runtime.py`, `router.py`,
`coordinator.py`, `outputs.py`, `adapter.py`, `contracts.py` (schema bump),
`app.py`, `conversation-workspace.tsx`. Depends on Stage 1 and decisions 7,
9, 10, 11.
Evidence: model-mode test where a Slow proposal becomes the executed intent;
an event at T+31 min yields a fresh strategy, not 409; A-1 repro routes
`slow_refresh` after a material offer; a Web test renders an assistant bubble
whose text came from the runtime, not a literal.

**Stage 4 — Multi-turn negotiation against a simulated counterpart (L).**
TalkAct idea 2, adapted: an LLM-simulated Provider representative (a
different model family from Fast and Slow, as `simuser.py` does) generates
the Provider's turns, but every offer, fee, transition, and confirmation
comes from the deterministic Provider state machine and is verified by the
Stage 2 verifier; the model only speaks, it never decides state. Replace
one-round `multi_turn.py` with cursor-ordered N-turn episodes; make
configurations change behaviour (D1-5); make `forged-evidence` and
`multi-hazard` test what they name or move them out of `SAFETY_FAMILIES`;
regenerate the manifest per episode when waits exceed 24 h (A-11). Removes:
D1-5, D1-6, D1-8, D1-9, D1-13, D1-14, A-11. Touches: `provider_simulator/*`,
`ml/evaluation` fixtures, `runner_v2.py`. Depends on Stages 2 and 3.
Evidence: episodes with ≥3 Provider turns whose transcript is model text;
verifier still deterministic; both configurations produce different oracle
outcomes on at least the hazard families; oracle labels are no longer the
verifier.

**Stage 5 — Free-text intake and a truthful negotiation surface (M–L).**
User states the goal in their own words; Slow compiles a typed `ConsumerGoal`
proposal the user confirms (typed approval retained, regex wizard removed);
the Web shows the Provider dialogue from `visible_events`, the assistant's
self-disclosure, the approval card with exact pins, a reject control (E-N5),
and truthful `blocked`/expired/reconnect states; direct mode either honours
`Idempotency-Key` through `apply_command` or is removed from `apps/README.md`
(decision 8); direct mode expires approvals or is documented as not doing so.
Removes: E-4, E-5, E-6, E-7, E-8, E-11, B2-4, B2-6, A-6 (receipt as a
contract), E §5. Touches: `conversation-workspace.tsx` (split), `app.py`,
`runtime.py`, `contracts.py`. Depends on Stage 3. Evidence: browser scene
where the Provider thread is model-generated and the receipt is
state-verified; Web tests for 409, poll exhaustion, blocked, 404/422, USD
parsing, 375 px.

**Stage 6 — Measure the Fast/Slow split (M).**
TalkAct idea 1: add a runner condition matrix `fast-only | sequential |
duplex` to `runner_v2` with per-turn latency percentiles and `slow_call_rate`
per dialogue turn, so spec:107 and ADR :144 are measured for the first time;
decide keep/drop Fast from the number. Removes: A-4 as an evidence gap.
Touches: `runner_v2.py`, `models.py`, report artifacts. Depends on Stages 3
and 4. Evidence: a committed report with the three conditions and latency
columns; `docs/ml-evidence.md` cites it.

**Stage 7 — Resume distillation and channels; memory last.** 03C Stage
1b/1c/2 run against the Stage 2 simulator only if V0 (below) does not end in
`GO_PROMPT_ONLY` (`phase-03c-fast-model-distillation.md:272`); 06B2 (real
controlled integration) is considered only after Stage 1 holds with a
non-simulator adapter (B1-1 is Blocking before 06B2 per root); full 07 after
Stage 5. Experience-memory tiers and PreAct-style compiled workflows are a
separate gated stage after Stage 4 produces real trajectories; not part of
the first demo.

**The user's V0 proposal — frontier Fast/Slow/Judge, no training, measure
completion / violation / false-commitment rates first** (*evaluated against
the findings*). It is the right target for Stages 1–3 and is consistent with
the 03C contract's `GO_PROMPT_ONLY` outcome. Two conditions the audit adds.
First, the runtime cannot host it today: a model-proposed action would hit
B2-1/C-1 on the first transient failure, B1-3/B1-4 make every model-compiled
intent dead on arrival, B2-3 kills the Case at 30 minutes, and E-1/E-2 hide
all of it — so Stage 1 and the Stage 3 wiring are prerequisites, not
follow-ups. Second, two of V0's three rates are not measurable by the current
evaluator: "completion rate" is script agreement for 22/32 scenarios (D1-3,
D2-3) and `policy_violation_count` is a constant 0 (D2-8); only
`false_completion_count` (false commitment) is a real number today. Stage 2
must land before V0's numbers mean anything. With Stages 1–3 done, V0 is a
runner_v2 condition set (`frontier_fast + frontier_slow [+ judge]`) over the
Stage 2 verifier, and its result decides whether 03C Stage 2 training happens.

**Reordering of current phases** (*proposed*): 03C Stage 1a (parameterisation,
USD 0, running) continues, but its acceptance must include D1-3, D1-4, D1-7
and content-free ids (Stage 2), since its own invariant suite asserts
oracle/verifier agreement on a verifier that is label equality. 03C Stage 1b
(hosted teacher pilot) and 1c are paused until Stage 2 lands: D1-1/D3-2 are
Blocking for them per root, and the teacher pipeline must not use
`build_phase03b_examples()`. 06B2 and 07 stay unauthorised; the audit adds
Stage 1 and Stage 5 as their prerequisites.

## 6. Remediation backlog

**P0 — before any further phase**

| Ids | Fix | Files | Regression test first | Size |
|---|---|---|---|---|
| B2-1, C-1, B2-2, C-2 | claim receipt (`command_id`, `before_revision`, `evaluated_at`); retry re-drives `_execute_claim`; recovery uses claim time; envelope accepts all `CompletionOutcome` | `runtime.py`, `postgres_repository.py` | same `CaseCommand` twice around injected final-write failure → terminal receipt, one Evidence (B2 `s2`, C `c2`, C `c1` D) | L |
| B1-1, B1-2 | executor ledger `approval_id → evidence`, reject `approval_already_consumed`; derive terms from snapshot offer | `capabilities.py` | `b1_exec_1` second execution rejected; `b1_exec_3` case 3 → `current_offer_terms_mismatch` | M |
| C-3 | catch activity failure in the timer path, keep run alive, re-arm | `workflow.py` | `c3`: workflow still `RUNNING` after 5 failed attempts; approval expires once DB returns | M |
| D2-1/D3-3, D2-4, F-1, C-6, README:87 | correct the claims per §7; mark r1 superseded; r5 "rule-following under oracle-flag parity" | `docs/ml-evidence.md`, `PLANS.md`, `README.md`, `progress.md` | `test_validity_smoke` leakage test scans for the oracle rule vocabulary, not the word "oracle" | S |
| D1-1, D3-1, D3-2 | content-free public ids; value-level (JSON-in-string) leakage scan in benchmark probe, both prompt guards (wrap `qwen_mlx`), pipeline; regenerate artifacts | `scenarios.py`, `run_phase_01b_benchmark.py`, `run_phase_03a1_harness.py`, `pipeline.py`, `openai_frontier.py`, new wrapper | `SafeObservation.to_json()` and a 03B example-view prompt contain no family/config/scenario id | M |
| D1-3, D1-4, D2-3 | per-action state predicates; Case-carried constraints; E2E = validity ∧ ¬false_completion ∧ (accept ⇒ verified) | `environment.py`, `scenarios.py`, `runner_v2.py` | `request_replan` on fee trap → valid; Case target 7 000 → verifier reads the Case; D2 safe-alternative probe `e2e=True` | L |
| B1-5/D1-2, B1-4, D1-7 | shared policy is the only oracle; one `material_terms_hash`; one unsupported-change list | `observation.py`, `outputs.py`, `environment.py`, `capabilities.py`, `domain.py` | `b1_policy` undisclosed-fee case declines by default; compiled intent hash equals executor hash; `unsupp.py` verifier rejects | M |
| E-1, E-2, E-3 | show category after non-advancing 409 reconcile; poll exhaustion → error + reconnect; keep approval command while `pending_execution` | `conversation-workspace.tsx` | R1, R2, R3 | M |

**P1 — before the demo stage that depends on it**

| Ids | Fix | Files | Test first | Size | Stage |
|---|---|---|---|---|---|
| B2-3, B2-5 | route `slow_refresh` to `self._slow`; agree whether `strategy.expires_at` gates execution | `runtime.py`, `capabilities.py` | `s8_expired` at T+31 m → new strategy | M | 3 |
| B1-3 | resolve capability id via manifest | `outputs.py` | `b1_outputs` case 1 compiles | S | 3 |
| A-1, A-2 | basis fingerprint on strategy; `ModelTrace` emitted or deleted; schema bump | `contracts.py`, `router.py`, `coordinator.py` | `repro_strategy_basis` routes `slow_refresh` | M | 3 |
| E-N1, B2-N1 | browser projection allow-list | `app.py`, `runtime-client.ts` | snapshot test of projected keys | M | 3 |
| D1-5, D1-6, D1-8, D1-9 | behavioural configurations; real forgery; hazard not one boolean; N-turn | `scenarios.py`, `multi_turn.py`, `environment.py` | `divergence.py` D–G produce differing outcomes; `mt.py` consumes message content | L | 4 |
| A-11 | manifest per snapshot or no expiry | `runtime.py` | execution at T+25 h succeeds | S | 4 |
| B2-4, E-4, E-11, B2-6 | direct mode honours the key via `apply_command` or is dropped; approval expiry; honest placeholder | `app.py`, `runtime.py`, `apps/README.md` | `s1_direct_keys` dedups; R4 | M | 5 |
| E-5, E-6 | `blocked` never re-offers confirm; write the recorded-but-missing tests | `conversation-workspace.tsx`, tests | R6; USD/404/422/readiness tests | M | 5 |
| A-6 | completion receipt as a canonical contract | `contracts.py`, `domain.py` | generated-schema fixture | M | 5 |
| D2-2, D2-5, D3-4 | `--check` replays labels via `replay_v2`; retire r1 from `make test` as historical; readiness compares to committed manifest | `run_phase_03a1_validity_smoke.py`, `artifacts.py`, `phase03b_readiness.py` | D2 probes (a), (c) fail | M | before any new eval artifact |
| C-4 | Update ID not the inbox `command_id` when body changes | `client.py`, `app.py` | `c4` second dispatch succeeds | S | 5 |

**P2 — hygiene**: G-1 (`preflight` asserts skip count or names real-dep
gates), G-2, G-3, F-2, F-3, A-3, A-5, A-7a–g, A-9, A-10, B1-6…B1-12,
B2-7…B2-9, C-5, C-7, C-8, D1-10…D1-12, D2-6…D2-9, D3-5…D3-9, E-7…E-10,
grep-based architecture tests replaced by Router precedence tests (A §3).

## 7. Doc claims to correct

| path:line | Current text (abridged) | Evidence supports |
|---|---|---|
| `README.md:87` | "At-most-once execution, evidence-gated completion" | at-most-once only for the in-memory simulator; pending-claim retry re-commits a reconstructed Provider (C-1) |
| `README.md:37, 111`; `progress.md:98` | "signed" / "HMAC-signed raw-byte fixtures" | unkeyed SHA-256, no authentication (C-6) |
| `README.md:66`; `user-flows.md:21-22`; `progress.md:93-94` | `Idempotency-Key` exact retry | header ignored in direct mode; exact retry → 409 in both modes (B2-4, B2-1) |
| `docs/ml-evidence.md:19-20` | "scripted oracle completes all 32" | 10 completions, 22 valid non-completions (F-1) |
| `docs/ml-evidence.md:13-15` | "verifier that inspects the simulated provider's real state" | state for `accept_offer` only; label equality for 22/32 (D1-3, D2-3) |
| `docs/ml-evidence.md:20` | "zero private-field leakage" | zero leaked *keys*; family id in 28/32 values (D1-1) |
| `docs/ml-evidence.md:31, 36-38`; `PLANS.md:101-104` | "5/6 after giving model and oracle the same public inputs"; "harness works" | 5/6 with the oracle's rule table in the system prompt (D2-1) |
| `docs/ml-evidence.md:31` | "USD 0.117 hosted spend" | usage × hard-coded tariff estimate (D2-11) |
| `docs/ml-evidence.md:17`; `phase-03a1-harness.md:23, 55` | 16 × 2 configurations; provider held-out | configurations change no outcome (D1-5) |
| `PLANS.md:23` | 03A1-B "full gate passed" | AC#4/#8 failed: r1 prompts carried the label (D2-4) |
| `PLANS.md:179-183` | "one authoritative shared policy … scripted oracle" | default oracle is the legacy predicate at six eval sites (B1-5) |
| `docs/architecture.md:243, 272` | executor revalidates approval/idempotency; stale approval cannot authorize | keyed on intent key; terms checked by Provider `prepare` (B1-1, B1-2) |
| `docs/architecture.md:54`; `phase-05a` fault rows | receipts avoid duplicate execution on retry | claim write has no receipt; timer exhaustion fails the run (C-1, C-3) |
| `docs/architecture.md:189`; ADR :110 | planning-basis fingerprint binds the Strategy Packet | no field; route unchanged after material change (A-1) |
| `docs/architecture.md:211, 276`; ADR :114-115 | `ModelTrace`; "traced and rejected" | no producer anywhere (A-2) |
| `docs/architecture.md:5, 124-170`; spec:65, :107 | Fast conducts dialogue; Slow ≤ 20–30 % of turns | runtime accepts only a constant Fast text; no per-turn measurement (A-4) |
| `docs/architecture.md:185` | `slow_refresh` for mandatory Slow work | no Slow path on the event route; 409 after 30 min (B2-3) |
| `docs/architecture.md:245` | five verifier outcomes | two produced (A-7f) |
| `docs/architecture.md:301-310` | Research MVP "no Temporal" | Temporal mode implemented (A-7b) |
| `docs/ui/state-matrix.md:13, 15, 18` | pending_execution recoverable; blocked hides actions; never silent | poll goes silent; confirm re-offered; 409 swallowed (E-2, E-5, E-1) |
| `harness/code_review/phase-06a-durable-web-resume.md:36-39`; `intake-ux.md:122-123` | tests "each have focused coverage" | tests do not exist (E-6) |
| `phase-01b:32-33, 60`; `phase-02:34-35` | no scenario labels in public payload | key-name check only (D1-1, D3-1) |
| `phase-03a1-evaluation-validity-smoke.md` AC2 | prompt contains no oracle action | contains the oracle's decision procedure (D2-1) |
| `tests/README.md:3` | DB/workflow/channel/browser tests "remain deferred" | they exist (F-3) |
| `contracts/README.md:3` | OpenAPI artifacts generated here | `.gitkeep` only (G-2) |
| `docs/planning/progress.md:27` | ML 177 tests | 220 since PR #33 (F-2) |
| `GOALS.md:27`; spec:5, :74 | Qwen3-4B default | Qwen3-8B per amendment (A-7a) |
| ADR fast-slow `:5` | "gated by Phase 03A1" | 03A1 complete (A-7c) |
| `CLAUDE.md` "final local gate" | `make preflight` | skips 36 DB/Temporal tests silently (G-1) |
| `apps/README.md:12-16` | run Runtime and Web separately | direct mode dead-ends on reload; one Case per process (E-4) |

## 8. Decisions only the user can make

| # | Decision | Recommended | Reason |
|---|---|---|---|
| 1 | Recovery contract: same-command retry, or new pin-less approval (B2 Q1, C Q1, C Q2) | same-command retry; timer path never fails the run | it is what the Web and Temporal already send; pin-less is a request no client makes |
| 2 | Does the executor own approval consumption and terms-vs-offer comparison (B1 Q1/Q2) | yes | otherwise `architecture.md:243` must be rewritten and 06B2 can never be safe |
| 3 | Canonical label authority (D1 Q2, B1 Q3) | shared `offer_policy`; delete the legacy predicate | it is the runtime's verifier; parity tests then test what runs |
| 4 | E2E metric (D2 Q3) and safety-family membership (D1 Q4) | state-based E2E; `reference_match` separate; drop `forged-evidence`/`multi-hazard` from SAFETY until Stage 4 | "3/32" is a script-agreement number and two families test nothing |
| 5 | r1 artifacts (D2 Q2) | mark superseded/historical; remove "replay" wording | not replayable without spend; the label leak is provable |
| 6 | r5 wording now vs parity-only rerun (D3 Q2) | reword now; rerun only after Stage 2 | a rerun on the current verifier measures the same thing |
| 7 | Model wiring shape: is Fast dialogue product behaviour (A Q3); is a Judge pass added before the deterministic gate | yes to both, wired in Stage 3; Fast kept or dropped after Stage 6; Judge quality-only, never in metrics or authority | today Fast has no consumer, and a decision without a measurement repeats A-4; a Judge that reaches metrics repeats D2-1 |
| 8 | Direct mode: honour `Idempotency-Key` or drop it (B2 Q3, E Q2) | route direct POSTs through `apply_command` | one receipt semantics for both modes |
| 9 | Browser projection allow-list (B2 N1, E Q3) | allow-list | shrinks Web validation and removes `idempotency_key`/fingerprints from the browser |
| 10 | 30-minute strategy lifetime (B2 Q2) | not a session bound; add Slow refresh | a demo that dies after 30 minutes is not runnable |
| 11 | Wire-version mechanism for contract fixes (A Q1/Q2): one `schema_version` bump covering A-1, A-2 (delete `ModelTrace`), A-6 | one bump, regenerated fixtures | three separate bumps with no migration mechanism is worse |
| 12 | Phase order: adopt V0 (frontier-only, no training) as the target of Stages 1–3; Stage 1a continues with §5 acceptance; 1b/1c and 03C Stage 2 wait for V0's numbers; 06B2/07 behind Stages 1 and 5 | as stated | D1-1/D3-2 are Blocking for 1b/1c; B1-1 is Blocking before 06B2; V0 may return `GO_PROMPT_ONLY` and make training moot |
