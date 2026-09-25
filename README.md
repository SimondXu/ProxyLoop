# ProxyLoop

**A durable consumer-negotiation agent that only claims completion when it can prove it.**

ProxyLoop represents a consumer in a bounded task — v1 is lowering a
(fictional) mobile phone bill — by collecting the consumer's goals and limits,
talking to the provider, asking for approval before anything consequential,
executing exactly once, and marking the case complete only from verified
Evidence. Authorization, side effects, and completion live in deterministic
code; language models only propose.

It is a simulator-first portfolio project. Everything runs locally with no
credentials, no real carrier, and no model download. See
[what is and is not implemented](#what-is-implemented) before reading further.

## Quick start

Prerequisites: Docker with Compose, [`uv`](https://docs.astral.sh/uv/),
[`pnpm`](https://pnpm.io/), Python 3.12, Node 22.

```bash
make portfolio-demo
```

This starts PostgreSQL and Temporal in Compose, then the workflow worker, the
FastAPI Runtime, and a production build of the Next.js Web app on loopback
ports (8000 and 3000; `RUNTIME_PORT=` and `WEB_PORT=` override them, and a
taken port fails closed), and prints the Web URL plus the scene order. Each
scene starts from fresh state (`make portfolio-demo-stop`, then
`make portfolio-demo-reset`, then `make portfolio-demo` again):

1. **Scene A — Web Case.** Open the Web URL and describe the bill in one
   message. The card shows what was read and asks only for what was not.
   Creating the Case brings in the fictional offer; Slow proposes it and a
   scripted Judge reviews that proposal (visible only in the Model Traces).
   Your confirmation turn gets one automated assistant line and opens the
   exact approval; the Status Bar follows each step. Approve, and the Runtime
   executes once and shows a receipt only after the Evidence predicate passes.
   Stop and restart the stack and the same Case comes back from
   PostgreSQL/Temporal.
2. **Scene J — scripted journey.** `make portfolio-demo-journey` drives the
   same HTTP routes and checks the whole journey, including an exact approval
   replay that does not execute again and the Model Trace counts.
3. **Scene B — controlled channel.** After `make portfolio-demo-reset` and a
   fresh `make portfolio-demo`, run `make portfolio-demo-channel` in a second
   terminal. It posts a SHA-256-fingerprinted synthetic provider e-mail (unkeyed
   integrity check, not authentication), replays it, and
   proves dedup, one delivery, one callback, two channel Evidence records, and
   that none of it leaks into the browser projection.

`make portfolio-demo-stop` stops everything and keeps data;
`make portfolio-demo-recovery` runs the Temporal lost-response recovery
check. `make ops-report` summarizes the gates and the committed local
measurements offline. Details, expected output, and troubleshooting are in
[docs/portfolio-demo.md](docs/portfolio-demo.md).

## How it works

```mermaid
flowchart LR
    subgraph Browser
        WEB[Next.js conversation UI<br/>apps/web]
    end
    subgraph Runtime["Python Runtime (uv workspace)"]
        API[FastAPI control plane<br/>runtime/services/api]
        WF[Temporal CaseWorkflow worker<br/>runtime/services/workflow_worker]
        CORE[Thin agent loop + policy<br/>case_runtime · agent_core · telecom_domain]
        FAST[Fast model adapter]
        SLOW[Slow reasoner adapter]
        SIM[Fictional provider simulator]
        MAIL[Synthetic local_mailbox connector]
    end
    subgraph Infra["Compose (local only)"]
        PG[(PostgreSQL<br/>Case + channel authority)]
        TEMP[Temporal server]
    end
    WEB -- "/cases, /approvals (Idempotency-Key, durable profile)" --> API
    API --> WF
    WF <--> TEMP
    WF --> CORE
    CORE --> FAST
    CORE --> SLOW
    CORE --> SIM
    CORE --> MAIL
    API --> PG
    CORE --> PG
    MAIL -- "signed raw-byte fixture" --> API
```

The design choices that matter:

- **Models propose, code decides.** A deterministic router splits each turn
  into a *Fast* view (small project-owned model, or the scripted policy) and
  optional *Slow* work (hosted reasoner). Both return typed structures that a
  policy gate checks against current Case state before anything happens.
- **Approvals are version-bound.** An approval pins the exact offer revision;
  a stale or drifted approval is rejected, not silently re-applied.
- **Approval-bound execution, evidence-gated completion.** Each approval
  executes at most once per Runtime process (executor ledger) and a
  persisted execution claim lets an interrupted command finish rather than
  re-execute in the durable profile; the fictional Provider's own state
  machine is the last line. The executor records content-addressed Evidence,
  and the verifier consults the provider's held state for accepted offers —
  a forged confirmation cannot complete a Case.
- **PostgreSQL is business truth; Temporal is orchestration.** The workflow
  orders commands, waits, retries, and recovers, but never owns Case state.
  Revision compare-and-swap protects every write.
- **The browser is a projection.** It stores a locator, the four confirmed
  facts, and one pending command for idempotent retry; it never holds
  channel content or provider references.

Full description: [docs/architecture.md](docs/architecture.md). Domain
vocabulary: [CONTEXT.md](CONTEXT.md).

## What is implemented

| Area | Status |
|---|---|
| Canonical contracts (Pydantic → JSON Schema → TypeScript, drift-checked) | Implemented |
| Fictional provider simulator, 16 scenario families × 2 configs, scripted oracle | Implemented |
| Thin agent Runtime: routing, policy, version-bound approvals, at-most-once execution, Evidence, completion verifier | Implemented |
| OpenAI-compatible Fast/Slow model adapter (explicit opt-in, no key in repo) | Implemented, not part of the demo |
| PostgreSQL Case store with revision CAS; liveness/readiness; redacted operation records | Implemented |
| Temporal `CaseWorkflow` with ordering, retries, and recovery | Implemented |
| Next.js conversation UI with four-fact intake and durable resume | Implemented |
| Synthetic `local_mailbox` channel (SHA-256-fingerprinted fixtures, inbox/outbox, dedup, callbacks) | Implemented |
| Multi-turn evaluation harness and untuned hosted baselines | Implemented (research) |
| Post-training of the Fast model | Phase 03C distillation ran and reached `GO_DISTILLED` (0.542 → 0.983 on held-out families); the earlier QLoRA smoke was stopped (`NO_GO`). The adapter is **not** promoted to serving — see [ML evidence](docs/ml-evidence.md) |
| Real e-mail / MCP / provider integration, voice, auth, deployment | Not started, separately gated |

The Web demo, mailbox, and recovery claims are local observations against the
deterministic simulator; they do not demonstrate production exactly-once
effects or real-provider delivery.

## ML evidence

The Fast model is meant to be a project-trained small model (Qwen3-8B), with
a hosted reasoner as the Slow model. Phase 03C trained one; nothing has been
promoted to serving, so the runtime still runs the untuned model.

Phase 03C distilled it from an oracle-filtered teacher set: 8,003
`claude-sonnet-5` samples, 807 quarantined (499 for disagreeing with the
scripted oracle), **7,196 accepted**; LoRA on 1.055 % of the parameters for
6.6 h on one A100. On 240 held-out rows from six scenario families that
appear in no training row, act agreement goes from **0.542 untuned to 0.983
distilled** — decision `GO_DISTILLED`, every raw output re-scored locally
against the repository evaluator with zero disagreements. No policy violation
fires on that set, but the set contains no disclosure-risk row, so that zero
is partly untested: on the in-family dev rows the distilled model still names
a restricted field 4 times in 400 (the untuned model, 7).

The write-up states what that does *not* show: the 240 rows carry only six
distinct decision rules, the gain is one repaired defect (the untuned model
almost never said `confirm`), the constrained-decoding arms were handicapped
by a token cap, and nothing has been promoted to serving. Earlier runs — the
evaluation harness, untuned baselines, a hosted reliability rerun, a
six-episode validity diagnostic (0/6 → 5/6 after fixing model/oracle input
parity) and the Phase 03B QLoRA smoke that returned invalid structured
output — are recorded with the same honesty, including costs.
Read [docs/ml-evidence.md](docs/ml-evidence.md).

## Repository layout

```text
apps/web/     Next.js conversation UI
runtime/      Python uv workspace: contracts, simulator, agent core, case runtime,
              connectors, OpenAI adapter, FastAPI service, Temporal worker
ml/           Data pipeline, evaluation, and experiment runners (separate env)
contracts/    Generated JSON Schema and TypeScript artifacts
data/         Versioned manifests, evaluation reports, and redacted samples
docs/         Specification, architecture, decisions, planning, evidence
harness/      Phase contracts, reviews, and execution logs (development governance)
infra/        Placeholders; live infrastructure is the root compose.yaml
tests/        Contract and integration lanes (collected by the runtime project)
voice/        Deferred LiveKit/SIP worker placeholder
```

## Development

```bash
make preflight-fast   # layout, syntax, whitespace — run while iterating
make validate         # format, lint, mypy, tests, contract drift, layout
make preflight        # the full local gate CI runs
make runtime-server   # scripted Runtime only, on 127.0.0.1:8000
```

The complete target list, model-mode configuration, the phase-gated workflow,
and the agent roles used to build this repository are in
[docs/development.md](docs/development.md). The documentation index is
[docs/README.md](docs/README.md); current authorization state is
[harness/status.toml](harness/status.toml).
