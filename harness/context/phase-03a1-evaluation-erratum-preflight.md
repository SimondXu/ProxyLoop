# Phase 03A1-E Evaluation Erratum Preflight

Date: 2026-08-24

## Human Gate

The user explicitly approved a second attempt after reviewing the Phase 03A1-B
zero-score diagnosis. The approved outcome is a corrected evaluator, a fresh
leakage-safe derivative set, and a complete untuned Qwen/Terra rerun. Training
and Phase 03B remain inactive.

## Integrated Base

- clean synchronized `main` at `f5c43d8` before temporary planning files;
- Phase 03A1-B was squash merged through PR #9;
- active short-lived branch: `fix/phase-03a1-evaluation-erratum`;
- old report remains immutable calibration evidence.

## Proven Defects

1. All 64 hosted Slow outputs passed provider JSON/Pydantic parsing, but the
   report labeled semantic/compiler failures as schema failures.
2. The model output requested infrastructure UUIDs that were not a meaningful
   model decision and permitted offer bindings on non-offer capabilities.
3. The output allowed up to four capability proposals while the runner executed
   exactly one.
4. Model fixtures preloaded oracle-derived ActionIntent/ApprovalRequest state,
   indirectly disclosing the reference action, while newly compiled intents
   could never match the preloaded approval identity.
5. Exact scripted-oracle capability equality was mixed into end-to-end validity,
   even when another proposal was safe and executable.
6. Terra requested `reasoning_effort=medium`, but the report did not bind the
   requested effort or returned reasoning-token metadata.

## Frozen Correction

- Preserve the deterministic Router, Policy, Approval, Executor, Evidence, and
  Verifier authority boundaries.
- Model output contains one optional next capability, not a list. Offer choice
  exists only on the accept-offer variant. Hard-constraint identities are bound
  deterministically; soft preferences use bounded positions in the visible list.
- Start model evaluation fixtures without oracle-derived actions or approvals.
  An accept-offer proposal creates an exact pending approval, routes to
  `wait_for_approval`, receives a deterministic fictional consumer decision on
  the next turn, and can execute only with the exact approved binding.
- Separate JSON/schema, semantic compile, canonical binding,
  authorization/execution, Provider outcome, and end-to-end measurements.
  Reference-action match is a non-gating diagnostic.
- Preserve the old manifest/report. Freeze separately versioned r2 artifacts
  whose scenario IDs do not overlap the old catalog. The r2 scenarios are new
  identities and public-surface derivatives of known behavior families; they
  are not claimed as novel semantic families.
- Freeze Terra medium and high configurations before any r2 hosted call. Record
  requested reasoning effort and provider reasoning-token metadata when
  returned; record `null` when the proxy omits it.

## External and Secret Boundary

The user authorized sending the fictional Phase 03A1 payloads to the approved
`https://29qg.com/v1` endpoint and stated that provider-side cost controls are
already configured. The credential remains process-only, ignored, unprinted,
and uncommitted. No hosted call occurs until the deterministic r2 gate and all
configuration fingerprints pass.

## Non-Goals

No SFT, QLoRA, DPO, RL, teacher generation, public/project training-data
expansion, serving, product Agent, database, channel, UI, real Provider,
deployment, release, or Phase 03B activation.
