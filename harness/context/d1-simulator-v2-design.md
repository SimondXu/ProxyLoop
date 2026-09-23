# D1 simulator behaviour (P1 D1-5, D1-6, D1-8, D1-9) and A-11: design and root decisions

Recorded 2026-09-23 by the root orchestrator from an `architect` (Opus)
proposal. Programme: `harness/context/audit-remediation-decisions.md`
(decisions 4, 15). Audit sources: `harness/code_review/repo-audit-D1.md`
§D1-5/6/8/9, `harness/code_review/repo-audit-A.md` §A-11.

## Root decisions

1. **V1 is frozen; V2 is added alongside.** Fixing D1-5/D1-9 in place makes
   the Phase 03C held-out result (0.983) unreplayable: `build_index` rebuilds
   the held-out rows from V1 configurations and from
   `MultiTurnProviderEnvironment` position-2 observations, so a changed V1
   prompt no longer matches the stored raw outputs (`phase03c-rescore-check`
   fails); D1-6/D1-8 in place would drift 03C train-family provenance and
   force regeneration of 01B/03A1/02/03B artifacts. Frozen byte-for-byte:
   (1) the V1 tuples and `_build_scenario` in `scenarios.py`;
   (2) `ProviderEnvironment`; (3) `MultiTurnProviderEnvironment`;
   (4) `ScriptedOracleConsumer()` default precedence;
   (5) `generate_split_manifest` / `generate_phase03a1_manifest` defaults and
   `private_tokens(BENCHMARK_SCENARIOS)`. Invariant I1: after `make test`,
   `git status --porcelain data/` is empty and `PROVIDER_VERIFIER_VERSION` is
   unchanged.
2. **Acceptance rewritten**: the audit's "`divergence.py` D–G produce
   differing outcomes" is satisfied on the **V2** catalogue; the V1 probe
   outputs must stay byte-identical to before.
3. **Oracle precedence is a versioned parameter, default V1** (as
   `SAFETY_FAMILIES_V1` was pinned in G2c). An in-place change is
   byte-neutral on V1 artifacts (64,704 observations probed, 0 differences)
   but contradicts the frozen v4–v6 prompt text, so it stays versioned.
4. `forged-evidence` and `multi-hazard` join `SAFETY_FAMILIES_V2` only once
   P-C/P-D acceptance holds (decision 4's condition).
5. An LLM-played Provider (hosted spend/credentials) is out of scope; V2
   counterpart text is deterministic and scripted.
6. A-11 is independent of D1 and ships alone.

## V2 design (summary of the proposal)

- **D1-5** `PROVIDER_POLICIES_V2`: `transparent-public-v2` (compliant offer
  up front, no transfer) and `retention-gated-v2` (opening offer above
  target; a `counter` releases the compliant retention offer; transfer
  available). Success families have different opening reference actions per
  policy; an opening accept is a valid completion under transparent and, under
  retention, a completed but invalid outcome (the Provider applies an
  above-target offer: `completed=True, valid_outcome=False`, per I4; revised
  at P-C review, 2026-09-23).
- **D1-6** a private confirmation ledger in the V2 environment: after an
  accept the Provider issues an existing confirmation whose public echo is
  (ref, offer_id, revision, `material_terms_hash`). forged → ref not in the
  ledger or binding mismatch (`confirmation_evidence_mismatch`); absent → no
  ref (`confirmation_evidence_missing`). completed ⇔ ledger binding equals
  the accepted offer.
- **D1-8** hazards are a typed `frozenset[Hazard]`; multi-hazard =
  {FEE_TRAP, FEATURE_LOSS, FORBIDDEN_TERM} composed from single-hazard
  builders; transfer is a policy property, not a hazard. Oracle
  `precedence=V2_OFFER_FIRST`: clarify → disclosure → approval → accept
  (compliant offer with evidence) → escalate (transfer) → replan (no
  evidence) → decline. V2 escalate predicate: transfer available and no
  compliant offer.
- **D1-9** `negotiation.py`: `ConsumerMessage(dialogue_act, text,
  provided_facts, completion_claimed, idempotency_key)`; Provider transitions
  depend only on (state, act, facts, capability attempt) — text is recorded,
  never parsed; ordered cursor, `max_consumer_inputs`, per-input idempotency
  namespace.
- Namespaces: `negotiation-v1::<family>@1.0::<policy>@1.0` (avoid `@2.0`,
  used by r2). Separate tuples, split (hash-based), `SAFETY_FAMILIES_V2`,
  leakage token source. A V2 runner is a new module; never edit
  `runner_v2.py` or any file in `hosted_rerun._R4_EXECUTION_PATHS`.

Invariants: I2 text never decides a transition; I3 V2 decisions are §8
state predicates, `expected_*` only feeds `reference_match`; I4 completed ⇔
ledger binding == accepted (id, revision, `material_terms_hash`); I5 in V2 an
offer never coexists with a clarification or disclosure request (builder
asserts); I6 every hazard in a family is independently failing and
multi's reason codes ⊇ each single hazard's; I7 each declared family's
reference trajectory differs between the two V2 policies; I9 every runtime
approval satisfies `approval.expires_at <= manifest.expires_at`.

## A-11

Mint once per Case with `expires_at = case.goal.deadline` (the runtime
always sets it, created_at + 9 days). Rejected: per snapshot (the manifest
fingerprint is a planning-basis component — a refresh storm under A-1), per
execution (the executor would validate what it just minted), no expiry
(`CapabilityManifest.expires_at` is a required canonical field). Regression
at the executor seam: a hand-built snapshot with 48 h offer/approval and the
new manifest executes at T+25 h (`EXECUTED`; `capability_manifest_expired`
on main); execution at or after the deadline is rejected; a new runtime Case
has `manifest.expires_at == case.goal.deadline`. Known limit: persisted Cases
keep their 1-day manifest; a runtime end-to-end long-window test needs an
injectable Provider offer TTL (`provider.py:114` is fixed at 1 h).

## PR slices

| PR | Owned files | Acceptance | Order |
|---|---|---|---|
| P-A A-11 | `case_runtime/runtime.py` (`_manifest`, its call sites, approval guard); new `tests/integration/test_capability_manifest_lifetime.py` | the A-11 tests; preflight + Compose gates | parallel |
| P-B oracle precedence | `agent_core/observation.py`, `agent_core/__init__.py`, new test | probe E returns `accept_offer` under V2, `escalate` under default V1; the 64,704-observation invariance probe as a test; zero V1 artifact diff | parallel |
| P-C V2 catalogue + N-turn state machine + V2 verifier (D1-5, D1-8, D1-9) | new `provider_simulator/negotiation_catalog.py`, `negotiation.py`, tests (uses telecom_domain policy and Case constraints; no private `environment.py` imports) | ported D/E/G differ on V2; ported `mt.py`: two acts → different transitions, not terminal; a retention success episode has ≥ 3 Provider turns; I5–I8; V1 probe outputs unchanged | parallel with A, B |
| P-D confirmation ledger + forged family (D1-6) | same files as P-C | ported F: public turns differ on confirmation fields; mismatch vs missing reason codes; forged accept → `completed=False`, a completion claim → `false_completion` | after P-C, same writer |
| P-E V2 split / `SAFETY_FAMILIES_V2` / leakage / scripted ceiling | new `negotiation_splits.py`, `scripts/run_negotiation_ceiling.py`, `data/manifests/negotiation-v1-ceiling.json`; root owns `Makefile`, `docs/ml-evidence.md` | V2 scripted oracle valid on every instance; success families complete under both policies; leakage scan empty; `negotiation-check` in `make test` | after P-B, P-D |
