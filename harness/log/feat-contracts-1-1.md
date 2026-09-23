# Feat log: canonical contract set 1.1, contracts only (PR1)

Spec: `harness/context/feat-contracts-1-1-preflight.md`. Design and root
decisions: `harness/context/schema-1.1-design.md`. Branch `feat/contracts-1-1`
from `main` @ `383d1fa`, rebased onto `main` @ `70c30c7` after review and onto
`a913733` after re-review. Neither rebase touched contract files.

## What changed

- `_base.py` adds three pieces:
  - `VersionedContract10Or11` and `VersionedContract11` bases, alongside the
    unchanged `VersionedContract` ("1.0").
  - `enforce_version_gate`, the one Python switch for 1.1-only fields.
  - `version_gate_json_schema`, its `dependentSchemas` twin.
- `contracts.py`:
  - `StrategyPacket` gains `planning_basis_fingerprint`.
  - `ModelTrace` gains `role`, `reason_codes`, `request_id`, and
    `input_pins`.
  - `CaseContextSnapshot` gains `completion_receipt`.
  - Every new field is `Field(default=None, exclude_if=absent)`, so a 1.0
    dump never carries it.
  - `PlanningBasis` accepts "1.1" (same shape; 1.1 means the narrowed
    formula).
  - New types `ExecutionClaim` and `CompletionReceipt` ("1.1" only). The
    receipt recomputes its hash with the canonical JSON of
    `AppliedOfferConfirmation.to_dict`.
  - New helpers `material_offers_fingerprint`,
    `approval_state_fingerprint`, and `strategy_basis_binding`.
  - Snapshot rules at 1.1: the basis version equals the snapshot's,
    components use the 1.1 formula, the receipt is present exactly when the
    phase is COMPLETE, and the receipt hash equals its CONFIRMATION
    Evidence `content_hash`.
  - Both new types are in `CANONICAL_MODELS` and in the union.
- `contracts/`: regenerated with `make contracts` (schema +551/-6;
  TypeScript +181/-75, mostly json2ts alias renumbering). The README gets a
  version-policy section.
- `scripts/generate_contracts.py` (root decision): the generated schema's
  `$id` is now `…proxyloop-contracts-1.1.json` and `x-schema-version` is
  "1.1", naming the contract-set release. Nothing else in the repo pins the
  old header; the grep covered web, tests, docs, scripts, `ml/`, and
  `data/`.
- Tests: 13 new fixtures (8 invalid, 5 valid). Additions to
  `tests/contract/test_generated_contracts.py`, the new
  `tests/contract/test_contract_set_1_1.py`, and the registry set in
  `runtime/packages/contracts/tests/test_contracts.py`.

## Per-type versions as implemented

| Type | Accepts | 1.1 fields |
|---|---|---|
| StrategyPacket | 1.0, 1.1 | `planning_basis_fingerprint`: required at 1.1, forbidden at 1.0 |
| PlanningBasis | 1.0, 1.1 | none (formula meaning only) |
| CaseContextSnapshot | 1.0, 1.1 | `completion_receipt`: forbidden at 1.0; at 1.1 present exactly when COMPLETE |
| ModelTrace | 1.0, 1.1 | `role` and `reason_codes` required at 1.1; `request_id` and `input_pins` optional; all forbidden at 1.0 |
| ExecutionClaim | 1.1 | new |
| CompletionReceipt | 1.1 | new |
| all other types | 1.0 | unchanged |

## Red → green

- Red (new tests before the source change):
  - `test_generated_contracts.py`: 9 failed, 14 passed. The four new valid
    fixtures failed, and so did the five null-key cases. The invalid
    fixtures were already rejected by the old code, because their keys or
    versions were unknown to it.
  - `test_contract_set_1_1.py`: ImportError (`CompletionReceipt`).
- Green: the contract tests pass (`tests/contract`,
  `runtime/packages/contracts/tests`).

## 1.0 byte stability (pre/post, scratch scripts, not committed)

Re-confirmed after the rebase, following the reviewer's approach:

- The `origin/main` @ `70c30c7` contracts package was exported and put on
  `PYTHONPATH`, then compared with this branch.
- Three document sets were compared:
  - runtime-produced 1.0 snapshots (4): created, pending approval,
    complete, and current at T0+40 m, from `ThinAgentRuntime` with an
    in-memory repository;
  - the 32 `fresh_fixtures` snapshots;
  - the 40 committed harness traces.
- For each set:
  - the `model_dump_json` bytes and `canonical_fingerprint` produced on
    base and on branch are equal;
  - every base document re-encoded by the branch is byte-identical, and so
    is every branch document re-encoded by base.
- No `PROXYLOOP_TEST_*` variable was set.

First pass, against `383d1fa`:

- The 40 harness `ModelTrace`s and `case.valid.json` match the `main`
  baseline byte for byte: `model_dump_json()`, sorted `model_dump(mode=json)`,
  and `canonical_fingerprint` (41/41 equal).
- `origin/main` sources on `PYTHONPATH` and this branch produce the same
  `model_dump_json` sha256 and `canonical_fingerprint`:
  - 1.0 strategy `d23f0ad9…` / `173a5d96…`
  - basis `0e8ae979…` / `c53ac10e…`
  - snapshot with offer + pending approval `61ee60cb…` / `c60343b1…`
- The 47 unchanged JSON Schema `$defs` hash to `3be49915…` on both.

## Deviations from the design

1. **The null-key rejection applies to JSON input only, and is implemented
   as an after-validator.** A `mode="before"` model validator turns strict
   JSON input into Python input, so pydantic then rejected every JSON
   timestamp (observed). The gate therefore reads `model_fields_set` in the
   after-validator. The first `make test` run then failed 14 tests in
   `tests/integration/test_phase_03a1_agent_core.py`. That file is not
   owned by this slice; it rebuilds snapshots with
   `CaseContextSnapshot(**snapshot.__dict__)`, which passes
   `completion_receipt=None`. Resolution: in Python mode `None` means absent
   (only a non-`None` value is rejected at 1.0); in JSON mode an explicit
   `null` key is rejected.
   - Rationale: with `strict=True`, wire documents can only be validated as
     JSON, so pydantic and the JSON Schema still agree on every JSON
     document.
   - A test pins both behaviours.
   - **Accepted by the root** and recorded in the design copy (decision 1).
2. The 1.1 approval component counts APPROVED and REJECTED only, per the
   design. The architect prototype excluded only EXPIRED.
3. `CaseContextSnapshot` at 1.1 also requires `receipt.case_id` to equal the
   Case id. The JSON Schema additionally encodes the basis-version and
   receipt/COMPLETE pairing. Hash and formula checks remain pydantic-only.
4. The existing fixture `case.valid.json` is not in canonical dump form,
   and was not on `main` either. Its nested constraint omits the optional
   keys `valid_until` and `priority`, which the dump emits as `null`. Those
   are the only differences. Its byte identity is therefore shown by the
   pre/post dump comparison above, not by a fixture round-trip test.

## Review

Independent review (`reviewer`): **Request Changes**. The reviewer verified
1.0 byte identity independently. Root decisions applied on this branch:

- **I-1: decision 3 tightened.** At 1.1 the receipt of a COMPLETE snapshot
  must be bound to the snapshot:
  - (a) an approval in the snapshot with the receipt's `approval_id`, with
    `revision == approval_revision` and decision APPROVED;
  - (b) that approval's `action_intent_id` and `offer_ref` equal the
    receipt's, and the offer (id and revision) is in `offers`;
  - (c) the CONFIRMATION Evidence's `source_ref == confirmation_id`,
    together with its hash;
  - (d) a COMPLETE `completion_decision` whose `evidence_ids` include the
    confirmation Evidence.

  JSON Schema mirrors only the part of (d) it can express: a COMPLETE 1.1
  snapshot requires a `completion_decision` with decision `complete`. The
  rest is pydantic-only, as the README states. `_complete_1_1()` now builds
  a genuinely bound snapshot. Negative tests cover (a) through (d),
  including the reviewer's repro: a REJECTED approval with the receipt's id
  and revision is rejected. The tightening is recorded in the design copy.
- **Minor 2:** a 1.1 `ModelTrace` rejects `input_pins.case_id` that differs
  from the trace's `case_id`, and rejects duplicate `reason_codes`.
- **Minor 3:** added to the design's Known limits: the aggregate
  fingerprint excludes `schema_version`, so with no offers and no approvals
  the 1.0 and 1.1 fingerprints coincide, and the Router must never infer a
  version from pins.
- **Minor 4:** the `strategy_basis_binding` docstring says to apply it
  through construction or `model_validate`, never `model_copy(update=...)`.
- **Minor 5:** the README says the generated TypeScript carries no version
  gates.
- **Minor 6:** a test pins that a nested 1.0 strategy with
  `planning_basis_fingerprint: null` inside a 1.0 snapshot is rejected by
  both validators. The fixture-difference wording is corrected (deviation
  4).
- **Item 7:** rebased and re-verified, as below.

Re-review (`reviewer`): **Approve**. Its three minors are applied:

- A 1.1 snapshot rejects duplicate `approval_id`s. Tested with the
  reviewer's repros: APPROVED + REJECTED with the same id, and rev 2
  APPROVED + rev 3 REJECTED. A 1.0 snapshot is unchanged.
- The approval bound to the receipt must be `ACCEPT_OFFER`. An APPROVED
  `SEND_MESSAGE` approval carrying an `offer_ref` is rejected.
- The README and the design state that consistency between the receipt and
  the offer's terms belongs to the deterministic verifier
  (`verify_completion`), which the COMPLETE decision cites.

## Checks

| Check | Result |
|---|---|
| contract tests (`tests/contract`, `runtime/packages/contracts/tests`) | 120 passed |
| `make contracts-check` | pass (artifacts match; `tsc` OK) |
| `make lint` | pass |
| `make typecheck` | pass (62 + 59 files) |
| `make format-check` | pass (104 + 89 files) |
| `make check-layout` | pass |
| `make test` (on `a913733`) | exit 0: runtime 950 passed, 46 skipped; ml 388 passed, 1 skipped (yaml) |
| harness-check | valid |
| hosted-rescore-check | r4 integrity valid, execution contract unchanged `6b50437f…`, rescored artifact equal |
| validity-smoke-check | valid |
| phase03c-prompt-set-check | consistent (4400 rows, content fingerprint unchanged) |
| phase03c-rescore-check | heldout and dev rescored checked |
| `git status --porcelain data/` | empty |

The drift states `drifted_since_r1`, `drifted_since_03b`, and
`drifted_since_bundle` are pre-existing informational states; they also
appear in the `main` baseline run.

Not run: `make preflight`, Compose gates (`postgres-check`,
`phase05a-check`, `phase06b1-check`; no runtime code changed), and a
re-review of the remediation.

## Known limits

- `exclude_if` depends on pydantic 2.13.4 (both locks). The "no new key in a
  1.0 dump" test pins the behaviour.
- Nothing produces 1.1 yet. PR2 switches the runtime snapshot and basis to
  1.1 and uses `strategy_basis_binding`.
