"""The user's stop behind an ESCALATED close (S1-SYS-90; ADR-0023: S is "the
user stopped"), as one chain read from events, for ``tiers``' S.

ADVISORY ONLY, like ``tiers``: never a metric, a claim or a merge gate.

The chain is stop -> revoke -> replan -> the last status.changed to ESCALATED:

1. **Stop.** In a sim run it is a ``user.sim`` whose ``stop`` is ``stop`` or
   ``mind_change`` (world truth, ``simuser._reply``). In a run with no such
   stop (the UI) the ``f2s_revoke`` itself is the stop.
2. **Revoke.** An ``authority.epoch`` before the ESCALATED. In a sim run it
   is an ``f2s_revoke`` (FastU) or a ``slow_revoke`` (Slow) strictly after
   the stop by seq. In the UI it is an ``f2s_revoke``; a bare
   ``slow_revoke`` is never a stop, since a UI stop relayed only as a NOTE
   has no stop marker yet.
3. **Replan.** Every NEEDS_REPLAN between the revoke and the ESCALATED must
   be the revoke's own; a NEEDS_REPLAN with another cause, such as a later
   card's expiry, breaks the chain. ``replan_seq`` cites the first of them
   (None when there is none). The branch is the last status before the
   revoke:
   (a) A card was pending (AWAITING_APPROVAL). The chain needs the
   NEEDS_REPLAN that the revoke's bump caused (``kernel/fence.py`` stales
   the card).
   (b) No card was pending. The real kernel reaches this when the stop lands
   while an accept waits (COMMIT_AUTHORIZED): the bump stales the accept
   line at the floor, and that replan is the revoke's. If the case was
   already NEEDS_REPLAN at the revoke, that replan must be the stop's too:
   owned by a qualifying revoke after the stop, or caused by the stop's user
   fence (a ``speak.revoked{reason: fence}`` after the stop). Otherwise,
   for example after a card expired, this revoke does not qualify.

A NEEDS_REPLAN is the revoke's in either of two cases:

- The revoke is among its causes, followed transitively through
  ``cause_ids``.
- A link carries no cause, and the order of seqs decides. Among its causes
  is a ``speak.revoked{reason: epoch}``, and the last bump before that event
  is the revoke. This is the accept line that the bump made stale at the
  floor (``kernel/speaker.py``).

The first revoke whose chain holds is cited as ``{stop_seq, revoke_seq,
replan_seq}``. ``stop_seq`` is None in the UI. With no such revoke, the
result is None.
"""

from __future__ import annotations

from proxyloop.contract.events import Event
from proxyloop.obs.detectors import Inputs

# ``simuser._reply``'s ``stop`` values; obs may not import env, and
# tests/obs/test_tiers.py pins them (tests/env/test_stop.py pins the payloads).
STOPS = frozenset({"stop", "mind_change"})
REVOKES = frozenset({"f2s_revoke", "slow_revoke"})  # FastU's or Slow's
_UI_REVOKES = frozenset({"f2s_revoke"})


def _ancestors(x: Inputs, e: Event) -> list[Event]:
    """``e``'s causes, followed transitively, each counted once."""
    seen, todo, out = set[str](), list(e.cause_ids), list[Event]()
    while todo:
        if (i := todo.pop()) in seen or (c := x.by_id.get(i)) is None:
            continue
        seen.add(i)
        out.append(c)
        todo += c.cause_ids
    return out


def _owns(x: Inputs, bumps: list[Event], revoke: Event, replan: Event) -> bool:
    """Whether the NEEDS_REPLAN ``replan`` is ``revoke``'s (module doc)."""
    for c in _ancestors(x, replan):
        if c.event_id == revoke.event_id:
            return True
        if c.type == "speak.revoked" and c.payload.get("reason") == "epoch":
            last = [b for b in bumps if b.seq < c.seq]
            if last and last[-1].event_id == revoke.event_id:
                return True
    return False


def _stop_replan(
    x: Inputs, bumps: list[Event], replan: Event, after: int, kinds: frozenset[str]
) -> bool:
    """Whether a NEEDS_REPLAN already in place at a revoke is the stop's
    (module doc, 3(b)): owned by a qualifying revoke after the stop, or caused
    by a ``speak.revoked{fence}`` after it."""
    if any(
        after < q.seq < replan.seq and q.payload.get("reason") in kinds
        and _owns(x, bumps, q, replan)
        for q in bumps
    ):  # fmt: skip
        return True
    return any(
        c.type == "speak.revoked" and c.payload.get("reason") == "fence"
        and c.seq > after
        for c in _ancestors(x, replan)
    )  # fmt: skip


def stopped(x: Inputs) -> dict[str, object] | None:
    """The user's stop chain before the last ESCALATED (module doc), or None."""
    changes = x.of("status.changed")
    esc = [c.seq for c in changes if c.payload.get("status") == "ESCALATED"]
    if not esc:
        return None
    stops = [e.seq for e in x.of("user.sim") if e.payload.get("stop") in STOPS]
    stop = stops[0] if stops else None
    after, kinds = (-1, _UI_REVOKES) if stop is None else (stop, REVOKES)
    bumps = x.of("authority.epoch")
    for r in bumps:
        if not (after < r.seq < esc[-1] and r.payload.get("reason") in kinds):
            continue
        replans = [
            c for c in changes
            if r.seq < c.seq < esc[-1] and c.payload.get("status") == "NEEDS_REPLAN"
        ]  # fmt: skip
        if not all(_owns(x, bumps, r, n) for n in replans):
            continue  # another cause replanned the case after this revoke
        at = [c for c in changes if c.seq < r.seq]
        now = at[-1].payload.get("status") if at else None
        if now == "AWAITING_APPROVAL" and not replans:
            continue  # (a): the stale card's replan is missing
        if now == "NEEDS_REPLAN" and not _stop_replan(x, bumps, at[-1], after, kinds):
            continue  # (b): another cause replanned the case before this revoke
        replan = replans[0].seq if replans else None
        return {"stop_seq": stop, "revoke_seq": r.seq, "replan_seq": replan}
    return None
