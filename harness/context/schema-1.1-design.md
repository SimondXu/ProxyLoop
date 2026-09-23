# Canonical contract set 1.1 (P1 A-1, A-2, A-6, A-10, canonical ExecutionClaim): design and root decisions

Recorded 2026-09-23 by the root orchestrator from an `architect` (Opus)
proposal with probes (scratch: `arch-1.1/` — `contracts-per-type.patch`
PR1 prototype, `patchR.py` PR2 prototype, `repro_a1_a10.py`,
`group_probe.log`). Programme: `harness/context/audit-remediation-decisions.md`
decisions 11, 12. Proposal: `docs/research/2026-09-21-target-architecture-proposal.md` §4.

## Why not a frozen `v1_0` module (proposal §4 as written)

Every ML prompt serialises contracts: `openai_frontier.py:720/748` dumps the
whole FastModelView / SlowWorkRequest (strategy, pins, planning basis, every
nested `schema_version`); `qwen_mlx.py:275-305` serialises pins and the full
strategy; `fresh_fixtures.py:428-431` dumps the snapshot; planning-basis
components fingerprint the **full dump** including `schema_version`. The
frozen r4 modules (`hosted_rerun._R4_EXECUTION_PATHS`) and
`phase03b_experiment.py` import top-level `proxyloop_contracts` class names
and `isinstance`-check them, and cannot be edited to import a `v1_0`
module. A required new field breaks `fresh_fixtures._strategy`
(`ValidationError`, observed: `hosted-rescore-check`,
`phase03c-prompt-set-check` fail); a plain `Optional = None` field drifts
4400/4400 prompt-set rows and the r4 rescored artifact; switching
`Phase01AEpisode` or the coordinator projections to "1.1" breaks eight
evidence gates (observed). Therefore **the top-level class names must keep
constructing and validating 1.0 documents byte-identically.**

## Root decisions

1. **Per-type versioning.** Only types whose shape or semantics change
   accept `"1.0" | "1.1"`: `StrategyPacket`, `PlanningBasis`,
   `CaseContextSnapshot`, `ModelTrace`. New types accept `"1.1"` only:
   `ExecutionClaim`, `CompletionReceipt`. Every other type stays
   `Literal["1.0"]`. New fields are declared `Field(default=None,
   exclude_if=<absent>)` with a version gate — required at 1.1, forbidden
   at 1.0 — plus a validator rejecting an explicit `null` key in a 1.0
   document, so a 1.0 dump is byte-identical and pydantic and JSON Schema
   agree. *Amended by the root at PR1 (2026-09-23):* the explicit-`null`
   rejection applies to JSON input only. It is implemented as a
   `mode="after"` check on `model_fields_set`. The design's `mode="before"`
   validator was dropped because it turns strict JSON input into Python
   input and rejects every JSON timestamp. In Python mode `None` means
   absent, so `Model(**other.__dict__)` keeps working; only a non-`None`
   1.1 value is rejected at 1.0. With `strict=True`, wire documents are
   validated only as JSON, so pydantic and JSON Schema still agree on every
   JSON document. The generated schema header (`$id`, `x-schema-version`)
   names the contract-set release, 1.1. The snapshot's own `schema_version` selects the rules:
   1.0 is the ML/evaluation world, 1.1 is the runtime. Decision 11 ("one
   bump") is kept as one contract-set release; its literal "regenerate
   fixtures at 1.1" is superseded: existing fixtures stay as 1.0 regression
   documents; 1.1 fixtures are added.
2. **The execution claim lives on runtime state, not on the snapshot.** It
   is execution bookkeeping, not model input; the claim/pending consistency
   is already enforced in `repository.py:46-50` and the Postgres envelope.
   (Deviation from proposal §4 row B2-1.)
3. **At 1.1, `phase == COMPLETE` ⇔ a `CompletionReceipt` is present**, and
   the receipt's hash equals the `content_hash` of its CONFIRMATION
   Evidence (same canonical JSON as `confirmation_hash`). Evidence hashing
   semantics are unchanged (A-5 out of scope).
   *Tightened by the root at PR1 review (2026-09-23), before PR2 writes 1.1
   rows:* at 1.1 the receipt of a COMPLETE snapshot must be bound to the
   snapshot itself:
   (a) an approval exists with `approval_id == receipt.approval_id`,
       `revision == receipt.approval_revision`, and decision APPROVED;
   (b) that approval's `action_intent_id` and `offer_ref` equal the
       receipt's, and the referenced offer (id and revision) is in
       `snapshot.offers`;
   (c) the CONFIRMATION Evidence's `source_ref == receipt.confirmation_id`,
       in addition to the hash check;
   (d) `completion_decision` is present with decision COMPLETE, and its
       `evidence_ids` include `receipt.confirmation_evidence_id`.
   JSON Schema mirrors only part of (d): a COMPLETE 1.1 snapshot requires a
   `completion_decision` whose decision is `complete`. The rest is
   pydantic-only. *Re-review minors (2026-09-23):* the bound approval must
   have `action_type` ACCEPT_OFFER, and a 1.1 snapshot rejects duplicate
   `approval_id`s. Consistency between the receipt and the offer's terms
   (price, features, term, Provider) is guaranteed by the deterministic
   verifier (`telecom_domain` `verify_completion`), which the COMPLETE
   decision must cite; the contract does not duplicate it.
4. **A-10 narrowing is in**, approval component over
   `sorted[(approval_id, decision)]` for **APPROVED/REJECTED only** (PENDING
   and EXPIRED excluded: a pending approval is produced by the current
   strategy and must not invalidate it; an expired one is not material).
   Offer component over `sorted[(offer_id, revision,
   material_terms_hash(offer_material_terms(o)))]`; no "unexpired" filter
   (the snapshot has no clock; expiry is a material term). The other six
   components are unchanged.
5. `_record_rejection`'s hard-coded `route="fast_now"` (`runtime.py` ~1456)
   is replaced by the Router's decision in PR2.

## Field-level changes

- `StrategyPacket` + `planning_basis_fingerprint: Sha256` (1.1 required,
  1.0 forbidden); helper `strategy_basis_binding(basis)` stamps version and
  binding for producers.
- `PlanningBasis`: shape unchanged; 1.1 means the narrowed formula.
- `CaseContextSnapshot` at 1.1: `planning_basis.schema_version` equals the
  snapshot's; components recomputed with the 1.1 formula; new
  `completion_receipt: CompletionReceipt | None` (1.1 only; decision 3).
- `ModelTrace` + `role: Literal["fast","slow","judge","intake"]` (1.1
  required), `reason_codes: tuple[ExternalRef, ...]` (1.1 required, may be
  empty), `request_id: EntityId | None`, `input_pins: ModelInputPins | None`.
  The 40 committed 1.0 harness traces stay valid.
- `ExecutionClaim` (1.1 only): `case_id, approval_id, action_intent_id,
  idempotency_key, before_revision, claimed_at, command_id?,
  command_fingerprint?` (the last two both or neither; `command_id` stays
  nullable until B2-4 because direct mode passes `None`).
- `CompletionReceipt` (1.1 only): every `AppliedOfferConfirmation` field +
  `approval_revision, confirmation_evidence_id, confirmation_content_hash`;
  the validator recomputes the hash.
- JSON Schema: only the six types and the union change; version gates use
  the existing `dependentSchemas` / `if … then required … else not` pattern
  (Draft 2020-12 accept/reject verified). TypeScript regenerates (json2ts
  alias renumbering, ~221 lines churn; the Web does not import generated
  types). `validate_contract_json` needs only the two new union members.

## PR slices

| PR | Owned files | Acceptance |
|---|---|---|
| **PR1 contracts only** | `runtime/packages/contracts/**`, `contracts/**` (regenerated; README version policy), `tests/fixtures/*` (add only), `tests/contract/test_generated_contracts.py` | new invalid fixtures rejected by **both** pydantic and JSON Schema: `strategy_packet.v1_1-missing-basis`, `strategy_packet.v1_0-with-basis`, `model_trace.v1_1-missing-role`, `model_trace.v1_0-with-role`, `execution_claim.v1_0`, `execution_claim.command-without-fingerprint`, `completion_receipt.v1_0`, `case.v1_1`; snapshot 1.1 cross-field rules (basis version, narrowed formula, receipt ⇔ COMPLETE, receipt hash) as Python tests; committed 1.0 documents (fixtures, harness traces) round-trip byte-identical; a test pins "1.0 dump has no new key"; `make preflight` green with prompt-set 4400/4400 unchanged; zero producer change |
| **PR2 runtime → 1.1 (A-1, A-10, A-6 producer)** | `case_runtime/runtime.py` (`_basis`, `_snapshot`, receipt on completion, `_record_rejection` route), `agent_core/router.py` (`strategy_basis_incompatible` when a 1.1 snapshot's strategy binding ≠ pins; a 1.0 strategy in a 1.1 snapshot is incompatible → one Slow refresh on the next event), `agent_core/coordinator.py` (`slow_strategy_basis_mismatch` at 1.1; add `CoordinatorOutcome.traces=()` to freeze the PR3 seam), `agent_core/scripted.py`, `openai_adapter/outputs.py` (use `strategy_basis_binding`), new `tests/integration/test_strategy_basis_binding.py`, `docs/architecture.md:189`, `CONTEXT.md` materiality wording | A-1 repro routes `slow_refresh`; expired approval → `fast_now`; rejected → `slow_refresh`; a stored 1.0 Case refreshes its strategy on the next event; every ML gate unchanged; Compose gates |
| **PR3 ModelTrace producer** | `agent_core/interfaces.py` (optional traced-adapter protocol + identity), `coordinator.py` `advance` (traces only for 1.1 snapshots, injected clock), `scripted.py`, `openai_adapter/adapter.py` (tokens from `response.usage`) | one trace with `role` per adapter call incl. rejected results; no `trace_id` in snapshot, views, browser payload |
| **PR4 persisted records** | `case_runtime/commands.py` (delete `ExecutionClaimRecord`), `repository.py`, `postgres_repository.py` (envelope `storage_version` 2 + v1 read-upgrade: `case_id`, `action_intent_id`, `idempotency_key` recovered from `execution_intent`), `runtime.py` (write claim, append `outcome.traces`) | stored v1 rows incl. a pending claim load and upgrade; Compose gates |

Order: PR1 → PR2 → (PR3 ∥ PR4). `ml/slow_output.py` stays 1.0 (frozen);
a 1.0 strategy handed to a 1.1 runtime is rejected — the safe side.

## Known limits / risks

- Implicit coupling on the snapshot version — keep the switch in one
  contracts helper, test both modes.
- A 1.1 snapshot embeds 1.0 Case/Offer/pins documents (documented).
- `exclude_if` depends on the pydantic version (2.13.4 in both locks) —
  pinned by the "no new key in a 1.0 dump" test.
- FAILED model calls produce no persisted trace in this bump.
- `model_traces` grows without bound — retention is a later decision.
- The harness stays at 1.0, so the new A-1 routes are covered by runtime
  tests only.
- The planning-basis aggregate fingerprint does not cover `schema_version`.
  With no offers and no approvals, the 1.0 and 1.1 components are equal, so
  the 1.0 and 1.1 aggregate fingerprints coincide. The Router must never
  infer a version from pins; it reads the snapshot's `schema_version`.
