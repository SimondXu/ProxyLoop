# Feat: canonical contract set 1.1, contracts only (PR1)

Slice PR1 of `harness/context/schema-1.1-design.md`. That file, carried by this
PR, holds the root decisions and is authoritative. Programme:
`harness/context/audit-remediation-decisions.md` decisions 11 and 12. Branch
`feat/contracts-1-1` from `main` @ `383d1fa`, rebased onto `70c30c7`.

## Scope

- `runtime/packages/contracts/**`: the per-type versions, the new fields with
  their version gates, the two new types, the 1.1 materiality formula, and the
  `strategy_basis_binding` producer helper.
- `contracts/**`: regenerated with `make contracts`. The README gets a
  version-policy section.
- `tests/fixtures/*`: new files only. No existing fixture is modified.
- `tests/contract/test_generated_contracts.py`, the new
  `tests/contract/test_contract_set_1_1.py`, and the registry assertion in
  `runtime/packages/contracts/tests/test_contracts.py`.

## Non-goals

- No producer change. That means no runtime, router, coordinator, scripted
  adapter, OpenAI outputs, Postgres repository, or any `ml/` or `data/` file.
  Nothing in this PR emits a 1.1 document yet; PR2 through PR4 do.
- `scripts/generate_contracts.py` changes only its schema header. At the
  root's decision, `$id` and `x-schema-version` name the 1.1 contract-set
  release.

## Frozen acceptance (design PR1 row)

1. Pydantic (`validate_contract_json`) and the generated JSON Schema
   (Draft 2020-12) both reject the eight new invalid fixtures:
   `strategy_packet.v1_1-missing-basis`, `strategy_packet.v1_0-with-basis`,
   `model_trace.v1_1-missing-role`, `model_trace.v1_0-with-role`,
   `execution_claim.v1_0`, `execution_claim.command-without-fingerprint`,
   `completion_receipt.v1_0`, and `case.v1_1` (each `*.invalid.json`). Each
   is one change away from a valid fixture, and its pydantic rejection
   reason is pinned.
2. Python tests cover the 1.1 snapshot rules:
   - the basis `schema_version` equals the snapshot's;
   - the narrowed A-10 formula: approvals as `(id, decision)` for APPROVED
     and REJECTED only, offers as `(id, revision, material_terms_hash)`;
   - the receipt is present exactly when the phase is COMPLETE;
   - the receipt hash equals the `content_hash` of its CONFIRMATION
     Evidence.
3. The committed 1.0 documents round-trip byte-identically: the 40 harness
   `ModelTrace`s in `data/manifests/phase-03a1-episodes.json` and the
   canonical fixtures.
4. A test pins that a 1.0 dump contains none of the new keys.
5. A 1.0 JSON document with an explicit `null` 1.1 key is rejected by both
   validators.
6. `make test` is green, `git status --porcelain data/` is empty, and the
   evidence gates are unchanged, including prompt-set 4400/4400.

## Verification

Contract tests, `make contracts-check`, `make lint`, `make typecheck`,
`make format-check`, and `make test` (after `pnpm install --frozen-lockfile`).
No Compose gate, because no runtime or connector code changes.

## Escalate

Stop and report in any of these cases: a committed evidence gate turns red, a
1.0 document's bytes change, or pydantic and JSON Schema cannot agree on a
gate.
