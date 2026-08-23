# Phase 01A Preflight Context

**Status**: Complete; decisions implemented and verified

**Checked**: 2026-08-23

**Question**: What is the smallest deterministic simulator slice that proves authorization and evidence-owned completion without starting the full benchmark phase?

## Observed Baseline

- Merged `main` commit `98a7514` contains the complete Phase 00B canonical contract package.
- `runtime/packages/provider_simulator/` and `runtime/packages/telecom_domain/` contain only placeholders.
- Canonical `Case`, `ProviderOffer`, `ActionIntent`, `ApprovalRequest`, `Evidence`, and `CompletionDecision` types already exist and are immutable.
- The canonical contracts bind approvals to exact Case/action/strategy/constraint/offer revisions and material-term hashes, but cross-document checks intentionally remain domain policy.
- The full roadmap Phase 01 includes 15-20 scenario families, safe observations, benchmark splits, oracle consumers, and multiple Provider configurations. None of that is implemented.

## Frozen 01A Decisions

| Decision | Status | Reason |
|---|---|---|
| One deterministic fictional postpaid-mobile Provider | Accepted | Proves the loop without benchmark breadth |
| Legal offer path is `available -> offered -> awaiting_approval -> confirmed` | Accepted | Smallest path that exposes an illegal-transition test |
| Approval expires when `execution_time >= expires_at` | Accepted | Matches the canonical decision window and prevents boundary ambiguity |
| Confirmation content is canonicalized and SHA-256 hashed into Evidence | Accepted | Lets the verifier reject a forged Evidence ID or payload |
| Completion verification lives in `telecom_domain` | Accepted | Provider mutation must not authorize its own success claim |
| CLI emits deterministic JSON for the built-in scenario | Accepted | Gives a reproducible human/CI execution surface without an API or database |
| Phase 01B remains a separate future gate | Accepted | Prevents one scenario from being mislabeled as a benchmark |

## Initial Implementation Seam

- `telecom_domain` owns the immutable applied-offer confirmation shape, material/confirmation hashing, approval binding, and `CompletionDecision` creation.
- `provider_simulator` owns Provider state and the legal transition methods, constructs canonical episode documents, and exposes the CLI.
- Tests exercise behavior through these interfaces and CLI output; they do not assert private implementation state.

## Boundaries

- Do not add external dependencies beyond the canonical contract package and its existing Pydantic runtime.
- Do not introduce abstract adapter ports while there is only one Provider implementation.
- Do not alter generated contract artifacts unless a failing Phase 01A test demonstrates a canonical-contract defect.
- Do not claim roadmap Phase 01 complete after this slice.
