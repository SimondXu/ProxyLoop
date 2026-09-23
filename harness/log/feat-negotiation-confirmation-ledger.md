# Feature log: V2 confirmation ledger and evidence families (P1 D1-6, slice P-D)

Spec: `harness/context/feat-negotiation-confirmation-ledger-preflight.md`.
Design: `harness/context/d1-simulator-v2-design.md` §D1-6, I4. Branch
`feat/negotiation-confirmation-ledger` from `main` @ `a913733`.

## What changed

- `negotiation_catalog.py`: `Hazard.FORGED_EVIDENCE` / `ABSENT_EVIDENCE`,
  `EVIDENCE_HAZARDS`, `EVIDENCE_REASON_CODES`, `ConfirmationMode`,
  `NegotiationAction.CLAIM_COMPLETION`, families `forged-evidence` and
  `absent-evidence` (22 instances), `NegotiationScenario.confirmation_mode`,
  `offer_terms_hash` (canonical `material_terms_hash` over the six canonical
  terms), and an extra reference step after every accept (claim, or
  escalate/replan for the evidence families).
- `negotiation.py`: private ledger; `ProviderConfirmation` gains
  `material_terms_hash` and `binding`; `offer_binding`; the non-terminal
  `CONFIRMATION_ISSUED` state; `NegotiationTurn.confirmation_ref` replaced by
  `offer_accepted` + `confirmation` (echo), with a post-accept I5-style
  assertion; post-accept verifier predicates; `completed` from the ledger in
  every verdict, including budget exhaustion; the input budget also closes
  after a non-terminal accept; `reference_input(accepted_offer=...)`.
- Tests: `test_negotiation.py` updated for the claim step (reference driver
  remembers the accepted offer; opening-accept, idempotency, disclosure,
  retention-turns, one-shot-agent tests); new
  `test_negotiation_confirmation.py` (probe F, isolation, ledger authority,
  post-accept predicates, budget at accept, hash parity for 22 instances).
- No V1 file, contract, or `__init__.py` change.

## Evidence

- Probe F: `test_probe_f_public_turns_differ_on_the_confirmation_fields`
  (only `turn_id` and `confirmation` differ),
  `test_a_claim_on_bad_evidence_is_a_false_completion_with_its_own_code`.
- Ledger authority: `test_the_ledger_not_the_echo_decides_completion`.
- Reference: all 22 instances reproduce `expected_steps`, valid, no false
  completion; honest families complete (`CONFIRMED`), evidence families do
  not and end by `request_replan` (transparent) / `escalate` (retention).
- One-shot reviewer agents over 22 instances: always decline 16 valid;
  accept-if-compliant-else-decline with a naive claim 18 valid, 2 completed,
  2 false completions (P-C had 14 and 16 valid of 18).
- Mutation self-check (scratch, file restored byte-identical):
  M1 evidence check accepts any echoed ref → 1 failure (ledger test);
  M2 completion trusts the echo → 1 failure (ledger test);
  M3 reference always claims → 8 failures.

## Verification (2026-09-23)

- provider_simulator tests: 282 passed.
- `make lint` exit 0; `make typecheck` exit 0; `make preflight-fast` exit 0.
- `make test` exit 0 (runtime 975 passed, 46 skipped for the DB/Temporal
  gates without `PROXYLOOP_TEST_*`; ml 388 passed, 1 skipped), including
  `benchmark-check`, `harness-check`, `phase03c-invariants-check`,
  `phase03c-rescore-check`; `make benchmark-check` and
  `make phase03c-rescore-check` also run standalone, both valid.
- V1 untouched (`git diff origin/main` on `scenarios`, `environment`,
  `multi_turn`, `provider`, `episode`, `__init__` is empty);
  `git status --porcelain data/` empty after `make test`.
- Not run: `make preflight`, Compose gates, `make web-check`.

## Review (2026-09-23): Request Changes; all root decisions applied

- **B1 (Blocking)** every post-accept `valid_outcome` requires that the
  accepted offer had no violations, and the violation codes are appended to
  the claim/replan/escalate reasons. Regression
  `test_bad_evidence_after_a_non_compliant_accept_is_never_valid`
  (retention × {forged, absent} × opening accept × {replan, escalate}); with
  the guard removed the two replan cases fail (they were `valid=True`).
- **I1** the echo carries the bound material terms in readable form
  (`BoundTerms`: monthly price, twelve-month total, currency, term months,
  features, offer expiry) beside ref/offer id/revision/hash; V2
  `NegotiationTurn.to_dict` renders each offer's `material_terms_hash` (V1
  `PublicOffer` untouched); the reference compares id, revision, terms, and
  hash. Test: the forged echo's `term_months` is visibly +12.
- **I2** the ledger test is parametrized over the four honest families × both
  policies, plus (a) `LEDGER_BINDS_OTHER` (same ref, other binding, honest
  echo → `completed=False`, mismatch, false completion) and (b)
  `TAMPERED_ECHO` (honest ledger, tampered echo → `completed=True`, mismatch,
  claim invalid, `false_completion=False`).
- Minors: verdict `confirmation_ref` comes from the ledger entry binding the
  accepted offer (else `None`); the canonical-hash gap (`fees_minor`,
  `applied_changes` not hashed) recorded as a known limit in the preflight;
  hash parity over opening and final offers (44 cases); `CapabilityAttempt`
  docstring fixed; `_budget_exhausted` carries the accepted offer's
  violations and the ledger-bound ref (the M1 rule; equal to the echo ref
  whenever the echo is honest).

Mutations after the fixes (scratch, file restored byte-identical):

| Mutation | Failing tests |
|---|---|
| M1 evidence check reads the echo instead of the ledger | 16 |
| M2 completion trusts the echo | 24 |
| M4 drop the `entry != echo` clause | 8 |
| B1 guard removed | 6 |

Reruns (2026-09-23): provider_simulator tests 333 passed; `make lint`,
`make typecheck`, `make benchmark-check`, `make phase03c-rescore-check`,
`make preflight-fast` exit 0; `make test` exit 0 (runtime 1026 passed, 46
skipped for DB/Temporal gates; ml 388 passed, 1 skipped);
`git status --porcelain data/` empty.

## Re-review (2026-09-23): Approve

Naive one-shot agents over the 22 instances (`test_reviewer_one_shot_agents`):

| Agent | valid | completed | false completion |
|---|---|---|---|
| always decline | 16 | 0 | 0 |
| accept-if-compliant-else-decline, claims whatever it is shown | 18 | 2 | 2 |

Mutation counts recorded at re-review: 16 / 24 / 8 / 17 / 9 failing tests.
The first three are M1, M2, M4 above (run here); the last two are the
reviewer's own: "any ledger entry counts as completion" (17) and "B1
removed, violations cleared incl. budget reasons" (9), as reported by the
reviewer. Reviewer's naive consumers over the 22 instances: accept first
offer + check echo 6 valid / 18 completed / 0 false completions; accept
first + claim blindly 4 / 18 / 4; counter then accept + check echo 12 / 18
/ 0; counter then accept + claim blindly 8 / 18 / 4; counter then escalate
or decline 10 / 0 / 0 — no constraint-ignoring rule passes every family.

Closing items applied: `ProviderConfirmation.__post_init__` rejects readable
terms that do not hash to `material_terms_hash`
(`test_a_confirmation_cannot_pair_terms_with_another_hash`); the catalogue is
pinned to the `HONEST` / `FORGED_BINDING` / `ABSENT` modes
(`test_catalogue_emits_only_family_confirmation_modes`) and the test-only
modes are listed as P-E exclusions in the preflight. Rebased onto
`origin/main` @ `69924fe` (WIP commit, rebase, reset; no stash).

After the rebase: provider_simulator tests 335 passed; `make lint` exit 0;
`make typecheck` exit 0; `make test` exit 0 (runtime 1077 passed, 46 skipped
for DB/Temporal gates; ml 388 passed, 1 skipped);
`git status --porcelain data/` empty.

Root, final diff: `make preflight` exit 0 — runtime 1077 passed / 46 gated
skips, ML 388 passed / 1 skipped, web 96 passed; `data/` empty. Compose
gates not run (simulator-only change).
