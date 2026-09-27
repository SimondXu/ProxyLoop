# ADR-0012: Plan before act: the call opens when ready; the needs ledger

- **Status:** accepted (user decisions 2026-09-27: Q1 readiness is a framework-wide constraint with a per-task-kind requirement rule; Q2 at most two holds; Q3 left to the root. `INTAKE_S` and the task split: root decisions under PLAN §0.5a, 2026-09-27)
- **Date:** 2026-09-27
- **Task:** S1-ROOT-05 (records); S1-SYS-21 builds it
- **Amends:** ARCHITECTURE §8 (tools, status bar), §9.5 (INTAKE), §11 (when the cp lane starts).

## Context
- **No readiness.** `Kernel._open` opens both lanes at once: INTAKE→IN_CALL, the disclosure, the rep's ingress and the watchdog's rep clock all start before the user's first message. Slow's identity rule is reactive ("when the representative asks … ask_user"). In the reviewed runs the rep asked for identity before the facts were public, FastC answered unguided (a refusal, heard as `refuse_fact`), and the rep struck. Bundles: `evidence/s0/20260927T011721Z-dcb1a6`; the main checkout's git-ignored `runs/20260927T032340Z-cb8cb2`, `runs/20260927T050729Z-723c8f`, `runs/20260927T054451Z-655087`. Sources: the architect's design (plan-v3 handoff `2026-09-27-plan-before-act-design.md` §1–§2, §6.1) and the principal-architect review (`2026-09-27-dual-agent-review.md`, F1–F3, F8, F14a/b, R1, R3).
- **Repeated asks.** `ask_user` carries free text only and has no memory; an echo relay from FastU woke Slow into a second ask for the same facts (dcb1a6).
- **Options.** A task field `required_facts` (rejected: changes the piloted families' instance hashes, so `evidence/s0` stops loading); the rep's hidden `counterparty.identity` (rejected: world data); "all shareable keys" (rejected: over-asks optional levers); an agent-side requirement table (chosen).

## Decision
- **Requirement table** (`guard/readiness.py`, new, pure): `REQUIRED = {"cp_call": ("account.holder_name", "account.last4")}`; `kind(task) = "cp_call"` when `"cp" in task.channels`; `required = REQUIRED[kind] ∩ task.disclosure.shareable`; `missing(bb) = [k for k in required if k not in bb.public.facts]`. `slow/tools.py`'s `_IDENTITY` moves here. Later task kinds add rows, not a redesign.
- **Gate.** `_open` opens the user lane only; the case stays INTAKE. `Kernel._call(cause, reason)` opens the cp lane: `chan.opened{lane: cp, call, reason, missing}` (extra untyped payload keys), `status.changed` on the existing `call_opened` edge, the disclosure, cp ingress, FastC and a Slow wake `call_opened`. The call opens on the first of:
  - `ready`: a public `fact.recorded` empties `missing` (spawned after the current Slow act, never re-entrant);
  - `slow_start`: Slow's new tool `start_call()`, Guard-checked, allowed only when every missing key was asked and is `replied` (below);
  - `intake_deadline`: `INTAKE_S = 120` s after `session.started`, a kernel constant (root decision; the human-demo value is revisited at S1-SYS-05).

  Sessions without Slow or without a user lane open at once, as today. The watchdog does not tick the rep before `chan.opened{cp}`.
- **Invariants (tests).** R1: no `chan.opened{cp}` while `missing ≠ ∅` unless `reason ∈ {slow_start, intake_deadline}`, and `slow_start` needs every missing key `replied`. R2: no rep strike and no FastC generation before `chan.opened{cp}`.
- **Needs ledger** (`guard/needs.py`, new, pure): an event fold over `slow.tool{ask_user, args.keys}`, `s2f.msg`/`s2f.voiced`, `fast.turn` items, user-lane `f2s.msg` (with `utt_ref`), `fact.recorded`, `chan.strike` and `chan.opened/closed`. The kernel holds it (as it holds `Authority`), and Slow reads it for its status bar. No new state field, so it survives replay and ADR-0009's bounded context. Per key: `pending` from the ask; `replied` once a user-lane relay cites a `user.msg` newer than the ask's voicing (an echo relay cites the old message, so it is not a reply); `answered` once a `fact.recorded` for the key exists. ADR-0014 adds holds to it.
- **Ask dedupe (A1).** `ask_user(question, keys=[…])`; `keys` is optional. It is refused while every listed key is `pending` ("already asked; waiting for the user"); `replied` or `answered` keys may be asked again; keyless asks are counted (`keyless_ask`), not deduped. Invariant A1: at most one successful `ask_user` per key while it is `pending`.
- **Slow.** The prompt's identity paragraph becomes readiness-first: in the first step, one `ask_user(…, keys)` for every missing readiness key. The status bar gains `readiness` (missing keys, ask age, the deadline) and `asks`.
- **Acknowledgement (review R3a).** A GUIDE counts as voiced (`s2f.voiced`) only if the turn spoke or gave a directive; otherwise it is re-triggered once per message. The needs fold opens implicit needs from `s2f.voiced`, so an empty turn must not count.
- **Public summary (review R3b).** `public_summary` is declassified after the act's calls, so it may cite a fact the same act recorded.

## Evidence
No measured value backs this ADR; it records decisions. The failure trace is in the two handoff files named above; smoke #2 (S1-ROOT-06) is its first real test.

## Consequences
- **Contract / fingerprint impact:** none. No event type, state field, status edge or `SessionConfig` field is added; `pl_user_v1` and `pl_cp_v2` are unchanged. Slow's `act` tool snapshot (`tests/slow/snapshots/act_tool.json`) changes; that is SYS, not contract.
- **Data invalidated:** none.
- **Migration:** S1-SYS-21 after S1-SYS-26; S1-SYS-05 depends on it (`kernel/session.py`).
- **Risks.** The four S1 families lose identity pressure (the mid-call path is exercised by ADR-0014's recheck variants). `INTAKE_S` may fire before a human replies in `make demo`. Slow may omit `keys` (measured) or `wait`-poll in INTAKE (steps and spend; the Slow step cap applies). The web shows "call connected" later.
