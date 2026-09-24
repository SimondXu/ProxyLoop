# PR-11 Stage 1c: model-backed Fast under Temporal + the 07A launcher flag — preflight spec

Status: implementer spec, 2026-09-24, from `main` @ `a8fdf5b` (#97, PR-9a).
Branch `feat/pr11-fast-under-temporal`. Build plan row PR-11
(`harness/context/build-plan-to-complete.md`): "model-backed Fast under
Temporal + a 07A launcher flag, inside the 30 s activity limit"; key files
`workflow.py` and the launcher; depends on PR-3 (#92, merged) and PR-9
(9a #97 merged; 9b, the gateway, in progress).

Binding inputs: the PR-9 frozen spec (`pr9-local-distilled-fast-design.md`),
root answers Q4 (only a typed `FastAdapterFailure` is captured: `FAILED`
trace + fallback + applied command; no retry, no backend switch) and Q10 with
the dated amendment (default timeout 25 s = the cap, bound by the 30 s
Temporal activity and Next proxy limits); PR-8 frozen spec I7 (channel path
unchanged: constant body, no assistant event, equality check) and root
answer 5 (PR-11 decides the channel outbound body); decisions 16–18.

Tags: **[O]** observed in code, **[I]** inferred, **[D]** decided here.

## 1. Current state [O]

- **Worker.** `activities.runtime_from_environment` builds
  `ThinAgentRuntime(PostgresCaseRepository(url))` and ignores
  `PROXYLOOP_FAST_BACKEND`, so the worker always runs the scripted default
  (`ScriptedDialogueFastAdapter`). `create_worker` builds it eagerly at start;
  the module-level activities build it lazily (`_get_default_adapter`). The
  worker package does not depend on `proxyloop-local-fast`.
- **API.** `services_from_environment` refuses any non-scripted
  `PROXYLOOP_FAST_BACKEND` under `PROXYLOOP_ORCHESTRATION_MODE=temporal`
  ("until PR-11"). In Temporal mode every command goes through
  `temporal_client.apply_command` (`app.py` `apply`, the channel route); the
  API's own `ThinAgentRuntime` serves reads, readiness, and the
  `adapter_mode` label, and never calls Fast.
- **Fast call sites.** `runtime.py` calls `self._fast` in two places:
  `_append_event_serialized` (consumer and Provider-offer events; a captured
  failure or gate reject delivers `FAST_FALLBACK_TEXT` and applies the
  command) and `ingest_channel_event` (raises `ModelRuntimeError("fast")`
  unless the accepted Fast text equals `BOUNDED_FAST_STATUS_TEXT`, and hard-
  wires that constant as the outbox body).
- **Activity limits.** `ACTIVITY_START_TO_CLOSE` 30 s,
  `ACTIVITY_SCHEDULE_TO_CLOSE` 2 min, `ACTIVITY_RETRY_POLICY` up to 5
  attempts (1 s → 10 s backoff) with `invalid_command`, `case_not_found`,
  `case_conflict`, `approval_expired`, `state_invalid`, `model_path`
  non-retryable. The activity maps `ModelRuntimeError` to `model_path`
  (non-retryable) and any unexpected `Exception` to retryable
  `activity_failed`.
- **Local Fast adapter (9a).** `fast_adapter_from_environment` is the one
  parse (unknown value, non-loopback URL, timeout outside [0.1, 25] →
  `ValueError`; absent gateway, bad identity, other backend, other prompt or
  base model → `LocalFastStartupError`). `LocalFastHttpAdapter` bounds the
  whole call (connect through last byte) by the timeout and raises only
  `FastAdapterFailure` on a call that yields no decision; the Runtime's
  coordinator captures it (`capture_fast_failures=True`).
- **Next proxy.** `apps/web/next.config.ts` rewrites `/api/runtime/*` to the
  Runtime with Next's default proxy timeout (30 s); no explicit override.
- **Launcher.** `build_demo_environment` inherits `os.environ` (minus the
  model keys), so an inherited `PROXYLOOP_FAST_BACKEND=distilled` reaches
  the API today and makes it refuse to start under Temporal. There is no
  launcher flag.

## 2. Decisions

### D1 — The worker builds Fast from `PROXYLOOP_FAST_BACKEND` [D]

- New `activities.activity_adapter_from_environment(environ)`:
  1. the worker's existing refusals (scripted Runtime mode, PostgreSQL
     storage, a database URL);
  2. `fast_adapter_from_environment(values)`: the same parse, the same
     refusal matrix, the same identity probe as the API. This runs **before**
     the PostgreSQL repository is built, so a refused start opens no database
     connection;
  3. `ThinAgentRuntime(repository, fast=<local adapter or None>)`, plus, with
     a local adapter, the scripted channel Runtime of D5.
- `create_worker` and `_get_default_adapter` use it; `runtime_from_environment`
  stays (exported, same signature) and returns the adapter's runtime.
- The worker therefore refuses to start on an unknown value, a non-loopback
  URL, a timeout outside [0.1, 25], `RUNTIME_MODE=model` (already refused),
  an absent gateway, or a gateway serving another backend, prompt version, or
  base model. The identity is probed once at start; every decide response is
  still checked against it (`fast_adapter_identity_mismatch`).
- `proxyloop-workflow-worker` gains the workspace dependency
  `proxyloop-local-fast` (`runtime/uv.lock` gains the edge; no third-party
  dependency changes).

### D2 — The API lifts its Temporal refusal and labels; the worker owns the calls [D]

- `services_from_environment` drops the "Temporal requires scripted Fast"
  refusal. Its runtime is already built by `runtime_from_environment`, which
  connects the local adapter from the same variables, so under Temporal the
  API also refuses to start on an absent or mismatched gateway, and its
  `/health/*` and operation records report `local_distilled_candidate` /
  `local_untuned_baseline`.
- The API never calls Fast in Temporal mode (every command is a Workflow
  Update), so the adapter it holds is used only for the start-time identity
  probe and the label.
- **How the API "knows" the worker is consistent: it does not.** Both
  processes read the same variables and probe the same gateway; the 07A
  launcher passes one environment to both (D6). Letting the API verify the
  worker's selection would need a Workflow query or a new activity (a
  Workflow command change, rejected below). The authority for what served a
  turn is the per-call Fast trace the worker writes (`provider`
  `local_mlx_gateway`, `model_version` `<backend>:<fingerprint prefix>`, or
  the scripted identity). A hand-started worker with a different variable
  would make `/health` mislabel the run: a recorded local limit.
- Only `api/config.py` changes; **no `app.py` edit**. The `model_path`
  409 message "model execution is unavailable in Temporal mode" becomes
  imprecise for a local validation reject (it is a redacted category); it is
  left as is to keep `app.py` untouched (PR-12 owns it).

### D3 — Timeout budget [D, from O]

| Segment | Bound | Source |
|---|---|---|
| Fast call (connect → last byte) | ≤ `PROXYLOOP_FAST_TIMEOUT_S` ≤ 25 s | adapter deadline (9a) |
| Slow (scripted), coordinator, gate | ≈ 0 ms | scripted adapters |
| Storage (fresh loopback PostgreSQL connection per op, a few ops + trace append) | milliseconds locally | `postgres_repository.py` |
| **Activity** `apply_case_command_activity` | start-to-close **30 s** | `workflow.py` (unchanged) |
| API → Workflow Update → response | Update waits for the activity | `client.py` |
| Web → Next rewrite proxy | **30 s** default | `next.config.ts` |

- Fast leaves ≥ 5 s of the 30 s activity for everything else; a new test
  pins `MAX_TIMEOUT_S + 5 ≤ ACTIVITY_START_TO_CLOSE`.
- **Busy gateway.** The gateway is single-flight: a second decide while one
  runs gets `503 busy` at once → `fast_adapter_busy` → `FAILED` trace +
  fallback line + applied command, well inside every limit. Under Temporal
  one Case's commands are serialized by the Workflow command lock, so busy
  comes from another Case's concurrent command, or from a call right after a
  client-side timeout (MLX cannot cancel a generation).
- **Queued commands (limit).** A second command for the same Case waits for
  the first behind the Workflow lock; with two 25 s Fast calls queued, the
  second Web request can exceed the 30 s Next proxy while the command still
  applies (the Web command carries an idempotency key; a retry deduplicates).
  This replaces direct mode's global B2-8 lock with a per-Case wait; it is
  recorded, not fixed.

### D4 — No activity retry on a Fast failure [D, from O]

- Every Fast outcome that yields no decision is a `FastAdapterFailure`
  (timeout, unavailable, busy, protocol error, invalid output, identity
  mismatch, unrenderable input). The Runtime's coordinator captures it, the
  command applies with the fallback line, and `apply_command` **returns
  normally**: the activity completes, so there is nothing for Temporal to
  retry. A new test drives `CaseCommandActivityAdapter.apply_command` through
  a fake gateway that is busy, slow past the timeout, or drops the
  connection, and asserts a returned transition, one decide request, a
  `FAILED` trace, and the fallback line.
- A validation reject of a model decision raises `ModelRuntimeError` →
  `model_path`, which is **non-retryable**: no retry either (unchanged).
- The only paths that re-run a whole command are unchanged and not
  Fast-specific: (a) an unexpected exception (`activity_failed`, a defect;
  9a made the wire decode total), and (b) the activity exceeding its 30 s
  start-to-close, which D3 bounds to "storage took more than ~5 s". In (b) a
  retry attempt that finds the first attempt committed returns the stored
  receipt without a model call; one that races the still-running first
  attempt (in the same worker) waits on the Case lane, fails the expected-
  revision check before any Fast call, and `apply_command`'s conflict path
  returns the first attempt's receipt as `deduplicated` (pre-existing
  behaviour). A retry landing on another worker process has no shared lane;
  PostgreSQL CAS still admits one commit, but that attempt may make its own
  model call first. Recorded as a limit.
- **No retry-policy change and no Workflow change.**

### D5 — Channel outbound body: stays the constant; channel commands keep scripted Fast [D, recommended; root may overrule]

Problem [O]: with a local backend in the worker, `ingest_channel_event`
would call the model (up to 25 s), then either fail the equality check
(model text ≠ constant) or see a captured failure (no decision); both raise
`ModelRuntimeError` → `model_path`, so **every channel ingest would fail**,
including the 07A mailbox scene.

| Option | What | Cost |
|---|---|---|
| **A (recommended)** | The outbound body stays `BOUNDED_FAST_STATUS_TEXT`. In the worker, channel commands (`ingest_channel_event`, `record_channel_delivery`) run on a second `ThinAgentRuntime` over the **same** repository with the scripted default Fast; every other command runs on the local-Fast runtime. | PR-8 I7 holds byte for byte (constant body, no assistant event, equality check, 06B1 fixtures). The model is never called on the channel path, so a Provider message arriving by channel gets the scripted Fast turn (its trace says so). No `runtime.py` change. Two runtimes share PostgreSQL CAS; their in-process Case lanes differ, as two worker processes' lanes already do; per-Case commands are serialized by the Workflow. |
| B | The body becomes the gate-passed model text or the fallback. | Model-authored text on an outbound channel is a send under `SEND_MESSAGE` authority, a semantic change PR-8 deferred; needs `runtime.py` (hot, owned by PR-13), new 06B1 fixtures/hashes, and a gate designed for an outbound send rather than an in-app line. Since `FAST_FALLBACK_TEXT == BOUNDED_FAST_STATUS_TEXT` and PR-9 predicts the distilled line is withheld on nearly every turn, the observable gain is close to nil. |
| C | Leave it: channel ingest fails closed under a local backend. | Breaks `make portfolio-demo-channel` with the flag and wastes up to 25 s per ingest before failing. |

Recommendation A. It is the only option that keeps I7, touches no hot file,
and keeps the mailbox scene working with the flag; B is a later product
decision (it belongs with real channels, which remain unauthorized). This
spec proceeds with A because it changes no committed behaviour or artifact;
if the root prefers B, the worker routing is the only code to revert.

### D6 — The 07A launcher flag [D]

- `FAST_BACKEND=distilled make portfolio-demo` (or `untuned`; default
  `scripted`). The Makefile passes `--fast-backend "$(FAST_BACKEND)"` to
  `serve`; argparse restricts it to `scripted | distilled | untuned`.
- `build_demo_environment(..., fast_backend="scripted")` sets
  `PROXYLOOP_FAST_BACKEND` explicitly for every child (worker, API, Web
  build, recovery), so the flag, not an inherited shell value, decides; one
  environment reaches both the worker and the API (D2).
  `PROXYLOOP_FAST_GATEWAY_URL` / `PROXYLOOP_FAST_TIMEOUT_S` are inherited as
  today.
- **The launcher expects the gateway; it does not start it.** The gateway is
  PR-9b's `make local-fast-gateway BACKEND=<backend>` (a ~17 GB MLX process
  with its own attestation; not on `main` yet). With a local backend, `serve`
  first runs the same `fast_adapter_from_environment` probe on the demo
  environment, before Compose, the Web build, or any host process starts;
  an absent gateway, a mismatched backend, or a bad URL/timeout is a
  `DemoScenarioError` naming `make local-fast-gateway BACKEND=<backend>`, and
  nothing is started. The start banner prints the Fast backend and its label
  ("local opt-in candidate" / "untuned local baseline").
- If the gateway dies mid-demo, each Fast call fails typed
  (`fast_adapter_unavailable`) and the turn delivers the fallback; the
  supervisor does not watch the gateway (it is not its process).

### D7 — Replay safety [D]

No Workflow command, timer, patch, activity option, or retry policy changes;
`workflow.py` is untouched. Only activity-internal construction and
configuration change, which Temporal replay does not observe. No patch gate
and no replay fixture are needed; the existing R-1 / R-16 replay tests stay
green unchanged.

## 3. Red-first tests

Non-gated (in `make test`), new file `tests/integration/test_fast_under_temporal.py`
unless noted; "red" = fails on `main` @ `a8fdf5b`:

- **T1 (red)** worker refusal matrix: unknown backend, non-loopback URL,
  timeout 0 / 25.5, absent gateway, backend mismatch → `ValueError` /
  `LocalFastStartupError`, and the PostgreSQL repository is never built
  (sentinel). On `main` the worker ignores the variable.
- **T2 (red)** a matching fake gateway selects the labelled local backend in
  the worker; channel commands get a scripted runtime over the same
  repository; scripted default builds a single runtime.
- **T3 (guarantee)** `CaseCommandActivityAdapter.apply_command` with a local
  adapter whose gateway is `busy`, `slow` (past a 0.5 s timeout), or `drop`:
  returns a transition, one decide request per command, a `FAILED` Fast trace
  with the code, the fallback line; no `ApplicationError`.
- **T4 (red)** channel ingest through the worker composition under a local
  backend: outbox body is the constant, no decide request reaches the
  gateway, no assistant event; the single-runtime composition fails
  `model_path` (documents the hazard D5 removes).
- **T5 (red)** API under Temporal (repository and Temporal client faked):
  a matching gateway starts with the local label; an absent gateway refuses
  with `LocalFastStartupError`. Replaces PR-9a's
  `test_temporal_refuses_a_local_fast_backend` (whose behaviour this PR
  lifts, as planned).
- **T6 (pin)** `MAX_TIMEOUT_S + 5 ≤ ACTIVITY_START_TO_CLOSE` seconds, and the
  retry policy is unchanged.
- **T7 (red, `test_phase_07a_portfolio_demo.py`)** the flag sets
  `PROXYLOOP_FAST_BACKEND` for every child and overrides an inherited value;
  `serve --fast-backend distilled` without a gateway refuses before Compose
  starts; a matching fake gateway passes the check; argparse refuses an
  unknown backend; the Makefile passes the flag.

Gated (PR-3 pattern: in-memory repository, process-local time-skipping
server, `skipif` on `PROXYLOOP_TEST_TEMPORAL_ADDRESS` alone, runs in
`phase05a-check`), same new file:

- **G1** the Workflow applies a consumer event whose Fast call hits a busy /
  timed-out fake gateway: the Update succeeds, the activity ran once
  (counting adapter), one decide request, `FAILED` trace, fallback line.
- **G2** a channel ingest Update under a local backend with the worker
  composition: accepted delivery, constant body, zero decide requests.

The per-file pin gains `tests/integration/test_fast_under_temporal.py: 3`
(G1 is parametrized busy | slow; 63 → 66); `phase05a-check` gains the file;
`docs/development.md` lists it.

## 4. Acceptance criteria

1. With `PROXYLOOP_FAST_BACKEND=distilled|untuned` and a matching gateway, the
   worker's Case commands use the local adapter; every applied consumer event
   yields one `assistant_message` (gate-passed line or fallback) and a Fast
   trace with the local identity.
2. The worker refuses to start exactly where the API does (D1), before any
   database connection.
3. Under Temporal the API starts with a local backend only when its gateway
   answers with the matching identity, and labels `adapter_mode`; `app.py`
   is unchanged.
4. A typed Fast failure never fails the activity: the command applies with
   the fallback and a `FAILED` trace, the activity runs once.
5. Channel ingest under a local backend is byte-identical to scripted: the
   constant body, no assistant event, no model call (D5-A).
6. `FAST_BACKEND=distilled make portfolio-demo` refuses before starting
   anything when the gateway is absent or mismatched, and passes one
   `PROXYLOOP_FAST_BACKEND` to every process; the default is unchanged.
7. `workflow.py`, the retry policy, and every committed `*-check` artifact are
   unchanged; no replay fixture is needed.
8. Docs: `docs/architecture.md` (Temporal Fast backend, D2–D5 limits),
   `docs/portfolio-demo.md` (the flag), `docs/development.md` (gated list and
   variables), `harness/context/audit-remediation-status.md` §0 PR-11 row,
   `harness/log/feat-pr11-fast-under-temporal.md`.

## 5. Gates

- Focused: the new tests, `test_local_fast_config.py`,
  `test_phase_07a_portfolio_demo.py`, `test_phase_06b1_workflow_worker.py`,
  `test_fast_failure_fallback.py`, `test_local_fast_adapter.py`.
- `make lint`, `make typecheck`, `make test`, `make preflight` (pin 66).
- DB lane (root, serially): `postgres-check` → `phase05a-check` (runs G1, G2)
  → `phase06b1-check`. The implementer does not run them or set
  `PROXYLOOP_TEST_*`.
- Independent `reviewer` (workflow/worker composition and a new network
  dependency in the worker).
- Manual (not in CI, needs PR-9b): `make local-fast-gateway BACKEND=distilled`,
  then `FAST_BACKEND=distilled make portfolio-demo`, Scene A and Scene B.

## 6. Owned files

- `runtime/services/workflow_worker/src/proxyloop_workflow_worker/{activities,worker}.py`,
  `runtime/services/workflow_worker/pyproject.toml`, `runtime/uv.lock`.
- `runtime/services/api/src/proxyloop_api/config.py`.
- `scripts/run_phase_07a_portfolio_demo.py`, `Makefile` (`portfolio-demo`
  target, `phase05a-check` list), `scripts/check_gated_skips.py` (pin).
- Tests: new `tests/integration/test_fast_under_temporal.py`;
  `test_local_fast_config.py` (the obsolete Temporal refusal test);
  `test_phase_07a_portfolio_demo.py`.
- Docs listed in AC 8.
- Not touched (escalate): `workflow.py`, `runtime.py` (PR-13), `app.py`
  (PR-12), `agent_core`, `local_fast` package, `contracts/`, every `ml/` file.

## 7. Risks and recorded limits

- **R1 label drift** (D2): the API labels from its own environment; a worker
  started by hand with another variable mislabels `/health`. Traces are the
  authority.
- **R2 queued Fast calls** (D3) can exceed the 30 s Next proxy for the second
  request on one Case; the command still applies.
- **R3 activity start-to-close** is 5 s above the Fast cap; a slow database
  plus a 25 s Fast call can still hit it (D4 (b)).
- **R4 two runtimes in one worker** (D5-A): distinct in-process lanes over one
  repository; safety rests on the Workflow's per-Case serialization and
  PostgreSQL CAS, as for API/worker today.
- **R5 unrun locally**: G1/G2 run only in the DB lane; the real model run
  needs PR-9b and is manual.
- Not claimed: latency, p95, capacity, or model quality under Temporal; any
  real channel; automatic fallback under load (decision 18).
