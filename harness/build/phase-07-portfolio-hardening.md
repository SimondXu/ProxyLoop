# Phase 07 — Portfolio Hardening

**Status**: **Frozen** by the root orchestrator on 2026-09-25, for build-plan
items PR-16 and PR-17 (`harness/context/build-plan-to-complete.md`). It was
drafted on 2026-09-24. The phase is not active yet: `harness/status.toml`
stays `idle` until the PR-16 implementation branch activates it (see "Harness
status transitions"). Implementation starts only after PR-14
(`feat/pr14-judge-seam`) merges, because Scene J asserts the Judge trace
count, and only when the root gives the go.

## Root decisions (2026-09-25)

The root accepted every recommendation in "Root decisions needed" below. Each
decision binds this contract.

1. **D1.** This contract covers both PR-16 and PR-17, with one phase gate at
   the end of PR-17.
2. **D2.** The launcher gains port overrides: `--runtime-port`/`--web-port`,
   with the Make variables `RUNTIME_PORT`/`WEB_PORT`. `apps/web/next.config.ts`
   gains a build-time override of the Runtime address. The defaults stay
   8000, 3000 and `http://127.0.0.1:8000`. Only loopback addresses are
   accepted, and a port that is in use makes the command fail closed. The
   launcher never picks another port on its own.
3. **D3.** The Scene J journey driver (`make portfolio-demo-journey`) and its
   committed, content-free artifact
   `data/evaluation/phase-07-demo-journey-scripted.json` are in scope.
4. **D4.** Browser verification uses scratch Python Playwright and is
   recorded in the log. It is not committed, and the repository gains no
   Playwright dependency and no browser in CI.
5. **D5.** `make ops-report` writes a committed, deterministic
   `data/evaluation/ops-report.json`. `make ops-report-check` joins
   `make test`. The report reads only committed files, plus the test counts
   from `pytest --collect-only`.
6. **D6.** The distilled and untuned split reports are not regenerated. They
   stay the pre-Judge observed artifacts (v1), labelled as such.
7. **D7.** The distilled scene is one manual run recorded in the log. It has
   no committed artifact and no reload. A run that the machine cannot host is
   reported as blocked, never as passed and never skipped silently.
8. **D8.** The final gate runs on PR-17's head once it is up to date with
   `main`. After the squash merge, the tree of `origin/main` must equal the
   tested tree. There is no separate gate-only PR.
9. **D9.** The docs, the narration and the completion claim describe the
   product's real order, as stated under "Objective", not the DoD's narrative
   order.

Also taken: decision 21 (PR-15 dropped; see the end of this contract).

## Authorization

Decision 16 (`harness/context/audit-remediation-decisions.md`) authorizes the
build to completion. Decision 18 places Phase 07 (option C) last. Decisions 17
and 18 bind here: every gate runs on scripted adapters, Slow stays scripted,
the Judge is scripted, and the distilled adapter is a Local Opt-in Candidate
that is only served locally. Decision 21 drops PR-15. Phase 07 therefore
depends on every other build-plan item: Wave 1, PR-7 through PR-13, and PR-14
(the Judge seam), which must merge before PR-16's implementation starts.

Phase 07A remains complete and unchanged as a bounded subphase. This phase
extends its demo. It does not reopen 07A's acceptance.

## Baseline and problem

On `main` at `eee47a3`, with PR-14 merged, every stage of the Definition of
done (DoD) item 2 journey exists, but only as separate pieces:

- stateless intake and the prefilled Draft Task Brief (PR-12);
- Fast dialogue through `fast-gate-v1`, with Assistant Messages in the Web
  (PR-8);
- the Agent Status Bar (PR-10);
- the Standing Proposal admitted by A-3 (PR-13) and the scripted Judge
  (PR-14);
- the opt-in local Fast Backend under Temporal (PR-9 and PR-11).

Each of these has its own tests and scratch Browser evidence. None of them has
a single reproducible run of the 07A demo that covers the whole journey. Most
of that evidence came from scratch launchers, because ports 8000 and 8765 were
held on the development machine. There is also no one place that reports the
gate counts, the split measurements, the parity headlines, and trace and log
health. PR-17 needs such a place to write the final reports from.

## Objective

1. The credential-free 07A demo runs the DoD item 2 journey end to end. The
   journey is: free-text intake → typed card → confirmed Case → per-turn Fast
   dialogue through the Disclosure Gate (scripted by default, distilled
   opt-in) → Status Bar → Slow proposal → advisory Judge → approval →
   at-most-once execution → Evidence → verified receipt. The 07A recovery and
   mailbox scenes still pass unchanged.
2. `make ops-report` gives one offline, deterministic summary of the gates and
   the local measurements.
3. PR-17 writes the reports and runs the fresh-clone reproduction. The phase
   gate then closes the build within the authorized limits.

**Honest order of the journey.** The DoD lists the stages as a narrative. In
the product they happen in this order, and the demo, the docs and the
narration must describe this order:

1. Intake produces the card, and the consumer confirms it.
2. `POST /cases` creates the Case. The fictional Offer arrives, Slow proposes
   (the Standing Proposal), and the Judge reviews that result, all within the
   create command.
3. The consumer's confirmation turn produces one Assistant Message and opens
   the Approval Request from the Standing Proposal.
4. The consumer approves, and the Runtime executes once.
5. The receipt is shown.

The Judge is not visible in the Web. It appears only as a `role=judge` Model
Trace and in the split report's call counts. With the default scripted Slow,
the scripted Judge always accepts (PR-14 K1): its revise-and-retry path is
exercised only in tests.

## Frozen scope

PR-16 (implementation) may change only these:

- `scripts/run_phase_07a_portfolio_demo.py`: a new `journey` subcommand, and
  the port overrides if root decision D2 accepts them.
- `apps/web/next.config.ts`: only for D2, to set a build-time loopback Runtime
  origin whose default stays `http://127.0.0.1:8000`.
- A new `scripts/run_ops_report.py`.
- `Makefile`: `portfolio-demo-journey`, `ops-report` and `ops-report-check`
  (the check joins `test:`), the new script added to `PYTHON_PATHS`, and the
  port variables if D2 accepts them.
- New committed artifacts: `data/evaluation/ops-report.json` and
  `data/evaluation/phase-07-demo-journey-scripted.json`.
- Tests: `tests/integration/test_phase_07a_portfolio_demo.py` (extended) and
  a new `tests/integration/test_ops_report.py`.
- Docs: `docs/portfolio-demo.md`, the demo section of `README.md`,
  `docs/development.md` (the ops-report entry), and the Phase 07 row of
  `PLANS.md`.
- `harness/status.toml`, and a new log at `harness/log/phase-07-portfolio-hardening.md`.

PR-16 must not change:

- `runtime.py`, `app.py`, `workflow.py`, `postgres_repository.py` or
  `conversation-workspace.tsx`;
- any canonical contract or schema, or the evaluator;
- the Disclosure Gate, the Judge, or the intake parser;
- the browser projection;
- any committed `*-check` artifact, which must stay byte-identical;
- the gated-skip pin.

If a scene cannot pass without one of these changes, stop and escalate.

PR-17 (reports) owns the build-plan PR-17 row. Its files are
`docs/ml-evidence.md`, the architecture reconciliation (A-7f), the
observed-versus-proposed README, the limitations and negative results, the
cost figures, the fresh-clone reproduction record, `PLANS.md`,
`harness/status.toml` back to `idle`, and the phase log's gate section. PR-17
changes no code.

## Demo scenes

Every scene runs on the documented commands with no credentials and no
network other than loopback. The fixed Case id (`SCRIPTED_CASE_ID`) means
that Scene A, Scene J and Scene B each need fresh demo state. The sequence is
therefore: start the stack, run the scene, run `make portfolio-demo-stop`, run
`make portfolio-demo-reset`, then start the stack again before the next scene.

The Status Bar strings below come from `apps/web/lib/status-block.ts`. The
revision numbers 2, 4 and 6 come from the PR-10 and PR-12 reference runs.
PR-13 and PR-14 claim that state is unchanged, so those revisions are
expected. A different revision is a finding: explain it in the log. It is not
an automatic failure.

### Scene 0: startup

- **Commands:** `make portfolio-demo`. With D2, the Makefile variables
  `RUNTIME_PORT=` and `WEB_PORT=` can be added. The defaults are 8000 and 3000.
- **Expected:**
  - The banner lists the Web URL, the Runtime readiness URL, the Temporal
    address, the log directory, the stop command, the scene order, and the
    Fast backend with its label.
  - Readiness reports `adapter_mode` `scripted`, `storage_mode` `postgres`,
    and `orchestration_mode` `temporal`.
  - An occupied port makes the command fail closed and name the port. It
    never picks another port on its own.
- **Evidence:** the banner text and the readiness JSON, recorded in the log.
- **Verified by:** the existing 07A supervisor tests, plus new tests for the
  port override if D2 is accepted. Script.

### Scene A: Web journey (scripted Fast, the default)

- **Commands:** Scene 0, then use the Web at the printed URL.
  1. Send one message: "My mobile bill is $92 and I want to get it under $75.
     Keep my hotspot. (zebra-7731)".
  2. Answer the financing question: "no change".
  3. Click Create fictional Case.
  4. Click "Keep both unchanged and continue".
  5. Click "Approve exact terms".
  6. Reload the page.
- **Expected:**
  - **Card.** The card shows three rows as "Read from your message":
    "$92.00", "$75.00", and hotspot "Required". Financing shows "Missing",
    and Create is disabled until the answer arrives. The financing row then
    reads "Confirmed · unchanged".
  - **After create.** The Status Bar reads "Planning from your confirmed
    goal.", as of Case revision 2. The phase is Strategy, approval is None,
    and execution is Not started. The Offer row shows the Runtime's offer.
  - **After confirm.** One Assistant Message appears: "Thanks. I'm reviewing
    the fictional offer against your constraints now.", followed by "ProxyLoop
    AI · automated message — it cannot accept, sign, or change anything
    without your approval." The Status Bar reads "Waiting for your approval of
    the exact terms.", as of revision 4. Approval reads "Pending · expires
    <t>", and <t> equals the expiry on the approval card.
  - **After approve.** The Status Bar reads "Done: the Runtime verified
    completion against Provider Evidence.", as of revision 6. It shows
    "Executed 1 time" and "Verified complete · 1 matching Evidence ID ·
    receipt shown", and the receipt artifact is visible.
  - **After reload.** The Status Bar rows are identical, and the same receipt
    is shown.
  - **Console and layout.** The console has no errors or warnings. At 375x812
    there is no horizontal overflow. The context rail, and with it the Status
    Bar, is hidden below 1120 px; that is a recorded PR-10 limit.
  - **Marker.** The marker `zebra-7731` is absent from `localStorage`, from
    the proposal response, and from the Runtime, worker and Web logs.
- **Evidence:** the screenshots and a `result.json` in the implementer's
  scratch directory (not committed). The log records the Status Bar text at
  each stage, the order of Runtime calls, the console state and the marker
  checks.
- **Verified by:** Browser. Use headless Chromium through scratch Python
  Playwright (the PR-8b, PR-10 and PR-12 method) at 1440x1000 and at 375x812,
  against the real `make portfolio-demo` stack (D4). The vitest cases already
  cover the Status Bar and the card offline.

### Scene J: scripted journey driver (new, machine-checked)

- **Commands:** on fresh state, `make portfolio-demo-journey`. It runs from a
  second terminal while Scene 0 is running.
- **What it does.** It uses the same HTTP routes the Web uses, in the order
  above:
  1. `POST /intake/proposals` with the marker message.
  2. Build the `CreateCaseRequest` from the returned keys, plus the financing
     answer.
  3. `POST /cases`.
  4. `POST …/events` with the Web's `CONFIRMATION_EVENT` text.
  5. `POST …/approvals/{id}` with the pins.
  6. `POST …/approvals/{id}` again, as an exact replay with the same
     `Idempotency-Key`.
  7. A final `GET`.
- **What it asserts:**
  - **Intake.** Three keys are read and financing is asked for. The proposal
    response does not echo the text.
  - **Events.** The visible events are `provider_offer`, then
    `consumer_message`, then `assistant_message`. The Assistant Message is the
    first scripted dialogue line.
  - **Approval and execution.** An approval is pending after the confirmation.
    After the approval, `execution_count == 1`, and the replayed approval
    leaves `execution_count == 1` and the revision unchanged.
  - **Completion.** The Web receipt predicate (`completionHasVerifiedEvidence`)
    holds, restated in Python over the same payload fields: completion
    `complete`, `execution_count == 1`, and every `evidence_ids` entry present
    in `evidence`.
  - **Trace log.** It reads the Model Trace log through the existing
    `PostgresCaseRepository.list_model_traces` seam, as Scene B reads the
    channel state. Expected, from the split `demo_path` and PR-14 §5: `slow`
    {succeeded: 1}, `judge` {succeeded: 1}, `fast` {succeeded: 1}, and no
    judge-triggered retry.
  - **Logs.** Every journey request has one JSON operation record in the
    Runtime log, and each has failure category `none`. The marker is absent
    from the Runtime, worker and Web logs.
- **Evidence:**
  - Printed pass lines.
  - With `--write-evidence`, a committed, content-free
    `data/evaluation/phase-07-demo-journey-scripted.json`. It holds the
    backend and `adapter_mode`, the readiness modes, the sequence of revisions
    and event types, whether the line came from the model or the fallback,
    the trace counts by role and result, the execution count before and after
    the replay, the completion decision, the receipt predicate, the operation
    record counts by route and failure category, and the result of the marker
    scan.
  - It carries no ids, timestamps, latencies, text or host identity, so a
    rerun on scripted produces the same bytes.
- **Verified by:** script (D3). Unit tests cover the assertions against fixture
  payloads. The live run is recorded in the log.

### Scene A-D: opt-in distilled Fast (manual)

- **Commands:**
  1. Run `make local-fast-gateway BACKEND=distilled LOCAL_FAST_PORT=<free>` in
     its own terminal. It needs Apple silicon, the cached base snapshot, and
     about 17 GB of memory.
  2. Run
     `PROXYLOOP_FAST_GATEWAY_URL=http://127.0.0.1:<free> FAST_BACKEND=distilled make portfolio-demo`.
  3. Repeat Scene A steps 1 to 5, without the reload.
  4. Optionally, run `make portfolio-demo-journey` without `--write-evidence`.
- **Expected:**
  - The banner prints the backend `distilled` and the label "local opt-in
    candidate".
  - After confirm, the Assistant Message is expected to be the fallback line
    "I am checking that and will update you.", with the same label. The Fast
    trace names the local model and the gateway identity, with result
    `rejected` (gate) or `failed` (a timeout up to 25 s).
  - Approval, one execution and the verified receipt are identical to
    Scene A, because Fast cannot change routing.
  - A model line that passes the gate is a new observation to record. It is
    not a failure.
- **Known limit, not re-tested:** after a reload, the Web shows "Runtime state
  not verified". The Web restores a Case only when `adapter_mode` is
  `scripted` (PR-9b).
- **Evidence:** the log records the banner, the delivered-line class, the
  trace result and model name, and the Case end state. Nothing is committed
  (D7).
- **Verified by:** manual run with a Browser, one recorded run. The committed
  measurement for this backend is the local split report, not this run.

### Scene B: synthetic `local_mailbox` (unchanged from 07A)

- **Commands:** on fresh state, `make portfolio-demo-channel`.
- **Expected:**
  - one server-correlated inbox identity;
  - one outbox delivery identity;
  - exact duplicate deduplication;
  - one accepted synthetic Provider reference;
  - one delivered callback and receipt;
  - two authoritative channel Evidence records;
  - a browser projection with no channel material.
  Channel commands keep the scripted Fast, so the outbound body stays
  `BOUNDED_FAST_STATUS_TEXT` on every backend.
- **Evidence:** the pass lines, recorded in the log.
- **Verified by:** the existing script.

### Scene R: recovery (unchanged from 07A)

- **Commands:** `make portfolio-demo-recovery`, with the demo's Temporal
  running.
- **Expected:** the message "Recovery check passed: the accepted Phase 06B1
  lost-response retry preserved one logical local delivery." Only the demo
  project's `postgres-test` service is started and stopped.
- **Evidence:** the pass line, recorded in the log.
- **Verified by:** script. It runs the DB-backed test named in
  `run_recovery_check`.

### Stop and reset

- `make portfolio-demo-stop` preserves data.
- `make portfolio-demo-reset` prints its scope and removes only
  `proxyloop-portfolio-demo_postgres-data`.
- The scratch launchers and throwaway Compose projects used by earlier PRs are
  not an accepted method for recording Scenes 0, A, J, B or R in this phase.

## `make ops-report`

- **Command:** `make ops-report` runs `scripts/run_ops_report.py --write`,
  which prints a text summary and writes `data/evaluation/ops-report.json`.
  `make ops-report-check` re-derives the report and fails on drift, and it
  joins `make test`.
- **It needs no credentials and no network.** It opens no sockets, starts no
  container and calls no model. A test runs `--check` with socket connections
  blocked.
- **It reads only committed repository files:**
  - `Makefile`;
  - `scripts/check_gated_skips.py`;
  - the three `data/evaluation/fast-slow-split-*.json` reports;
  - `data/experiments/phase-03c/local-parity/parity-report.json` (M1);
  - `data/experiments/phase-03c/local-parity/product-path-report.json` (M2);
  - `data/evaluation/phase-07-demo-journey-scripted.json`.
  It records each input's path and SHA-256.
- **Optional, printed only.** If `.gate/runtime-junit.xml` exists, it prints
  the observed gated-skip counts next to the pin. These counts are never
  written to the JSON, because the file is git-ignored and local.

The report contains five sections.

1. **Gates.**
   - The `*-check` targets that `make test` runs, as names and a count parsed
     from the `test:` prerequisites.
   - The three real-dependency targets from `REAL_DEPENDENCY_TARGETS`.
   - For each of those targets, the test files it runs, parsed from the
     Makefile, and the number of collected test items. The count comes from
     `pytest --collect-only -q` and needs no DB or Temporal.
   - The report says in plain words that pass counts come only from the
     serial gate run recorded in the phase log.
2. **Gated-skip pin.**
   - `EXPECTED_GATED_SKIPS_PER_FILE` per file, and its total (66 on
     `eee47a3`; PR-14 adds none).
   - A consistency flag that is true when every pinned file belongs to one of
     the three gates.
3. **Split reports.** For each backend (scripted, distilled, untuned) and each
   scenario (`demo_path`, `dialogue_path`):
   - turns and dialogue turns;
   - `fast_model_line_rate` and `gate_fallback_rate`;
   - `fallback_cause_counts` and `calls_by_role_and_result`;
   - unapplied calls, the top reject codes, the schema version, the label and
     the `claim_boundary`.
   - Scripted is `fast-slow-split-v2` and includes the Judge call and retry
     counts, but no verdict distribution (decision 7 and PR-14 Q7).
   - Distilled and untuned are marked "pre-Judge observed artifact (v1)" and
     are never compared on Judge fields (D6).
   - Their `measured` latency block is copied with its boundary text and
     summarized nowhere else.
4. **Parity headlines.**
   - **M1:** the verdict ("stack parity held"), distilled local act agreement
     0.983, and cloud concordance 1.000.
   - **M2**, for each arm, with the 95% interval the report carries:
     - delivered lines: distilled 0/240, untuned 8/240;
     - act agreement: distilled 157/240 (0.654), untuned 97/240 against the
       true oracle;
     - the divergence classes.
   - The Local Opt-in Candidate label is stated, as are the decision-18 caveats
     E1 to E5 plus the four Phase 03C caveats, and the result role
     `local_measurement`.
5. **Trace and log health.**
   - **From the split reports**, which come from the in-process trace log, for
     each backend:
     - every dialogue turn delivered exactly one line (model or fallback);
     - the count of Fast `failed` and `rejected` results;
     - on scripted v2, Judge calls equal admitted Slow results and there are
       zero retries.
   - **From the journey artifact:**
     - the PostgreSQL trace counts by role and result;
     - the execution count stayed 1 after the replay;
     - operation records were complete and all had failure category `none`;
     - the marker was absent from the logs.
   - Every invariant is a boolean that shows its inputs, so a false value is
     visible and is never hidden.

The report ends with a **Not measured / not done** block: every item in
"Non-goals and hard limits" below that concerns a measurement.

What gets committed: `scripts/run_ops_report.py`, its test, the Make targets,
and `data/evaluation/ops-report.json`. Future PRs that change an input must
regenerate the report, because the check pins it.

## Acceptance criteria

Mapped to the build-plan Definition of done.

| DoD | Criterion | Verified by | PR |
|---|---|---|---|
| 1 | Every Blocking and Important finding in `harness/context/audit-remediation-status.md`, including R-12, R-16, R-17 and R-18, is closed with a merged PR. Every remaining Minor is either closed or listed as a recorded limit with its reason. This includes R-11b and B1-9b (decision 21), R-6 if still deferred, and D2-7, D2-8, D2-9, D3-7, D3-8 and D3-9. PR-16 and PR-17 reopen nothing. | Root inspection; a closure table in the phase log | PR-17 |
| 2a | Scene 0 starts the stack from the documented command, including any D2 overrides, and fails closed on an occupied port. | Script and tests | PR-16 |
| 2b | Scene A passes at desktop and mobile widths with the expected text above, a clean console and the marker absent. | Browser (Playwright), recorded | PR-16 |
| 2c | Scene J passes on fresh state. The committed journey artifact equals a rerun byte for byte. | Script; `ops-report-check` | PR-16 |
| 2d | Scene A-D has one recorded manual run. If the machine cannot host the gateway, report it as blocked. It is never recorded as passed. | Manual, recorded | PR-16 |
| 2e | Scenes B and R pass unchanged on fresh state after Scene A and Scene J. | Script | PR-16 |
| 3 | The three split reports and the M1 and M2 reports are committed, and their `--check` targets pass in `make test`. `make ops-report` surfaces them with their labels and boundaries, and the distilled and untuned reports are marked pre-Judge. | `make test`, `make ops-report-check` | PR-16 |
| 4 | The contract, the scenes, `make ops-report` and the journey artifact exist (PR-16). The PR-17 documents exist. A reviewer reproduces the simulator benchmark from a fresh clone, following only the README: `make benchmark-check` passes, a regeneration of `data/manifests/phase-01b-*.json` leaves `git diff --exit-code` clean, and the log records the result. PR-17 names the exact commands. | Fresh clone, recorded | PR-16, PR-17 |
| 5 | The phase-gate procedure below passes. | Gate record | PR-17 |
| 6 | `docs/portfolio-demo.md`, the README and the ops-report "Not measured / not done" block state every item under "Non-goals and hard limits" as not done, and none of them is described as done anywhere. | Review | PR-16, PR-17 |
| — | No file outside "Frozen scope" changes. Every committed `*-check` artifact is byte-identical, and the gated-skip pin is unchanged. | Diff review; `make preflight` | PR-16 |
| — | Each PR has an independent `reviewer` pass recorded under `harness/code_review/`, with no unresolved Blocking or Important finding. Minors are applied or recorded. | Review artifact | PR-16, PR-17 |

### Phase-gate procedure

1. Merge PR-16 after `make preflight`, the three DB gates and the scene runs
   pass on its head once it is up to date with `origin/main`, and after CI and
   independent review.
2. Bring PR-17 up to date with `origin/main` with no other PR in flight. On
   its final head, in one fresh worktree, after
   `pnpm install --frozen-lockfile`, run these one at a time:
   1. `make preflight`, which prints and enforces the gated-skip pin;
   2. `make postgres-check`;
   3. `make phase05a-check`;
   4. `make phase06b1-check`.

   Use the Compose `postgres-test` profile and the `temporal` service, and set
   the variables on the command line only. Record the exit status and the
   pass counts. The demo stack must be stopped during the gates.
3. CI (phase-gate and GitGuardian) is green on the final PR-17 head, and the
   independent review is recorded.
4. Squash merge. Then confirm that `git rev-parse origin/main^{tree}` equals
   the tested head's tree, so the gated tree is the final `main` (D8). If it
   differs, rerun step 2 on `main`.
5. The root records the gate in the phase log and checks the final diff and
   the evidence. That completes the gate. Nothing after it starts another
   phase.

## Non-goals and hard limits (stated as not done)

- Production of any kind. This includes production serving of the distilled
  adapter, real-model load, p95, capacity, concurrency, OOM, automatic
  fallback under load, production exactly-once effects, production monitoring
  and production readiness.
- Deployment, hosting and release.
- Phase 06B2 and every real channel: real Providers, Gmail and OAuth, e-mail,
  MCP, SMS, Voice (LiveKit, SIP, telephony), and any credential.
- V0 (a hosted frontier model in both slots), frontier-as-Fast, and a
  second-family Judge. These are "not measured (budget)" under decision 17.
- A model Judge, and any Judge verdict distribution in a metric.
- Any further training, data expansion, rerun or promotion. The Phase 03B
  `NO_GO_STOP_PHASE03B` decision is unchanged.
- Narrow contracts 1.2 (PR-15, dropped by decision 21).
- The build-plan "Do not do" list: D3-5, D3-6, D1-10 to D1-12, D2-7 to D2-9,
  D3-7 to D3-9, A-9b, and `SlowWorkRequest.revision_feedback`.
- A Web free-text turn after Case creation, Web exposure of channels or the
  Judge, a Web restore of a Case on a local backend after reload, and any UI
  redesign.
- Hosted spend of any kind. No budget is recorded.

## Harness status transitions

| When | `product_phase_state` | `active_product_phase` | `active_contract` | `next_phase_authorized` |
|---|---|---|---|---|
| This contract PR | `idle`, unchanged | `""` | `""` | `false` |
| First commit of the PR-16 implementation branch | `in_progress` | `"07"` | `"harness/build/phase-07-portfolio-hardening.md"` | `false` |
| Between PR-16's merge and PR-17 | `in_progress` | `"07"` | same | `false` |
| A hard limit or an unresolvable finding is hit | `blocked`, with the reason in `boundaries.summary` | `"07"` | same | `false` |
| Final commit of PR-17, at the gate | `idle` | `""` | `""` | `false` |

- Every transition also updates `updated_at` and `boundaries.summary`.
- The `inactive` list keeps every entry. The final summary states that
  Phase 07 closed within the authorized limits, and it lists what is not done.
- `scripts/validate_layout.py` accepts these values. A non-idle state requires
  the contract file to exist.

## Ownership and verification

- The root owns this contract, the decisions below, the status transitions,
  the acceptance semantics, the final diff and evidence review, the gate, and
  every completion claim.
- One `implementer` owns PR-16 inside "Frozen scope". It must not change this
  contract, the hot files, any contract or evaluator, the gate or the Judge.
  It must not use credentials or start another phase.
- PR-17 is a separate `implementer` task, docs only.
- One fresh `reviewer` reviews each PR once its diff is stable.
- Focused checks while working:
  - `make lint`, `make typecheck`;
  - `pytest tests/integration/test_phase_07a_portfolio_demo.py tests/integration/test_ops_report.py`;
  - `make ops-report-check`;
  - `make web-check`, only if D2 touches `next.config.ts`.
- Then run `make preflight` once on the stable diff, and the DB lane serially
  when the root hands it out.

## Risks

| # | Risk | Mitigation |
|---|---|---|
| K1 | **Port collisions on this machine.** Ports 8000 and 8765 were held by unrelated processes. The launcher hard-codes 8000 and 3000, and the Next rewrite hard-codes `127.0.0.1:8000`. PR-8b, PR-10 and PR-12 therefore recorded Browser evidence from scratch launchers and throwaway Compose projects (`proxyloop-pr10-browser`, `proxyloop-pr12-browser`), not from `make portfolio-demo`. | D2 adds explicit, fail-closed overrides whose defaults are unchanged. Never stop an unrelated process. Use `LOCAL_FAST_PORT` together with `PROXYLOOP_FAST_GATEWAY_URL` for the gateway. The scenes must be recorded from the documented commands. |
| K2 | **The fixed Case id couples the scenes.** Scenes A, J and B collide on `SCRIPTED_CASE_ID`. | Stop and reset between scenes, as documented. Scene J refuses state that is not fresh, as Scene B does. |
| K3 | **The Judge is invisible and never revises in the product** (PR-14 K1). | Describe it as "advisory, scripted, accepts on the default path". Show it through traces and counts only, and claim no quality effect. |
| K4 | **The DoD narrative order differs from the product order.** | The docs and the narration use the honest order (see "Objective"). The root confirms the wording (D9). |
| K5 | **The local reports predate the Judge.** | Label them. Never compare them on Judge fields (D6). |
| K6 | **The distilled demo depends on the machine**: about 17 GB of memory, the cached snapshot, and a Fast call of up to 25 s (the M2 p50 was 23.9 s, and 64 of 200 calls exceeded 25 s). | The fallback line is the expected outcome, and a timeout is recorded as `failed`, not as a fault. If the lane cannot run, report it as blocked. |
| K7 | **`ops-report-check` in `make test` couples every future change to an input.** | That coupling is intended, and it matches the existing `*-check` pattern. The failure message names `make ops-report`. |
| K8 | **The DB lane is shared** (`proxyloop_test`, fixed Case ids). The recovery scene and the gates both use Compose Postgres. | Keep one lane and run everything serially. Stop the demo during the gates, and never run Scene R at the same time as a gate. |
| K9 | **PR-14 is still in review.** The Judge expectations here follow its frozen spec. | If the merged PR-14 differs (trace counts, split v2 fields), the merged behaviour wins. Escalate to the root before adjusting the expectations. |
| K10 | **Content leakage through new evidence.** | The journey artifact and the ops report are content-free by construction, and a test asserts that neither contains the marker, ids or timestamps. |

## Root decisions needed

Each decision below carries the drafter's recommendation. All nine were
accepted on 2026-09-25; see "Root decisions (2026-09-25)" at the top.

| # | Decision | Recommendation |
|---|---|---|
| D1 | Whether this contract spans PR-16 and PR-17, with one gate at the end of PR-17. | **Yes.** This matches the build plan, where PR-17 returns the status to `idle`, and DoD items 3 and 4 need PR-17. |
| D2 | Whether to add port overrides: `--runtime-port`/`--web-port` (Make `RUNTIME_PORT`/`WEB_PORT`), plus a build-time loopback Runtime origin in `next.config.ts`. | **Yes.** DoD 2 evidence must come from the documented command, and 8000 is held here. Keep the defaults, fail closed, and accept loopback only. The alternative is to record from a scratch launcher again, which is weaker evidence. |
| D3 | Whether to add the Scene J journey driver and its committed, content-free artifact. | **Yes.** It is the only machine check of the whole journey that a reviewer can rerun without Playwright. |
| D4 | How Browser verification runs. | **Use scratch Python Playwright, recorded in the log and not committed.** Add no Playwright dependency or CI browser. This follows the PR-8b, PR-10 and PR-12 precedent. |
| D5 | The ops-report shape. | **A committed deterministic JSON, with `ops-report-check` in `make test`, reading only committed files plus collect-only counts.** The alternative, print-only output, leaves PR-17 citing unpinned numbers. |
| D6 | Whether to regenerate the distilled and untuned split reports after PR-14. | **No.** Keep them as pre-Judge observed artifacts (PR-14 root answer 8). The scripted Judge never revises, so regenerating them adds no Judge claim. |
| D7 | What the distilled scene records. | **One recorded manual run in the log, with no committed artifact and no reload.** It is required for DoD 2, and it may be reported as blocked, never skipped silently. |
| D8 | The final-main gate. | **Run the gate on PR-17's up-to-date head and prove tree identity after the squash.** The alternative is a separate gate-only PR after PR-17, which adds a cycle and gives no extra assurance. |
| D9 | The wording of DoD 2 in the docs and the completion claim. | **Use the honest product order in the objective.** The root owns this completion wording. |

Already taken: **decision 21**. PR-15 (narrow contracts 1.2) is dropped, and
R-11b and B1-9b stay recorded limits. The reason: YAGNI; decision 19 made it
optional and droppable; no DoD item needs it. It is recorded in
`harness/context/audit-remediation-decisions.md`.

## Stop conditions

The implementer stops and reports to the root, without working around the
problem, if any of these holds:

- a scene needs a change outside "Frozen scope", a hot file, a contract, the
  gate, the Judge or the projection;
- a committed `*-check` artifact or the gated-skip pin would move;
- the merged PR-14 differs from the Judge expectations here;
- a port or dependency conflict can be solved only by touching an unrelated
  process;
- any step needs credentials, hosted spend, a real external channel,
  deployment, training, or destructive work outside the demo's named Compose
  resources.
