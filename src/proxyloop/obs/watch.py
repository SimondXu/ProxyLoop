"""Watch items (S1-SYS-86): whether the risks accepted this round fired.

DIAGNOSTIC — not a claim or metric: reported, never a gate, never imported by
``proxyloop.eval``, and no number of it goes into a doc (rule 13). Events
only, from fixed emitters; each item is one pure fold over the run's events
with a ``count`` and the ``seqs`` that triggered it (``count`` None: the
bundle cannot tell, never 0).

- ``revoked_after_grant`` (B1, R-l): a speak.revoked{reason: fence} of an
  accept line (its speak.verbatim{kind: accept}) after a granted card
  (approval.decided; a mandate grant is not one); ``reaccepted``: those
  followed by a speak.released accept line.
- ``ttl_lost`` (B2): rep.policy{intent: offer_expired} (the world expires only
  open offers). Both sub-counts are scoped to the expired world offer through
  the agent's records (``progress.world_refs``: slot source_utt -> utt.final
  -> rep.mouth -> rep.policy offer_ref): ``after_grant``, a granted card for a
  revision whose record cites that offer, before the expiry;
  ``during_readback``, a cp ask_readback GUIDE citing an agent offer whose
  records cite it, or a rep.policy readback/confirm_accept of it, between the
  rep.policy that made the offer and the expiry. A card or ask whose record
  cites no rep line obs can follow counts for no offer.
- ``readback_asks`` (B3): ask_readback GUIDEs per offer revision while it had
  a slot not confirmed (``slow.readback_asks_max_per_revision``'s count, with
  its seqs); a revision with 2 or more is flagged (ADR-0020 W2's e2 rule).
- ``identity_strikes`` (B4): ``identity.strikes`` (chan.strike{kind:
  identity}) and the IDENTIFY -> ENDED hang-up with its intent ``reason``.
- ``slow_refusals`` (B5): slow.tool{ok: false} by ``code`` (``none``: an
  uncoded one) and tool; ``naming``: record_offer ``invalid_args`` refusals
  for a fee or credit code that is not the rep's name for it (S1-SYS-85), by
  kind and ``generic_word``/``not_said``. Documented exception (root ruling,
  rev-270): it reads ``result_text`` without ``--content``, matching only the
  anchored ``slow/offer_slots.py``-authored phrases (the whole problem list,
  from its start, is ``_named``'s: a model's field or value a shape refusal
  echoes never matches; tests pin it), and emits codes and counts, never text.
- ``sys72_activation`` (B7): a rep.policy{confirm_accept} whose rep.ear heard
  a Guard-released accept line (``tiers._accepted``), and each commit that
  only the confirm path holds (``tiers._check``: confirmed_by_free_speech).
- ``rep_confirm`` (B8): each rep.policy entering CONFIRM, and the next one
  leaving it (``exits``); ``wedged``: never left (X4), with the end reason.
- ``stop_to_grant`` (B9, S1-SYS-84): per user.sim{stop}: its delivery (the
  user.msg citing it) and the sim approver's first post after the stop (an
  approval.post by ``sim_approver``, or its refusal, action.denied{intent:
  approval.post}; for an ``after_card`` stop, the one citing its card);
  ``delay_ms``: post minus delivery on the bus clock.

Moved out (S1-SYS-89): world calls ending ``finish_reason: length`` (B6).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import cast

from proxyloop.contract.events import Event
from proxyloop.obs import grading, tiers
from proxyloop.obs.detectors import DETECTORS, Inputs, as_dict, safe
from proxyloop.obs.progress import LABEL, family, world_refs

# ``slow.result.Code``; obs may not import slow (.importlinter), test_watch pins.
CODES = frozenset({"invalid_args", "unknown_tool", "act_shape"})
# ``slow/offer_slots.py``: ``refused`` of ``_named``'s two problems, the
# whole problem list anchored at its start; test_watch pins the text.
_PROBLEM = (
    r"{o}fee|credit):[A-Za-z0-9_.:-]+: '[a-z0-9]+' is (?:{o}a generic word); "
    r"name a (?:fee|credit) by the words the rep used for it without "
    r"'[a-z0-9]+' \(e\.g\. [^()]*\)|{o}not in the cited line) [^;]+; use the "
    r"rep's words)"
)
_ONE = re.compile(_PROBLEM.format(o="("))
_ANY = _PROBLEM.format(o="(?:")
_NAMING = re.compile(
    rf"record_offer refused, nothing recorded: {_ANY}(?:; {_ANY})*\. Each slot is "
)
Item = dict[str, object]


def _grants(x: Inputs) -> list[Event]:
    """Granted cards (approval.decided); a mandate grant is the intake's
    pre-approval, before everything in its family, so it tells nothing here."""
    return [
        e for e in x.of("approval.decided") if e.payload.get("decision") == "granted"
    ]


def _cause(x: Inputs, e: Event, type_: str) -> Event | None:
    found = (x.by_id.get(c) for c in e.cause_ids)
    return next((c for c in found if c is not None and c.type == type_), None)


def _accept_line(x: Inputs, e: Event) -> bool:
    said = _cause(x, e, "speak.verbatim")
    return said is not None and said.payload.get("kind") == "accept"


def _revoked(x: Inputs) -> Item:
    grants = [g.seq for g in _grants(x)]
    released = [e.seq for e in x.of("speak.released") if _accept_line(x, e)]
    seqs = [
        e.seq for e in x.of("speak.revoked")
        if e.payload.get("reason") == "fence" and _accept_line(x, e)
        and any(g < e.seq for g in grants)
    ]  # fmt: skip
    again = sum(any(r > s for r in released) for s in seqs)
    return {"count": len(seqs), "seqs": seqs, "reaccepted": again}


def _kind(e: Event) -> object:
    return as_dict(e.payload.get("intent")).get("kind")


def _ref(e: Event) -> object:
    return as_dict(e.payload.get("intent")).get("offer_ref")


def _granted_offers(x: Inputs) -> list[tuple[int, set[object]]]:
    """Each granted card's seq and the world offers its revision cites."""
    cards = {
        c.payload.get("approval_id"): c.payload for c in x.of("approval.requested")
    }
    out = list[tuple[int, set[object]]]()
    for g in _grants(x):
        card = cards.get(g.payload.get("approval_id")) or {}
        refs = world_refs(x, card.get("offer_ref"), card.get("revision"))
        out.append((g.seq, refs))
    return out


def _asked_offers(x: Inputs) -> list[tuple[int, set[object]]]:
    """Each cp ask_readback GUIDE's seq and the world offers its cited agent
    offers (``offer:<ref>.<field>`` slots) cite."""
    out = list[tuple[int, set[object]]]()
    for g in x.of("s2f.msg"):
        guide = as_dict(g.payload.get("guide"))
        if g.payload.get("lane") != "cp" or guide.get("move") != "ask_readback":
            continue
        slots = [str(s) for s in cast(list[object], guide.get("slots") or [])]
        agent = {s[6:].partition(".")[0] for s in slots if s.startswith("offer:")}
        out.append((g.seq, set[object]().union(*(world_refs(x, a) for a in agent))))
    return out


def _ttl(x: Inputs) -> Item:
    policy, grants, asked = x.of("rep.policy"), _granted_offers(x), _asked_offers(x)
    seqs, after, during = list[int](), 0, 0
    for e in policy:
        if _kind(e) != "offer_expired":
            continue
        made = [p.seq for p in policy if p.seq < e.seq and _ref(p) == _ref(e)
                and _kind(p) in ("offer", "final_offer")]  # fmt: skip
        since = made[-1] if made else -1
        reads = [p.seq for p in policy if _ref(p) == _ref(e)
                 and _kind(p) in ("readback", "confirm_accept")]  # fmt: skip
        asks = [s for s, refs in asked if _ref(e) in refs]
        seqs.append(e.seq)
        after += any(s < e.seq and _ref(e) in refs for s, refs in grants)
        during += any(since < s < e.seq for s in [*asks, *reads])
    return {"count": len(seqs), "seqs": seqs, "after_grant": after,
            "during_readback": during}  # fmt: skip


def _asks(x: Inputs) -> Item:
    by: dict[str, list[int]] = {}
    asked = grading._asked(x)  # pyright: ignore[reportPrivateUsage]
    for ref, asks in asked.items():
        for g, o in asks:
            statuses = grading._statuses(x, o, g.seq)  # pyright: ignore[reportPrivateUsage]
            if any(s != "confirmed" for s in statuses.values()):
                by.setdefault(f"{safe(ref)}@{o.payload['revision']}", []).append(g.seq)
    flagged = sorted(s for seqs in by.values() if len(seqs) >= 2 for s in seqs)
    return {"count": sum(len(s) >= 2 for s in by.values()), "seqs": flagged,
            "by": {k: len(v) for k, v in sorted(by.items())}}  # fmt: skip


def _identity(x: Inputs) -> Item:
    value = as_dict(DETECTORS["identity.strikes"](x))
    if not value:
        return {"count": None, "seqs": []}
    strikes = cast(list[int], value.get("strikes") or [])
    end = next((e for e in x.of("rep.policy") if e.seq == value.get("abandoned")),
               None)  # fmt: skip
    ends = [] if end is None else [end.seq]
    return {"count": value.get("count"), "seqs": sorted([*strikes, *ends]),
            "strikes": strikes, "hang_up": None if end is None else end.seq,
            "hang_up_reason": None if end is None else safe(
                as_dict(end.payload.get("intent")).get("reason"))}  # fmt: skip


def _refusals(x: Inputs) -> Item:
    refused = [e for e in x.of("slow.tool") if e.payload.get("ok") is False]
    codes, tools = Counter[str](), Counter[str]()
    naming, why = list[int](), Counter[str]()
    for e in refused:
        code, name = e.payload.get("code"), e.payload.get("name")
        codes["none" if code is None else str(code) if code in CODES else "other"] += 1
        tools[grading._name(e)] += 1  # pyright: ignore[reportPrivateUsage]
        if name == "record_offer" and code == "invalid_args":
            whole = _NAMING.match(str(e.payload.get("result_text", "")))
            found = _ONE.findall(whole.group(0)) if whole else []
            why.update(
                f"{k}:{'generic_word' if g else 'not_said'}" for k, g, _ in found
            )
            naming += [e.seq] * bool(found)
    return {"count": len(refused), "seqs": [e.seq for e in refused],
            "by_code": dict(sorted(codes.items())),
            "by_tool": dict(sorted(tools.items())),
            "naming": {"count": len(naming), "seqs": naming,
                       "by": dict(sorted(why.items()))}}  # fmt: skip


def _sys72(x: Inputs) -> Item:
    confirms = list[int]()
    for p in x.of("rep.policy"):
        ear = _cause(x, p, "rep.ear") if _kind(p) == "confirm_accept" else None
        accepted = tiers._accepted  # pyright: ignore[reportPrivateUsage]
        if ear is not None and accepted(x, ear.payload.get("utt_id"), p.seq):
            confirms.append(p.seq)
    free = [
        c.seq for c in x.of("rep.commit_heard")
        if tiers._check(x, c)[2]  # pyright: ignore[reportPrivateUsage]
    ]  # fmt: skip
    return {
        "count": len(confirms) + len(free),
        "seqs": sorted([*confirms, *free]),
        "confirm_after_release": confirms,
        "confirmed_by_free_speech": free,
    }


def _confirm(x: Inputs) -> Item:
    policy, exits = x.of("rep.policy"), list[dict[str, object]]()
    for e in policy:
        if e.payload.get("to") != "CONFIRM" or e.payload.get("from") == "CONFIRM":
            continue
        left = next((p for p in policy if p.seq > e.seq
                     and p.payload.get("to") != "CONFIRM"), None)  # fmt: skip
        exits.append({
            "entered": e.seq, "left": None if left is None else left.seq,
            "to": None if left is None else safe(left.payload.get("to")),
            "intent": None if left is None else safe(_kind(left)),
        })  # fmt: skip
    ends = x.of("session.ended")
    end = safe(ends[-1].payload.get("reason")) if ends else None
    return {"count": len(exits), "seqs": [d["entered"] for d in exits],
            "exits": exits, "wedged": sum(d["left"] is None for d in exits),
            "end_reason": end}  # fmt: skip


def _stops(x: Inputs) -> Item:
    posts = [
        e for e in x.of("approval.post", "action.denied")
        if (e.type == "approval.post" and e.actor == "sim_approver")
        or e.payload.get("intent") == "approval.post"
    ]  # fmt: skip
    out = list[dict[str, object]]()
    for s in x.of("user.sim"):
        if "stop" not in s.payload:
            continue
        msg = next((m for m in x.of("user.msg") if s.event_id in m.cause_ids), None)
        card = _cause(x, s, "approval.requested")  # an after_card stop's card
        mine = [p for p in posts if card is None or card.event_id in p.cause_ids]
        post = next((p for p in mine if p.seq > s.seq), None)
        outcome = None if post is None else (
            safe(post.payload.get("decision")) if post.type == "approval.post"
            else f"denied:{safe(post.payload.get('reason'))}"
        )  # fmt: skip
        delay = None if post is None or msg is None else post.t_ms - msg.t_ms
        out.append({"stop": s.seq, "kind": safe(s.payload.get("stop")),
                    "delivered": None if msg is None else msg.seq,
                    "post": None if post is None else post.seq,
                    "outcome": outcome, "delay_ms": delay})  # fmt: skip
    return {"count": len(out), "seqs": [d["stop"] for d in out], "stops": out}


ITEMS: dict[str, Callable[[Inputs], Item]] = {
    "revoked_after_grant": _revoked, "ttl_lost": _ttl, "readback_asks": _asks,
    "identity_strikes": _identity, "slow_refusals": _refusals,
    "sys72_activation": _sys72, "rep_confirm": _confirm, "stop_to_grant": _stops,
}  # fmt: skip
# Per-run sub-counts the family summary sums beside ``total``.
_SUMS = {
    "revoked_after_grant": ("reaccepted",),
    "ttl_lost": ("after_grant", "during_readback"),
    "rep_confirm": ("wedged",),
}


def run(x: Inputs) -> dict[str, object]:
    return {"label": LABEL, "items": {name: fn(x) for name, fn in ITEMS.items()}}


def summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Per family over one diagnose group's rows: per item the ``total`` count,
    the ``runs`` it fired in (``unknown``: runs that cannot tell), the summed
    sub-counts, and B9's delays and naming refusals."""
    fams: dict[str, dict[str, object]] = {}
    for r in rows:
        w = as_dict(as_dict(r.get("watch")).get("items"))
        if not w:
            continue
        fam = fams.setdefault(family(r), {"runs": 0})
        fam["runs"] = cast(int, fam["runs"]) + 1
        for name, value in w.items():
            v, got = as_dict(value), cast(dict[str, object], fam.setdefault(
                name, {"total": 0, "runs": []}))  # fmt: skip
            n = v.get("count")
            if not isinstance(n, int):
                got["unknown"] = cast(int, got.get("unknown", 0)) + 1
                continue
            got["total"] = cast(int, got["total"]) + n
            cast(list[object], got["runs"]).extend([r.get("run_id")] * bool(n))
            for key in _SUMS.get(name, ()):
                got[key] = cast(int, got.get(key, 0)) + cast(int, v.get(key, 0))
            if name == "stop_to_grant" and n:
                got["delays_ms"] = [*cast(list[object], got.get("delays_ms", [])),
                                    *(as_dict(d).get("delay_ms") for d in
                                      cast(list[object], v.get("stops")))]  # fmt: skip
            if name == "slow_refusals":
                naming = as_dict(v.get("naming")).get("count")
                got["naming"] = cast(int, got.get("naming", 0)) + cast(int, naming)
    return {"label": LABEL, "families": dict(sorted(fams.items()))}


def block(s: Mapping[str, object], group: str) -> str:
    """The human block diagnose prints per group, after the progress block."""
    kind, _, value = group.partition(":")
    out = [f"== watch {kind} {value[:12]} ({LABEL})"]
    for fam, c in as_dict(s["families"]).items():
        cells = [f"  {fam} runs={as_dict(c)['runs']}"]
        for name in ITEMS:
            got = as_dict(as_dict(c).get(name))
            fired = len(cast(list[object], got.get("runs") or []))
            extra = [f"{k}={got[k]}" for k in got if k not in ("total", "runs")]
            cells.append(" ".join([f"{name}={got.get('total', 0)} ({fired} runs)",
                                   *extra]))  # fmt: skip
        out.append(cells[0])
        out += [f"    {x}" for x in cells[1:]]
    return "\n".join(out)
