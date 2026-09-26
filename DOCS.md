# ProxyLoop v3: Documentation as a deliverable

Three rules carry over from v2:
- numbers are never hand-typed (I10);
- every figure is generated;
- every stage gate includes the docs made true by that stage.

v3 adds a fourth: **a public artefact is a data release** (§8).

The reference shape is unchanged [O TalkAct, principal-loyalty and interaction-scaling READMEs]: claim → results with n/CI → what is where → how to run → docs index → limitations → citation.

## 1. Changes from v2
- The pitch uses the **narrowed authority claim** (I6), never "deterministic code owns every commitment".
- The stage-by-stage results sections appear only once the stage is closed: S1 no numbers; S2 the instrument audit; S3 the curve; S4 the headline.
- The TalkAct and PrincipalBench tables carry fixed wording: "our contemporaneous reproduction" and "diagnostic subset with matched-information controls".
- Publication safety: synthetic-only replay, and release-scoped approval by bundle hash.
- The claim ledger records the stage and whether the user closed it. A claim cannot be `final` before the stage closes.

## 2. README.md outline (`[gen]` = a generated block between markers)
1. **Title + pitch:** "A small, real Pine-AI-style agent: one self-hosted Qwen3.5-9B (vLLM) chats with the user and talks live to a company rep while Claude Sonnet 5 plans from its typed relays. Transactions are guarded, unauthorised speech is measured, and status is evidence-verified." Architecture figure.
2. **Demo:** a GIF recorded from the web replay of a **synthetic** bundle, and `make replay`.
3. **Results `[gen]`**, with rows appearing as stages close:
   - (S2) Ear audit: precision and recall per harmful class with CIs;
   - (S3) ablation table and learning-curve figure (LOFO), with cost per useful example;
   - (S4-a) L1 test: C1, C2, C2r, C2f, C3, C4 × safe success, realised harm (with the 0/n bound wording), blocked attempts, relay recall, false-completion claims, TTFS / time-to-heard p50/p95, $/episode;
   - (S4-b) TalkAct rows, labelled as our reproduction;
   - (S4-c) PrincipalBench diagnostic subset with the matched-information arms.
4. **What is real vs simulated `[gen]`**, from the evidence-check reality reports: Fast (vLLM, attested shards), Slow (Sonnet via relay), counterparty (Gemini Ear/Mouth + deterministic policy), user (Gemini + deterministic approver), human probes (n), FSM (baseline only).
5. **Authority model:** what is guarded, measured and verified (one table from ARCHITECTURE §9), plus what is *not* claimed.
6. **The ML cycle figure:** environment → teacher-in-harness (wall clock) → relabel student states → filters → dataset → BF16 LoRA → LOFO curve → pre-registration → dev selection → artefact lock → unseal → vLLM serve, with the make target under each box.
7. **Repository layout:** the annotated tree (ARCHITECTURE §3), with lane ownership noted.
8. **Quickstart:**
   - `make replay` (no keys, no GPU);
   - `make demo` (keys + GPU; you are the principal);
   - `make smoke-live FAMILY=…`;
   - reproduce evaluation and training (`make eval-l1`, `make curve`, `make data`, `make train`).
9. **Documentation index** (§3).
10. **Limitations `[gen from docs/limitations.yaml]`:**
    - simulator realism;
    - a held-out mixture of 3 families;
    - the relay dependency;
    - text, not voice;
    - the sim approver ignores FastU's text;
    - semantic laundering is measured, not blocked;
    - the cp-lane capability is a release token, not complete mediation;
    - the deviation log.
11. **Citation, licence and acknowledgements:** TalkAct (MIT, Bojie Li / Pine AI), PrincipalBench (MIT), Qwen3.5 (Apache-2.0); PreAct credited as inspiration for an **independently implemented** compiler (S5c).

## 3. `docs/` tree
```
docs/
├── architecture.md      # from ARCHITECTURE.md; updated at each stage gate
├── ml-cycle.md          # data → training → eval → serving; commands; artefact paths (S3, S4)
├── eval-protocol.md     # layers, schema, metric definitions [gen from eval docstrings], statistics
├── prereg.md            # S4 scientific pre-registration (signed) + deviations log
├── dataset-card.md  model-card.md   # HF-style front matter from day one (S3 draft, S4 final)
├── results/             # pl.report/1 JSON (the source of truth) + rendered .md; spend.json; rate_card.json; artefacts.lock.json
├── decisions/           # ADRs: 0001 relay, 0002 serving, 0003 training, 0004 contract v1, 0005+ contract changes, 0006 TalkAct anchor, …
├── releases/            # release manifests (§8); empty until the user approves a release
├── claims.yaml  limitations.yaml
├── figures/  media/     # generated + committed, with manifest.json of input hashes
└── v0-retrospective.md  v0-worktrees.md
```

## 4. Generated-results mechanism (owned by MOD: `eval/report.py`, `scripts/mod/render_docs.py`)
1. Reports are `pl.report/1` JSON: `{report_id, git_sha, contract_version, spec_hash, prereg_hash?, bundles: [{run_id, evidence_sha}], tables: {name: {columns, rows, n, ci}}, generated_at}`.
2. `render_docs.py` replaces only `<!-- gen:table=<report>#<table> -->…<!-- /gen -->` blocks.
3. **The claim ledger** `docs/claims.yaml` (root-owned):
   ```yaml
   - id: s4-sft-delta
     stage: S4
     template: "On never-piloted held-out families, safe success moved {c2:pct} → {c1:pct} (Δ {delta:pp}, 95% CI {ci}); pre-registered bar {verdict}."
     report: docs/results/s4-l1-test.json
     pointers: {c1: "/tables/primary/rows/C1/safe_success", …}
     evidence: [evidence/s4/…]           # must pass evidence-check --offline in CI
     status: provisional | final         # final only after the user closes the stage
     forbidden_words: ["guarantee", "deterministic code owns", "clean-room", "state of the art"]
   ```
   `render_claims.py` writes the README "Claims" subsection and `docs/results/resume_lines.txt`.
4. **`make docs-check` (CI) fails if:**
   - re-rendering changes any file;
   - a pointer does not resolve;
   - an evidence bundle is missing or fails the offline check;
   - a digit appears outside a `gen` block in a results section;
   - a claim uses a forbidden word;
   - a figure's input hashes differ from its manifest;
   - a `final` claim belongs to a stage that PLAN.md does not show as closed.

## 5. Figures (`scripts/mod/figures/` → `docs/figures/`)
| Figure | Input | Stage |
|---|---|---|
| `architecture.svg` | static spec | S0 |
| `timeline_<run>.svg` (two lanes + Slow + Guard, overlap, fence and revocation marks) | one bundle | S1 |
| `authority.svg` (fence and epoch sequence for a stop during approval) | the S1 gate bundle | S1 |
| `ear_audit.svg` | `s2-ear-audit.json` | S2 |
| `curve.svg` (LOFO Δ vs n, with fold spread) | `s3-curve.json` | S3 |
| `ml_cycle.svg`, `results.svg`, `latency.svg` | S4 reports | S4 |

## 6. Make targets
| Target | Needs | Does |
|---|---|---|
| `make check` | – | lint, typecheck, tests, P1/P2/P4 (+P6/P7 from S4), counterfactual test, import contracts, pilot-lock, seal-check, docs-check, web build |
| `make replay [RUN=]` | – | web replay over committed `evidence/` bundles |
| `make demo` | keys + GPU | serve-up + kernel server + live web (you are the principal; `REP=human` optional) |
| `make smoke-live FAMILY= [FAST=]` | keys + GPU | one real episode → bundle → `evidence-check --claim` |
| `make evidence-check RUN= [--claim\|--offline]` | – | chain verification + reality report |
| `make pull-through MODE=full\|verify` | keys + GPU | TRAINING §9 |
| `make eval-l1 SPEC=` / `make curve` / `make eval-talkact` / `make eval-principal` | keys + GPU | matrices → reports |
| `make data` / `make relabel` / `make dataset-check` / `make train` / `make select` / `make export` | keys / GPU | TRAINING §11 |
| `make figures` / `make docs` / `make docs-check` | – | generated docs |
| `make serve-up` / `make serve-down` | GPU | Modal vLLM lifecycle (a trap runs `serve-down`) |
| `make publish-replay` / `make publish-dataset` / `make publish-adapter` | release approval | §8; refuses without an approved release manifest |

## 7. Per-stage docs gate (part of each close in PLAN §0.7)
| Stage | Docs that must be true at close |
|---|---|
| S0 | README skeleton (sections, `gen` markers, "under construction"); `v0-retrospective.md`; ADR-0001…0004; `architecture.md` v1; `third_party/README.md` |
| S1 | README pitch (narrowed claim), architecture figure, `make replay` quickstart, authority model table, timeline + authority figures, the S1 claim (no numbers); `eval-protocol.md` §Metrics (provisional) |
| S2 | `eval-protocol.md` §Metrics frozen [gen]; the Ear-audit section and figure; limitations updated; the TalkAct anchor (if run) as "our reproduction" |
| S3 | the ablation table + curve figure [gen]; `ml-cycle.md` draft; `dataset-card.md` draft (funnel, cpue); the S3 claim or the honest negative |
| S4 | headline tables a/b/c [gen]; `prereg.md` (signed) + deviations; final model and dataset cards; `ml-cycle.md`; final claim ledger; demo GIF from a synthetic bundle |

## 8. Publication safety: a public artefact is a data release
- **Synthetic-only by default.** A bundle is publishable only if its reality report shows no `human` role: no human-typed principal or rep text, and no human-probe or audit-label content.
- **Release-scoped approval.** A release is `docs/releases/<release_id>.yaml`: `{release_id, kind: replay|dataset|adapter, bundle_hashes | dataset_hash | adapter_shards, approved_by: user, approved_on, scope}`. Every `make publish-*` target checks that `PL_PUBLISH_APPROVED=<release_id>` matches an approved manifest, and that every published file hash is listed in it. There is no global "publishing enabled" flag.
- **Scrub check (CI on release manifests):** no relay base URL, key-like strings, `.env` values, Modal workspace names or local paths in any published file; PII scan over synthetic names (generated from `gen: person_name` only).
- The HF card front matter exists from S3, so publishing is a flip, not a rewrite, and the flip is always a user decision.
