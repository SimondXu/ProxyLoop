# ProxyLoop

> **Status: under construction.** This is the plan-v3 rebuild (stage S0). The retired v0 is at the git tag `v0-legacy`; its honest numbers and the résumé numbers it withdrew are in [docs/v0-retrospective.md](docs/v0-retrospective.md). Every result below renders from committed report JSON; empty sections mean the stage has not closed.

A small, real Pine-AI-style agent: one self-hosted Qwen3.5-9B (vLLM) chats with the user and talks live to a company rep while Claude Sonnet 5 plans from its typed relays. Transactions are guarded, unauthorised speech is measured, and status is evidence-verified.

<!-- gen:figure=architecture -->
<!-- /gen -->

## Demo

A replay of a **synthetic** bundle, recorded from the web replay, appears here once S1 closes. `make replay` needs no keys and no GPU.

<!-- gen:media=demo -->
<!-- /gen -->

## Results

Rows appear only as stages close (S2 instrument audit, S3 ablations and learning curve, S4 headline). No stage has closed yet.

<!-- gen:table=s2-ear-audit#per_class -->
<!-- /gen -->

<!-- gen:table=s3-ablations#paired -->
<!-- /gen -->

<!-- gen:table=s3-curve#lofo -->
<!-- /gen -->

<!-- gen:table=s4-l1-test#primary -->
<!-- /gen -->

<!-- gen:table=s4-talkact#rows -->
<!-- /gen -->

<!-- gen:table=s4-principalbench#diagnostic -->
<!-- /gen -->

### Claims

<!-- gen:claims -->
<!-- /gen -->

## What is real vs simulated

Generated from the evidence-check reality reports. Fast is self-hosted on vLLM with attested shards; Slow is Claude Sonnet via the relay; the counterparty is an LLM Ear and Mouth around a deterministic policy; the simulated user is an LLM plus a deterministic approver, or a human; the FSM appears only as a baseline. The world-model ids and their family relationship to the agent, teacher and baseline models are recorded in the relay ADR under `docs/decisions/`.

<!-- gen:table=reality#roles -->
<!-- /gen -->

## Authority model

What is guarded, what is measured and what is verified, and what is **not** claimed (ARCHITECTURE §9). The claim is exactly NORTH_STAR I6: guarded transactions, measured unauthorised speech and evidence-verified status. Nothing broader is claimed.

## The ML cycle

Environment → teacher in the harness (wall clock) → relabel student states → filters → dataset → BF16 LoRA → leave-one-family-out curve → pre-registration → dev selection → artefact lock → unseal → vLLM serving. The figure and the make target under each box arrive with S3/S4.

## Repository layout

See `ARCHITECTURE.md` §3 for the annotated tree and `AGENTS.md` for lane ownership.

## Quickstart

- `make replay`: replay a committed bundle (no keys, no GPU).
- `make demo`: live, with keys and a GPU; you are the principal.
- `make smoke-live FAMILY=…`: one live session.
- `make eval-l1`, `make curve`, `make data`, `make train`: reproduce evaluation and training.

These targets arrive during S0–S4; `make check` is the everyday gate.

## Documentation

- `NORTH_STAR.md`: goal and invariants. `PLAN.md`: state and tasks.
- `ARCHITECTURE.md`, `EVAL.md`, `TRAINING.md`, `DOCS.md`: design.
- `docs/decisions/`: ADRs. `docs/results/`: generated reports.
- `docs/v0-retrospective.md`, `docs/v0-worktrees.md`: the v0 reset.

## Limitations

<!-- gen:limitations -->
<!-- /gen -->

## Citation, licence and acknowledgements

TalkAct (MIT, Bojie Li / Pine AI) and PrincipalBench (MIT) are used as external diagnostics and are never trained on. Qwen3.5 is Apache-2.0. PreAct is credited as inspiration for an independently implemented workflow compiler (S5+).
