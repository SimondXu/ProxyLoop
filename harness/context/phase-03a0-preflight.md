# Phase 03A0 Preflight

Date: 2026-08-23

## Starting Point

- `main` commit: `f45b1ea` (`feat(data): add phase 02 trajectory pilot (#6)`);
- active branch: `docs/phase-03a0-fast-slow-architecture`;
- worktree before activation: clean and synchronized with `origin/main`;
- baseline `make preflight`: passed with 83 runtime tests, 12 ML tests, and all format, lint, type, schema/type drift, Phase 01B/02 artifact, layout, lock, compile, and Compose checks;
- Phase 02 review sample remains `pending_human` and `training_ready=false`.

## Observed Reusable Surface

- `FactLedger` is versioned, provenance-bearing Case state rather than a free-form memory blob.
- `StrategyPacket` binds Case and Fact Ledger revisions, expiry, constraints, disclosure policy, concessions, fallback outcomes, Evidence requirements, and replan/escalation conditions.
- `FastTurnDecision` is a proposal containing dialogue act, candidate fact updates, reasoner request, completion candidate, response text, and an optional Action Intent.
- Action Intent, Approval Request, Evidence, and Completion Decision already keep authorization and completion outside model output.
- `SafeObservation` provides a leakage-safe Provider-facing allowlist for one turn.
- Phase 01B provides family/entity/provider splits and a deterministic simulator/verifier ceiling.
- Phase 02 provides lineage, license, PII, deduplication, leakage, rejection, and artifact-drift plumbing, but only for one-turn scripted candidates.

## Observed Gaps

- no deterministic Router contract or mandatory Slow-trigger precedence;
- no shared Case-context snapshot or separate Fast/Slow model-view contract;
- no event cursor, planning-basis fingerprint, Slow work lifecycle, or stale-result semantics;
- no frozen capability manifest or sole execution authority;
- no explicit rule preventing Phase 03A1 Qwen outputs from using the optional Fast Action Intent;
- no multi-turn evaluation Agent, model adapter, model call, frozen multi-turn test set, or baseline report;
- roadmap/status documents still describe the already merged Phase 02 PR as pending.

## Public Pine Evidence Boundary

Observed from Pine's public material, checked 2026-08-23:

- Pine describes Fast as the low-latency conversational surface and Slow as concurrent deeper reasoning, planning, tool use, and longer work.
- Pine says Slow writes results through shared context and that structured task state should not be reduced to the transcript.
- Pine exposes one assistant while multiple background agents may work across longer tasks.

Unverified and therefore not copied or claimed:

- exact model identities or weights;
- Router code or thresholds;
- shared-context schema or persistence;
- version-conflict and stale-result algorithm;
- authorization and side-effect protocol;
- training data, objectives, or recipe.

Sources:

- https://www.19pine.ai/blog/pine-takes-no-1-on-taubench-voice-leaderboard
- https://www.19pine.ai/blog/pine-ai-the-most-natural-human-computer-interface-is-your-voice
- https://www.19pine.ai/blog/pine-launches-message-gateway

## Frozen Decisions

- Fast and Slow are independently replaceable interfaces behind one deterministic Case-coordination module.
- Shared state is a model-external structured snapshot; models receive separate allowlisted views and never communicate directly.
- Router rules own mandatory Slow work; Fast `reasoner_request` is advisory input to those rules.
- Fast performs bounded turn policy only; Slow performs complex planning and proposes capability/action work.
- Phase 03A1 accepted Fast outputs require `action_intent=null`.
- Models never authorize, execute, hold credentials, mutate business state, or decide final completion.
- Strategy validity uses material planning-basis pins plus existing business revisions and expiry, not event cursor alone.
- Fast/Slow reads may be parallel, while Case writes and side effects are serialized and version checked.
- Stale results are auditable rejected proposals and cannot patch current state.
- Phase 03A1 advertises local simulator capabilities only; external MCP, Gmail, telephony, and real Providers remain absent.

## Risks for Independent Review

- Router outcomes or mandatory triggers could overlap and leave priority ambiguous.
- Planning-basis fields could omit a material authorization, offer, Provider, or capability change.
- `fast_now_and_slow_refresh` could permit unsupported or consequential speech while strategy is stale.
- Slow tool proposals could be mistaken for executed tool calls or authorization.
- Disabling Fast Action Intent only in prose could drift during Phase 03A1 implementation.
- Pine self-description could be presented as verified internal implementation rather than external inspiration.
- Status corrections could accidentally overstate Phase 02 human review or training readiness.
