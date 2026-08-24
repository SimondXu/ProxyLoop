# Freeze Fast/Slow Orchestration and Shared Case Context

## Status

Accepted. Phase 03A0 passed independent review, preflight, CI, and GitGuardian, then squash merged to `main` as `54afcb8` through PR #7. Runtime contracts and implementations remain gated by Phase 03A1.

## Context

ProxyLoop trains or evaluates one low-latency Fast Model while retaining a hosted Slow Reasoner for complex work. The existing design correctly keeps business truth, authorization, side effects, and final completion outside models, but it did not define one deterministic routing authority, the shared-state protocol, stale-result behavior, or the exact boundary of Qwen training.

Without those decisions, a multi-turn harness could accidentally make Qwen responsible for strategy, tools, memory, approval, and completion, or allow two model calls to overwrite newer Case state.

Pine publicly describes a Fast system that maintains live conversation and a Slow system that reasons, plans, uses tools, and handles longer work over shared context. Pine also states that structured task state is more reliable than treating the transcript as ground truth. These are Pine's public, self-reported product principles. Pine has not published its router implementation, shared-state schema, version-conflict rules, authorization protocol, model identities, or training recipe. The protocol below is a ProxyLoop decision, not a claim about Pine's undisclosed implementation.

Public references checked on 2026-08-23:

- https://www.19pine.ai/blog/pine-takes-no-1-on-taubench-voice-leaderboard
- https://www.19pine.ai/blog/pine-ai-the-most-natural-human-computer-interface-is-your-voice
- https://www.19pine.ai/blog/pine-launches-message-gateway

## Decision

### One coordinator, two model interfaces

`agent_core` will expose one deep Case-coordination module whose external interface advances a Case from an immutable context snapshot and one triggering event. Its implementation owns deterministic routing, model-view projection, result validation, stale-result handling, and handoff to policy, approval, execution, and verification modules.

Fast and Slow remain separate, replaceable model interfaces:

- the Fast interface consumes a `FastModelView` and returns a `FastTurnDecision`;
- the Slow interface consumes a `SlowWorkRequest` and returns a `SlowWorkResult` containing a version-bound strategy and bounded capability/action proposals;
- neither model calls the other or mutates shared state;
- local deterministic adapters are required for evaluation tests before remote model adapters are promoted.

### Authority matrix

| Concern | Sole authority | Model role |
|---|---|---|
| Mandatory Fast/Slow scheduling | Deterministic Router | Fast may request Slow, but cannot suppress or force routing. |
| Low-latency dialogue, candidate facts, and escalation signal | Fast Model | Proposal only. |
| Strategy, complex reasoning, and bounded capability/action plan | Slow Reasoner | Proposal only. |
| Schema, disclosure, delegated authority, capability, and current-state validation | Deterministic policy gate | Models supply inputs, never authorization. |
| Version-bound consequential permission | Approval coordinator and Consumer decision | Neither model approves. |
| Simulator, tool, MCP, or channel invocation | Capability executor | Models never execute. |
| Business facts, offers, approvals, Evidence, and Case state | Model-external Case state | Models read allowlisted projections. |
| Final completion | Deterministic verifier | Models may create completion candidates only. |

### Shared Case Context

Models share structured Case state, not model memory. `CaseContextSnapshot` is an immutable projection of authoritative state at one event cursor. It includes:

- Case, Consumer Goal, constraints, and Delegated Authority revisions;
- Fact Ledger revision and supported facts;
- current Strategy Packet and its planning basis;
- current offers, Action Intents, Approval Requests, Evidence, and completion state;
- recent Provider-visible events and the event cursor;
- pending Slow work and pending execution status;
- Provider episode/configuration reference;
- capability-manifest version.

It excludes hidden chain-of-thought, model KV caches, raw prompts, free-form model memory, Provider-private policy or database state, reference actions, rewards, evaluator criteria, and gold outcomes.

Separate allowlisted projections are derived from the same snapshot:

- `FastModelView` contains the current valid Strategy Packet, verified facts, a bounded recent visible-event window, latest Provider event, pending Slow status, and allowed dialogue/disclosure policy.
- `SlowReasonerView` contains a broader safe Case snapshot, relevant visible-event history or deterministic summary, current strategy, reason for work, domain policy, and the current capability manifest.

The transcript is evidence-bearing event history, not the authoritative representation of goals, facts, approvals, offers, or completion.

### Routing

The Router produces one version-bound `RoutingDecision`:

- `terminal`;
- `verify_only`;
- `wait_for_approval`;
- `slow_refresh`;
- `fast_now_and_slow_refresh`;
- `fast_now`.

Every decision records deterministic reason codes and the snapshot pins that produced it. Mandatory Slow work takes priority when any of these conditions holds:

- Case initialization;
- changed Consumer Goal, hard constraint, or Delegated Authority;
- Provider refusal or a materially changed offer;
- expired or planning-basis-incompatible Strategy Packet;
- conflicting facts;
- stalled or repeated dialogue;
- Fast `reasoner_request` accepted by Router policy;
- proposed high-risk or consequential action;
- verifier outcome `needs_replan`, or a completion candidate whose strategy/basis is missing, expired, or incompatible;
- new Evidence that can change the strategy or completion decision.

Fast remains available only for dialogue permitted by the current valid strategy. In the text research MVP, mandatory Slow refresh may complete synchronously before Fast proceeds. The interface also supports a later `fast_now_and_slow_refresh` path for bounded acknowledgements while Slow works concurrently; voice/full-duplex behavior is not implemented in Phase 03A1.

Routing outcomes are mutually exclusive. The Router evaluates the following precedence table top to bottom and emits exactly one outcome: the first match.

| Priority | Outcome | Exact selection condition |
|---:|---|---|
| 1 | `terminal` | The Case is already in a verified terminal state. No model or executor work is scheduled. |
| 2 | `verify_only` | New executor/Provider Evidence or a completion candidate awaits deterministic verification. The verifier runs before any replan; a `needs_replan` result creates a new event that is routed again. |
| 3 | `wait_for_approval` | A current, unexpired Approval Request blocks consequential work and the triggering event is not the Consumer's approval decision. Approval decisions go directly through the approval/current-state gate; resulting execution Evidence is routed again at priority 2. |
| 4 | `slow_refresh` | A mandatory Slow trigger exists and no current strategy permits a bounded non-consequential acknowledgement. Fast waits. |
| 5 | `fast_now_and_slow_refresh` | A mandatory Slow trigger exists, while a current strategy and disclosure policy explicitly permit a bounded acknowledgement, clarification, or status response that cannot state material terms, accept an offer, or trigger a side effect. |
| 6 | `fast_now` | A current compatible strategy exists, no higher-priority condition matches, and the event requires a normal dialogue turn. |

Events handled entirely by deterministic policy, approval, execution, or verification modules do not create a second model route in the same decision. If one of those modules appends Evidence or changes material state, the coordinator projects a new snapshot and runs this algorithm again.

### Planning basis and stale results

Strategy validity is bound to a `planning_basis_fingerprint` computed from material state: goal, constraints, delegated authority, verified facts, material offer set, active approval state, Provider configuration, and capability-manifest version. A non-material conversational event advances the event cursor but does not automatically invalidate the strategy.

Fast and Slow may read the same immutable snapshot concurrently. A Case has one serialized state-write and side-effect lane. Every model result echoes its input pins. Before accepting a result, the coordinator compares those pins with current state:

- a stale Fast result is traced and rejected without sending its response;
- a stale Slow result is traced and rejected without merging or patching the old plan;
- both cases return to deterministic routing on the latest snapshot;
- an executor result is recorded idempotently as immutable Evidence, then evaluated against current state.

This compare-and-swap behavior is implemented locally for the text research MVP. Temporal later supplies durable waits and retries; it does not own the validity rules.

### Capabilities and side effects

A versioned `CapabilityManifest` is the only action/tool vocabulary available to models and the executor. Phase 03A1 contains local fictional-Provider simulator capabilities only. It does not advertise MCP, Gmail, telephony, LiveKit, real Provider, or production credentials.

Slow may propose a bounded capability/action plan. The deterministic compiler and policy gate translate a valid proposal into inert Action Intents. The capability executor is the only module allowed to invoke an adapter and must re-check current strategy/basis, authorization, approval, expiry, and idempotency immediately before execution.

The existing optional `FastTurnDecision.action_intent` wire field remains backward-compatible, but Phase 03A1 Fast requests and accepted outputs require it to be `null`. Enabling any Fast-originated side-effect proposal requires a later explicit contract and evaluation gate.

### Qwen training boundary

The Fast Model may be trained or evaluated only for:

- dialogue-act selection;
- concise provider-facing response conditioned on a valid strategy;
- candidate fact extraction with visible-message provenance;
- reasoner-request classification;
- completion-candidate classification.

It is not trained to own strategy generation, multi-step tool selection or argument planning, MCP/phone execution, long-term memory, approval, consequential acceptance, Evidence verification, final completion, credentials, or workflow durability.

## Alternatives Considered

- **One all-purpose Qwen Agent:** rejected because a 4B Fast Model would own complex reasoning, execution, and memory that the architecture deliberately keeps outside it.
- **Slow on every turn:** rejected because it removes the latency/cost hypothesis and makes Fast value impossible to measure.
- **Fast decides whether Slow runs:** rejected because stale strategy, high-risk action, and completion checks require mandatory deterministic triggers.
- **Shared transcript as memory:** rejected because unverified prose cannot replace versioned facts, approvals, offers, Evidence, or completion state.
- **Implement production concurrency with Temporal now:** rejected because the text evaluation MVP needs deterministic local concurrency semantics before durable infrastructure.

## Consequences

- Phase 03A1 must implement the Router, context projections, model interfaces, stale-result rules, simulator-only capability manifest, and multi-turn evaluation harness before any Qwen benchmark.
- Phase 03A1 must compare untuned Fast with Slow disabled and enabled, plus scripted-oracle and frontier reference baselines.
- Open-data SFT and project-specific generation remain later evidence-driven decisions.
- Canonical Phase 00B contracts are not changed by this decision; any wire-schema change requires its own implementation and drift gate.
