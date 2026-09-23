# Feature log: V2 negotiation catalogue, N-turn state machine, V2 verifier (P1 D1-5, D1-8, D1-9)

Spec: `harness/context/feat-negotiation-v2-catalogue-preflight.md`.
Design and root decisions: `harness/context/d1-simulator-v2-design.md`
(slice P-C). Branch `feat/negotiation-v2-catalogue` from `main` @ `383d1fa`.

## What changed

- New `provider_simulator/negotiation_catalog.py`: typed `Hazard` set,
  single-hazard offer builders composed by `apply_offer_hazards`, nine
  families under `transparent-public-v2` and `retention-gated-v2` (18
  instances, namespace `negotiation-v1::<family>@1.0::<policy>@1.0`),
  Case-derived `compliance_context`, `offer_violations` (shared policy plus
  the bounded applied-change check), `expected_steps` from (hazards, policy).
  The builder asserts the hazard truth against the Case.
- New `provider_simulator/negotiation.py`: `ConsumerMessage` /
  `CapabilityAttempt` inputs, `NegotiationEnvironment` (fact request →
  quote → counter → final offer → confirmed/closed), I5 in
  `NegotiationTurn`, state-predicate `NegotiationVerification`, one
  idempotency namespace, `max_consumer_inputs`, and the V2 reference
  consumer `reference_input`.
- New tests `tests/test_negotiation_catalog.py` (7) and
  `tests/test_negotiation.py` (168 with parametrisation).
- No V1 file changed; `__init__.py` not changed (no re-exports needed yet).

## Acceptance evidence

- Probe D: `test_probe_d_multi_hazard_is_decided_by_offer_terms_not_a_transfer_flag`.
- Probe E: `test_probe_e_compliant_offer_with_transfer_is_accepted_not_escalated`
  (V1 default oracle still escalates on the same state; V2 escalation is
  `compliant_offer_available`).
- Probe G / I7: `test_probe_g_policies_differ_for_every_declared_family`,
  `test_i7_every_family_reference_trajectory_differs_between_policies`,
  `test_opening_accept_completes_under_transparent_and_is_false_under_retention`.
- `mt.py` port: `test_two_dialogue_acts_produce_different_transitions`,
  `test_no_message_ends_the_episode` (18 scenarios x 6 acts),
  `test_i2_text_is_recorded_but_never_decides_a_transition`,
  `test_retention_success_episode_has_at_least_three_provider_turns`,
  `test_per_input_idempotency`, `test_max_consumer_inputs_closes_the_episode`.
- I3, I5, I6: `test_i3_*`, `test_i5_*`, `test_i6_*`.
- Mutation checks (scratch, reverted, file restored byte-identical):
  putting transfer before accept in `reference_input` fails 6 tests;
  dropping the compliant-offer guard from the escalate predicate fails
  probe E.

## Verification (2026-09-23)

- `pytest runtime/packages/provider_simulator/tests`: 197 passed.
- `make lint`: exit 0. `make typecheck`: exit 0 (62 + 59 source files).
- `make format-check`: exit 0. `make preflight-fast`: exit 0.
- `make test`: exit 0 (runtime unit 880 passed, 42 skipped for
  PostgreSQL/Temporal; ml 381 passed, 1 skipped). Within it
  `benchmark-check`, `harness-check`, `phase03c-invariants-check`,
  `phase03c-rescore-check` printed their valid/consistent lines. The first
  run failed only in `contracts-check` because the fresh worktree had no
  `node_modules`; `pnpm install --frozen-lockfile --offline` fixed it.
- V1 untouched: `git diff origin/main --` `scenarios.py`, `environment.py`,
  `multi_turn.py`, `provider.py` is empty; `git status --porcelain data/` is
  empty after `make test`; `PROVIDER_VERIFIER_VERSION` unchanged.
- Not run: `make preflight` (Compose config), Compose gates (not needed:
  no `case_runtime`/`workflow_worker`/`connectors`/`api` change),
  `make web-check`.

## Deviations and notes

- P-B is not on `main`, and `provider_simulator` cannot import `agent_core`;
  the V2 reference precedence lives in `negotiation.reference_input`.
- The V2 reference has no approval step (the V2 Provider has no approval
  state) and no evidence step (P-D); a `counter` is tried once before
  escalating or declining. `expired-approval`, `refusal-transfer`,
  `revised-offer`, `plan-change`, `add-on-removal` are not V2 families;
  `forged-evidence` and `absent-evidence` wait for P-D.
- Disclosure: the reference `challenge`s a protected fact request and the
  Provider continues without it; the terminal `refuse_disclosure` action is
  still verified by its §8 predicate.
- `episode_ref` is an unsalted hash of the scenario id, like V1: content-free
  but reversible by a catalogue dictionary. The salted scheme and the leakage
  scan belong to P-E.

## Review (2026-09-23): Request Changes, no Blocking

Root decisions applied in the same branch:

- **F1** decline/end-interaction while an answerable fact request is pending
  (`AWAITING_FACTS`, every requested fact inside `allowed_disclosures`) is
  invalid, `pending_allowed_fact_request`. A decline at the retention opening
  stays valid (safe); P-E measures it (preflight "Carried to later slices").
  Reviewer one-shot agents over the 18 instances
  (`test_reviewer_one_shot_agents`):

  | Agent | before | after |
  |---|---|---|
  | always decline | 16 valid, 0 completed | 14 valid, 0 completed |
  | accept-if-compliant-else-decline | 18 valid, 2 completed | 16 valid, 2 completed |

- **F2** the V2 default Case (`default_negotiation_case`) forbids
  `remove_add_on:international_roaming` (a supported change); the builder
  asserts every single-hazard family's final offer carries exactly its own
  hazard-class code and rejects the V1 fixture Case for `forbidden-term`
  (`not isolated`). Multi ⊇ each single still holds.
- **F3** I4 literally: `completed` ⇔ the confirmation binds to the accepted
  offer; compliance lives in `valid_outcome`; `false_completion` is a claim
  (message claim or rejected accept) without `completed`. The retention
  opening accept is now `completed=True, valid_outcome=False,
  false_completion=False`; test renamed
  `test_opening_accept_is_valid_under_transparent_and_invalid_under_retention`;
  the design text in `d1-simulator-v2-design.md` is revised to match.
- Minor 1: the budget-closing turn carries no offer, request, or transfer,
  and a pending claim adds `completion_claimed_without_completion`.
- Minor 2: `build_negotiation_scenario(offer_ttl=, seconds_per_cursor=)`
  (defaults unchanged); new `NegotiationEnvironment.next_input_at`;
  `reference_input` takes `evaluated_at` and is fed `next_input_at`, so an
  offer expiring exactly at the next input is no longer accepted. Tests
  reach `offer_expired` and a valid `request_replan`.
- Minor 3: tests for `refuse_disclosure`, `request_clarification` (including
  `fee_total_mismatch`), `request_replan`, `end_interaction`.
- Minors 4–5 recorded in the preflight for P-E (policy-distinguishing text,
  unsalted `episode_ref`, id-only leakage test) and P-D (post-accept
  non-terminal state for the confirmation echo).

Reruns after the changes (2026-09-23): provider_simulator tests 208 passed;
`make benchmark-check` exit 0; `make phase03c-rescore-check` exit 0;
`make lint` exit 0; `make typecheck` exit 0; `make preflight-fast` exit 0;
`git status --porcelain data/` empty. `make test` was not rerun after the
review changes (it passed on the pre-review diff).

## Re-review (2026-09-23): Approve

The reviewer re-ran its probes: both naive agents 14/18 valid, the
accept-if-compliant agent 16/18 valid and 2/18 completed; forbidden-term
isolated to `forbidden_change_present` under both policies; the expiry
boundary and `request_replan` behave as specified; I2 (0 transition/turn
differences under text changes), I3, I5–I7 hold; V1 untouched. Its one Minor
— V2 `false_completion` no longer counts a hazardous accept, so V1/V2 counts
are not comparable — is recorded in the preflight as a P-E headline metric
(`completed ∧ ¬valid_outcome`).

Root, final diff: `make preflight` exit 0 — runtime 891 passed / 42 gated
skips, ML 381 passed / 1 skipped, web 52 passed; `git status --porcelain
data/` empty. Compose gates not run (no runtime/worker/API change).
