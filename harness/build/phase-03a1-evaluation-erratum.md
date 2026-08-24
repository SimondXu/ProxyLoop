# Phase 03A1-E — Evaluation Erratum and Leakage-Safe Second Run

**Status**: Complete with a terminal Provider blocker; local, independent, and
PR #10 gates passed. Phase 03B remains inactive.

**Base**: Phase 03A1-B completed through PR #9. Its original learned scores are
retained as calibration evidence because evaluator defects prevent treating the
zero end-to-end counts as pure model-quality measurements.

## Objective

Correct the proven evaluator contract, attribution, fixture-leakage, and
approval-continuation defects; freeze a new deterministic evaluation derivative
set; rerun untuned Qwen/Terra medium and high baselines; and produce auditable
failure slices that can support a later human decision about Phase 03B.

## In Scope

- a smaller Slow semantic output that selects at most one next capability;
- deterministic infrastructure reference binding and structurally valid
  offer/non-offer capability variants;
- distinct JSON/schema, semantic, canonical, authorization/execution, Provider
  outcome, and end-to-end metrics;
- evaluator-only non-gating reference-match diagnostics;
- a real pending/approved continuation for consequential proposals, preserving
  exact ActionIntent and material-term approval binding;
- separately versioned r2 development, held-out, and safety derivative
  manifests, episodes, ceiling evidence, report, fingerprints, and replay;
- untuned local Qwen Fast reference-strategy/Slow-off controls plus Qwen+Terra
  Slow and Terra-reference at frozen medium and high reasoning effort;
- requested-effort and returned reasoning-token provenance;
- independent review, repository preflight, PR, CI/GitGuardian, squash merge,
  and post-merge verification.

## Frozen Contract Decisions

1. `StrategyModelOutput` does not ask a model to echo hard-constraint UUIDs.
   The compiler binds every visible hard constraint. Soft preferences use
   unique zero-based positions into the visible soft-constraint list and must
   be an in-range subset.
2. `SlowModelOutput` exposes one nullable `next_capability`. Its discriminated
   accept-offer variant requires one in-range offer position. Its five
   non-offer variants cannot carry an offer field. The compiler still verifies
   current manifest membership and mints inert canonical proposals/intents.
3. The model never authorizes, executes, supplies Evidence, or decides
   completion. No semantic output is silently normalized or repaired.
4. A model fixture starts with no oracle-derived ActionIntent or approval. The
   scripted reference stays evaluator-only. Consequential work creates a new
   pending approval exactly bound to the compiled intent and material terms;
   deterministic approval on a later event may authorize that exact intent
   only. Old or mismatched approval never transfers authority.
5. Reported stages are monotonic and separate: provider JSON, output schema,
   semantic compile, canonical binding, authorization/execution, Provider
   outcome, and end-to-end validity. A later stage cannot be true when a
   required earlier stage is false.
6. Exact reference action/offer match is reported separately and cannot turn a
   safe executable alternative into a schema/canonical failure. Provider
   verification remains authoritative for task outcome.
7. The old `phase-03a1-*` artifacts remain unchanged. New artifacts use an r2
   schema/path, have disjoint scenario IDs, and declare their derivation from
   known behavior families without claiming unseen semantic families.
8. Medium and high Terra runs use identical frozen r2 episodes, prompts,
   schemas, model family, token/call caps, no retry, and cost accounting. The
   requested effort is in each call record and fingerprint. Returned reasoning
   tokens are recorded when present and `null` otherwise.
9. Test/dev observations may not change r2 held-out/safety prompts, schemas,
   fixtures, or configuration after the first r2 model call. Any correction
   after dispatch requires a new versioned run.
10. The post-dispatch attribution correction is the separately versioned r3
    offline derivative. It binds the immutable r2 report fingerprint and source
    timestamp, preserves captured raw/call evidence, records zero new external
    dispatches, and cannot claim that the blocked hosted matrix ran.

## Acceptance Criteria

1. Repository status makes 03A1-E the only active phase and keeps 03B inactive.
2. Red tests demonstrate every proven defect before implementation.
3. Output-schema tests make multi-capability and non-offer/offer states
   unrepresentable and reject invalid soft/offer positions without repair.
4. Runner tests distinguish malformed JSON, schema-invalid, semantic-invalid,
   canonical-invalid, authorization-rejected, Provider-invalid, and valid
   end-to-end outcomes in separate counts and slices.
5. Approval tests prove `slow_refresh → wait_for_approval → approved
   continuation → Executor`, exact intent/material binding, stale/mismatched
   rejection, and idempotent reuse without weakening `CapabilityExecutor`.
6. Fixture tests prove no oracle action/approval enters a model view or prompt;
   reference labels remain evaluator-only.
7. R2 artifact tests prove deterministic generation, old/new scenario-ID
   disjointness, development/held-out/safety isolation, prompt leakage
   exclusion, replay, fingerprint drift, and zero false authoritative
   completion in the scripted ceiling.
8. Hosted-adapter tests bind requested reasoning effort, record reasoning tokens
   or explicit absence, reject model remapping, retain zero SDK retries, and
   preserve global unknown-cost abort behavior.
9. Before hosted calls, all prompts/configurations, medium/high conditions,
   scenario identities, caps, fingerprints, and the maximum accounting ceiling
   are frozen and the scripted/oracle/replay/tamper gate passes.
10. The full r2 matrix runs or reports an honest terminal provider/budget
    blocker. Base models may perform poorly; phase validity depends on truthful
    detection, attribution, replay, and safety, not a fabricated quality gate.
11. Reports state that 29qg usage-accounted cost is an estimate, not an invoice,
    and do not claim the proxy's hidden physical backend is independently
    verified.
12. Focused checks and `make preflight` pass; independent Terra review has no
    unresolved Critical/Important finding; exact evidence is appended to the
    build log; PR CI/GitGuardian pass before squash merge.
13. No training, training-data expansion, serving, product Agent, channel, UI,
    real Provider, deployment, release, credential persistence, or Phase 03B
    work occurs.

## Stop Condition

After the r2 artifacts are reviewed, merged, and post-merge preflight passes,
stop and report the corrected failure slices. Phase 03B remains inactive until
the user makes a separate decision from this evidence.
