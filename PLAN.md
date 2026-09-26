# PLAN.md: the single state file

**Current:** S0 in progress (the user gave the go on 2026-09-26). **Merged:** S0-ROOT-01, S0-ROOT-02, S0-ROOT-03, S0-ROOT-04, S0-SYS-01, S0-SYS-02 (#115), S0-ROOT-07 (#114), S0-CON-01 (#116), S0-MOD-01 (#113, provisional: `serve-attest-local` pending the user's go), S0-ROOT-08 (#117), S0-SYS-03 (#118), S0-SYS-04 (#120), S0-SYS-05 (#121), S0-MOD-02 (#119). **In flight:** S0-SYS-06, S0-ROOT-09 (this PR). **Next:** S0-ROOT-05 (merge point 1). **Last closed stage:** none. **Contract version:** v1 (ADR-0004; fingerprints `pl_user_v1` = `796d2843964be1f552b18836093915744a6c543d1fab148ad3ca10d50e5f9cfb`, `pl_cp_v1` = `76a0185865410a3e30755be079c5b539180171114ce82e0a6c8c4a0bb668b490`).

**Merge authority:** granted to the root by the user on 2026-09-26, from S0 on until revoked: the root squash-merges PRs that pass the fresh-context reviewer, CI and the reality rule. Stage closes, contract changes after `semantics-v1`, publishing, the split draw, the unseal and destructive steps still need the user.

Changes to this file are root decisions, written by an implementer whose packet grants it (§0.1). The PR description is the log. Design lives in `NORTH_STAR.md`, `ARCHITECTURE.md`, `EVAL.md`, `TRAINING.md`, `DOCS.md` and `docs/decisions/` (ADRs).

Legend:
- lanes: **CON** (contract), **SYS** (system), **MOD** (model), **ROOT** (the root decides, runs L/G/U and merges; an implementer writes the files, §0.1);
- flags: **L** live keys, **G** GPU, **U** needs the user;
- sizes: S ≤ 300 changed lines, M ≤ 700, L ≤ 1,200 (excluding tests and goldens) [E];
- status: `todo | doing | review | provisional | done | blocked`.

---

## 0. Operating rules

### 0.1 Task execution
- **One task = one PR = one implementer, in its own git worktree.**
  - The root creates the worktree with `git worktree add ../pl-wt/<ID> -b task/<id-lowercase> origin/main`.
  - The implementer works only there and commits on the task branch. It never pushes, merges, rebases `main` or touches another worktree.
  - The root verifies (`make check` + the task's verification, read through `test-log-analyzer`, `CLAUDE.md`), pushes, opens the PR titled `<ID>: <title>` (CI checks the title), spawns a fresh-context reviewer, reconciles the findings, squash-merges, then removes the worktree and branch.
- **The packet** is `.claude/task-packet-template.md` filled with: the task block from this file verbatim, plus `NORTH_STAR.md`, plus ≤ 5 named files, the verification commands and the escalation triggers.
- **Concurrency:** ≤ 2 implementers per lane, except SYS, which may run 3 (user decision 2026-09-26), and ≤ 4 in flight in total, with disjoint owned paths. Reviewers do not count.
- **ROOT tasks:** the root decides, runs the L/G/U steps and merges. It never authors files or code, not even for a ROOT task: every file (scripts, docs, ADRs, README, this file) is written by an implementer whose packet grants the root-owned paths. Packets and PR bodies stay root-written.
- **Merge floor:** `main` is branch-protected with CI required; the root configures it.
- **Rotation:** the root moves to a fresh session at each stage close, or when its context passes ~60 %, after a short handoff is written to `~/Desktop/proxyloop-review-packet-2026-09-25/plan-v3/handoffs/<date>-<stage>.md` by an implementer from a root packet. The handoff lives outside the repo; it is not a repo process file.
- **The root owns** `PLAN.md`, the contract, `docs/decisions/`, `docs/claims.yaml`, `tasks/splits/`, the shared files (§0.2), `evidence/`, and every merge, gate and claim.
- **"done"** requires a merged PR. For model-touching tasks it also requires a real bundle id (or real artefact) cited in the PR.
  - Infrastructure merged before a real bundle exercises it is `provisional`.
  - It becomes `done` only when a named real run exercises it (for example S0-ROOT-05 flips S0-SYS-03…06).

### 0.2 Lane ownership (owned paths are disjoint; an implementer edits only its task's paths)
| Owner | Paths |
|---|---|
| **ROOT** | `PLAN.md` `NORTH_STAR.md` `AGENTS.md` `CLAUDE.md` `.claude/**` `.github/**` `Makefile` `pyproject.toml` `uv.lock` `docs/decisions/**` `docs/claims.yaml` `docs/limitations.yaml` `docs/v0-*` `README.md` (non-generated text) `tasks/splits/**` `evidence/**` |
| **CON** (root-owned after S0-CON-01) | `src/proxyloop/contract/**` `tests/contract/**` `tests/golden/**` |
| **SYS** | `src/proxyloop/{core,kernel,slow,guard,llm,env,evidence,obs,serve}/**` `src/proxyloop/cli.py` `apps/web/**` `tasks/families/**` `compose.yaml` `mk/sys.mk` `tests/{support,core,kernel,concurrency,slow,guard,llm,env,evidence,obs,serve,web,port}/**` `third_party/**` `scripts/sys/**` |
| **MOD** | `serving/**` `training_jobs/**` `src/proxyloop/{models,training,eval}/**` `mk/mod.mk` `tests/{serving,models,training,eval}/**` `scripts/mod/**` `docs/results/**` (generated only) |

- **Shared files** are root-owned.
  - An implementer who needs a dependency adds it to its lane's group in `pyproject.toml` (`[dependency-groups] sys = […]` / `mod = […]`, or `dev` for test-only tools) and names it in the PR. The root runs `uv lock` at merge.
  - New make targets go only into `mk/sys.mk` or `mk/mod.mk`.
- **Cross-lane imports** go only through the contract (`contract.llm.LLMClient`, `contract.config`, `contract.bundle`). `llm.factory` (SYS) may import `models` (MOD) only for the `LLMClient` adapters of kind `baseline`/composite.

### 0.3 Contract-change procedure
1. An implementer who needs a contract change **stops** and returns a proposal. It never edits `src/proxyloop/contract/**`.
2. The root decides. If the answer is yes, the root writes an ADR `docs/decisions/NNNN-contract-<slug>.md`: context, the change, fingerprint impact (yes/no), data invalidated, migration.
3. A `Sx-CON-nn` task (an implementer under a CON packet, or the root) makes the change together with the goldens.
4. The root runs `make pull-through MODE=full` if the fingerprint changed, otherwise `MODE=verify`. The contract version is bumped in this file.
5. Every in-flight worktree rebases before its next commit.
6. After `semantics-v1` (S3-ROOT-01), a fingerprint change also invalidates every dataset built under the old fingerprint. That requires the user's go (§0.6).

### 0.4 Reviewer (fresh-context Claude subagent, `.claude/agents/reviewer.md`): mandatory fields in the review
1. The `make check` output tail (run by the reviewer) and the task's verification output as it was actually run.
2. **"Could this pass with every model stubbed? Could it pass with the model endpoint dead? Why not?"**
3. At least one defect, **or** the adversarial cases tried (listed). Every finding is tagged **blocker**, **major** or **nit**.
4. NORTH_STAR invariants touched, and whether they hold.
5. Owned paths: is the diff inside the task's paths? Is the contract untouched, or is there an ADR?
6. "Does this add a second path for eval, data, serving or rendering? A fallback? Anything on the TTFS path? A process doc?"
7. **Anti-absorption:** "Does this make base Qwen look better without changing semantics (parser leniency, retries, templates, Fast-specific kernel help)?"
8. The reality statement: `real_http` vs `recorded_replay` vs `test_fake` vs `baseline`, and where each is used.

**Fixes and rounds.** Only blocker and major findings must be fixed before merge. Nits go to the follow-up list (§0.9) and never trigger another round. An S task gets at most one review round unless a blocker is found; wording-only fixes never trigger re-review.

### 0.5 Root-run tasks and the reality rule
- **L, G and U work is executed by the root** (or CI), never by an implementer. Implementers get recorded bundles from `evidence/` through `tests/support/recorded.py`, and fakes from `tests/support/fakes.py`.
- **Keys:** `.env` is never copied into a worktree.
- **Acceptance that mentions a model** names a real bundle that passes `make evidence-check --claim`: the provenance chain, echoed served model, request ids, response shas, attestation, fingerprint and P3 (ARCHITECTURE §14).
- **Tests prove logic; bundles prove reality.** A stubbed pass cannot close a model-touching task.

### 0.6 Tripwires (stop and ask the user)
- **PR count:** S0 > 16 PRs, S1 > 14, S2 > 10, S3 > 10. Root evidence PRs are excluded.
- **Code size:**
  - `src/` Python over 6,300 lines at S0 close, over 9,000 at S1 close, or over 7,000 at S3 close (S0 3,700 → 6,300 and S1 5,800 → 9,000, user decision 2026-09-26);
    - the S3 figure (unchanged) now sits below S1's and must be revisited at S1 close;
  - S0-SYS-06: a hard cap of L = 1,200 changed lines (user decision 2026-09-26).
  - web TypeScript over 1,500 lines through S1;
  - `serving/` + `training_jobs/` over 900 lines (700 → 900, user decision 2026-09-26; reformat of serving/).
  - A module over 600 lines is a warning.
- **No new reality:** after merge point 1 (S0-ROOT-05), two consecutive merged SYS/MOD PRs without a new real bundle or real artefact cited mean the root runs the smoke itself before merging anything else.
- **Contract discipline:**
  - a contract diff without an ADR is rejected;
  - more than one renderer-fingerprint change after `semantics-v1` means stop (data invalidation);
  - any import from `src/` into `tests/support`, or any fallback model path, is rejected.
- **Red signals:** `evidence-check` red on `main`, or `make pull-through` red, stops merges into the affected lane.
- **Model choice:** a model swap is the user's decision, never the root's alone.
- **Intentionally removed:** there is no "metric must rise every N PRs" tripwire.

### 0.7 Stage close
The user closes every stage; the root never self-closes one. The close requires:
1. a replay the user watches (terminal in S0, web from S1);
2. **a live, unscripted correction performed by the user**, chosen at the gate and written in no packet. The bundle must show it handled: relayed, and then fenced, revoked or applied;
3. the stage's docs gate (DOCS §7);
4. the stage's spend summary when due (§0.8).

### 0.8 Spend visibility (information stops, not approvals)
After S0, after S1, after S3, and before S4's data generation (a projection), the root shows:
- measured $/episode by role (Slow, Fast-hosted, world, teacher);
- GPU $ by job;
- the cumulative total;
- the projection for the next stage.

The source is `docs/results/spend.json`, generated from `spend.charged` events and Modal usage.

### 0.9 Follow-up list (review nits; never a merge blocker)
- #114: AGENTS rule 16's advisory list should name `xargs`, `eval`, backticks and paths held in variables explicitly.
- #114: the hook denies `find . -name __pycache__ -exec rm -rf {} +` (target `.`), a false positive.
- #114: `.claude/hooks/block_destructive.py` is ~175 lines against a ~80-line target.
- #114: the rotation handoff path is outside every worktree; say how an implementer packet grants it.
- #114: CLAUDE.md's "Commit and PR creation are root actions" reads as contradicting implementer commits on task branches.
- #114: root-session rules (never authors, log agent, decisions changed) live only in CLAUDE.md, not in a tool-agnostic file.
- #114: the PLAN.md header status line goes stale between PRs.
- #116 (contract; for the lane named):
  - N1 `fingerprint()` hashes profile text, not the rendering code; paths no golden covers can change unseen.
  - N3 ARCH §5 view table gives `FastView[user]` "case facts"; `view_user` has none: align the doc.
  - N4 `RoleModel.served_model` duplicates `ModelRef.model_id`; state which one evidence-check compares (SYS-03).
  - N5 `Manifest` does not check that reality, models and cfg agree (SYS-03 evidence/reality).
  - N7 snapshot tests rewrite under `PL_UPDATE_SNAPSHOTS`; CI must never set it.
  - N8 `Manifest.split` has no value for demo/smoke runs.
  - N9 no hook for the C2f 3-shot block (S4-CON-01).
  - N11 the allow-list test is vacuous for `c01_empty`.
  - Unbounded ints (`OfferPublic.revision`, `Trigger.wait_s`) can still exceed the render budget.
  - Parser: mid-sentence `@Hold`/`@Wait` are case-sensitive while `@end_call` is not.
  - SYS: `guard/terms._utc_text` emits microseconds (27 chars) > `MAX_SLOT_VALUE` 24; format expiry without them.
  - SYS-03: `check_causes` does not require increasing unique seq or a single `run_id`; `read_bundle` does not check `event.run_id == manifest.run_id`.
  - SYS-03: `Event.payload` is a mutable dict; `model_copy`/`model_construct` skip validation, so the bus must validate at append.
  - SYS: `fact.recorded` is untyped and open; the reducer enforces I4 source binding.
  - Guard: a decision is accepted without a prior `approval.requested` / `mandate.proposed`; Guard must join.
- #113 (MOD):
  - `lora_ladder` `main()` gates on `aborted_at`, not `summary["complete"]`.
  - No test drives `run()`'s loop (a fake `vllm` module in `sys.modules` would).
  - Exceptions outside the per-adapter try are neither saved to the volume nor move a stale `--out`.
  - `diff_stats` `max()` ignores NaN after the first element; a NaN zero-R could pass.
  - Run attn-mlp probes before GDN probes, so a GDN engine kill still measures attn-mlp.
  - `lora_ladder.py` whole-file pyright exclude → a file pragma like `scripts/sys/capture_v0_fixtures.py`.
  - The pyproject comment "Every tool covers src, tests and scripts" is stale; ruff `src` lacks `serving`.
  - `mk/mod.mk` `--with` pins duplicate the pyproject groups (drift risk).
  - ADR-0002 hand-types "8.6 GB", "adapter 10 of 16", "9 finished records".
  - `default-groups` now installs the mod group (21 packages, httpx pinned) for every lane.
  - `tests/serving` test doubles live outside `tests/support` (AGENTS rule 5).
- #115 (SYS): `fetch_external.sh` clones into a temp dir then moves; drop the stale `!.env.example` in `.gitignore`; pin the CI Python patch release; add shellcheck; amend S0-SYS-02's acceptance grep to the exclusions actually used.
- Hook (#114): protect the worktree parent `../pl-wt`; track `pushd`; the heredoc false positive (text that mentions recursive deletes near data/external is blocked when shlex cannot parse it).
- Process: the S0 PR count is at 10 of the 16 tripwire with ~7 tasks left; ROOT evidence PRs are excluded.
- Docs:
  - EVAL §9.4: stratify the Ear-audit sampling frame by speaker model (Fast condition) and report Ear accuracy per speaker model (S0-ROOT-08 could not edit EVAL.md).
- #118 (SYS evidence):
  - a scripted bundle relabelled `real_http` still passes `--claim` (authenticity is provenance, ADR-0006);
  - extra files in a bundle are ignored;
  - a verbatim revoked and then released still passes;
  - every line interrupted with an empty `text_heard` passes;
  - envelope epoch jumps are allowed (the rule is monotone, not +1);
  - `ScriptedLLM` accepts a `real_http` ref: make claim fixtures explicit.
- #120 (SYS llm):
  - S0-SYS-06 / P3 at session start needs the P2 ids inside `src/`;
  - Claude may reject `top_p` together with `temperature` (the S4 Haiku baseline);
  - the black-hole 5 s bound is untested;
  - move the `tests/llm/wire.py` transport doubles into `tests/support`.
- #121 (SYS world):
  - `WorldError` lacks attempts and `call_ids` for `session.ended`;
  - `RepTurn` lacks the strike's `rep.policy` id;
  - an expired pending offer leaves the policy in CONFIRM;
  - the loader finds families via `parents[4]`;
  - Ear regenerations at temperature 0 repeat the same output;
  - Mouth fidelity is set-based (swapped values pass);
  - the `refuse_fact` key is not required, and the `provide_fact` value is not checked against the heard text;
  - the reverse reveal check (a fact said but not listed) is missing;
  - the `tests/env/bus_sink` prompts store is a stand-in until S0-SYS-06.
- #119 (MOD training):
  - `metrics.jsonl` may repeat steps after a resume;
  - `per_target` is compared only for > 0, not against the committed dump;
  - the cached-result path still allocates an H100;
  - `src/proxyloop/training` is 160 lines against a ≈ 150-line target;
  - S3 cost planning must re-measure tokens/s on a realistic batch: the smoke (`docs/decisions/data/peft-train-smoke.json` `tokens_per_s`) is far below TRAINING §8's estimate.
- Process: CLAUDE.md still says ≤ 2 implementers per lane (a harness file; update it in the next harness session).

---

## 1. Stage table

| Stage | User-visible demo | Proven vs merely built | Acceptance a fake cannot pass | Evidence artefacts | Honest résumé line | Exit gate |
|---|---|---|---|---|---|---|
| **S0** Foundation + first real interaction + pull-through | Terminal: the user types as principal. FastU (Qwen3.5-9B on vLLM) chats, Sonnet steers, FastC talks to a Gemini-voiced rep (or the user plays the rep), and offers come back as "on the table, not accepted". Terminal replay. Both lanes then run on the pull-through adapter | **Proven:** a real 3-model concurrent session; the chain response→parse→state→heard; dead-endpoint abort; P2/P3/P5; adapter liveness through vLLM. **Built only:** information-only semantics; no success rate | `evidence-check --claim` on real bundles (echoed served model, request ids, response shas, complete chains); a dead endpoint aborts loudly; the user's unscripted opening appears in `user.msg`; adapter shard hashes + logprob liveness | `evidence/s0/**`, ADR-0001…0004, `docs/results/pull-through.json`, `docs/v0-retrospective.md` | NORTH_STAR S0 line (the v0 audit + a traceable rebuild; no performance claim) | S0-ROOT-06 |
| **S1** Semantic slice (4 families) | Browser: the rep offers $65 + a fee outside the mandate. FastC holds and gets the read-back; the approval card appears; the user clicks approve, or types "actually, stop" and the fence blocks the verbatim accept. Per-lane model dropdown; replay of any run | **Proven:** the authority properties under a concurrency suite and live; relay-only Slow; public/private separation (counterfactual test + no private value heard in real runs). **Descriptive only:** the headroom probe | the user's improvised stop/correction during a pending approval, fenced and revoked in a real bundle; the approval POST security tests; a live `x-out-of-envelope-approval` chain to `VERIFIED_COMPLETE`; the probe generated from ≥ 380 of 400 evidence-checked bundles | `evidence/s1/**`, `docs/results/s1-headroom.json`, concurrency suite, web replay | NORTH_STAR S1 line (no numbers) | S1-ROOT-04 |
| **S2** Minimal breadth + instruments | 6 families live; the user plays rep and principal; the audit page; the base-9B TalkAct row | **Proven:** Ear precision/recall on rare harms (human-adjudicated); frozen repaired metrics; human-probe comparison. **Not proven:** that training helps | the human labels and human sessions exist only with the user; TalkAct episode JSONs carry relay response ids; the anchor meets its criterion | `docs/results/s2-ear-audit.json`, `s2-human-probe.json`, `s2-talkact-anchor.json`, `evidence/s2/**` | NORTH_STAR S2 line (numbers generated) | S2-ROOT-04 |
| **S3** Causal pilot + learning curve (go/no-go) | Ablation table; learning-curve chart (LOFO); base vs adapter replays on the same seed | **Proven:** Fast's causal share of failures (paired), and whether and how steeply served SFT moves LOFO dev safe success. **Not proven:** a held-out test claim | every curve point is an attested, served adapter with real dev bundles; ablations are paired on seeds; the Ear is audited; failed episodes count | `docs/results/s3-ablations.json`, `s3-curve.json`, 19 adapter cards | NORTH_STAR S3 line (or the honest negative) | S3-ROOT-05 (user go/no-go) |
| **S4** Confirmatory ML | The same live demo with SFT Fast; a base-vs-SFT replay on a test instance chosen by committed seed; results tables | **Proven:** the pre-registered verdict (pass or fail) on never-piloted families; external diagnostics | pre-registration before data (git order); artefact lock before unseal; attested adapter in every C1 bundle; the test run once | `docs/prereg.md`, `artefacts.lock.json`, `s4-*.json`, cards, `evidence/s4/**` | NORTH_STAR S4 line | S4-ROOT-08 |
| **S5+** Voice → durability → compilation → memory | per milestone (§6) | each claim only after its own measured gate | per milestone | per milestone | per milestone | per milestone |

---

## 2. S0: foundation, first real interaction, first training (plumbing)

Order: the reset tasks (ROOT-01…04, SYS-01/02) clear the ground. **S0-CON-01 is the first build PR**, and every SYS/MOD build task depends on it except the two MOD spikes that do not touch the contract.

### S0-ROOT-01 Worktree inventory and `v0-legacy` tag — ROOT — S — flags U (only if unique work) — done
- **Objective:**
  - Inventory every `git worktree` (22 entries at planning time [O `git worktree list | wc -l`]): branch, HEAD, merged into `main`?, count of unique unpushed commits.
  - Tag `v0-legacy` at `514fe31` and push the tag.
  - Remove only fully merged, pushed worktrees.
- **Owned paths:** `docs/v0-worktrees.md`.
- **Interfaces:** none. **Deps:** the user's go on plan v3.
- **Acceptance:**
  - `git rev-parse v0-legacy^{commit}` = `514fe31…`;
  - `git ls-remote --tags origin v0-legacy` is non-empty;
  - the table row count equals the `git worktree list` count;
  - each row carries `git log main..<branch> --oneline | wc -l`.
- **Verify:** the commands above, pasted in the PR.
- **Escalate if:** any worktree has unique unpushed commits (the user decides), or the tag exists at another commit.

### S0-ROOT-02 Harness diet and agent kit — ROOT — S — done
- **Objective:**
  - Install `agent-kit/AGENTS.md` → `AGENTS.md`, `agent-kit/CLAUDE.md` → `CLAUDE.md`, and `agent-kit/{implementer,reviewer}.md` → `.claude/agents/`.
  - Keep `.claude/agents/architect.md`, with its orientation lines changed to PLAN/NORTH_STAR.
  - Delete `.claude/agents/{explorer,fast-worker}.md` and `.codex/`.
  - Add `agent-kit/pr-template.md` as `.github/pull_request_template.md`, and `.github/workflows/pr-title.yml` (regex `^S[0-9]-(CON|SYS|MOD|ROOT)-[0-9]{2}: `).
  - Add `NORTH_STAR.md` and `PLAN.md` at the root, `docs/decisions/0000-template.md`, and `agent-kit/task-packet-template.md` → `.claude/task-packet-template.md`.
- **Owned paths:** the files listed.
- **Deps:** S0-ROOT-01.
- **Acceptance:**
  - `wc -l AGENTS.md` ≤ 120 and `wc -l CLAUDE.md` ≤ 40;
  - `rg -n "status.toml|phase contract|build-log|harness/" AGENTS.md CLAUDE.md .claude` is empty;
  - a CI run rejects a PR titled without a task id.
- **Verify:** the commands above, and the CI link.
- **Escalate if:** a kept rule conflicts with `NORTH_STAR.md`.

### S0-ROOT-03 v0 retrospective and README skeleton — ROOT — S — done
- **Objective:**
  - `docs/v0-retrospective.md` (≤ 150 lines): what was built; the honest numbers (0.542→0.983 act agreement on the trained path; **0/240 lines delivered** on the product path); the unsupported résumé numbers (58→67, 6→2, "4-bit QLoRA") disowned explicitly; root causes; five lessons; an asset index of `v0-legacy:<path>` links.
  - A README skeleton with the DOCS §2 sections, `<!-- gen:… -->` markers and "Status: under construction".
  - `docs/claims.yaml` (empty) and `docs/limitations.yaml`.
- **Owned paths:** `docs/v0-retrospective.md`, `README.md`, `docs/claims.yaml`, `docs/limitations.yaml`, `scripts/check_legacy_links.py`, `scripts/lint_readme.py`.
- **Deps:** S0-ROOT-01.
- **Acceptance:**
  - `python scripts/check_legacy_links.py docs/v0-retrospective.md` exits 0;
  - every number cites a `v0-legacy:` path;
  - `python scripts/lint_readme.py` finds no digits outside `gen` markers in the results sections.
- **Escalate if:** a number cannot be traced to an artefact at the tag. Drop it; never paraphrase it.

### S0-ROOT-04 Relay capability probe (ADR-0001) — ROOT — S — flags L — done
- **Objective:** through the relay (key from `.env`, never printed), for `claude-sonnet-5`, `claude-haiku-4-5`, `gemini-3.6-flash`, `claude-opus-4-8` and `gemini-3.5-flash`, measure:
  - availability;
  - streaming with usage;
  - tool calls (parallel), and JSON-schema output;
  - Anthropic-native `/v1/messages` and Gemini-native routes (TalkAct transport);
  - TTFT p50 over 20 calls;
  - the echoed model id;
  - $/1k tokens from balance deltas.
- **Owned paths:** `docs/decisions/0001-relay.md`, `docs/decisions/data/relay-*.json`, `scripts/spikes/relay_probe.py`.
- **Deps:** none.
- **Acceptance:** raw request ids and usage per model; a yes/no per capability; a TalkAct transport decision.
- **Escalate if:** Sonnet tool calling or streaming is broken (blocks S0-SYS-04/06); the TalkAct models are missing (E4; does not block S0).

### S0-SYS-01 New workspace and ported pure functions with v0 fixtures — SYS — M — done
- **Objective:**
  - Create the root `pyproject.toml` (uv, package `proxyloop` under `src/`, with ruff, pyright, pytest and import-linter config) **beside** the old code.
  - Port, with tests:
    - `guard/terms.py`: the v1 six-field hash [O `runtime/packages/contracts/src/proxyloop_contracts/material_terms.py:18-46`] and `pl.terms/2` (ARCHITECTURE §9.1);
    - `guard/policy.py`: `offer_compliance_violations` and `unsupported_applied_changes` [O `…/contracts/offer_policy.py:42,105`];
    - `env/ledger.py`: honest, misquote and absent modes;
    - `env/splits.py`: the salted stratified rank [O `…/provider_simulator/negotiation_splits.py:81-119`].
  - `scripts/sys/capture_v0_fixtures.py` imports the v0 packages once and writes `tests/fixtures/v0/*.json`, so the tests survive deletion.
- **Owned paths:** `pyproject.toml`, `uv.lock`, `.importlinter` (all root-owned after merge), `src/proxyloop/__init__.py`, `src/proxyloop/guard/{__init__,terms,policy}.py`, `src/proxyloop/env/{__init__,ledger,splits}.py`, `tests/port/**`, `tests/fixtures/v0/**`, `scripts/sys/capture_v0_fixtures.py`.
- **Interfaces:** new: `terms_hash_v1`, `terms_hash`, `offer_violations`, `Ledger`, `stratified_split`.
- **Deps:** S0-ROOT-01.
- **Acceptance:**
  - the v1 hash equals v0 `material_terms_hash` on every v0 catalogue scenario (the count is printed);
  - `pl.terms/2` property tests: changing any single field (including `applied_changes`, fees, credits and `offer_revision`) changes the hash, and the hash is order-insensitive;
  - the split reproduces the v0 family assignment;
  - `tests/port` passes with the v0 packages **not** importable.
- **Verify:** `uv run pytest tests/port -q`; `uv run lint-imports`.
- **Escalate if:** the v0 hashes cannot be reproduced.

### S0-SYS-02 Deletion, new Makefile/CI, `external/` handling — SYS — L — done
- **Objective:**
  - Physically delete `runtime/`, `ml/`, old `tests/` and `scripts/`, `data/`, `harness/`, `contracts/`, `infra/`, `voice/`, old `apps/`, `compose.yaml`, `PLANS.md`, `PROMPTS.md`, `GOALS.md`, `CONTEXT.md`, `package.json` and the pnpm files. Everything stays at `v0-legacy`.
  - A new `Makefile` (`check lint typecheck test docs-check`, `include mk/*.mk`), plus empty `mk/sys.mk` and `mk/mod.mk`.
  - `.github/workflows/ci.yml` running `make check`.
  - `.gitignore` gains `external/`, `runs/`, `data/sft/` and `adapters/`.
  - `third_party/README.md` with the pins (TalkAct `7d70007…`, principal-loyalty `776e921…`) and licences.
  - `scripts/sys/fetch_external.sh`.
  - `CONTRIBUTING.md` rewritten in ≤ 40 lines.
- **Owned paths:** repo-wide deletions; `Makefile` and `.github/workflows/ci.yml` (root-owned after merge), `mk/*.mk`, `.gitignore`, `third_party/**`, `scripts/sys/fetch_external.sh`, `CONTRIBUTING.md`.
- **Deps:** S0-ROOT-01, S0-ROOT-03, S0-SYS-01.
- **Acceptance:**
  - CI is green on a fresh clone;
  - `rg -l "proxyloop_contracts|case_runtime|provider_simulator|harness/" -g '!docs/v0-*' -g '!third_party/**'` is empty;
  - no tracked file is larger than 1 MB;
  - `git ls-files | wc -l` ≤ 150 [E];
  - `fetch_external.sh` reproduces the pins;
  - `tests/port` stays green.
- **Escalate if:** a deletion hits anything outside this list.

### S0-CON-01 Freeze the shared contract (contract v1) — CON — L — done — **first build PR**
- **Objective:** implement `src/proxyloop/contract/` exactly as ARCHITECTURE §4–§7, §12 and §14 specify:
  - `events.py`: `pl.event/2` and the event registry;
  - `state.py`: `Blackboard`, `PublicState`, `PrivateState`, `OfferPublic`, `ReadbackSlot`, `ReadbackBinding`, `Mandate`, `ApprovalCard`, `Approval`, `Capability`, `CaseStatus`, `Fence`;
  - `views.py`: `view_user`, `view_cp`, `view_slow(mode)`;
  - `messages.py`: `FastToSlow` with REVOKE, `SlowToFast`, `Guide`, `GuideMove`, `SlotRef`;
  - `protocol.py` plus `profiles/pl_user_v1.py` and `pl_cp_v1.py`, with **every S1 section present** and `CONTEXT_BUDGET_CHARS`;
  - `llm.py`: `LLMClient`, `ModelRef`, `TextRequest`, `ToolRequest`, `LLMCallRecord`, `AdapterKind`, `LLMUnavailable`;
  - `config.py`: `SessionConfig`, `AblationId` (all S3 ablations enumerated now), `SlowViewMode`;
  - `bundle.py`: `pl.bundle/1`, `Manifest`, `read_bundle`;
  - the conformance kit `tests/contract/llm_conformance.py`;
  - ADR-0004 "contract v1", with the fingerprints.
- **Owned paths:** `src/proxyloop/contract/**`, `tests/contract/**`, `tests/golden/**`, `docs/decisions/0004-contract-v1.md`.
- **Interfaces:** **new → frozen on merge:** all of the above. Changes after that follow §0.3.
- **Deps:** S0-SYS-01 (the workspace). It runs in parallel with S0-SYS-02, since the paths are disjoint; until SYS-02 lands it uses `uv run pytest` directly.
- **Acceptance:**
  - **P1:** ≥ 12 golden views across both profiles (empty sections, a pending approval, guidance with slots, an over-budget transcript).
  - **P2:** HF token ids for those goldens under a pinned tokenizer revision with `enable_thinking=False`; the think bytes are recorded.
  - **P4:** holds for every prefix split of ≥ 60 canonical turns.
  - **Private-value counterfactual:** 500 random blackboards × every `PrivateState` field perturbed leaves `render_messages(view_cp(…), "pl_cp_v1")` byte-identical.
  - An AST test shows that `view_cp` never references `.private`.
  - **Allow-list:** no protected or mandate value appears in any cp golden.
  - Snapshots of the event registry and of the manifest JSON schema.
  - A GUIDE slot that references a non-public key fails at render time.
- **Verify:** `uv run pytest tests/contract tests/golden -q`; `uv run pyright src/proxyloop/contract`.
- **Escalate if:** a TalkAct-compatibility conflict; the think bytes differ between chat-template paths; any need for a field not in ARCHITECTURE §5–§7 (the root decides).

### S0-MOD-01 Pinned CUDA serving configuration for Qwen3.5-9B (ADR-0002) — MOD — M — flags G (root runs) — provisional (merged in #113; the root's `serve-attest-local` run awaits the user's go)
- **Objective:**
  - `serving/modal_vllm.py`: pinned image digest, vLLM version and HF revision; ARCHITECTURE §13 flags (`--language-model-only`, LoRA enabled, prefix caching **off**).
  - `serving/attest.py`: per-shard sha256 at container start → `GET /pl/attest`.
  - A zero-initialised LoRA over the full target list: record which modules vLLM accepts.
  - Measure:
    - cold start;
    - TTFT/TTFS from the Mac (1.5k-token prompt, 20 requests, concurrency 1 and 4);
    - `/tokenize` vs HF ids with `enable_thinking=false`;
    - LoRA overhead;
    - prefix caching with `--mamba-cache-mode align` on vs off (**measured only**).
  - `make serve-up`/`serve-down` (with a trap) in `mk/mod.mk`.
- **Owned paths:** `serving/**`, `mk/mod.mk`, `tests/serving/**`, `docs/decisions/0002-serving.md`, `docs/decisions/data/vllm-*.json`.
- **Deps:** S0-ROOT-01 only. It runs in parallel with the reset and the contract.
- **Acceptance:**
  - raw JSON with the vLLM version, GPU name, `/v1/models`, and per-request ids and timings;
  - `/pl/attest` shard hashes match a local recomputation for 2 shards;
  - zero-LoRA liveness: `prompt_logprobs` equal to base within 1e-4;
  - the ADR picks a rung of the LoRA ladder with evidence;
  - `/tokenize` ids equal HF ids on 5 prompts.
- **Verify:** `make serve-up && python -m serving.probe --out docs/decisions/data/vllm-probe.json && make serve-down` (root).
- **Escalate if:** Qwen3.5-9B does not load with `--language-model-only`; TTFS p50 from the Mac exceeds 1.5 s on H100; no LoRA path works and merged serving also fails.

### S0-MOD-02 Pinned training configuration and SFT skeleton (ADR-0003) — MOD — M — flags G — provisional (merged in #119; `make train-smoke` passed: `docs/decisions/data/peft-train-smoke.json` `p5.ok`; adapter liveness moved to S0-MOD-03)
- **Objective:**
  - `training_jobs/{modal_train,sft}.py` (PEFT + TRL, BF16) with pinned transformers, peft, trl, flash-linear-attention and causal-conv1d versions.
  - A `named_modules()` dump; a language-model-anchored target regex; the vision tower frozen; a **fused GDN kernel check** that fails on the torch fallback.
  - `src/proxyloop/training/masking.py`: `verify_trained_span` as a pure function over ids, labels and the tokenizer [O port of `ml/training/phase03c_cloud/train.py:359-393`].
  - `training/dataset.py` (minimal): rows from contract golden views through `render_prompt`.
  - A 50-step smoke on 64 rows with P5 on the real batch; save the non-zero adapter and a merged BF16 copy.
- **Owned paths:** `training_jobs/**`, `src/proxyloop/training/{__init__,masking,dataset}.py`, `tests/training/**`, `docs/decisions/0003-training.md`, `docs/decisions/data/peft-*.json`.
- **Deps:** S0-CON-01 for the dataset part. The module dump may start earlier.
- **Acceptance:**
  - the ADR lists exact module paths, trainable parameters, tok/s, peak memory and the P5 result from the real run;
  - adapter liveness in S0-MOD-01's server: moved to S0-MOD-03;
  - the train targets equal the serve-accepted targets.
- **Verify:** `make train-smoke` (root, G); `uv run pytest tests/training -q`.
- **Escalate if:** the fused kernels are unavailable; PEFT cannot target the GDN modules; the vision tower cannot be isolated.

### S0-SYS-03 Event log, bus, fold, evidence-check with provenance and mutation tests — SYS — M — provisional (merged in #118; until S0-ROOT-05)
- **Objective:**
  - `core/{log,bus,fold,clock}.py`: a single-writer JSONL log with dense `seq`; a bus whose subscribers are isolated (a subscriber exception never propagates); reducers for every S0 event type.
  - `evidence/{check,chain,reality}.py` (ARCHITECTURE §14), with `--claim` and `--offline` modes.
  - `tests/support/{fakes,recorded,manual_clock}.py`.
- **Owned paths:** `src/proxyloop/{core,evidence}/**`, `tests/{core,evidence,support}/**`.
- **Interfaces:** new: `EventLog`, `Bus`, `fold`, `evidence_check`.
- **Deps:** S0-CON-01.
- **Acceptance:**
  - `fold` is deterministic (property test);
  - every registry type has a reducer or is declared world/ops;
  - `evidence-check` rejects a missing cause, a `response_sha` mismatch, `test_fake` in a claimed role, and a seq gap (negative tests);
  - **mutation test:** flipping one byte of a recorded response changes the parsed items and the delivered text in a bundle built from recorded fakes.
  - Status `provisional` until S0-ROOT-05.
- **Verify:** `make test`; `uv run pytest tests/evidence -q`.
- **Escalate if:** a chain rule needs information that the contract events lack.

### S0-SYS-04 LLM adapters, P3 parity, spend ledger — SYS — M — flags L+G for the smoke — provisional (merged in #120; until S0-ROOT-05; `make llm-smoke` passed: `docs/decisions/data/llm-smoke.json` `checks`, `p3.passed`)
- **Objective:** `llm/{factory,vllm,relay,spend,parity}.py`:
  - vLLM `/v1/completions` streaming with the pre-rendered prompt;
  - relay chat streaming (hosted Fast gets the same `render_messages`) and relay tool calls (Slow);
  - every call returns an `LLMCallRecord`;
  - `LLMUnavailable` on connection failure, with ≤ 1 retry before the first token (recorded) and **no fallback**;
  - live mode rejects any non-`real_http` adapter;
  - `check_parity` (P3);
  - `SpendLedger` with a runaway guard at 10× the projected episode cost.
- **Owned paths:** `src/proxyloop/llm/**`, `tests/llm/**`, `mk/sys.mk` (`llm-smoke`).
- **Interfaces:** implements `contract.llm.LLMClient`.
- **Deps:** S0-CON-01, S0-ROOT-04 (relay facts), S0-MOD-01 (endpoint shape; the tests use recorded fixtures).
- **Acceptance:**
  - the conformance kit passes;
  - a dead URL raises `LLMUnavailable` within 5 s (unit test);
  - `make llm-smoke` (root) writes `docs/decisions/data/llm-smoke.json` with 20 real 9B streams (request ids, TTFT), 3 real Sonnet tool calls, P3 = pass and the attestation.
- **Verify:** `make test`; `make llm-smoke` (root).
- **Escalate if:** P3 fails, or more than 5 % of relay tool calls are malformed.

### S0-SYS-05 World minimum: schema, one family (information-only), SimRep, async SimUser — SYS — L (re-sized from M, root decision 2026-09-26) — flags L for the smoke — provisional (merged in #121; until S0-ROOT-05)
- **Objective:**
  - `env/tasks/{schema,loader}.py` (EVAL §2);
  - `tasks/families/cp-direct-discount.yaml` with `mode: info_only`;
  - `env/counterparty/{policy,ear,mouth}.py`: ladder, identity, hidden terms until read-back, TTL, cp patience, and `rep.commit_heard` + ledger write if the agent's speech accepts;
  - `env/user/simuser.py`: JSON `revealed`, reply delay, no patience;
  - the world model (Ear, Mouth, SimUser) is `gemini-3.8-flash` via TeamRouter (`ModelRef.endpoint = "teamrouter"`), superseding ADR-0001's world choice (ADR-0005);
  - World structured-call policy: ADR-0005 (≤ 2 regenerations, counted; then episode error; wall-clock timeout).
  - The `rep-chat` CLI moved to S0-SYS-06, which owns `cli.py` (root decision 2026-09-26).
- **Owned paths:** `src/proxyloop/env/**` (it may extend the ledger), `tasks/families/cp-direct-discount.yaml`, `tests/env/**`.
- **Deps:** S0-CON-01, S0-SYS-04.
- **Acceptance:**
  - Mouth fidelity ≥ 95 % over 50 real calls;
  - SimUser reveal check: ≥ 95 % of `revealed` values appear verbatim across 30 real calls, with the rest regenerated and counted;
  - an import-linter rule forbids `env` → agent modules.
- **Verify:** `make test`.
- **Escalate if:** the Ear misclassifies more than 3 of 30 hand-checked utterances, or the policy needs agent-side state.

### S0-SYS-06 Kernel, two lanes, minimal Slow, bundle, CLI, terminal replay — SYS — L — flags L+G for the smoke — todo
- **Objective:**
  - `kernel/{session,lanes,speaker,channels,watchdog}.py`: `run_session`; FastU as async chat; FastC in real time with the speech clock and barge-in; the Guard-authored AI-disclosure line as the first cp utterance.
  - `slow/{loop,tools,prompt}.py` with `ask_user`, `tell_user`, `wait`, `guide_fast`, `record_fact`, `record_offer` (no statuses yet) and `finish(info_only)`, over a **relay-only** SlowView.
  - `guard/declass.py` (numbers source-bound).
  - The bundle writer.
  - `python -m proxyloop.cli session --family … --user sim|human --rep sim|human`, `python -m proxyloop.cli replay RUN=`, `python -m proxyloop.cli rep-chat --family cp-direct-discount` (from S0-SYS-05), and `make smoke-live FAMILY=`.
- **Size:** hard cap L = 1,200 changed lines (§0.6).
- **Owned paths:** `src/proxyloop/{kernel,slow}/**`, `src/proxyloop/guard/declass.py`, `src/proxyloop/cli.py`, `tests/{kernel,slow}/**`, `mk/sys.mk` (`smoke-live`, `replay-cli`).
- **Interfaces:** implements `run_session(cfg, task, channels=None)`.
- **Deps:** S0-SYS-03, S0-SYS-04, S0-SYS-05.
- **Acceptance (tests; reality at S0-ROOT-05):**
  - a full session runs with `tests/support` fakes;
  - no user or cp utterance text appears in Slow's rendered context unless relayed (relay-only test);
  - the disclosure line is the first cp agent utterance;
  - a `public_summary` containing a private bound is denied with `declass.denied`;
  - with `live=True`, any non-`real_http` adapter raises at startup;
  - `rep-chat` (root, L): the root negotiates by hand to a final offer, and `rep.ear`/`rep.mouth` cite `llm.call` events with request ids.
- **Verify:** `make test`; `python -m proxyloop.cli rep-chat …` (root).
- **Escalate if:** a behaviour needs a contract change.

### S0-ROOT-05 MERGE POINT 1: the first real interaction — ROOT — S — flags L+G+U — todo
- **Objective:** run the SYS kernel against the MOD-served Qwen3.5-9B:
  - `make smoke-live FAMILY=cp-direct-discount` ×3 (sim user, sim rep);
  - 1 session in which the user types as principal (an unscripted opening);
  - the dead-endpoint mutation: `fast_cp` pointed at a closed port.

  Commit the bundles to `evidence/s0/`.
- **Owned paths:** `evidence/s0/**`, `PLAN.md`.
- **Deps:** S0-SYS-06, S0-MOD-01.
- **Acceptance:**
  - `make evidence-check RUN=… --claim` passes on ≥ 3 bundles;
  - each bundle has ≥ 1 complete "relayed and used" chain (ARCHITECTURE §4.3);
  - ≥ 1 FastC sentence was released while a Slow step was in flight;
  - the dead-endpoint run exits non-zero with `session.ended{llm_unavailable}` and no later `utt.delivered`;
  - TTFS p50 from the Mac is recorded;
  - the user's opening appears verbatim in `user.msg`.
- **After:** S0-SYS-03…06 become `done`.

### S0-MOD-03 `make pull-through` — MOD — M — flags L+G (root runs) — todo
- **Objective:** `training/pull_through.py` and the `make pull-through MODE=full|verify` target, exactly as TRAINING §9 describes. The S0 label source is the base-9B turns from `evidence/s0/` (§9 E1). A trained-adapter LoRA slot in `serving/` (root decision 2026-09-26).
- **Owned paths:** `src/proxyloop/training/pull_through.py`, `mk/mod.mk`, `tests/training/test_pull_through.py`, `serving/**`.
- **Deps:** S0-ROOT-05, S0-MOD-01, S0-MOD-02.
- **Acceptance:** `docs/results/pull-through.json` contains:
  - fingerprint = current;
  - the adapter shard hashes;
  - liveness > 1e-3 nats;
  - P5 = pass;
  - a product-path bundle with both lanes on the adapter that passes `evidence-check --claim`, with every Fast `served_model_echo` = the adapter name;
  - `claim: "none"`.
- **Acceptance moved from S0-MOD-02:** the S0-MOD-02 smoke adapter loads in S0-MOD-01's server through the LoRA slot with liveness > 1e-3 nats.
- **Verify:** `make pull-through MODE=full` (root).
- **Escalate if:** liveness ≤ 1e-3 (the adapter is not live in serving), or P5 fails.

### S0-ROOT-06 S0 close — ROOT — S — flags U — todo
- The user watches the terminal replay of an S0 bundle and of the pull-through bundle.
- The user performs a **live unscripted correction** as principal. The bundle must show an f2s correction → a Slow summary or fact update → a later FastC view that reflects it.
- The docs gate S0 is met (DOCS §7).
- Spend summary #1.
- PLAN.md is updated: contract v1 and fingerprints.

### S0-ROOT-08 Docs sync and world-model probe (ADR-0005) — ROOT — S — flags L (root runs the probe) — done
- **Objective:** bring PLAN/ARCHITECTURE/EVAL/DOCS/retrospective in line with contract v1, S0-MOD-01 and the
  user's world-model decision; record review follow-ups; add a TeamRouter env mode to the relay probe; after the
  root's probe run, write ADR-0005 (world model = `gemini-3.8-flash` via TeamRouter) citing the committed probe JSON.
- **Owned paths:** see the packet (root-owned docs granted).
- **Acceptance:** `make check` green; no measured number typed into prose (AGENTS rule 13); ADR-0005 cites JSON keys.

### S0-ROOT-09 Record the S0 build-phase decisions — ROOT — S — review
- **Objective:** write the user's and root's decisions of 2026-09-26 (after S0-ROOT-08) into PLAN.md, ARCHITECTURE.md
  and a one-page ADR-0006; update statuses; extend the §0.9 follow-up list. Documentation only.
- **Owned paths:** PLAN.md, ARCHITECTURE.md (§4, §14, §16 lines named below), docs/decisions/0006-llm-call-writer-and-claim-endings.md.
- **Acceptance:** `make check` green; no measured number typed (AGENTS rule 13); every decision below appears once.

---

## 3. S1: semantic slice (4 families), Guard v2, live web, headroom probe (diagnostic)

S1 SYS/MOD tasks may start after S0-ROOT-05. **Any teacher run in the harness** (the T and R conditions, S1-MOD-01's teacher smoke, S1-MOD-03, S1-ROOT-02) waits until S1-SYS-01, -02, -03 and -05 have merged. Decisions D require capability minting, read-back slots, the fence and epochs, and approval-endpoint security first (§9 E1).

### S1-SYS-00 Simplification pass (no weaker guarantees) — SYS — M — todo
- **Objective:** before the rest of S1, trim only redundancy in the S0 code, without weakening any guarantee (the user's example: `llm/` ≈ 550 lines) (user decision 2026-09-26).
- **Owned paths:** `src/proxyloop/{core,evidence,llm,env,kernel,slow}/**` (code only; no contract).
- **Acceptance:** `make check` green; every existing test unchanged or strictly stronger; net `src/` lines reduced.

### S1-ROOT-01 Pilot lock — ROOT — S — todo
- **Objective:** `tasks/splits/pilot_lock.json`, listing families 1–4 as train-only, plus a `check-pilot-lock` step in CI that fails if any split file assigns a locked family to dev or test.
- **Owned paths:** `tasks/splits/**`, `.github/workflows/ci.yml`.
- **Acceptance:** a CI run fails on a planted split file.

### S1-SYS-01 Guard v2 (pure) — SYS — L — todo
- **Objective:** `guard/{terms,readback,mandate,authorize,capability,verify,status}.py` per ARCHITECTURE §9.1–§9.5:
  - read-back slots, lexicons and required fields;
  - the binding;
  - the rules;
  - capability minting;
  - `business_action_id`;
  - `verify_completion`;
  - the **non-omniscient** `verify_no_deal`;
  - the speech screen with the public-value exemption;
  - the status reducer.
- **Owned paths:** `src/proxyloop/guard/**` (except `declass.py`), `tests/guard/**`.
- **Deps:** S0-ROOT-05.
- **Acceptance:**
  - table tests cover every rule × every denial reason;
  - read-back property tests: a role swap (fee ↔ monthly), a negation ("no activation fee"), an omitted required field, and a later contradicting utterance each leave the offer **not confirmed**;
  - approval use requires the same epoch;
  - the speech screen passes a value that is both a public offer and a private bound;
  - `guard.verify` importing `env` fails import-linter (negative test);
  - `business_action_id` is stable under `run_id` and `seq` changes.
- **Verify:** `make test`.
- **Escalate if:** a rule needs an LLM judgement.

### S1-SYS-02 Authority timing: fence, epochs, generations/acks, release revalidation, concurrency suite — SYS — L — todo
- **Objective:** `kernel/{fence,speaker,lanes,session}.py` per ARCHITECTURE §9.4 and §11, and the concurrency suite in `tests/concurrency/` (7 cases).
- **Owned paths:** `src/proxyloop/kernel/{fence,speaker,lanes,session,watchdog}.py`, `tests/concurrency/**`.
- **Deps:** S1-SYS-01.
- **Acceptance:** the 7 manual-clock cases assert event-level outcomes:
  - (1) `speak.revoked{fence}` and no delivered accept;
  - (2) the card goes stale and returns 409;
  - (3) `speak.revoked{expired}` when `t_release_end > expires`;
  - (4) a truncated `text_heard` → `NEEDS_REPLAN`;
  - (5) exactly one `approval.decided`;
  - (6) the session completes after an exporter crash;
  - (7) a stale generation is cancelled.

  In addition, a hypothesis stateful test (500 interleavings) finds no `speak.released{accept}` with a fence raised or a stale epoch, and `seq` stays dense.
- **Verify:** `uv run pytest tests/concurrency -q`.
- **Escalate if:** a case needs a new event type (a contract change).

### S1-SYS-03 Slow v2: authority tools, public/private summaries, declassification — SYS — M — flags L+G for the smoke — todo
- **Objective:**
  - the ARCHITECTURE §8 S1 tools;
  - `private_summary` required and `public_summary` declassified;
  - GUIDE slot and lever checks;
  - the status bar;
  - denials returned as text.
- **Owned paths:** `src/proxyloop/slow/**`, `src/proxyloop/guard/declass.py`, `tests/slow/**`.
- **Deps:** S1-SYS-01.
- **Acceptance:**
  - a tool-schema snapshot;
  - the relay-only test holds under all tools;
  - `cite_competitor` without a shareable quote, or `cancel_lever` without authorisation, is denied;
  - a live smoke (root) of `x-out-of-envelope-approval` produces the chain `approval.requested → approval.decided(sim_approver) → action.authorized → speak.released → utt.delivered → ledger.write → evidence.recorded → completion.decided(VERIFIED_COMPLETE)` in an `evidence-check --claim` bundle.
- **Verify:** `make test`; `make smoke-live FAMILY=x-out-of-envelope-approval` (root).
- **Escalate if:** Slow systematically needs transcript text to act (relay-only is frozen: bring the evidence to the root).

### S1-SYS-04 World for the slice: 3 families, accept path, approver, stop — SYS — M — flags L for the smoke — todo
- **Objective:**
  - `tasks/families/{cp-hidden-fee-readback,x-out-of-envelope-approval,x-user-mind-change}.yaml`;
  - `cp-direct-discount` gains full mode;
  - SimRep: accept and confirm, and ledger modes;
  - the deterministic approver through the endpoint semantics;
  - SimUser `stop` and `mind_change`;
  - a reference completability predicate per family.
- **Owned paths:** `src/proxyloop/env/**`, `tasks/families/**`, `tests/env/**`.
- **Deps:** S1-SYS-01 (types only).
- **Acceptance:**
  - the reference predicate proves 50 instances per family completable;
  - in a root hand negotiation in the CLI, fees stay hidden until the read-back;
  - one real bundle per family.
- **Verify:** `make test`; `make smoke-live FAMILY=<each>` (root).
- **Escalate if:** a family needs agent-side information in the world.

### S1-SYS-05 Web: live view, replay, approval endpoint, rep page — SYS — L — flags L+G for the smoke — todo
- **Objective:**
  - `serve/{api,csrf}.py` per ARCHITECTURE §9.6 and §14;
  - `HumanWebChannel` for the user and cp lanes;
  - `apps/web`: live and replay pages sharing one component tree, with approve/deny on the card and a per-lane model dropdown that lists only `real_http` models;
  - `make demo`, `make replay`, `make web-test`.
- **Owned paths:** `apps/web/**`, `src/proxyloop/serve/**`, `src/proxyloop/kernel/channels.py`, `tests/{serve,web}/**`, `mk/sys.mk`.
- **Deps:** S1-SYS-02.
- **Acceptance:**
  - with keys and GPU unset, Playwright loads an `evidence/s0` bundle and asserts a Qwen3.5-9B sentence and a Slow tool event;
  - security: a missing CSRF token → 403; a wrong Origin → 403; a stale epoch or hash → 409; a replayed POST → 409 with exactly one `approval.decided`; the server binds 127.0.0.1;
  - the web never imports prompt text (lint);
  - a root live session (L+G): the root clicks approve, and the bundle has `approval.decided{by: ui}` and passes the claim check.
- **Verify:** `make web-test`; `make demo` (root).
- **Escalate if:** the WebSocket adds work to the TTFS path.

### S1-SYS-06 OTel export to Phoenix, failure isolation — SYS — S — todo
- **Objective:** `obs/otel.py` (spans derived from `event_id`/`cause_ids`), `compose.yaml` (Phoenix) and `make traces-up`.
- **Owned paths:** `src/proxyloop/obs/**`, `compose.yaml`, `tests/obs/**`.
- **Deps:** S0-ROOT-05.
- **Acceptance:** a real smoke shows overlapping Fast and Slow spans (span JSON + a screenshot in the PR); concurrency case 6 passes.

### S1-MOD-01 Model registry, per-lane swap, 4B serving, hosted/teacher Fast, FSM, teacher-repair — MOD — L — flags L+G for the smoke — todo
- **Objective:**
  - `models/registry.py` and `conditions.yaml` (C2, C3, C4, T, F, R);
  - the 4B app in `serving/`;
  - `models/fsm.py`: a capable FSM that templates from `FastView` only, relays every number and key it can parse, asks for the read-back on offers, holds at decisions and never claims completion unless verified;
  - `models/repair.py`: `TeacherRepair` with a decision-point detector over `FastView`.
- **Owned paths:** `src/proxyloop/models/**`, `serving/modal_vllm.py`, `tests/models/**`.
- **Deps:** S0-ROOT-05, S0-CON-01.
- **Acceptance:**
  - the conformance kit passes for `FsmTalker` and `TeacherRepair`;
  - the FSM imports no world module (lint);
  - detector unit tests pass on goldens;
  - a root smoke produces one real bundle per condition on `cp-direct-discount`, with the reality report labelling F as `baseline`. The T and R smokes run only after S1-SYS-01/02/03/05 merge;
  - teacher outputs are parsed by the student parser, with the resample count recorded;
  - a grep test shows no clock-dilation option exists.
- **Verify:** `make test`; `make smoke-live FAMILY=cp-direct-discount FAST=<cond>` (root).
- **Escalate if:** the hosted-Fast path needs different prompt text (I3: it must not).

### S1-MOD-02 Metrics v1, report and statistics — MOD — M — todo
- **Objective:** the EVAL §7 metrics marked S1, plus `stats.py` (Wilson, cluster bootstrap), `report.py` (`pl.report/1`) and `matrix.py` (interleaved blocks, integrity gate).
- **Owned paths:** `src/proxyloop/eval/**`, `tests/eval/**`, `mk/mod.mk`.
- **Deps:** S0-ROOT-05.
- **Acceptance:**
  - metrics on 3 committed real bundles equal the root's hand computation (the expectations are committed);
  - `relay_recall` uses `user.sim.revealed`;
  - an errored bundle counts as a failure;
  - the bootstrap is checked against a known distribution.
- **Verify:** `make test`.

### S1-MOD-03 Headroom probe, diagnostic only — MOD (spec) + ROOT (run) — M — flags L+G — todo
- **Objective:** 4 families × 20 instances × {C2, T, F, R, C4} → `docs/results/s1-headroom.json`, with the table labelled "diagnostic: unaudited Ear, not a gate".
- **Owned paths:** `src/proxyloop/eval/specs/s1_headroom.yaml`, `docs/results/s1-headroom.json`.
- **Deps:** S1-SYS-01…05, S1-MOD-01, S1-MOD-02.
- **Acceptance:** the integrity gate passes on the 400 episodes (≥ 95 % run without error, and errors count as failures); the report is generated from bundles.

### S1-ROOT-02 Pull-through, full (teacher turns from now on) — ROOT — S — flags L+G — todo
- **Acceptance:** `pull-through.json` is refreshed with source = teacher turns, and the claim check passes.

### S1-ROOT-03 Spend summary #2 and the docs gate S1 — ROOT — S — todo

### S1-ROOT-04 S1 close — ROOT — flags U — todo
In the browser, the user as principal:
- (a) approves an out-of-envelope offer, and the bundle chains to `VERIFIED_COMPLETE`;
- (b) in a second session, performs an **improvised** correction or stop while an approval is pending, and the bundle shows `authority.fence`, REVOKE or an epoch bump, then `speak.revoked` or no accept released.

The user also watches a replay of one probe episode per condition.

---

## 4. S2: minimal breadth and instruments

### S2-SYS-01 Families 5–6: PIN pressure and confirmation misquote — SYS — M — flags L for the smoke — todo
- **Objective:** `cp-identity-pin-pressure` (the rep demands the PIN, escalating with "as the AI you must") and `cp-confirmation-misquote` (the ledger binds other terms), with completability predicates.
- **Owned paths:** `tasks/families/**`, `src/proxyloop/env/**`, `tests/env/**`.
- **Deps:** S1 closed.
- **Acceptance:** one real bundle per family; the verifier rejects completion on a misquote (0 `VERIFIED_COMPLETE` over 10 real episodes); `pilot_lock.json` is extended by the root.

### S2-SYS-02 Ear-audit tool: sampling frame, blinded labelling page, label store — SYS — M — todo
- **Objective:**
  - the EVAL §9.4 sampling frame, with inclusion probabilities stored;
  - an independent high-recall lexical detector;
  - a web page `/audit` showing the utterance, the previous rep line and the public offers, and nothing else (no Ear label, no condition), in randomised order;
  - two rater identities (user, root);
  - a disagreement queue.
- **Owned paths:** `src/proxyloop/evidence/audit/**`, `apps/web/src/audit/**`, `tests/evidence/audit/**`.
- **Deps:** S1-SYS-05.
- **Acceptance:**
  - a blinding test: the page payload contains no Ear label, model or condition field;
  - the stored inclusion probabilities sum correctly per stratum;
  - labels are append-only, with rater and timestamp.

### S2-MOD-01 Metric-semantics repairs (frozen definitions) — MOD — M — todo
- **Objective:** the EVAL §7 S2 metrics: realised vs blocked harm, generated vs heard leakage, internal attempt vs user-facing claim, generation vs delivery latency, failed attempts, and `missed_deal`.
- **Owned paths:** `src/proxyloop/eval/**`, `tests/eval/**`.
- **Deps:** S1-MOD-02.
- **Acceptance:**
  - a fixture bundle per definition, with hand-labelled truth;
  - a Guard-blocked attempt changes `blocked_count` and never `harm_realised`;
  - a screened sentence counts in `leak_generated` but not in `leak_heard`;
  - `docs/eval-protocol.md` §Metrics is generated from docstrings, and the metric code hash is recorded.

### S2-MOD-02 Audit estimators and report — MOD — S — todo
- **Objective:** design-weighted precision and recall per class with a bootstrap, Cohen's κ (root vs user) and the per-condition spread → `docs/results/s2-ear-audit.json`.
- **Owned paths:** `src/proxyloop/eval/audit_stats.py`, `tests/eval/test_audit_stats.py`.
- **Deps:** S2-SYS-02.
- **Acceptance:** the estimator recovers known precision and recall on a simulated labelled population within its CI in ≥ 94 % of 500 simulations.

### S2-MOD-03 TalkAct anchors and the base-9B row (parallel, non-blocking) — MOD — M — flags L+G+U (root runs; executes TalkAct code, Opus spend) — todo
- **Objective:**
  - `eval/external/talkact.py`, a scheduler that never edits TalkAct;
  - `scripts/mod/vllm_proxy.py`, plus the translation proxy if ADR-0001 requires it;
  - ADR-0006 with the anchor criterion;
  - runs: Haiku, Qwen3-14B and Qwen3.5-9B base on `forms-insurance` and `booking-flight`, ≥ 10 repeats each, interleaved.
- **Owned paths:** `src/proxyloop/eval/external/talkact.py`, `scripts/mod/**`, `docs/decisions/0006-talkact-anchor.md`, `docs/results/s2-talkact-anchor.json`.
- **Deps:** S0-ROOT-04, S0-MOD-01.
- **Acceptance:** episode JSONs archived with hashes and relay response ids; the anchor criterion evaluated and stated; $/episode recorded.
- **Escalate if:** Haiku scores below 8/10 on either task (stop our rows), or a workaround would need edits to TalkAct.

### S2-ROOT-01 Instrument corpus run — ROOT — flags L+G — todo
6 families × 15 instances × {C2, T, F} of real bundles as the audit population → `evidence/s2/corpus/` (bundle hashes; bundles archived).

### S2-ROOT-02 Human probes — ROOT — flags L+G+U — todo
The user plays the rep 5 times and the principal 3 times in the web UI, and `docs/results/s2-human-probe.json` compares them with the simulated sessions. **Acceptance:** 8 human bundles pass the claim check, with the human flagged in the reality report.

### S2-ROOT-03 Ear audit labelling and one allowed revision — ROOT — flags U (≈ 90 min [E]) — todo
- The root labels first as the second rater, then the user labels, then the user adjudicates the disagreements.
- If a harmful class misses the acceptance bar, SYS makes one Ear or lexicon revision under a small task, and the affected strata are re-audited.
- **Acceptance:** `s2-ear-audit.json` meets EVAL §9.4, or the switch criterion (§8) fires.

### S2-ROOT-04 S2 close — ROOT — flags U — todo
The docs gate S2 and a live correction (for example the user, playing the rep, withdraws an offer mid-read-back).

---

## 5. S3: causal pilot and learning curve (the go/no-go)

### S3-ROOT-01 Semantics freeze v1 — ROOT — S — todo
- **Objective:** tag `semantics-v1` and record in PLAN.md the hashes of the contract version, `src/proxyloop/{env,guard,slow}/**`, `tasks/families/**` and the Ear prompts. From then on, changes to those paths need an ADR and state which S3 data they invalidate.
- **Deps:** S2 closed.

### S3-SYS-01 Ablation mechanics in the kernel — SYS — M — todo
- **Objective:** implement the `AblationId` values already in the contract:
  - `suppress_relay_user/cp` (the f2s is dropped after logging, flagged);
  - `mute_fastu_explanations` (FastU turns triggered by `APPROVAL_NOTICE` are not delivered; the card stays);
  - `approval_without_fastu_readback`;
  - `teacher_repair_*` wiring to `models.repair`;
  - the `raw_transcript` SlowView.
- **Owned paths:** `src/proxyloop/kernel/**`, `tests/kernel/test_ablations.py`.
- **Deps:** S3-ROOT-01.
- **Acceptance:**
  - per ablation, a test shows exactly the intended edge removed and nothing else (the event diff against a paired baseline run on recorded fakes);
  - live mode records the ablation in the manifest;
  - `evidence-check --claim` refuses ablation bundles for product claims.

### S3-MOD-01 Ablation matrix spec and causal report — MOD — M — todo
- **Objective:** `eval/ablations.py` and `specs/s3_ablations.yaml` (EVAL §4.2, §8.3), with paired estimators for `f̂_repair`, the relay dependence and the Slow compensation → `docs/results/s3-ablations.json`.
- **Owned paths:** `src/proxyloop/eval/{ablations.py,specs/**}`, `tests/eval/**`.
- **Deps:** S2-MOD-01.
- **Acceptance:** the estimators are unbiased on simulated paired data (CI coverage ≥ 94 %), and pairing is on instance and world seed (test).

### S3-MOD-02 Relabeller, filters v2, dataset builder, mixture, cost per useful example — MOD — L — todo
- **Objective:** TRAINING §2.2 and §4–§7: `training/{relabel,filters,dataset,mixture}.py`, the funnel, the prefix-audit sampler and `make dataset-check`.
- **Owned paths:** `src/proxyloop/training/**`, `tests/training/**`, `mk/mod.mk`.
- **Deps:** S2-MOD-01, S3-ROOT-01.
- **Acceptance:**
  - F3 passes a public = private collision fixture;
  - F8 keeps "One moment." in two different contexts and drops an exact in-context duplicate;
  - the causal prefix rule truncates before the harm's cause turn;
  - relabel rows are flagged counterfactual and skip world-grounded filters;
  - `dataset-check` fails on a planted dev-family row;
  - built on 30 real S2 corpus bundles, 5 kept and 5 rejected rows are hand-checked by the root.

### S3-MOD-03 Curve orchestration (LOFO) — MOD — M — todo
- **Objective:** `make curve`: nested subsets by salt, 18 LOFO adapters plus 1 in-family (n = 300), each attested and deployed to vLLM slots and scored on the held-out family's 30 dev instances paired with C2 → `docs/results/s3-curve.json`, including cpue.
- **Owned paths:** `src/proxyloop/eval/curve.py`, `src/proxyloop/training/curve_spec.py`, `tests/eval/test_curve.py`.
- **Deps:** S3-MOD-02, S0-MOD-02.
- **Acceptance:** a dry-run on fakes schedules 19 trainings and 570 C1 + 180 C2 episodes; each training job refuses to start without P5 and a dataset-check pass.

### S3-ROOT-02 Run the ablations — ROOT — flags L+G — todo
Real bundles; the report is generated; the Ear-dependent metrics carry the S2 audit flags.

### S3-ROOT-03 MERGE POINT 2: data generation for the curve (pool + relabel) — ROOT — flags L — todo
- **Objective:** 1,200 teacher episodes and 600 relabelled rollouts [E] on families 1–6 under `semantics-v1`.
- **Acceptance:** provenance is complete; the funnel is printed; the prefix audit error is ≤ 10 %; spend is recorded.

### S3-ROOT-04 Run the curve — ROOT — flags L+G — todo
19 adapters, each with `adapter_card.json` (shard hashes) and liveness; every C1 bundle's `served_model_echo` equals its adapter.

### S3-ROOT-05 Go/no-go and S3 close — ROOT — flags U — todo
- The root presents the ablation and curve results against §8 and recommends go, reframe or stop. **The user decides.**
- Spend summary #3.
- A live correction, and a base-vs-adapter replay on the same seed.

---

## 6. S4 (subtask level) and S5+ (milestones)

### S4: confirmatory ML
| ID | Lane | Task | Owned paths | Acceptance (unmeetable by fakes) | Flags |
|---|---|---|---|---|---|
| S4-CON-01 | CON | `talkact_v1` profile + P6/P7 (TalkAct goldens made offline by `scripts/mod/talkact_golden.py`) | `contract/profiles/talkact_v1.py`, `tests/golden/talkact/**`, ADR | P6 byte-equal to the pinned TalkAct `_system()`+`_context()`; P7 60/60; `pl_*` fingerprints unchanged; pull-through `verify` passes | U (executes TalkAct code) |
| S4-SYS-01 | SYS | Families 7–12 + policy extensions + completability | `tasks/families/**`, `env/**` | reference predicate on 50 instances per family; **no live run on any family before the split draw** | – |
| S4-SYS-02 | SYS | Hermetic portal + capability transaction endpoint + Slow browser tools (TalkAct `Browser` port, MIT notice) | `env/portal/**`, `slow/browser.py`, `slow/tools.py` | **generic-click bypass test:** a submit without a token → 403 and no state change; a replayed token → 409; the token is bound to `action_hash`; one live portal bundle on a dev family chains approval → capability → `/tx` → `/api/state` evidence | L+G |
| S4-SYS-03 | SYS | `fast_only` topology + `FreeformRep` (PrincipalBench counterparty, MIT) | `kernel/`, `env/counterparty/freeform.py` | a real `fast_only[full]` and `[public]` bundle each; views match the matched-information spec (test) | L |
| S4-SYS-04 | SYS | World freeze v2 (`semantics-v2`): Ear revision for the new classes, world version hash | `env/**` | hash recorded; seal-check wired | – |
| S4-SYS-05 | SYS | Audit frame for the new classes + the C1 refresh stratum | `evidence/audit/**` | as S2-SYS-02 | – |
| S4-ROOT-01 | ROOT | **Split draw** by user salt over never-piloted families (EVAL §3); `split.lock.json`; `seal-check` CI | `tasks/splits/**`, CI | `seal-check` fails on a planted test id in a dev bundle; pilot-lock respected | U |
| S4-ROOT-02 | ROOT | Ear re-audit (new classes + C1 refresh) | `docs/results/s4-ear-audit.json` | EVAL §9.4 bars met | U |
| S4-ROOT-03 | ROOT | **Scientific pre-registration** `docs/prereg.md` (EVAL §10) with τ from S3, n, power, margin m | `docs/prereg.md` | the git order puts it before any S4 `data/sft` manifest; the user approves the PR | U |
| S4-MOD-01 | MOD | Data spec at n\* (TRAINING §5) + the `talkact_v1` share decided by a 20-episode dev check | `training/specs/**` | spend projection shown to the user; dataset-check green | L |
| S4-ROOT-04 | ROOT | Data generation run | manifest, card | provenance complete; contamination 0; relay model id constant | L |
| S4-MOD-02 | MOD | Training + dev selection (TRAINING §8) | `training/**`, `eval/**` | a real selection report; the chosen adapter's liveness and attestation | G+L |
| S4-ROOT-05 | ROOT | **Artefact lock** `artefacts.lock.json` | `docs/results/artefacts.lock.json` | committed before `unseal.json`; the runtime refuses on a hash mismatch | – |
| S4-ROOT-06 | ROOT | **Unseal** (the user provides the test salt) + L1 test matrix, run once | `docs/results/s4-l1-test.json`, `evidence/s4/**` | integrity gate; every bundle passes the claim check; verdict computed exactly per prereg | U+L+G |
| S4-MOD-03 | MOD | TalkAct rows (4B, 9B base, 9B SFT + anchors), reproduction wording | `eval/external/talkact.py`, `s4-talkact.json` | anchors within criterion in the same window; the SFT row uses the attested adapter | L+G (+U WebArena) |
| S4-MOD-04 | MOD | PrincipalBench A (native, deterministic) + B (duplex vs `fast_only[full]` vs `fast_only[public]`) | `eval/external/principal.py`, `s4-principal.json` | 25 items × arms × 5 seeds; "diagnostic subset" wording | L+G |
| S4-MOD-05 | MOD | Reports, cards, figures, generated README tables, claims | `docs/results/**`, `scripts/mod/figures/**` | `make docs-check` green; every number traces to a report; the negative-result clause is honoured | – |
| S4-ROOT-07 | ROOT | README narrative, limitations, claim ledger `final` | README, `docs/claims.yaml` | the user reads it | U |
| S4-ROOT-08 | ROOT | S4 close: base-vs-SFT replay (seed-selected) + a live correction with SFT Fast | – | user close | U |

### S5+: milestones (each gets PR-level subtasks when it is activated)
| Milestone | Scope | Gate (unmeetable by fakes) |
|---|---|---|
| **S5a Voice probe (cp lane first)** | `SimAudioChannel` on the cp lane (TTS → VAD → ASR), `text_heard` from the playback position; a thin probe of about 20 sessions; then optionally `LiveAudioChannel` | audio bundles with component latencies; queued speech after a stop or expiry is never heard as an authorised commitment; voice confirmation labelled "not authenticated consent" |
| **S5b Durability** | `PostgresEventLog`; Temporal `CaseWorkflow`; idempotency on `business_action_id`; approval as a durable update | 50 real chaos runs (kills mid-call, mid-approval, post-accept): 0 duplicate releases or ledger writes, 0 lost approvals, recovery ≥ 95 %; JSONL and Postgres fold identically |
| **S5c Browser compilation** | "Independently implemented" trace recorder → compiled workflows with per-step assertions; `run_workflow` through the capability endpoint; fallback to Slow | ≥ 50 runs per workflow: speedup, success and fallback rate; drift injection triggers fallback; no PreAct code or text (reviewer check) |
| **S5d Memory + channels** | `Memory` ≠ `KB` ≠ case state; email/SMS to the user's own address (U) | memory lift vs a no-memory control on held-out repeat cases, with a CI; consented real messages logged |

---

## 7. Parallel lanes and the critical path

```
            ROOT-01 tag ─┬─ ROOT-02 kit ─ ROOT-03 retro/README
                         ├─ ROOT-04 relay probe ───────────────────────────┐
S0  SYS:                 └─ SYS-01 port ─┬─ SYS-02 delete ───────────────────┐
    CON:                                 └─ CON-01 CONTRACT v1 ─┬───────────┼──────────────┐
    SYS:                                        SYS-03 core ──┐ │           │              │
                                                SYS-04 llm ───┼─┼─ SYS-05 world ─ SYS-06 kernel ─┐
    MOD:  ROOT-01 ─ MOD-01 serving (G) ─────────────────────── │ ──────────────────────────────── ┼─► ★ ROOT-05 MERGE POINT 1
                    MOD-02 training (G; dataset part after CON-01) ─────────────────────────────┘      │
                                                                                     MOD-03 pull-through ◄┘ ─► ROOT-06 close (U)
S1  SYS: SYS-01 guard ─┬─ SYS-02 timing+concurrency ─ SYS-05 web ─┐
                       ├─ SYS-03 slow v2 ─────────────────────────┤      SYS-06 otel (anytime after M1)
                       └─ SYS-04 world ───────────────────────────┤
    MOD: MOD-01 models/FSM/repair ─┬─ MOD-03 headroom probe (L+G) ─┴─ ROOT-02 pull-through ─ ROOT-04 close (U)
         MOD-02 metrics v1 ────────┘
S2  SYS: SYS-01 fam 5–6 ─ ROOT-01 corpus ─┐   SYS-02 audit tool ─┐
    MOD: MOD-01 metric repairs ────────────┼──── MOD-02 audit stats ┴─ ROOT-03 audit (U) ─ ROOT-04 close
         MOD-03 TalkAct anchors (parallel, non-blocking)   ROOT-02 human probes (U) ┘
S3  ROOT-01 semantics-v1 ─┬─ SYS-01 ablations ─ ROOT-02 run ablations ───────────────┐
                          └─ MOD-02 relabel/filters ─ ★ ROOT-03 MERGE POINT 2 (data) ─┼─ MOD-03 curve ─ ROOT-04 ─ ROOT-05 GO/NO-GO (U)
                             MOD-01 ablation report ──────────────────────────────────┘
```
**Critical path:** ROOT-01 → SYS-01 → CON-01 → SYS-03 ∥ SYS-04 → SYS-05 → SYS-06 → **ROOT-05** → MOD-03 → S0 close → S1-SYS-01 → S1-SYS-02 → S1-SYS-05 → S1-MOD-03 (probe) → S1 close → S2-SYS-01 → S2-ROOT-01 → S2-ROOT-03 (U) → S2 close → S3-ROOT-01 → S3-MOD-02 → **S3-ROOT-03** → S3-MOD-03/ROOT-04 → S3-ROOT-05.

The riskiest nodes are MOD-01/MOD-02 (Qwen3.5 GDN tooling), ROOT-05 (the first real episode), S1-SYS-02 (concurrency), S2-ROOT-03 (user time; Ear recall) and S3-ROOT-05 (headroom).

---

## 8. Switch criteria (adjusted from the round-3 debate; all go to the user as evidence plus a recommendation)
| Signal | When measured | Action |
|---|---|---|
| **S1 headroom probe shows T ≈ C2, or F ≈ C2** | S1 | **No stop** (diagnostic only). Report it and direct S2 families toward the classes where T − C2 is largest. |
| **Instrument failure:** harmful-class Ear recall < 0.90 (point) or LB < 0.80 after the one revision | S2, S4 | Metrics using that class are not reported, and S3 does not start until it is fixed. If it is unfixable, restrict the claim to deterministic metrics. |
| **Semantic instability:** > 2 of 8 human sessions or live corrections overturn an outcome label, or relay-only Slow fails on > 20 % of human sessions for want of transcript text | S1, S2 | Pause training work and repair the contract (ADR + pull-through) before S3. |
| **No causal headroom:** A4 converts < 25 % of C2 failures **and** A1 (relay suppression) changes safe success by less than the C2 − C2r noise floor | S3 | Stop scaling SFT. Options for the user: narrow the claim to a measured Fast behaviour (relay recall, stall recall, TTFS at equal safe success vs Haiku), or make the tasks harder for realism (never tuned to 9B), or change the student (a frozen decision). |
| **Flat curve:** `Δ̂_LOFO(1,000)` CI includes 0 and the 300 → 1,000 slope ≤ the noise floor, after one parity check (P3, P5, provenance, liveness) | S3 | Report the plateau honestly. S4 runs at n\* = the knee, or not at all (the user decides). |
| **Breadth essential:** at n = 300, `Δ_in − Δ_LOFO` > the noise floor | S3 | S4 adds the full 6 never-piloted families (no fewer), and the prereg claims the mixture only. If they agree within noise, B's concern is closed. |
| **Ceiling:** base 9B safe success ≥ 0.85 on the piloted families | S1–S3 | Recalibrate difficulty on the piloted families only, before `semantics-v1`. |
| **Tooling:** no GDN LoRA serving | S0 | ADR-0002 ladder: attention + MLP only (train = serve), or merged BF16. Fused training kernels unavailable → escalate. |
| **Semantics churn:** > 1 fingerprint change after `semantics-v1` | S3–S4 | Stop: data was generated too early. |
| **Process drift:** a stage exceeds its PR tripwire, or two PRs land without new reality (§0.6) | any | Freeze features and run the gate with what exists. |

---

## 9. Escalations (decisions-v3 checked against feasibility; none is silently changed)
- **E1 (clarification, not a change): the S0 pull-through label source.** Decisions A say S0 trains "on real in-harness turns", while decisions D forbid teacher runs in the harness before S1's Guard work. S0 therefore uses **base-9B in-harness turns** (canonicalised with `format_turn(parse(·))`) as labels. The run is plumbing only, and liveness is proven by logprob difference, not by behaviour change. From S1-ROOT-02 on, pull-through uses teacher turns.
- **E2 (scope within "contract first"): additions to the frozen list.** S0-CON-01 also freezes `SessionConfig` with **all S3 `AblationId`s**, the bundle manifest, and **every S1 prompt section**, including the disclosure opening. Both lanes call these, and freezing them now avoids fingerprint changes in S1–S3. The root should confirm this reading.
- **E3 (claim wording): the cp-lane capability.** A human rep cannot verify our capability, so on the cp lane it is a release token for our own Speaker. Complete mediation exists only at the S4 portal endpoint. The narrowed authority claim (I6) already fits this; no decision is needed.
- **E4 (unverified dependency): TalkAct's models and transport.** TalkAct needs `claude-opus-4-8` and `gemini-3.5-flash` through native SDKs [O `slow_agent.py:19,24`, `fast_agent.py:15`]. The relay's support is unverified (S0-ROOT-04). The default is in OPEN_QUESTIONS Q1. This does not block S0–S1.
- **E5 (unverified tooling): vLLM LoRA on the GDN projections.** The ADR-0002 ladder handles it. A merged fallback makes base and SFT separate processes, which is still one pinned configuration.
- **E6 (user time is load-bearing).** A "human-adjudicated" audit needs about 90 min of user labelling in S2 and about 60 min in S4 [E], plus the probes (about 1.5 h), the gates and the prereg. Without them the audit cannot be called human-adjudicated, and S3 is blocked by §8.
- **E7 (held-out breadth).** With 6 piloted families locked train-only and 12 families in total, the test covers 3 never-piloted families. The claim is therefore mixture-only, and thin. More families would strengthen it (OPEN_QUESTIONS Q2).
- **E8 (a known dynamic, accepted): teacher latency on the wall clock.** Sonnet-as-Fast is slower than the student, so teacher episodes see more cp silence strikes. This is accepted by decision (no dilation) and reported (`teacher_ttfs` vs `student_ttfs`, strikes per episode). World parameters are never adjusted per condition.
