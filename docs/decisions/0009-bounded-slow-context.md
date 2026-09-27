# ADR-0009: Bounded Slow context

- **Status:** accepted (root decision under §0.5a, 2026-09-27)
- **Date:** 2026-09-26
- **Task:** S0-SYS-07
- **Amends:** ARCHITECTURE §8 "Slow context" ("the append-only tool history").

## Context
ARCHITECTURE §8 gives Slow an append-only tool history, with a prompt cache on the newest tool result. The failed S0-ROOT-05 live smokes (handoff 2026-09-26 §3; the runs are not in the repo) showed what that costs without the cache. Every `f2s.msg` woke Slow, FastC repeated the same HOLD relay every turn, and each step resent the whole history. Back-to-back Slow steps hit the $5 runaway guard in one sim session, all of it Slow spend. The relay adapter refuses the cache breakpoint, and the main root dropped the prompt-cache work until the Slow model is settled. So the history itself has to stop growing. The options were:
- trim by characters or tokens (rejected: a cut inside a turn can separate an assistant tool call from its result, which the OpenAI-shaped API rejects);
- keep the last K turns and let Slow's own summaries stand in for older ones (chosen);
- have a model summarise the dropped turns (rejected: a second model call per step, and a model-written text Slow never wrote itself).

## Decision
Each Slow request is, in order:
1. the stable system prompt;
2. one user message: `TASK: slow_brief` and the canonical shareable fact keys, then
   - while nothing has left the window: the first step's notes, exactly as before;
   - after that: `[EARLIER] N earlier turns left this context`, and Slow's latest `private_summary` and `public_summary` from `SlowView`;
3. the last `WINDOW = 6` answered turns [E]. A turn is Slow's assistant message with the messages that answered it: one `tool` result per tool call, with the next step's notes appended to the last result, or one `user` message with the notes when the answer called no tool. A turn leaves the window whole, so every tool call stays followed by its result.

The current step's notes (`[WAKE]`, the unread `[USER CHAT]`/`[REP CALL]` relays, `[STATUS]`) are always the last content. The status bar now also lists the facts Slow recorded (`key=value [public|private]`), so a fact relayed before the window stays visible.

Everything in the context comes from `SlowView` or from Slow's own answers and tool results. The bound changes how much of Slow's own history it sees, not what Slow may see: no transcript enters it (I5, AGENTS rule 9). The cache breakpoint of §8 stays unused until the Slow model is settled.

## Evidence
No measurement backs `WINDOW = 6`; it is an estimate, marked [E]. `tests/slow/test_loop.py::test_slow_context_is_bounded_and_keeps_every_call_with_its_result` runs 18 steps and checks the following: each request keeps `min(step, 6)` assistant turns; every tool call is followed by its result; the notes of steps that left the window are gone; the head carries the latest summaries; and the request size stops growing after the window fills. The S0-ROOT-05 re-run (root, flag L) measures the per-step Slow tokens.

## Consequences
- **Contract / fingerprint impact:** none. Slow's messages are not rendered by `proxyloop.contract.protocol`, and `pl_user_v1` and `pl_cp_v1` are unchanged. The same task (S0-SYS-07) records the S0 runaway guard in force as an extra `runaway` key on `session.started` (`factor`, `tokens`, `unpriced_calls`, `cap_micro_usd`). `session.started` has no payload model, so no snapshot, golden or `evidence-check` changes.
- **Data invalidated:** none. No dataset trains on Slow requests.
- **Migration:** none. ARCHITECTURE §8 should point here when the root next edits it.
- **Risks and what would make us revisit this:** Slow can forget a relay it never recorded or summarised once it leaves the window. The prompt asks Slow to record facts, and the status bar keeps them. Revisit this if live runs show Slow re-asking for things it already had, or when the prompt cache lands: with a cache, a longer window can cost less than this one.
