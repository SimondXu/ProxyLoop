# ProxyLoop Execution Plan

This is the harness-level phase index. Detailed product requirements live in the specification, and executable acceptance criteria live in the selected `harness/build/phase-*.md` file.

Canonical current authorization and active-phase state live in `harness/status.toml`. This file is the historical roadmap and phase index, not the live state source.

Phase 04A, Phase 04B, Phase 04C persistence, and Phase 04D control-plane
operations are separately gated control-plane slices. Their completion does
not promote a model or make a production-serving claim.

## Status

| Phase | Outcome | Status | Gate artifact |
|---|---|---|---|
| 00A | Repository foundation and documentation | Complete | Initial repository setup and layout validation |
| 00B | Canonical contracts and contract verification | Complete | `harness/build/phase-00b-contracts.md` |
| 01A | Thin deterministic Provider loop | Complete | `harness/build/phase-01a-provider-simulator.md` |
| 01B | Simulator breadth and benchmark gate | Complete | `harness/build/phase-01b-simulator-benchmark.md` |
| 02 | Data factory and trajectory pilot | Complete; squash merged as `f45b1ea` through PR #6 | `harness/build/phase-02-data-factory.md` |
| 03A0 | Fast/Slow architecture and acceptance criteria | Complete; squash merged as `54afcb8` through PR #7 | `harness/build/phase-03a0-fast-slow-architecture.md` |
| 03A1-H | Deterministic multi-turn evaluation harness | Complete; squash merged as `e08c9b6` through PR #8 | `harness/build/phase-03a1-harness.md` |
| 03A1-B | Untuned Qwen/Terra baselines | Complete; full gate passed through PR #9 | `harness/build/phase-03a1-baselines.md` |
| 03A1-E | Evaluation erratum and leakage-safe second run | Complete; terminal Provider blocker; PR #10 gates passed | `harness/build/phase-03a1-evaluation-erratum.md` |
| 03A1-R | Hosted baseline reliability rerun | Complete; corrected full matrix; r4 ready | `harness/build/phase-03a1-hosted-rerun.md` |
| 03A1-V | Evaluation-validity six-episode smoke | Complete; 5/6 diagnostic, evaluator mismatch isolated | `harness/build/phase-03a1-evaluation-validity-smoke.md` |
| 04A | Thin Agent Runtime | Complete; independently approved | `harness/build/phase-04a-thin-agent-runtime.md` |
| 04B | Model-backed Thin Agent Runtime | Complete; squash merged as `6daa1bc` through PR #13 | `harness/build/phase-04b-model-backed-runtime.md` |
| 04C | Persistent Case Store | Complete; independently approved in PR #23 | `harness/build/phase-04c-persistent-case-store.md` |
| 04D | Control-Plane Operations and Failure Evidence | Complete; independently approved; squash merged as `4258b95` through PR #24 | `harness/build/phase-04d-control-plane-operations.md` |
| Minimal local Web demo | Thin Runtime-backed conversation UI | Complete; squash merged through PR #18 as `ef2ce53`; post-merge Repository checks passed | `harness/build/phase-minimal-local-web-demo.md` |
| Local Conversation Intake UX | Four-fact Runtime-owned fictional Case intake and exact Web snapshot verification | Complete; squash merged through PR #20 as `02466df`; post-merge Repository checks passed | `harness/build/phase-local-conversation-intake-ux.md` |
| 03B | Open-data SFT, gap-driven project data, and evaluation | Complete; final `NO_GO_STOP_PHASE03B`; squash merged as PR #15 (`f441335` short); no promotion or expansion; Decided from Phase 03A1 failure slices | `harness/build/phase-03b-qwen-qlora-smoke.md` |
| 04 | Broader serving and control plane | Bounded 04A/04B/04C/04D complete; promoted serving deferred | Real-model serving, OOM/capacity, promotion, and production rollout remain separately gated |
| 05A | Durable agent loop / Temporal | Complete; independently approved | `harness/build/phase-05a-temporal-case-workflow.md` |
| 06A | Durable Web Case resume and progress | Complete; independently approved | `harness/build/phase-06a-durable-web-resume.md` |
| 06B1 | Local controlled mailbox | Complete; synthetic-only and independently approved | `harness/build/phase-06b1-local-controlled-mailbox.md` |
| 06B2 | Real controlled integration | Not started; separate user gate | Real Provider/email/MCP/credentials remain unauthorized |
| 07 | Portfolio hardening | Not started | To be prepared after Phase 06 |

## Critical Dependency Chain

```text
domain contracts
  -> simulator and deterministic verifier
  -> trajectory schema and data quality
  -> Fast/Slow routing and shared-state contract
  -> multi-turn evaluation harness and untuned baselines
  -> evidence-driven public/project data and post-training
  -> serving and business control plane
  -> Temporal durability and approvals
  -> controlled email/voice and UI
  -> reproducible portfolio evidence
```

The web UI is not the first roadmap implementation phase. A bounded local
Runtime-backed conversation demo may be built after the Case, approval, offer,
Evidence, and completion contracts stabilize; production UI and channels still
wait for a separate gate.

## Parallelization Policy

Phase 00B is intentionally narrow and mostly sequential because every downstream area depends on the same canonical contracts.

After contracts stabilize, Sol may run these workstreams in parallel when their ownership is independent and delegation materially improves execution:

- simulator transition engine and scenario authoring;
- deterministic verifier and adversarial test fixtures;
- benchmark/reporting infrastructure;
- read-only architecture or documentation review.

These remain sequential or require an integration gate:

- canonical contract changes before generated schemas and TypeScript types;
- simulator semantics before large-scale data generation;
- dataset gates before full training;
- model evaluation before serving promotion;
- policy/approval semantics before durable side effects;
- stable product contracts before production UI and channels.

## Goal Usage

Create a Codex Goal only when the user explicitly requests Goal tracking for an approved bounded objective. Do not create a permanent “finish the whole repository” Goal or use a loop to bypass human gates. Normal phase state lives in `harness/status.toml`.

Current gate:

> Phase 03A0 remains complete at `54afcb8`.
>
> Phase 03A1-H is squash merged as `e08c9b6` through PR #8. Phase 03A1-B completed its frozen model matrix, independent review, and PR #9 gates.

Phase 03A1-E completed its bounded gate with an honest terminal Provider blocker. The
immutable r2 evidence records one unknown-cost hosted failure and a global
zero-call abort; the source-bound r3 report corrects attribution offline with
zero new external dispatches. PR #10 passed phase-gate and GitGuardian.

Phase 03A1-R completed its bounded gate after correcting the model-facing Slow
union from unsupported `oneOf`/`discriminator` to OpenAI-supported `anyOf`.
The failed pre-correction r4 is preserved as a separate attempt artifact. Both
zero-retry probes and all four frozen hosted conditions completed through 29qg
with response identities and complete usage accounting; canonical r4 records
`phase_completion_ready=true`. This is an evidence-completeness result, not a
model-quality or training-readiness decision. Phase 03A1-V then isolated the
discovered model/oracle input mismatch and structured-output ambiguities on six
representative episodes: the same model path improved from 0/6 to 5/6 after
prompt/input parity, while the remaining fee case depends on a twelve-month
cost predicate absent from the visible goal. Phase 03A1-R/V was then squash
merged through PR #11 as `e501e0f`; its CI phase-gate and GitGuardian checks
passed.

Phase 04A Thin Agent Runtime is complete and independently approved. Its
bounded scope was a local FastAPI, simulator-backed loop with an in-memory
Case store interface, typed Fast/Slow routing, deterministic policy,
version-bound approvals, at-most-once fictional-Provider execution, Evidence,
completion verification, and one multi-turn integration path.

Phase 04B Model-backed Thin Agent Runtime is complete and squash merged through
PR #13 as `6daa1bc`. It adds one runtime-owned OpenAI-compatible typed
Fast/Slow adapter, mocked-transport failure gates, explicit opt-in model mode,
a local server command, and a localhost HTTP black-box smoke while retaining
the fictional Provider and deterministic authority boundaries.

Phase 04C Persistent Case Store is complete and squash merged through PR #23 as
`e64fa85`. It adds explicit opt-in PostgreSQL aggregate persistence, revision
compare-and-swap, strict decode/reconstruction, and deterministic fictional
Provider restart/recovery evidence behind the unchanged Case repository and
HTTP interfaces.

Phase 04D Control-Plane Operations and Failure Evidence is complete locally
and independently approved. It adds correlated allowlisted JSON operation
records, process liveness, read-only configured-storage readiness, stable
redacted failure categories, a credential-free local diagnostic profile, and
an explicit fake-model-to-scripted PostgreSQL switch proof. These are local
operational observations, not promoted-serving, production-capacity, real
Provider, deployment, or production-readiness claims. Phase 05A is complete
and independently approved. It adds the bounded scripted/PostgreSQL Temporal
CaseWorkflow without authorizing any real external effect or Phase 06 work.

Phase 03B is complete and squash merged as PR #15 (`f441335` short). The one
frozen six-scenario, 40-iteration QLoRA training run and one canonical B
evaluation completed as descriptive evidence. Clean Terra returned
`NO_GO_STOP_PHASE03B`, accepted by Sol, based on
Arm B schema/canonical/E2E `0/6`, six invalid JSON outputs, mostly unassessable
apparent safety zeros, unsupported `4/6`, and `arm_b_hard_gates_pass=false`.
That boolean is only a necessary detector-based safety summary, not sufficient
for experiment Go, evaluability, task quality, or promotion. No additional
training, data expansion, model rerun, promotion, deployment, or next phase is
authorized. No ML/roadmap implementation phase is active. The separate bounded
local Web demo was squash merged through PR #18 as `ef2ce53`; its post-merge
Repository checks passed, its fully merged short-lived branch was safely
removed locally and remotely, and the legacy local-only UI worktree/branch
remains preserved. The explicitly authorized Local Conversation Intake UX has
completed independent review, final PR-head CI/GitGuardian, squash merge
through PR #20 as `02466df`, post-merge Repository checks, and fully merged
branch cleanup. It is limited to four confirmed
fictional-telecom facts, one Runtime-owned Case, and exact Web snapshot
verification. The demo does not activate serving, channels, or production UI.
Phase 06A Durable Web Case resume and progress is complete locally and
independently approved. It preserves the existing conversation intake while
adding a strict browser Case locator, one exact pending-command retry,
readiness plus PostgreSQL GET-first recovery, monotonic projection handling,
bounded visible polling, truthful expiry/finalizing/reconnect states, and a
final authoritative Evidence read. Phase 06B1 Local controlled mailbox is
complete locally and independently approved: one synthetic, credential-free
mailbox with PostgreSQL channel authority and Temporal dispatch under the
unchanged Web flow. No product phase is active. Phase 06B2 and all real
Provider/email/MCP/credential/voice paths remain separate unauthorized gates.
Phase 03A1
continuation, r6/r7, model downloads,
additional PostgreSQL work beyond Phase 05A, real tools or Providers, authentication, channels, voice,
production UI, deployment, and release remain inactive.

Phase 04A recorded the offer-compliance result that had previously been an
open recommendation: one authoritative shared policy now consumes the same
explicit public inputs for Provider verification and the scripted oracle,
with shared fixtures and parity/adversarial tests. This result is complete
and does not authorize another evaluation run or a new implementation phase.
