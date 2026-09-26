# Task packet template (the root sends this to one `implementer`)

Rules for the root: fill every field, and paste the task block from `PLAN.md` **verbatim** (never paraphrase it). Attach `NORTH_STAR.md` in full. Name at most 5 files; the implementer may read code they point to, but gets no other briefing. One packet = one task = one worktree = one PR.

```text
TASK PACKET — <TASK-ID>: <title>
Contract version: v<N> (fingerprints: pl_user_v1=<fp8>, pl_cp_v1=<fp8>)      PLAN.md commit: <sha>

WORKTREE
  path:   ../pl-wt/<TASK-ID>
  branch: task/<task-id-lowercase>   (created by root from origin/main@<sha>)
  You may commit on this branch. Never push, merge, rebase main, or touch another worktree.

NORTH STAR
  <full text of NORTH_STAR.md attached>

TASK BLOCK (verbatim from PLAN.md)
  <paste>

OWNED PATHS (edit only these; anything else → stop and report)
  <list>
  Shared-file exception: <none | "one dependency line in [dependency-groups] <sys|mod>">
  Root-owned paths granted (ROOT tasks only, PLAN.md §0.1): <none | list>

FROZEN INTERFACES YOU CALL BUT MUST NOT CHANGE
  <list of contract symbols / other modules>

NAMED FILES (≤ 5; read these first)
  1. <path> — <why>
  2. …

OUT OF SCOPE (do not do)
  <explicit non-goals, including adjacent tasks by ID>

VERIFICATION (run all that do not need L/G/U; paste output tails)
  <commands>
  Root-run later (do NOT attempt): <commands with flags L/G/U>

ESCALATE (stop and return a note) IF
  <task-specific triggers>
  + any contract need, any file outside owned paths, any fallback/second path, size > <S|M|L> budget,
    any held-out data, anything needing keys/GPU.

RETURN FORMAT
  The 8-section report in .claude/agents/implementer.md.
```

---

## Filled example: S0-CON-01

```text
TASK PACKET — S0-CON-01: Freeze the shared contract (contract v1)
Contract version: none → v1 (this task creates it)      PLAN.md commit: <sha after S0-SYS-01 merge>

WORKTREE
  path:   ../pl-wt/S0-CON-01
  branch: task/s0-con-01   (created by root from origin/main@<sha>)
  You may commit on this branch. Never push, merge, rebase main, or touch another worktree.

NORTH STAR
  <full text of NORTH_STAR.md attached>

TASK BLOCK (verbatim from PLAN.md)
### S0-CON-01 Freeze the shared contract (contract v1) — CON — L — todo — **first build PR**
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

OWNED PATHS (edit only these; anything else → stop and report)
  src/proxyloop/contract/**
  tests/contract/**
  tests/golden/**
  docs/decisions/0004-contract-v1.md
  Shared-file exception: dependency lines in [dependency-groups] dev for `transformers` (tokenizer
  only, for the P2 tests; pinned) and `hypothesis`. The contract itself imports only stdlib + pydantic.

FROZEN INTERFACES YOU CALL BUT MUST NOT CHANGE
  proxyloop.guard.terms.terms_hash, terms_hash_v1 (from S0-SYS-01) — reference only; never import it
  into the contract (the contract imports stdlib + pydantic only; render_prompt receives the tokenizer).

NAMED FILES (≤ 5; read these first)
  1. ARCHITECTURE.md — §0 (changes table), §2 (module map, import rules), §4 (events), §5 (public/private
     state, views, declassification tests), §6 (grammar, profiles, context budget), §7 (F↔S messages),
     §12 (parity tests), §14 (bundle). This is the spec; implement it, do not redesign it.
  2. external/pine-ai-tasks/repos/TalkAct/src/cuv/fast_agent.py — lines 21-44 (SYSTEM text to adapt for
     pl_user_v1), 79-91 (section layout), 168-191 (parser behaviour our tolerant parser must accept).
  3. external/pine-ai-tasks/repos/TalkAct/src/cuv/shared.py — lines 53-64 (transcript rendering; our
     budget trimming replaces the fixed last-40 window).
  4. EVAL.md — §2 (task schema fields the briefs and disclosure allow-list come from).
  5. pyproject.toml — workspace layout and tool config from S0-SYS-01.

OUT OF SCOPE (do not do)
  Reducers/fold (S0-SYS-03), LLM adapters (S0-SYS-04), Guard logic incl. declassify() and readback
  grounding (S0-SYS-06, S1-SYS-01), kernel, the talkact_v1 profile and P6/P7 (S4-CON-01), P3 live parity
  (S0-SYS-04), any Makefile/CI edit (S0-SYS-02), any make target.

VERIFICATION (run all; paste output tails)
  uv run pytest tests/contract tests/golden -q
  uv run pyright src/proxyloop/contract
  uv run ruff check src/proxyloop/contract tests/contract tests/golden
  uv run lint-imports            # contract imports only stdlib + pydantic
  Root-run later (do NOT attempt): S0-MOD-01 compares vLLM /tokenize ids with your P2 goldens (G).

ESCALATE (stop and return a note) IF
  - the Qwen3.5 chat template yields different generation-prompt bytes for enable_thinking=False between
    apply_chat_template(tokenize=True) and (tokenize=False)+encode;
  - any ARCHITECTURE §5–§7 field seems insufficient for S1 (read-back slots, approval card, capability)
    or for the S3 ablations — propose, do not add;
  - TalkAct's tolerant parsing conflicts with canonical output for our extensions;
  - the counterfactual property fails for a reason that implies a view design change;
  - diff > 1,200 changed lines excluding tests/goldens.

RETURN FORMAT
  The 8-section report in .claude/agents/implementer.md. Include the recorded fingerprints and the
  think-block bytes (hex) in section 3.
```
