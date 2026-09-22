# Docs log: audit claim corrections (P0-4)

Audit backlog row 4 (`docs/research/2026-09-21-repository-audit.md` §6) and
the §7 table of unsupported claims. Branch `docs/audit-claim-corrections`
from `main` @ `0dcd25f` (after P0-1 #38, P0-2 #39, P0-3 #40, P0-8 #43).
Scope: current-state, doc-only rows; design claims reserved to the user
(§8) and historical `harness/` artifacts are untouched.

## Corrections

| File | Claim | Now says | Finding |
|---|---|---|---|
| `README.md` | "At-most-once execution" | approval-bound: per-approval executor ledger, persisted execution claim in the durable profile, Provider state machine last line | C-1 (fixed by P0-1), B1-1 (P0-2) |
| `README.md`, `docs/planning/progress.md` | "signed" / "HMAC-signed" fixtures | SHA-256-fingerprinted, unkeyed (integrity, not authentication) | C-6 |
| `README.md`, `progress.md`, `docs/ui/user-flows.md` | `Idempotency-Key` exact retry | honoured in the durable Temporal profile; direct mode ignores the header | B2-4 |
| `docs/ml-evidence.md` | verifier inspects provider state; oracle "completes all 32"; "zero private-field leakage"; r5 "same public inputs"; "USD 0.117 spend"; "harness works" | state only for accepted offers, label equality otherwise; 10 completions + 22 valid non-completions; no private keys but family ids in values; r5 prompt carried the oracle's decision rules (rule-following); cost is usage × assumed tariff | D1-3/D2-3, F-1, D1-1, D2-1, D2-11 |
| `PLANS.md` | 03A1-B "full gate passed"; r5 parity; "one authoritative shared policy" | complete with erratum (r1 Slow prompts carried the accept label on 10 episodes); rule-following; default eval oracle is still the legacy predicate (agrees 32/32) | D2-4, D2-1, B1-5 |
| `progress.md` | test counts 291/177/47 | measured on this branch: runtime 316 + 39 gated skips, ML 318 + 1 skipped, Web 51 | F-2 |
| `tests/README.md` | DB/workflow/channel tests "deferred" | they exist; the PostgreSQL/live-Temporal tests are env-gated (39 skips) with the three make gates | F-3 |
| `contracts/README.md` | OpenAPI artifacts generated here | `make contracts` writes JSON Schema + TypeScript; no OpenAPI yet | G-2 |
| `apps/README.md` | run Runtime and Web separately | direct mode caveats: one Case per process (default in-memory), ignores the key, no resume after reload | E-4 |
| `GOALS.md`, spec header | Qwen3-4B default | Qwen3-8B per the 2026-09-21 amendment | A-7a |
| `docs/architecture.md` | Research MVP "no Temporal" | Temporal added in 05A as the durable profile | A-7b |
| ADR fast-slow | "gated by Phase 03A1" | 03A1 completed | A-7c |
| `CLAUDE.md` | `make preflight` final gate | notes the 39 gated skips and when the real-dependency gates are required | G-1 |
| `tests/contract/test_phase_03a1_architecture.py` | pinned the old 03A1-B wording | asserts "Complete with erratum" | — |

Not changed: `docs/architecture.md` executor/receipt claims (true after
P0-1/P0-2), the five verifier outcomes (A-7f, design target), Fast/Slow
turn-share and `ModelTrace` claims (§8 decisions), historical phase
contracts and reviews, `docs/ui/state-matrix.md` (updated in P0-8). The
audit row's test item ("validity-smoke leakage test scans for the oracle
rule vocabulary") is deferred to Group 2: the committed r5 prompt does
contain the rule table, so the test can only be made honest together with
the r5 relabel, not by tightening the assertion.

## Checks

- Passed: `make preflight` on the rebased branch — runtime 316 / 39
  gated skips, ML 318 / 1 skipped, web 51, all artifact and layout gates
  valid; `tests/contract/test_phase_03a1_architecture.py` 7 passed.
- Independent review (`reviewer`, Opus): first pass **Request Changes** —
  B1 the PLANS.md wording broke the contract test (fixed by updating the
  assertion); I1 counts were stale (re-measured after rebase); I2
  `tests/README.md` over-claimed which suites are gated (reworded to the
  reviewer's wording); minors M1–M4 applied (accept-label wording,
  Group 2 anchor, in-memory qualifier, spec header amendment,
  `architecture.md` Temporal line). Every other hunk verified against
  primary evidence (path:line in the review).
