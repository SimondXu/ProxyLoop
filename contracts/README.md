# Generated contracts

Pydantic domain contracts in `runtime/packages/contracts` are the source of truth. Generated artifacts belong here and must not be hand-authored: `make contracts` writes the JSON Schema (`jsonschema/`) and TypeScript declarations plus fixture (`typescript/`), checked by `make contracts-check`. No OpenAPI document is generated yet; `openapi/` is a placeholder.

## Version policy

Every contract document carries its own `schema_version`. Versions are per type, not one version for the whole set. The top-level class names in `proxyloop_contracts` keep constructing and validating 1.0 documents byte-identically. The reason is that ML prompts, fingerprints, and the frozen r4 evaluation modules serialise these classes. The design and root decisions are recorded in `harness/context/schema-1.1-design.md`.

Contract set 1.1 is one release. The generated schema's `$id` and `x-schema-version` name that release (`1.1`); the per-type `schema_version` enums below say what each document accepts.

| Type | Accepts | 1.1 change |
|---|---|---|
| `StrategyPacket` | `"1.0"`, `"1.1"` | `planning_basis_fingerprint` is required at 1.1 and forbidden at 1.0 |
| `PlanningBasis` | `"1.0"`, `"1.1"` | Same shape. At 1.1 the offer and approval components use the narrowed materiality formula |
| `CaseContextSnapshot` | `"1.0"`, `"1.1"` | See the snapshot rules below |
| `ModelTrace` | `"1.0"`, `"1.1"` | `role` and `reason_codes` (which may be empty) are required at 1.1. `request_id` and `input_pins` are optional at 1.1. All four are forbidden at 1.0 |
| `ExecutionClaim` | `"1.1"` only | New type. `command_id` and `command_fingerprint` must both be present or both absent |
| `CompletionReceipt` | `"1.1"` only | New type. It carries every applied-offer confirmation field plus `approval_revision`, `confirmation_evidence_id`, and `confirmation_content_hash`. The validator recomputes that hash |
| every other type | `"1.0"` only | unchanged |

Rules that keep 1.0 documents stable:

- A field added in 1.1 defaults to "absent" and is left out of every dump while unset. A 1.0 dump therefore has none of the new keys, and its bytes and every fingerprint over it do not change.
- A 1.0 JSON document may not carry a 1.1 key, not even as `null`. Pydantic JSON validation and the generated JSON Schema (`dependentSchemas` on `schema_version`) both reject it. When a model is built in Python, `None` counts as absent.
- The snapshot's own `schema_version` selects its rules. 1.0 is the ML/evaluation world. At 1.1:
  - `planning_basis.schema_version` must equal the snapshot's `schema_version`.
  - The approval component covers `sorted[(approval_id, decision)]` for APPROVED and REJECTED approvals only.
  - The offer component covers `sorted[(offer_id, revision, material_terms_hash)]`.
  - `case.phase == "complete"` holds exactly when a `completion_receipt` is present.
  - The receipt's `confirmation_content_hash` equals the `content_hash` of its CONFIRMATION Evidence.
- Nested documents keep their own versions. A 1.1 snapshot may embed 1.0 `Case`, `ProviderOffer`, pins, and strategy documents.

At 1.1 the receipt of a COMPLETE snapshot is also bound to the snapshot:

- it names an APPROVED approval revision that is in the snapshot;
- that approval's action intent and offer equal the receipt's;
- the offer revision is in `offers`;
- the CONFIRMATION Evidence's `source_ref` is the receipt's `confirmation_id`;
- the snapshot's `completion_decision` is COMPLETE and cites that Evidence.

Consistency between the receipt and the offer's terms (price, features, term, Provider) is guaranteed by the deterministic verifier (`telecom_domain` `verify_completion`), which the COMPLETE decision must cite; the contract does not duplicate it.

Pydantic and the JSON Schema both enforce:

- the version gates;
- the new-type versions;
- the `ExecutionClaim` command pair;
- the snapshot's basis version;
- the receipt/`complete` pairing;
- the requirement that a COMPLETE 1.1 snapshot carries a `complete` `completion_decision`.

Pydantic alone enforces the cross-document rules, which JSON Schema cannot express:

- the recomputed hashes;
- the narrowed-formula components;
- the receipt's binding to the approval, offer, Evidence, and the Evidence cited by the completion decision;
- `ModelTrace` `input_pins` referencing the traced Case;
- unique `reason_codes`.

The generated TypeScript declarations carry none of the version gates. `json2ts` ignores `dependentSchemas`, so a 1.1 field shows as optional and nullable at every version. Validate documents against the JSON Schema or pydantic, not the TypeScript types.

Adding a later version follows the same pattern. Widen only the types that change. Gate each new field by version on both validators. Add a valid fixture and a single-cause invalid fixture under `tests/fixtures/` for each gate. Never rewrite an existing fixture.
