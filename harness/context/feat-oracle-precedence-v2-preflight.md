# Feat: versioned scripted-oracle precedence, V2 offer-first (P1 D1-8, slice P-B)

Bounded change under the D1 simulator-v2 design (root decision 3: oracle
precedence is a versioned parameter, default V1). Audit source:
`harness/code_review/repo-audit-D1.md` §D1-8. Branch
`feat/oracle-precedence-v2` from `main` @ `383d1fa`.

## Defect (observed on main)

`ScriptedOracleConsumer.decide`
(`runtime/packages/agent_core/src/proxyloop_agent_core/observation.py:348-349`)
returns `escalate` whenever `transfer_available` is set, before it looks at
any offer. Audit probe E: a `direct-success` observation with
`transfer_available=True` returns `escalate` although it carries a compliant
offer with confirmation evidence.

## Frozen design

- New `OraclePrecedence` `StrEnum` in `observation.py`, exported from
  `proxyloop_agent_core`: `V1 = "v1"` (today's order) and
  `V2_OFFER_FIRST = "v2_offer_first"`.
- `ScriptedOracleConsumer(*, offer_policy=None, precedence=OraclePrecedence.V1)`;
  the value is coerced through `OraclePrecedence(...)` so an unknown value
  raises instead of silently falling back to V1.
- V1 (default, unchanged): clarify → disclosure → approval → escalate
  (transfer) → replan (no evidence) → accept / decline.
- V2_OFFER_FIRST: clarify → disclosure → approval → accept (a compliant offer
  and confirmation evidence available) → escalate (transfer available) →
  replan (no evidence) → decline. V2 escalates only when a transfer is
  available and no compliant offer with evidence exists.
- Reason codes and offer selection (`min` by 12-month total, monthly price,
  offer id) are shared; V2 adds no new reason code.
- Non-goals: no caller switches to V2 in this slice (the V2 catalogue, P-C,
  is the first consumer); no scenario, environment, manifest or artifact
  change; the v4–v6 prompt text stays as is.

Where V2 differs from V1: exactly the observations that pass the three gates,
have `transfer_available`, `confirmation_evidence_available`, and at least one
compliant offer. In the V1 generation space transfer is set only on
`refusal-transfer` and `multi-hazard`, neither of which carries a compliant
offer, so V2 == V1 there (the architect's 64,704-observation probe: 0
differences).

## Tests (write first) — `ml/tests/test_oracle_precedence_v2.py`

The invariance probe needs the 03C builders (`proxyloop_evaluation`), which
exist only in the ML environment, so the test lives under `ml/tests`.

1. Probe E: catalogue `direct-success` opening observation with
   `transfer_available=True` → V2 `accept_offer` on the expected offer;
   default and explicit V1 → `escalate` (`transfer_available`).
2. Invariance over the full V1 generation space: the 32 catalogue instances
   plus seeds 1–1010 × 32 instances, both harvested positions (64,704
   observations, ~5 s, run in full):
   - the SHA-256 digest of default `(action, offer_id, reason_codes)` equals
     the digest measured on unmodified `main` @ `383d1fa` (a 64-hex pin, not
     a fixture);
   - default == explicit V1 on every observation;
   - V2 == V1 on every observation (none satisfies the differing predicate);
   - with `transfer_available` forced on every observation, V2 ≠ V1 exactly
     where V1 of the original observation was `accept_offer`, and there V2
     returns that same decision.
3. Unknown precedence value is rejected.
4. `make test` leaves `git status --porcelain data/` empty (checked in the log).

## Verification

The new test module; `make harness-check`, `make benchmark-check`,
`make phase03c-invariants-check`, `make phase03c-rescore-check`, `make lint`,
`make typecheck`, `make preflight-fast`, `make test` followed by
`git status --porcelain data/`. No Compose gate (no runtime, worker, connector
or API change).
