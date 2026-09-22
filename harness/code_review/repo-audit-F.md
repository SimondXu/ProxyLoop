# Repo audit — Lane F: documentation claims

Reviewer: `explorer` (Sonnet, medium), read-only. Recorded by the root
orchestrator from the lane's card; root verification at the end.

## Coverage of this pass

Fully traced: `README.md` implementation table, `PLANS.md` numeric and r4/r5
claims, every number in `docs/ml-evidence.md`, `docs/planning/progress.md`
counts, `docs/portfolio-demo.md` attestations, the 03B post-training review
numbers, and the module READMEs. Only keyword-grepped, not claim-traced:
`docs/architecture.md`, the spec, the four ADRs, `docs/ui/*`,
`docs/development.md`, `docs/README.md`, the Phase 02 annotation guide, the
initial plan, `GOALS.md`, `PROMPTS.md`. The ~14 non-numeric "Complete /
independently approved" rows in `PLANS.md` were confirmed only by the
existence of their `harness/build`, `harness/code_review`, and
`harness/log` files, not by re-reading acceptance criteria against evidence
(F-5). Lanes C, D1, D2, E carry that per-phase check for their own phases.

## Claim table (traced items)

| doc:line | claim | class | support |
|---|---|---|---|
| README.md:112 | multi-turn harness and untuned hosted baselines implemented | supported | `data/manifests/phase-03a1-ceiling-report.json` (`valid_outcome_count=32`), `data/evaluation/phase-03a1-r4-hosted-rerun-report.json` |
| README.md:113 | one QLoRA smoke ran and was stopped, `NO_GO` | supported | `data/experiments/phase-03b-qlora-smoke/results/comparison.md` |
| PLANS.md:24 | r4 records `phase_completion_ready=true` | supported | r4 report top-level field |
| PLANS.md:99-100 | probes and four hosted conditions completed with usage accounting | supported | r4 `probe_ready`, `cost_accounting_complete`, 4 hosted conditions |
| PLANS.md:104 | 0/6 → 5/6 after input parity | supported | r4 `untuned_fast_frontier_slow_medium.end_to_end_valid_count=0`; r5 `smoke_metrics.end_to_end_valid_count=5` of 6 |
| PLANS.md:141-143 | Arm B 0/6, six invalid JSON, unsupported 4/6, `arm_b_hard_gates_pass=false` | supported | `comparison.md` |
| ml-evidence.md:19-22 | "scripted oracle completes all 32" | **contradicted** | ceiling report: `completed_count=10`, `valid_noncompletion_count=22`, `valid_outcome_count=32` |
| ml-evidence.md:29-31, 41-42 | 32/32 schema-valid; best hosted E2E 3/32; r5 5/6; USD 0.117 | supported | r4 `slow_json_valid_count=32`, `frontier_reference_medium.end_to_end_valid_count=3`; r5 `actual_cost_microusd=117456` |
| ml-evidence.md:32 | A 1/6, B 0/6, `NO_GO_STOP_PHASE03B` | supported | `comparison.md` |
| progress.md:26-28 | runtime 291 + 33 skips, ML 177, web 47 "at the last gate" | stale | ML is 220 on `main` since PR #33 (`harness/log/phase-03c-stage0-rebaseline.md:129-130`: 177 existing + 43 new) |
| progress.md:12 | last completed phase 07A `763a1a9` | supported | git history |
| portfolio-demo.md:5, 112-115 | review passed; Browser evidence at 1280×900 / 375×812 | attested-only | `harness/code_review/phase-07a-…md` "Approve"; `harness/log/phase-07a-…md` Browser section |
| tests/README.md:3 | DB, workflow, channel, browser tests "remain deferred" | **contradicted** | `tests/integration/test_phase_04c/05a/06b1_*.py`, web vitest, Phase 06A/07A Browser evidence |
| ml/README.md:5 | runtime never imports the ML workspace | supported | `grep -rn "proxyloop_(evaluation|data_pipeline)" runtime` → none (root check) |
| research/2026-09-21-…review.md:19, 30, 100 | 03B and r4/r5 numbers | supported | same artifacts |

## Findings

**F-1 (Important) — `docs/ml-evidence.md:19-22` misstates the oracle ceiling.**
"The scripted oracle completes all 32 with zero false completions" — the
artifact records 10 completions and 22 valid non-completions; 32 is the
count of *valid outcomes*. A reader takes away that every scenario is
completable, which is false by design (fee-trap, forbidden-term, and
clarification families must not complete). Reproduction:
`python3 -c "import json;print(json.load(open('data/manifests/phase-03a1-ceiling-report.json'))['completed_count'])"`
→ `10`. Direction: "reaches a valid outcome on all 32 (10 completions, 22
correct non-completions)".

**F-2 (Minor) — `docs/planning/progress.md:27` test counts are one PR stale.**
Header says "checked 2026-09-21" but ML is 220 since PR #33 the same day.
Direction: either drop counts from progress.md (they live in each phase
log) or date-stamp them per gate.

**F-3 (Minor) — `tests/README.md:3` is a Phase 01A sentence contradicted by
main.** Direction: rewrite to list the actual test tiers and the guarded
real-dependency gates.

**F-4 — rejected.** `ml/README.md:5` is supported (root grep).

**F-5 (Note) — per-phase acceptance-vs-evidence not re-verified for the 14
non-numeric "Complete" rows.** Carried into lanes C, D1, D2, E for their own
phases; A covers 00B/03A0 contracts.

**F-6 (Note)** — every number in `docs/ml-evidence.md` other than F-1 traced
to a committed artifact.

## Docs to rewrite / merge

- `tests/README.md` — rewrite (F-3).
- `docs/planning/progress.md` — remove or date-stamp counts (F-2).
- `docs/ml-evidence.md:19-22` — correct wording (F-1).

## Terminology vs CONTEXT.md

Not checked in this pass (out of the lane's budget). Lane A reads
`CONTEXT.md` against `architecture.md` and the contracts.

## Checks run / not run

Run: `python3 -c` field reads on the ceiling, r2, r4, r5 reports and the
03B `comparison.md`; keyword sweeps across all docs and READMEs; existence
checks of harness artifacts per phase. Not run: full claim tracing of the
docs listed under Coverage; no test execution.

## Root verification (2026-09-21)

| Id | Verdict | Evidence inspected |
|---|---|---|
| F-1 | confirmed, Important | ceiling report fields printed above; `ml-evidence.md:17-23` |
| F-2 | confirmed, downgraded to Minor | `phase-03c-stage0-rebaseline.md:129-130` explains the delta (43 new tests in PR #33) |
| F-3 | confirmed, Minor | `tests/README.md` read in full |
| F-4 | rejected | root grep found no runtime → ml import |
| F-5, F-6 | accepted as Notes | — |
