# Phase 03C Stage 1a Parameterisation Review

**Target**: `feat/phase-03c-stage1a-parameterisation` working tree against
`main` at `aaae134`
**Reviewer**: independent read-only `reviewer` subagent (Claude Opus, high
effort, fresh context), two passes.
**Final recommendation**: Approve after remediation.

## Scope reviewed

Byte-identity of the 32 frozen scenarios and the historical Case; hazard
truth of seeded instances under both Provider configurations (independent
9,600-instance script); oracle/verifier agreement semantics and a concrete
demonstration that the parameterised verifier context changes outcomes vs
the historical constants; `environment.py` behaviour under defaults;
observation parity; manifest reproducibility and fail-closed behaviour;
scope (no frozen-file edits, no model calls, no new deps).

## Findings and resolutions

- **Important — message/offer contradiction.** Frozen and variant texts
  named "mobile hotspot"/"device-financing" regardless of parameters.
  Fixed: every hazard text is a `{feature}`/`{change}` template (variant 0
  renders the frozen bytes); new `message_offer_consistency` invariant,
  verified non-vacuous by tampering.
- **Important — no pin on seeded content.** Fixed: manifest
  `parameters_fingerprint`; seeds 1/42/999 pinned as literals.
- Minor: tautological Case equality → sha pin `37d8e149…`; iterator
  materialisation; `id_suffix` collisions (`::p<seed>-<8hex>` for hand-built
  params, never touching frozen ids); `current_monthly_minor > 1000` and
  builder-token rejection; quarantine-row and variant tests; promo constant
  dedup. All applied.
- Accepted semantic widening: `check_invariant_manifest` also reports
  quarantine rows stored in the committed manifest (fail-closed).
- Residual (not blocking): success-family message check accepts any offer
  feature; the generator only ever names `required_features[0]`.

## Verification observed by the reviewer

Frozen catalogue sha `425c7afb…` recomputed from `git archive main`;
eleven artifact `*-check` targets, `phase03c-invariants-check`, lint,
typecheck, `make unit-test` (303/33 skipped; 236) all passed on the final
tree; `parameters_fingerprint` independently recomputed as `41390f7c…`.
