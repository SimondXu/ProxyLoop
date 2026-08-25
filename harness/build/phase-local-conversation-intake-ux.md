# Local conversation intake UX

**Status**: Local implementation and independent review complete on
`feat/local-conversation-intake-ux` from `main@0d0acb3`; integration is through
PR #20. The phase remains active until that PR merges; the merge closes this
phase without activating another.

## Objective

Replace the local Web demo's implicit fixed-Case creation with one explicit,
conversation-first intake for four fictional-telecom facts. The Runtime must
own the authoritative canonical Case, the Web must verify that returned state
matches the user's confirmed draft, and the existing deterministic event,
authorization, approval, Provider Evidence, execution, and completion path
must remain unchanged.

## Frozen authority and scope

- The HTTP boundary owns one API-local `CreateCaseRequest`; no canonical public
  contract or generated schema changes.
- The four required request fields are:
  - `current_monthly_total: Money`
  - `target_monthly_total: Money`
  - `mobile_hotspot_required: Literal[True]`
  - `device_financing_change_forbidden: Literal[True]`
- Extra and missing fields fail closed. Both Money values must be USD. The
  fixed fictional `$72` offer requires `current > $72` and
  `$72 <= target < current`; unsupported requests return HTTP 422 before any
  Runtime state is stored.
- `ThinAgentRuntime.create_case()` may retain the current fixture defaults for
  direct harness callers, but the HTTP route always supplies all four explicit
  facts.
- The Runtime rebuilds and revalidates one canonical `Case`. It may vary only
  the current and target Money values; required hotspot, forbidden financing
  change, and the matching hard constraint retain their canonical identities.
  The current bill keeps a `$10` premium add-on and assigns the remainder to
  mobile service.
- Intake facts are immutable after create in this phase. No PATCH, correction
  endpoint, generic mutation surface, dynamic Provider behavior, persistence,
  or entity-ID redesign.
- The Web sends no Runtime request while intake is incomplete or merely
  drafted. One explicit user action creates the fictional Case.
- The Web compares the locally confirmed draft with both the create response's
  root Case and `snapshot.case`, including the Case identity, exact Money
  values, exact required-feature and forbidden-change sets, and matching hard
  constraint. Every later snapshot-bearing response must retain those facts.
  Missing or mismatched authoritative state is blocked, never shown as
  verified.
- Existing session-generation protection continues to invalidate late create,
  event, or approval responses after restart.
- After authoritative create, changing a fact cannot be represented locally.
  The UI must explain that the user must restart the local Runtime and then
  start a New task. This limitation is due to fixed deterministic fixture IDs;
  this phase must not hide it or expand storage/identity scope to remove it.

## Frozen UX

- Preserve the existing calm, conversation-first, three-column local demo and
  native-CSS visual system. This is a preserve-mode product extension, not a
  landing-page redesign or production UI activation.
- Progressively collect current bill, target bill, required mobile hotspot,
  and forbidden device-financing change. Use strict USD parsing and clear
  inline retry guidance for malformed, negative, other-currency, false fixed
  constraints, or fixed-offer-incompatible values.
- Show a visibly local `Draft Task Brief` with missing/confirmed status and an
  Edit action for each fact. Derive readiness during render; do not duplicate
  it in effect-managed state.
- Provide one explicit, non-wrapping `Create fictional Case` action only when
  all four facts are valid. Preserve labels, helper/error text, keyboard focus,
  contrast, busy/disabled/error states, and mobile readability.
- After exact Runtime confirmation, replace the local draft with the existing
  Runtime-verified Task Brief and continue the current one-event constraint,
  offer, exact approval, and Verified receipt flow.
- Design read: preserve-mode localhost portfolio product UI for technical
  recruiters, calm and trust-first, using the existing native CSS. Design
  dials are approximately variance `4`, motion `2`, density `5`.

## Acceptance criteria

1. Opening/supported conversation input begins local progressive intake and
   does not call `POST /cases`.
2. Draft correction is local, preserves other confirmed facts, and cannot
   bypass the four required facts or the explicit create action.
3. A valid create request contains exactly the frozen four fields. The Runtime
   response's root Case and nested snapshot contain exactly the confirmed
   facts in existing canonical locations.
4. Missing/extra/false/unsupported-currency/malformed/negative/
   fixed-offer-incompatible requests return 422 and do not create state.
5. Existing direct Runtime fixture callers remain compatible.
6. Root-vs-snapshot, confirmed-draft, and later snapshot fact drift blocks the
   UI. It cannot expose a confirmation, approval, or receipt action.
7. Existing consumer-event, deterministic authorization, exact approval pins,
   Provider Evidence, at-most-once execution, completion, and stale-response
   behavior remain unchanged and covered by regression tests.
8. Post-create correction truthfully names the Runtime-restart/New-task
   boundary and performs no authoritative mutation.
9. Desktop and `375px` browser smoke pass without horizontal overflow or
   unaccounted console warnings/errors. A temporary non-production fault aid
   demonstrates semantic mismatch fails closed.
10. Repository-native focused checks, Web lint/typecheck/test/build,
    `git diff --check`, `make check-layout`, and complete `make preflight` pass;
    any environment aid is disclosed and removed.
11. A fresh independent Terra review has no unresolved P0/P1/P2 findings before
    the PR gate.

## Required tests

### Runtime/API

- exact valid create request-to-canonical-Case mapping;
- every frozen 422 validation class and no stored Case on rejection;
- direct fixture-call compatibility;
- event snapshot preserves intake facts;
- unchanged approval/Evidence/completion behavior;
- existing Phase 04A/04B HTTP create callers send the explicit request.

### Web client and workspace

- exact create serialization;
- malformed payload, Case-identity disagreement, root-vs-snapshot mismatch,
  draft mismatch, and later fact drift fail closed;
- progressive prompts, strict USD parsing, no early create, local editing,
  explicit confirmation, and exact request payload;
- create/event/approval stale-response restart guards;
- existing 409/503/network, exact pins, missing/mismatched Evidence, and
  terminal-unverified cases.

## Verification and integration

One Luna xhigh implementer owns the bounded implementation. Sol reads every
changed source file and the complete diff, runs local verification and Browser
smoke, and reconciles independent Terra review evidence. Only after the local
and independent gates pass may Sol commit, push, open a bounded PR, wait for
fresh PR-head CI/GitGuardian, approve, squash merge, verify post-merge `main`,
and clean only the fully merged short-lived branch.

## Explicit exclusions retained on the roadmap

This phase does not implement authentication/accounts, persistence/PostgreSQL,
Temporal, real tools/Providers/models, external channels, voice, deployment,
release, training/evaluation expansion, another journey or vertical, dynamic
pricing, general NLP, a generic form/state-machine framework, production UI,
or canonical contract/schema changes. Deferral here is not permanent roadmap
removal. Stop and escalate if any excluded capability becomes necessary.
