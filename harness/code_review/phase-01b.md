# Phase 01B Independent Review

Date: 2026-08-23

Reviewer role: independent, read-only reviewer. Sol retains the final integration and merge decision.

## Initial Decision

Request Changes.

### P1 — Completion Evidence could be omitted

The environment accepted a correct offer reference with no caller Evidence reference and still returned `completed=true`. This weakened the rule that deterministic Provider Evidence owns completion.

Resolution: removed the caller Evidence-reference seam. The environment now binds its own Provider confirmation Evidence and returns the exact reference only on verified completion. Missing or unverified Evidence cannot complete.

### P1 — Breadth was reported but not enforced by the gate

The aggregate gate could pass with 32 rows drawn from one Provider configuration because it did not hard-require 16 families and two configurations.

Resolution: the gate now requires exactly 32 scenarios, 16 families, two configurations, 10/3/3 family split counts, and 20/6/6 scenario split counts, in addition to all valid outcomes and zero false completions/leakage.

### P1 — Conflicting family/entity derivatives were order-dependent

The split generator used a dictionary comprehension that silently overwrote a conflicting entity cluster for one family, making the result dependent on input order.

Resolution: every derivative is checked before assignment. A family mapped to two entity clusters raises `ValueError` in either input order.

### P1 — Versions did not affect identities or fingerprints

Changing only a Provider configuration version left scenario identity, manifest hash, and report fingerprint unchanged.

Resolution: family and Provider-configuration versions enter scenario IDs; those IDs enter the split manifest; both versions also appear in report provenance and its fingerprint.

## Root Additional Finding

The initial Provider messages copied private family descriptions. Even though no forbidden key appeared in the Safe Observation, this risked semantic evaluator-rationale leakage.

Resolution: public messages are now separate factual Provider-facing strings. Tests prove they do not contain family descriptions, private reason codes, or evaluator/gold/reward language.

## Rereview Decision

Approve. No unresolved blocking finding.

The reviewer independently confirmed that:

- caller-controlled Evidence is absent and completed results carry environment-bound Provider Evidence;
- breadth and split counts are hard gate inputs;
- conflicting family/entity derivatives fail in both orders;
- family/config versions affect scenario identity, manifest, and report;
- the oracle receives only Safe Observation;
- `agent_core` depends only on canonical contracts;
- no Phase 02, model, service, Temporal, channel, or UI scope entered the change.

## Reviewer Verification

- focused Phase 01A/01B/architecture tests: 59 passed;
- benchmark artifact and gate check: passed;
- Ruff format/lint: passed;
- mypy: passed;
- layout and diff checks: passed.

The reviewer did not run the complete `make preflight`, uv/pnpm lock, Compose, TypeScript, or GitHub CI gates because the restricted environment could not access the external uv cache. Sol separately ran the available full local equivalents. GitHub CI remains mandatory before merge.

## Residual Boundary

Raw `ProviderTurn` includes a benchmark correlation `scenario_id`. It must remain environment-side. Model and oracle integrations must continue to receive only Safe Observation, as the current composition does.

## Final Runner-Configuration Review

The first authoritative preflight exposed that pytest launched from the repository root did not discover the nested runtime configuration, so the benchmark test could not import the root composition script. After two documented failed path attempts, the final fix made the Make target pass `-c runtime/pyproject.toml` explicitly and set that configuration's Python path to the repository root.

The independent reviewer approved this final diff after confirming that it collects all 78 contract, Phase 01A, architecture, observation, environment, and benchmark tests and does not narrow discovery or conceal a failure.
