# Docs log: P2 reconciliation batch (A-7d, A-7e, A-7g, G-1, check-target docs)

Spec: `harness/context/docs-p2-reconciliation-preflight.md`. Programme:
`harness/context/audit-remediation-status.md` §4. Branch
`docs/p2-reconciliation` from `origin/main` @ `5bedcce`.

## What changed, and what each statement was checked against

- **A-7d, revision vocabulary** (`docs/architecture.md`, `CONTEXT.md`).
  StrategyPacket bullets now read `revision`, `case_revision`,
  `fact_ledger_revision`. Checked: `contracts.py` `StrategyPacket` fields
  (`case_revision`, `fact_ledger_revision`); `revision: Revision` on
  `VersionedContract`, `VersionedContract10Or11`, and `VersionedContract11`
  (`_base.py`, `Revision = Annotated[int, Field(ge=1)]`). "Optimistic versions"
  is replaced by `schema_version` plus `revision`, following `CONTEXT.md`
  (Contract Schema Version vs Entity Revision). The optimistic use is backed by
  "revision compare-and-swap" (`architecture.md` §High-Level Shape). The
  `Constraint` and `ApprovalRequest` bullets and the Observability list say
  revision. Checked: `ApprovalRequest` has `case_revision`,
  `action_intent_revision`, `strategy_revision`, `constraint_set_revision`,
  `offer_ref.offer_revision`, and `material_terms_hash`. In `CONTEXT.md`, the
  Approval Request definition now says "Case revision" instead of "Case
  version". This follows its own Entity Revision term and changes no other
  wording.
- **A-7e, Case owner** (`docs/architecture.md`). `Case` now lists
  `consumer_id`, phase, revision, constraint-set revision, timestamps, and the
  embedded goal, constraints, delegated authority, and optional bill snapshot.
  Checked: `contracts.py` `class Case` fields. There is no owner field.
- **A-7g, contract count** (`docs/architecture.md`). The section names
  `CANONICAL_MODELS` as the registry: 25 types at contract set 1.1, frozen by
  `test_canonical_model_registry_has_exact_phase_surface`
  (`runtime/packages/contracts/tests/test_contracts.py`). The 03A1 paragraph
  now names `VisibleCaseEvent`, `FastModelView`, `SlowReasonerView`,
  `ModelInputPins`, and `PlanningBasis`. A new sentence names the 1.1
  additions `ExecutionClaim` and `CompletionReceipt`. Checked: the
  `CANONICAL_MODELS` tuple (25 entries), the test's set (25 names), and
  `git log -S` (`VisibleCaseEvent` since `e08c9b6`, 03A1-H #8;
  `ExecutionClaim` since `69924fe`, #65).
- **G-1, stronger form** (`CLAUDE.md` verification section and
  `docs/development.md` "Local gate and real-dependency gates"). Checked:
  - `Makefile`: `preflight: validate lock-check` plus `compileall` and
    `docker compose config --quiet`, with
    `validate: format-check lint typecheck test check-layout web-check`.
  - `unit-test` collects `tests/integration`.
  - The recipes of `postgres-check`, `phase05a-check`, and `phase06b1-check`
    fail on a missing variable and list their files.
  - The skip sites (`pytest.skip`) are in exactly four files: 04c, 05a
    case_runtime, 05a temporal_workflow, and 06b1 temporal (grep
    `PROXYLOOP_TEST_`). The other gate files carry no skip.
  - The `proxyloop_test` assertion is in each fixture. `TRUNCATE` runs in the
    fixtures and `_truncate` helpers.
  - Fixed ids: `CASE_ID` (04c); `SCRIPTED_CASE_ID` and fixed command UUIDs
    (05a, 06b1).
  - `compose.yaml` `postgres-test` uses port 55432. CI uses
    `127.0.0.1:7233`.
  - The concurrent-run failure mode (`case_not_found`, `state_invalid`) is
    recorded in `harness/log/fix-capability-manifest-lifetime.md`.

  A run of the eight gate files with no `PROXYLOOP_TEST_*` set gave
  `51 passed, 46 skipped`. `make test` below gave `46 skipped` in the Runtime
  suite. That count is deliberately not written into the docs. No Makefile
  change.
- **`*-check` descriptions** (`docs/development.md`). Each line is checked
  against the script's check function:
  - `generate_contracts.py check_committed`: temp-dir render, byte compare.
  - `run_phase_01b_benchmark.py check_artifacts`: re-runs scenarios, byte
    compare, `ceiling_gate_failed`.
  - `run_negotiation_ceiling.py check_report`: drift plus gate.
  - `run_phase_02_data_pilot.py check_artifacts`: drift plus
    `automated_audit_status`.
  - `run_phase_03a1_harness.py check_harness`: builds twice, three artifact
    drifts, ceiling gate.
  - `artifacts.py check_baseline_artifacts(_historical)`: `replay=False` skips
    the episode-fingerprint binding and `replay_report`.
  - `artifacts_v2.py check_r2_artifacts`: fixture regeneration, r2 report
    integrity with no replay when r3 exists, r3 `replay_report_v2`,
    `_check_r3_source_binding`.
  - `hosted_rescore.py check_r4_integrity`, `execution_contract_state`
    (reported only), and `check_rescored_artifact` (byte-equal to
    `derive_rescored_r4`). `hosted-rescore --write` writes
    `R4_RESCORED_REPORT_PATH`.
  - `run_phase_03a1_validity_smoke.py _check_report`: `source_r4_sha256`,
    then `check_validity_smoke_replay`.
  - `phase03b_readiness.check_packet_artifact`: regenerate and compare.
  - `phase03b_experiment.check_phase03b_artifacts`: re-derive with the
    Phase 02 provenance fields as recorded, `manifest_fingerprint_unbound`.
  - `rescore_phase03c_heldout.py --check`: byte compare, exit 1 on any cloud
    disagreement. The Makefile exits 0 when `heldout-report.json` is absent.
  - `run_phase_04d_control_plane_profile.py --check`: the three asserts.

  The `make validate` and `make test` lines are corrected too (they omitted
  `web-check` and the artifact checks).
- **Test pin** (`tests/contract/test_phase_03a1_hosted_rerun_architecture.py`).
  The substring assertion `"scripts.run_phase_03a1_hosted_rerun --check" in
  makefile` is gone. It also matched `--check-sources` and a Makefile comment.
  In its place the test pins:
  - the exact line `hosted-rerun-check: hosted-rescore-check`;
  - the recipe line under `hosted-rescore-check:` (tokenised);
  - `hosted-rerun-check` as a token of the `test:` prerequisites.

## Red and green for the test pin

The old and new assertions were run as a script against altered copies of the
Makefile text. With the dependency dropped (`hosted-rerun-check:` alone), the
old assertions still passed (`True`) and the new ones failed. The new ones
also fail when the rescore recipe changes to `hosted_rerun --check` and when
the target is removed from `test:`. On the real Makefile they pass.

## Verification (this worktree, no `PROXYLOOP_TEST_*` set)

- Touched test plus `test_phase_03a0_architecture.py` (reads `CONTEXT.md`):
  14 passed.
- `make lint`: exit 0. `make format-check`: exit 0.
- `make preflight-fast`: exit 0.
- `make test`: exit 0. Runtime `1127 passed, 46 skipped`; ML
  `390 passed, 1 skipped`. The first run failed two
  `test_generated_contracts.py` tests because this fresh worktree had no
  `node_modules` (`pnpm exec tsc` exit 254). After
  `pnpm install --frozen-lockfile --ignore-scripts` the run was green. That
  was environment, not the diff. Observed output: negotiation gate passed;
  r1 `intact (not replayed)` with `harness episodes: drifted_since_r1`; r4
  execution contract `unchanged` and rescored artifact equal to the
  derivation; Phase 03C `cloud disagreements: 0` for held-out and dev.
- `make baselines-check`: exit 2 as documented. The failures are the episode
  fingerprint, Qwen/frontier prompt mismatches, and three "recorded Slow
  output does not recompile" errors. The docs give the cause stated in the
  Makefile comment (r1 bound to the Harness episodes of its time). This change
  did not attribute each message independently.

Not run: `make typecheck` (no Python source changed besides one test), `make
web-check`, `make preflight`, and the real-dependency gates (`postgres-check`,
`phase05a-check`, `phase06b1-check`, no `PROXYLOOP_TEST_*` by instruction).

## Update from `origin/main` @ `f989613` (#70, #71)

Merged, not rebased; no conflicts. The merge touched no file this branch
changes, nor `Makefile`, `contracts/`, or `runtime/packages/contracts`.
Re-checked after the merge: `CANONICAL_MODELS` still holds 25 entries, and
`PROXYLOOP_TEST_` with `pytest.skip` still appears in exactly the four files
named in the docs.

Verification (no `PROXYLOOP_TEST_*` set):

- `make format-check lint typecheck`: exit 0.
- `make preflight-fast`: exit 0.
- `make test`: exit 0. Runtime `1158 passed, 46 skipped`; ML
  `390 passed, 1 skipped`. `git status --short data/` empty.

Not run: `make web-check`, `make preflight`, and the real-dependency gates.
