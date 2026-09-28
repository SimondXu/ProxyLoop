"""Offer-ladder detectors: how far the rep's ladder went, from rep.* events.

ADVISORY ONLY: triage signals, never a metric, a claim or a merge gate (and
never imported by ``proxyloop.eval``). They register in ``DETECTORS``.

Events only: a bundle carries no ladder, only its task_ref, and obs never
resolves a task spec (AGENTS rule 11). The world policy's lever rule
(``env/counterparty/policy.py`` ``_lever``) is read back from its events: a
rep.ear whose act is a lever causes one rep.policy (``SimRep._run``); an
``offer``/``final_offer`` answer takes the lever and moves one rung; a
``no_better`` answers a lever already taken (a repeat) or a new one past the
last rung (the ladder is exhausted, so its length is known). A lever answered before
identity passed (from GREET or IDENTIFY: ``ask_identity``, ``hang_up``) is
heard, not pulled. None: no rep.policy (no world policy in the bundle).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeGuard

from proxyloop.obs.detectors import Inputs, Value, as_dict, detector, safe

# ``env.counterparty.ear.Lever``; obs may not import env (.importlinter),
# tests/obs/test_ladder.py pins them equal.
LEVERS = frozenset({"ask_discount", "cite_competitor", "cancel_intent", "tenure"})
# The levers an S1 agent can pull: cancel_intent needs an authorisation this
# build never grants (slow/state.py) and no format makes competitor.* public.
REACHABLE = frozenset({"ask_discount", "tenure"})
_TAKES = frozenset({"offer", "final_offer"})
# ``env.counterparty.policy.State`` split at identity (test_ladder pins that
# these, TRANSFER and ENDED cover it): past identity is IDENTIFY -> DISCOVER,
# or GREET -> DISCOVER when the first line gives every fact; ENDED and
# TRANSFER straight from IDENTIFY are a hang-up or a transfer, never a pass.
BEFORE_IDENTITY = frozenset({"GREET", "IDENTIFY"})
PAST_IDENTITY = frozenset({"DISCOVER", "OFFER", "FINAL", "CONFIRM", "CONFIRMED"})


def _is(value: object, names: frozenset[str]) -> TypeGuard[str]:
    """A payload value is one of ``names``; a malformed one (a list, a dict)
    matches nothing instead of raising."""
    return isinstance(value, str) and value in names


@dataclass(frozen=True)
class _Ladder:
    rungs: int  # rungs reached
    heard: frozenset[str]
    taken: frozenset[str]
    pulled: frozenset[str]  # answered by the ladder, after identity
    repeats: tuple[int, ...]  # seqs of the no_better answers to a taken lever
    exhausted: bool
    identified: bool  # some rep.policy moved past identity


def _read(x: Inputs) -> _Ladder | None:
    policy = x.of("rep.policy")
    if not policy:
        return None
    answer = {c: e for e in policy for c in e.cause_ids}
    heard, taken, pulled = set[str](), set[str](), set[str]()
    repeats, exhausted = list[int](), False
    for ear in x.of("rep.ear"):
        if not _is(lever := ear.payload.get("act"), LEVERS):
            continue
        heard.add(lever)
        if (reply := answer.get(ear.event_id)) is None:
            continue
        frm = reply.payload.get("from")
        if isinstance(frm, str) and frm not in BEFORE_IDENTITY:
            pulled.add(lever)
        kind = as_dict(reply.payload.get("intent")).get("kind")
        if _is(kind, _TAKES):
            taken.add(lever)
        elif kind == "no_better" and lever in taken:
            repeats.append(reply.seq)
        elif kind == "no_better":
            exhausted = True
    rungs = [r for e in policy if isinstance(r := e.payload.get("rung"), int)]
    reached = max(rungs) + 1 if rungs else 0
    identified = any(_is(e.payload.get("to"), PAST_IDENTITY) for e in policy)
    return _Ladder(reached, frozenset(heard), frozenset(taken), frozenset(pulled),
                   tuple(repeats), exhausted, identified)  # fmt: skip


@detector("rungs_reached")
def _rungs(x: Inputs) -> Value:
    """The highest rep.policy ``rung`` + 1 (0: no offer was made);
    ``ladder_len`` only once a new lever was answered ``no_better`` (the
    ladder is exhausted), else None: unknown, never guessed."""
    if (d := _read(x)) is None:
        return None
    length = d.rungs if d.exhausted else None
    return {"count": d.rungs, "ladder_exhausted": d.exhausted, "ladder_len": length}


@detector("levers_heard")
def _heard(x: Inputs) -> Value:
    """The distinct levers the rep heard (rep.ear), and those it answered
    with an offer (``taken``)."""
    if (d := _read(x)) is None:
        return None
    return {"count": len(d.heard), "levers": sorted(d.heard),
            "taken": sorted(d.taken)}  # fmt: skip


@detector("repeated_lever_no_better")
def _repeats(x: Inputs) -> Value:
    """``no_better`` answers to a lever already taken (their rep.policy seqs)."""
    if (d := _read(x)) is None:
        return None
    return {"count": len(d.repeats), "seqs": list(d.repeats)}


@detector("no_deal_ladder_unfinished")
def _unfinished(x: Inputs) -> Value:
    """1 when the session ended (any reason) past identity with no
    rep.commit_heard, the ladder not proven exhausted, and a reachable lever
    never pulled (``unused``); else 0, ``reason`` says which: ``no_ladder``
    (identity never passed: the ladder was never open, ``unused`` is []),
    ``committed``,
    ``exhausted``, ``all_pulled`` or ``unfinished`` (the 1). None: no
    rep.policy, or no session.ended yet."""
    ends = x.of("session.ended")
    if (d := _read(x)) is None or not ends:
        return None
    unused = sorted(REACHABLE - d.pulled) if d.identified else []
    reason = (
        "no_ladder" if not d.identified
        else "committed" if x.of("rep.commit_heard")
        else "exhausted" if d.exhausted
        else "unfinished" if unused
        else "all_pulled"
    )  # fmt: skip
    return {"count": int(reason == "unfinished"), "reason": reason,
            "end_reason": safe(ends[-1].payload.get("reason")),
            "unused": unused}  # fmt: skip
