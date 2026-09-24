# Build plan to complete

Adopted 2026-09-24 by the root orchestrator under decision 16
(`harness/context/audit-remediation-decisions.md`, decisions 16–20). This is
the resume order for the audit remediation and proposal work; live progress
stays in `harness/context/audit-remediation-status.md`. It is a plan, not a
phase contract: `harness/status.toml` stays `idle` until a PR needs one.

Baseline: `main` @ `d23aff9` (#80). Hard limits (decision 16) apply to every
PR: no real credentials, no real external channels or Providers (Phase 06B2),
no deployment or release, no hosted spend beyond a recorded budget, no
force-push, no destructive operation. Decision 17: every gate runs on
scripted adapters, Slow stays scripted, no further training.

Waves group the PRs in order; the per-PR dependencies and the serialization
rules below are what bind. "Architect first" means the root obtains an
`architect` proposal, decides, and freezes a spec under `harness/context/`
before an `implementer` starts. "DB" means the PR touches a service that
needs the real-dependency gates.

## Wave 0 — in flight

| Item | State |
|---|---|
| #80 B1-12 router precedence (lane A) | merged (`d23aff9`) |
| #81 B1-9 total offer policy (`fix/b1-9-total-offer-policy`) | open |
| #82 P2 API hygiene (`fix/p2-api-hygiene`) | open |
| `refactor/r14-basis-switch-owner` (R-14) | branch pushed, no PR yet |
| #83 contract-semantics limits (`docs/contract-semantics-limits`) | open |

## Waves 1–6 — PR-1..PR-17

| PR | Wave | Objective | Key files | Depends on | Architect first | Verification |
|---|---|---|---|---|---|---|
| PR-1 | 1 | Gate honesty: R-15 deterministic test for the ML concurrency ceiling; G-1 strong form — `make preflight` prints and pins the gated-skip count and names the real-dependency targets | `ml/tests/test_teacher_pipeline.py`, `Makefile` | — | no | `make preflight` |
| PR-2 | 1 | R-16: the expiry failure classifier reads the outermost typed `ApplicationError`; second workflow patch gate | `workflow.py` | — | no | `make preflight`; DB lane |
| PR-3 | 1 | R-17 + R-5: a channel ingest exhausted on the delivery activity is re-driven on redelivery; `expected_revision` is read under the lock. Reproduce first | `workflow.py`, `app.py` channel route | PR-2 (`workflow.py`) | no | `make preflight`; DB lane |
| PR-4 | 1 | R-18: the terminal codec rule pairs callback events with their Provider-event Evidence | `postgres_repository.py` | — | no | `make preflight`; DB lane |
| PR-5 | 1 | Ops/tests: C-5, C-7, C-8, R-6 | `scripts/run_phase_07a_portfolio_demo.py` (C-5), tests | — | no | `make preflight`; DB lane |
| PR-6 | 1 | B2-8: synchronous runtime calls run via `run_in_threadpool` | `app.py` | PR-3, #82 (`app.py`) | no | `make preflight`; DB lane |
| PR-7 | 2 | R-12 + R-13b: append-only model-trace log (rejected-result traces are written), `storage_version` 3 | `runtime.py`, `postgres_repository.py` | PR-4, R-14 branch | **yes** | `make preflight`; DB lane |
| PR-8 | 3 | Stage 1a: Fast dialogue reaches the product, scripted, through a deterministic disclosure gate, with per-turn measurement (`make fast-slow-split-report`) | `runtime.py`, `app.py`, `conversation-workspace.tsx` | PR-7 | **yes** | `make preflight`, `make web-check`; DB lane |
| PR-9 | 3 | Stage 1b: local distilled Fast backend via an `ml/serving` gateway + runtime HTTP Fast adapter + `PROXYLOOP_FAST_BACKEND`, with the local parity re-measure (decision 18) | `ml/serving/`, runtime Fast adapter | PR-8 | **yes** | CI uses a fake gateway; the local model run is manual and recorded in the PR log |
| PR-10 | 3 | Stage 4: Agent Status Bar, `render_status_block(snapshot)`; it must not become the distilled Fast prompt | `conversation-workspace.tsx`, a renderer module | PR-8 | no | `make preflight`, `make web-check` |
| PR-11 | 3 | Stage 1c: model-backed Fast under Temporal + a 07A launcher flag, inside the 30 s activity limit | `workflow.py`, launcher | PR-9, PR-3 | no | `make preflight`; DB lane |
| PR-12 | 4 | Stage 3: stateless `POST /intake/proposals` with a deterministic parser; a Web card replaces the wizard | `app.py`, `conversation-workspace.tsx` | PR-6, PR-10 | no | `make preflight`, `make web-check`; DB lane |
| PR-13 | 4 | Slow's proposal drives the intent + A-3 coordinator validator (replaces A-3a, decision 19); scripted Slow reproduces today's behaviour exactly | `runtime.py` | PR-8, PR-12 | **yes** | `make preflight` with every committed `*-check` byte-identical; DB lane |
| PR-14 | 4 | Stage 2: Judge seam — scripted Judge, at most one Slow retry, `role=judge` traces, evaluation never imports the Judge; feedback passed outside the contract (decision 20) | `runtime.py`, Judge module | PR-7, PR-13 | no | `make preflight` + an import-boundary test; DB lane |
| PR-15 | 5 | Narrow contracts 1.2 (decision 19: R-11b, B1-9b). Optional and droppable | `contracts.py`, contract fixtures | PR-10, #81 | **yes** | `make preflight` with every committed `*-check` byte-identical; DB lane |
| PR-16 | 6 | Phase 07: contract under `harness/build/`, demo scenes, `make ops-report` | `harness/build/`, demo scripts, `Makefile` | PR-14 (PR-15 if taken) | no | `make preflight`; DB lane; demo run recorded |
| PR-17 | 6 | Reports: `docs/ml-evidence.md`, architecture reconciliation (A-7f), observed-vs-proposed README, limitations and negative results, cost (relay ≈ USD 146, Modal USD 22.25), fresh-clone reproduction; `harness/status.toml` back to `idle` | docs | PR-16 | no | `make preflight`; fresh-clone reproduction recorded |

File paths: `workflow.py` =
`runtime/services/workflow_worker/src/proxyloop_workflow_worker/workflow.py`;
`app.py` = `runtime/services/api/src/proxyloop_api/app.py`;
`conversation-workspace.tsx` = `apps/web/app/components/conversation-workspace.tsx`;
`runtime.py` and `postgres_repository.py` exist in both
`runtime/packages/case_runtime/src/proxyloop_case_runtime/` and
`runtime/services/api/src/proxyloop_api/`; the single-writer rule covers both.

## Serialization rules

- **One DB-gate lane.** `make postgres-check` → `make phase05a-check` →
  `make phase06b1-check`, one PR at a time. The gates share the
  `proxyloop_test` database and fixed Case ids (R-9); implementers do not set
  `PROXYLOOP_TEST_*`.
- **One writer at a time** for `runtime.py`, `app.py`,
  `conversation-workspace.tsx`, `workflow.py` and `postgres_repository.py`.
  A PR that touches one of them merges `origin/main` after the previous
  writer merged (no rebase, no force-push).
- A fresh worktree needs `pnpm install --frozen-lockfile` before `make test`
  or `make preflight`.

## Do not do

- D3-5, D3-6 — `qwen_mlx.py` is frozen by r4.
- D1-10, D1-11, D1-12 — the V1 simulator is frozen (V2 supersedes it).
- D2-7, D2-8, D2-9, D3-8, D3-9 — left as recorded limits; D2-9 and D3-8
  earlier stood only if a check proved no committed report byte moves.
- D3-7 field deletion.
- A-9b (dropped, decision 19) and a `SlowWorkRequest.revision_feedback`
  field (decision 20).

## Blocked by the hard limits (stated as not done)

- V0 (hosted frontier in both slots), frontier-as-Fast and a second-family
  Judge: "not measured (budget)" (decision 17).
- Any further training or data expansion (decision 17).
- Production serving of the distilled adapter, real-model load, p95,
  capacity, OOM and automatic fallback under load (decision 18).
- Phase 06B2: real Providers, e-mail, MCP, SMS, credentials (decision 18).
- Deployment and release.

## Definition of done

1. Every Blocking and Important finding is closed, including R-12, R-16,
   R-17 and R-18; the remaining Minors are closed or recorded as
   frozen-evidence limits.
2. The credential-free 07A demo runs: free-text intake → typed card →
   confirmed Case → per-turn Fast dialogue through the disclosure gate
   (scripted by default, distilled opt-in) → Status Bar → Slow proposal →
   advisory Judge → approval → at-most-once execution → Evidence → verified
   receipt; the recovery and mailbox scenes still pass.
3. Local measurements are committed: the Fast/Slow split for scripted,
   distilled and untuned Fast, and the adapter parity re-measure.
4. The Phase 07 deliverables exist and a reviewer can reproduce the
   simulator benchmark from a fresh clone.
5. `make preflight` and the three DB gates pass serially on the final
   `main`, CI is green, and every material PR was independently reviewed.
6. Everything blocked is stated as not done.
