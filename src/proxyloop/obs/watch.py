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
  for a fee or credit code that is not the rep's name for it (S1-SYS-85,
  S1-SYS-87), by field kind and ``snake_case``/``not_said``/``generic_word``.
  Documented exception (root ruling, rev-270): it reads ``result_text``
  without ``--content`` and emits codes and counts, never text. The problem
  list is read left to right against ``slow/offer_slots.py``'s own templates
  (S1-SYS-91): each item whole, a naming item, then "; " or the table, whose
  tails must then be one per named field. ``record_offer`` refuses by stage
  and returns at the first, so a list that starts with a shape, value or
  conflict item holds no naming item: a model's field, value, key or ref such
  an item echoes never counts (tests pin it). A list that breaks after k
  naming items, or whose tails do not match, counts k and lists its seq in
  ``lower_bound`` ("naming ≥ k"). No refusal vanishes: one whose first item
  fits no offer_slots template (naming, shape, conflicts, value) nor the
  dispatcher's is listed in ``naming_unparsed``, never counted as 0.
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

from proxyloop.contract import base
from proxyloop.contract.events import Event
from proxyloop.contract.state import READBACK_FIELD
from proxyloop.obs import grading, tiers
from proxyloop.obs.detectors import DETECTORS, Inputs, as_dict, safe
from proxyloop.obs.progress import LABEL, family, world_refs

# ``slow.result.Code``; obs may not import slow (.importlinter), test_watch pins.
CODES = frozenset({"invalid_args", "unknown_tool", "act_shape"})
# ``slow/offer_slots.py``'s texts (``refused``, ``_named``, ``EXAMPLE``,
# ``unnamed``), restated; test_watch_naming pins each against offer_slots.
_REFUSED = "record_offer refused, nothing recorded: "
_TABLE = (
    ". Each slot is {field, value, utt_ref}; by field (field → role, unit, value): "
)
_EXAMPLE = {
    "fee": "a porting fee is fee:porting",
    "credit": "a paperless credit is credit:paperless",
}
_TAIL = (
    "{field}: if the rep named this {kind} by no specific word, record_offer the "
    'other slots, then guide_fast(ask_readback, ["offer:{ref}"]) once more; '
    "a {kind} must be named by the rep to be recorded"
)
_ID = r"[A-Za-z0-9_.:-]+"  # READBACK_FIELD's code chars; a kernel utt_id's
_WORD = r"[a-z0-9]+"  # a code word, once the code passed ``_CODE``
# One pattern per naming kind and field kind, matched whole at an item's
# start; its key is the ``by`` key.
_ITEMS = {
    f"{k}:{kind}": re.compile(f"(?P<field>{k}:{_ID}): {rest}")
    for k in ("fee", "credit")
    for kind, rest in {
        "snake_case": rf"a code is lower snake_case \({k}:[a-z0-9_]*\)",
        "not_said": rf"'{_WORD}' is not in the cited line {_ID} as a whole "
        r"word; use the rep's words",
        "generic_word": rf"'(?P<w>{_WORD})' is a generic word; name a {k} by "
        rf"the words the rep used for it without '(?P=w)' \(e\.g\. "
        rf"{re.escape(_EXAMPLE[k])}\)",
    }.items()
}
# The first item of offer_slots' other refusals, up to the model's text: shape
# (l.90-114), value (l.136-138) and conflicts (l.122-127, no table after
# them), and the dispatcher's (``slow/tools.py``: "invalid arguments: ...").
_F = READBACK_FIELD.removeprefix("^").removesuffix("$")  # a field shape passed
_OTHER = re.compile(
    "|".join((
        "a slot is an object, not ", "a slot takes no ", "unknown field ",
        "utt_ref is the utt id of the rep line that says it, not ",
        rf"{_F} is over {base.MAX_SLOT_FIELD} chars",
        rf"{_F} value is text of ≤ {base.MAX_SLOT_VALUE} chars, not ",
        rf"{_F} is whole (?:cents|months), not ",
        rf"{_F} is true or false, not ",
        rf"{_F} is an ISO time with zone or none, not ",
        r"no slots(?:; |\Z)", rf"{_F} repeats(?:; |\Z)",
        rf"{_F}=true with {_F}(?:; |\Z)",
    ))
)  # fmt: skip
_DISPATCH = "invalid arguments: "
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
    naming, why, lower = list[int](), Counter[str](), list[int]()
    unparsed = list[int]()
    for e in refused:
        code, name = e.payload.get("code"), e.payload.get("name")
        codes["none" if code is None else str(code) if code in CODES else "other"] += 1
        tools[grading._name(e)] += 1  # pyright: ignore[reportPrivateUsage]
        got, text = None, str(e.payload.get("result_text", ""))
        if name == "record_offer" and code == "invalid_args":
            got = _naming(text)
            unparsed += [e.seq] * (got is None and not _known(text))
        if got is not None:
            why.update(got[0])
            naming.append(e.seq)
            lower += [e.seq] * got[1]
    return {"count": len(refused), "seqs": [e.seq for e in refused],
            "by_code": dict(sorted(codes.items())),
            "by_tool": dict(sorted(tools.items())),
            "naming": {"count": len(naming), "seqs": naming,
                       "by": dict(sorted(why.items())),
                       "lower_bound": lower},
            "naming_unparsed": {"count": len(unparsed),
                                "seqs": unparsed}}  # fmt: skip


def _naming(text: str) -> tuple[Counter[str], bool] | None:
    """A record_offer refusal's naming items by ``by`` key, and whether that
    count is only a lower bound. Left to right from the list's start, each item
    matched whole by an ``_ITEMS`` pattern and followed by "; " or the table;
    at the first point that is neither, the count stops (a lower bound), as it
    does when the tails after the table are not one per named field. None: the
    first item is no whole naming item; a shape, value or conflict refusal
    holds none (``record_offer`` returns at its first failing stage), and
    ``_known`` tells those from a text that fits no template."""
    if not text.startswith(_REFUSED):
        return None
    pos, found, fields = len(_REFUSED), Counter[str](), dict[str, str]()
    while hit := _item(text, pos):
        key, m = hit
        if not text.startswith(("; ", _TABLE), m.end()):
            break
        found[key] += 1
        fields.setdefault(m["field"], key.partition(":")[0])
        if text.startswith(_TABLE, m.end()):
            return found, not _tails(text, m.end() + len(_TABLE), fields)
        pos = m.end() + 2
    return (found, True) if found else None


def _item(text: str, pos: int) -> tuple[str, re.Match[str]] | None:
    """The naming item at ``pos``: its ``by`` key and match; else None."""
    for key, pattern in _ITEMS.items():
        if m := pattern.match(text, pos):
            return key, m
    return None


def _tails(text: str, start: int, fields: Mapping[str, str]) -> bool:
    """After the table: one ``unnamed`` tail per named field, in order, all
    naming the same offer ref, and nothing after them. The ref is the model's
    text, so its length is solved from the rest's (n tails, n copies of it)
    and the tails rebuilt and compared: exact whatever the ref holds, and
    linear. The first tail starts at its first ". <field>: if ..." after the
    table (the table, offer_slots' constant, holds none)."""
    head, _, end = _TAIL.partition("{ref}")
    heads = [f". {head.format(field=f, kind=k)}" for f, k in fields.items()]
    ends = [end.format(kind=k) for k in fields.values()]
    first = text.find(heads[0], start)
    if first < 0:
        return False
    rest = text[first + len(heads[0]) :]
    size = len(rest) - sum(map(len, ends)) - sum(map(len, heads[1:]))
    ref = rest[: max(size, 0) // len(heads)]  # the only length that can fit
    rebuilt = "".join(
        f"{ref}{e}{h}" for e, h in zip(ends, [*heads[1:], ""], strict=True)
    )
    return rest == rebuilt


def _known(text: str) -> bool:
    """A refusal with no naming item whose first item is one of
    offer_slots' other templates (``_OTHER``), or the dispatcher's."""
    if text.startswith(_DISPATCH):
        return True
    return text.startswith(_REFUSED) and bool(_OTHER.match(text, len(_REFUSED)))


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
    sub-counts, B9's delays, and B5's naming refusals (``naming_lower_bound``:
    those whose count is only a lower bound; ``naming_unparsed``: record_offer
    refusals that fit no offer_slots template)."""
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
                naming = as_dict(v.get("naming"))
                lower = cast(list[object], naming.get("lower_bound", []))
                unparsed = as_dict(v.get("naming_unparsed")).get("count", 0)
                for key, k in (("naming", naming.get("count")),
                               ("naming_lower_bound", len(lower)),
                               ("naming_unparsed", unparsed)):  # fmt: skip
                    got[key] = cast(int, got.get(key, 0)) + cast(int, k)
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
