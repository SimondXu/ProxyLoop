# Post-Phase-03C handoff (written 2026-09-23)

Purpose: let a fresh session pick up after Phase 03C without re-deriving it.
Read this, then `harness/status.toml`. Read
`harness/log/phase-03c-stage2-stage3.md` only if you need a 03C number, and
`docs/ml-evidence.md` if you need to explain the result to anyone. Do not
start from `PLANS.md` prose or the 144 KB `harness/build-log.md`.

First sentence for the new session: **"读 `harness/context/post-phase-03c-handoff.md`，
然后按第 3 节告诉我下一步该做什么。"**

## 1. Where things are

Phase 03C is **closed**, squash merged as `059d333` through PR #51.
`harness/status.toml` is `idle`, `active_product_phase` and `active_contract`
are empty, `next_phase_authorized = false`. **No phase is active.** The next
one is a new user decision; do not start one because the roadmap lists it.

A parallel audit-remediation track merged PRs #46–#50 the same day (offer
policy authority, workflow receipt guard, r4 rescore, state-based action
verification, content-free public ids). That track has its own standing
authorization; see the user's memory, not this file.

## 2. What Phase 03C established, and what it did not

**Decision `GO_DISTILLED`.** LoRA r32 on 1.055 % of Qwen3-8B, 7,196
oracle-filtered `claude-sonnet-5` rows, 1,350 steps, 6.75 h on one A100-80GB
through Modal. On 240 held-out rows from six families absent from training,
act agreement is **0.542 untuned against 0.983 distilled**. Every raw output
was re-scored locally against the repository evaluator: 2,560 comparisons,
zero disagreements.

**Four qualifications travel with that number. Do not quote it without them**
(they are argued in full in `docs/ml-evidence.md`):

1. The 240 rows carry **six decision rules**, not 240 independent trials —
   each family's 40 rows share one oracle act — so the row-level Wilson
   intervals in the reports are optimistic.
2. The whole gain is **one repaired defect**. The untuned model already
   handled the three push-back families (116/120) and almost never said
   `confirm` (14/120). Training taught it when to accept. The majority-class
   baseline is 0.500, so 0.542 is near guessing.
3. The guided-JSON arms lost 114/240 and 22/240 rows to the 512-token cap and
   measure truncation, not constrained decoding. The decision is unaffected:
   it rests on A1 and A3, neither of which truncated a row.
4. "Zero policy violations" on held-out is **partly untested** — no row there
   can trip the disclosure detector — while the same run's dev rows show the
   distilled model naming a restricted field 4 times in 400 (untuned: 7).

**`make phase03c-rescore-check` locks these numbers.** It replays every
stored raw output through the current evaluator and fails if the committed
re-scored reports drift. It already proved the numbers survive the evaluator
changes in PRs #48–#50. Run it after any evaluator or simulator change.

## 3. The open decision

Three candidates, in the order the previous session recommended:

**A. Promote the adapter into the Runtime Fast slot.** The product still
runs the untuned model, so 03C's result exists only on paper. Purely
internal; contacts no external party. Needs real-model load, capacity, p95,
and a fallback path. `PLANS.md` marks promoted serving as separately gated
and `harness/status.toml` has listed it as inactive throughout.

A sub-decision comes with it: the selected adapter still leaks a restricted
field 4 times in 400 on in-family rows. The previous session's view was to
promote but carry that into serving-side detection, on the grounds that the
untuned model is worse on the same detector (7/400), so not promoting is not
the safer option. That view is recorded, not decided.

**C. Phase 07 portfolio hardening.** Lowest risk, advances no product
capability.

**B. Phase 06B2 real controlled integration.** Real provider, e-mail, MCP,
credentials. **The only phase that contacts real external parties.** Every
channel needs its own explicit authorization. Should be last.

Also queued, small and independent: `scripts/run_phase03c_training.py` globs
one directory level, so `make test` reports the training-manifest check green
while skipping both cloud manifests (`cloud-run-01`, `smoke-01`). A task chip
exists for it; see `harness/code_review/phase-03c-stage3-decision.md` I5.

## 4. Facts that save time

- **The relay keys are exhausted.** All three in `.env` (`api`, `备用key1`,
  `备用key2`, `key:value` lines, never print them). No teacher call is
  possible or needed. Real relay usage over Stages 1b/1c was ≈ USD 121.59.
  *Correction (2026-09-25, PR-17):* USD 121.59 is the accounted estimate
  for the v6 full generation run alone. Real relay usage across all Stage
  1b/1c runs was ≈ USD 146 (`harness/log/phase-03c-stage1c-full-generation.md`,
  `harness/context/phase-03c-stage2-handoff.md` §5). The original sentence is
  kept above; the full cost table is in `docs/limitations.md`.
- **Modal is set up**: CLI installed with `uv tool install modal`,
  authenticated for workspace `simondxu`. The run cost ≈ USD 18 of the
  USD 30 monthly free credit, USD 22.25 including six smoke runs. Billing is
  a console reading (`modal billing summary`), not a repository artifact.
  Stop a stray app with `modal app stop -y <app-id>`.
- **Re-running the training is not free and not automatic.** The bundle and
  the runner are in the repository; `modal run --detach
  ml/training/phase03c_cloud/modal_run.py` would cost another ≈ USD 18 and
  the monthly credit does not cover two full runs.
- **Frozen by fingerprint, add modules and never edit**: `qwen_mlx.py`,
  `fast_output.py`, `fresh_fixtures.py`, `phase03b_experiment.py`,
  `hosted_rerun.py`, `openai_frontier.py`.
- **Captured run logs are evidence and are committed byte-exact.**
  `.gitattributes` exempts `data/experiments/**/*.log` from git's whitespace
  check because tqdm and vLLM leave carriage returns before the newline. Do
  not normalise a log to make a check pass; change the check.
- **CI checks what the local gate does not.** `make preflight-fast` runs
  `git diff --check` over the working tree, which is empty after a commit;
  CI runs it over the committed branch diff. Reproduce CI locally with
  `git diff --check origin/main...HEAD` before pushing.
- `.claude/worktrees/phase-03c-parallel` belongs to a sibling session. Never
  add it; it shows as untracked in every `git status`.
- Verification: `make preflight-fast` while iterating, `make preflight` once
  on the stable diff, `make test` for every artifact check. Report passed,
  failed, blocked, skipped and unrun separately; never claim a check passed
  without its output.
- Keep the main session as orchestrator and run every gate past an
  independent `reviewer`. Both 03C reviews returned Request Changes with
  findings that mattered, including one the orchestrator had missed.
