"""Success-path progress (S1-SYS-86): how far each run got toward success.

DIAGNOSTIC — not a claim or metric: reported, never a gate, never imported by
``proxyloop.eval``, and no number of it goes into a doc (rule 13). Events
only, from fixed emitters (never model text), and one generic ladder for every
family, never a per-family table.

The ladder, in order; each milestone is one pure fold, the seq of its first
trigger event (None: not reached):

1. ``identified``: a rep.policy moving past identity (``ladder.PAST_IDENTITY``);
   the run's identity strikes travel with it (``identity.strikes``).
2. ``discount_asked``: a cp GUIDE ``ask_discount`` (s2f.msg).
3. ``offer_recorded``: an offer.recorded.
4. ``lever_sent``: a cp GUIDE with a lever move (``grading._LEVER_MOVES``)
   after the first offer.recorded.
5. ``lever_heard``: a rep.ear lever act (``ladder.LEVERS``) after it.
6. ``later_rung``: a rep.policy offer or final_offer at rung >= 1 (#239).
7. ``readback_confirmed``: the H5 read-back scope (#243,
   ``offer.required_unconfirmed_after_readback``) passes: every offer sent for
   approval or accepted was read back and all its slots are confirmed.
8. ``approval_requested``, 9. ``approval_decided`` (either decision).
10. ``accept_released``: a speak.released of a speak.verbatim{accept}.
11. ``commit_heard``: a rep.commit_heard.
12. ``verified``: a completion.decided{verdict: ok} of the deal verifier (its
    slow.tool is ``finish(completed)``; a no-deal finish is not this ladder's).

Each run then carries the end status (``end.status``) and the ADR-0023 tier.

A milestone is ``reached`` (its fold found an event), else ``n/a``, else
``not_needed``, else ``missing``. ``n/a``: an ``OPTIONAL`` one (the approval
pair) in a run with no approval.requested. ``not_needed`` (P-OBS, 2026-09-28):
a ``BY_OUTCOME`` one (a lever sent or heard, a later rung) when every offer
sent for approval or accepted (``grading._committed``) is the ladder's first
rung, as the causes tell: each slot of its committed revision cites a rep line
(``source_utt``) whose utt.final -> rep.mouth -> rep.policy names a world
offer the rep offered at rung 0; a chain obs cannot follow keeps them needed.
``furthest``: the last milestone reached in list order; ``first_missing``: the
first ``missing`` one (``n/a`` and ``not_needed`` never are).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import cast

from proxyloop.contract.events import Event
from proxyloop.obs import grading, ladder
from proxyloop.obs.detectors import DETECTORS, Inputs, as_dict, safe

LABEL = "DIAGNOSTIC — not a claim or metric"
MILESTONES = (
    "identified", "discount_asked", "offer_recorded", "lever_sent",
    "lever_heard", "later_rung", "readback_confirmed", "approval_requested",
    "approval_decided", "accept_released", "commit_heard", "verified",
)  # fmt: skip
OPTIONAL = frozenset({"approval_requested", "approval_decided"})
BY_OUTCOME = frozenset({"lever_sent", "lever_heard", "later_rung"})
_LEVER_MOVES = grading._LEVER_MOVES  # pyright: ignore[reportPrivateUsage]
_TAKES = ladder._TAKES  # pyright: ignore[reportPrivateUsage]


def _first(events: Sequence[Event]) -> int | None:
    return events[0].seq if events else None


def _after_first_offer(x: Inputs, events: Sequence[Event]) -> int | None:
    offers = x.of("offer.recorded")
    return _first([e for e in events if offers and e.seq > offers[0].seq])


def _cp_guides(x: Inputs, moves: frozenset[str]) -> list[Event]:
    return [
        e for e in x.of("s2f.msg")
        if e.payload.get("lane") == "cp" and e.payload.get("type") == "GUIDE"
        and as_dict(e.payload.get("guide")).get("move") in moves
    ]  # fmt: skip


def _identified(x: Inputs) -> int | None:
    return _first(
        [e for e in x.of("rep.policy") if e.payload.get("to") in ladder.PAST_IDENTITY]
    )


def _discount(x: Inputs) -> int | None:
    return _first(_cp_guides(x, frozenset({"ask_discount"})))


def _offer(x: Inputs) -> int | None:
    return _first(x.of("offer.recorded"))


def _lever_sent(x: Inputs) -> int | None:
    return _after_first_offer(x, _cp_guides(x, _LEVER_MOVES))


def _lever_heard(x: Inputs) -> int | None:
    ears = [e for e in x.of("rep.ear") if e.payload.get("act") in ladder.LEVERS]
    return _after_first_offer(x, ears)


def _rung(e: Event) -> int | None:
    rung = e.payload.get("rung")
    return rung if isinstance(rung, int) and not isinstance(rung, bool) else None


def _offered(x: Inputs) -> list[Event]:
    """The rep.policy events that made an offer (``offer``/``final_offer``)."""
    return [
        e for e in x.of("rep.policy")
        if as_dict(e.payload.get("intent")).get("kind") in _TAKES
    ]  # fmt: skip


def _later_rung(x: Inputs) -> int | None:
    return _first([e for e in _offered(x) if (_rung(e) or 0) >= 1])


def _readback(x: Inputs) -> int | None:
    """The last readback.updated (else record) of the offers in H5 scope, when
    the scope passes."""
    value = as_dict(DETECTORS["offer.required_unconfirmed_after_readback"](x))
    if value.get("h5_pass") is not True:
        return None
    scoped = {tuple(str(k).rsplit("@", 1)) for k in as_dict(value.get("offers"))}
    seqs = [
        e.seq for e in x.of("offer.recorded", "readback.updated")
        if (str(e.payload.get("offer_ref")), str(e.payload.get("revision"))) in scoped
    ]  # fmt: skip
    return max(seqs) if seqs else None


def _requested(x: Inputs) -> int | None:
    return _first(x.of("approval.requested"))


def _decided(x: Inputs) -> int | None:
    return _first(x.of("approval.decided"))


def _released(x: Inputs) -> int | None:
    return _first([
        e for e in x.of("speak.released")
        for c in e.cause_ids
        if (v := x.by_id.get(c)) is not None and v.type == "speak.verbatim"
        and v.payload.get("kind") == "accept"
    ])  # fmt: skip


def _commit(x: Inputs) -> int | None:
    return _first(x.of("rep.commit_heard"))


def _verified(x: Inputs) -> int | None:
    """An ok completion.decided of the deal verifier: the one a
    ``finish(completed)`` slow.tool caused (``slow.authority.finish``; a
    ``finish(no_deal)`` verifies no deal, not this ladder's success)."""
    return _first([
        e for e in x.of("completion.decided")
        if e.payload.get("verdict") == "ok"
        and any(as_dict(t.payload.get("args")).get("outcome") == "completed"
                for c in e.cause_ids
                if (t := x.by_id.get(c)) is not None and t.type == "slow.tool")
    ])  # fmt: skip


FOLDS: dict[str, Callable[[Inputs], int | None]] = {
    "identified": _identified, "discount_asked": _discount,
    "offer_recorded": _offer, "lever_sent": _lever_sent,
    "lever_heard": _lever_heard, "later_rung": _later_rung,
    "readback_confirmed": _readback, "approval_requested": _requested,
    "approval_decided": _decided, "accept_released": _released,
    "commit_heard": _commit, "verified": _verified,
}  # fmt: skip


def _policy_of_line(x: Inputs, utt: object) -> Event | None:
    """The rep.policy a cp partner line voiced: utt.final -> rep.mouth ->
    rep.policy, by their causes."""
    for line in x.of("utt.final"):
        if line.payload.get("utt_id") != utt or line.payload.get("lane") != "cp":
            continue
        for m in (x.by_id.get(c) for c in line.cause_ids):
            if m is None or m.type != "rep.mouth":
                continue
            for p in (x.by_id.get(c) for c in m.cause_ids):
                if p is not None and p.type == "rep.policy":
                    return p
    return None


def committed_rung(x: Inputs) -> int | None:
    """The highest ladder rung among the offers sent for approval or accepted
    (module doc); None: none committed, or a slot whose rung obs cannot
    follow."""
    committed = grading._committed(x)  # pyright: ignore[reportPrivateUsage]
    rung_of: dict[object, int | None] = {}  # world offer_ref -> its offer's rung
    for e in _offered(x):
        rung_of.setdefault(as_dict(e.payload.get("intent")).get("offer_ref"), _rung(e))
    rungs = list[int | None]()
    for o in x.of("offer.recorded"):
        if o.payload.get("revision") not in committed.get(
            str(o.payload.get("offer_ref")), ()
        ):
            continue
        for slot in map(as_dict, cast(list[object], o.payload.get("slots") or [])):
            p = _policy_of_line(x, slot.get("source_utt"))
            ref = (
                None if p is None else as_dict(p.payload.get("intent")).get("offer_ref")
            )
            rungs.append(rung_of.get(ref))
    if not rungs or None in rungs:
        return None
    return max(cast(list[int], rungs))


def run(x: Inputs) -> dict[str, object]:
    """One run's milestones (status and first seq), ``furthest``,
    ``first_missing``, its committed rung, identity strikes, end status and
    tier."""
    carded, rung = bool(x.of("approval.requested")), committed_rung(x)
    out: dict[str, dict[str, object]] = {}
    for name in MILESTONES:
        seq = FOLDS[name](x)
        status = (
            "reached" if seq is not None
            else "n/a" if name in OPTIONAL and not carded
            else "not_needed" if name in BY_OUTCOME and rung == 0
            else "missing"
        )  # fmt: skip
        out[name] = {"status": status, "seq": seq}
    reached = [m for m in MILESTONES if out[m]["status"] == "reached"]
    missing = [m for m in MILESTONES if out[m]["status"] == "missing"]
    tier = as_dict(DETECTORS["tier"](x))
    strikes = as_dict(DETECTORS["identity.strikes"](x)).get("count")
    return {
        "label": LABEL, "milestones": out,
        "furthest": reached[-1] if reached else None,
        "first_missing": missing[0] if missing else None,
        "committed_rung": rung, "identity_strikes": strikes,
        "end_status": safe(DETECTORS["end.status"](x)),
        "tier": tier.get("tier"), "tier_reason": tier.get("reason"),
    }  # fmt: skip


def family(r: Mapping[str, object]) -> str:
    """The tier's family (task_ref before ``@``), as ``tiers.summary``."""
    tier = as_dict(as_dict(r.get("detectors")).get("tier"))
    return str(tier.get("family") or "unknown")


def summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Per family over one diagnose group's rows: runs, how many reached each
    milestone, how many had it not needed or n/a, and the counts of
    ``furthest`` and ``first_missing``."""
    fams: dict[str, dict[str, Counter[str]]] = {}
    runs = Counter[str]()
    for r in rows:
        p = as_dict(r.get("progress"))
        if not p:
            continue
        fam = family(r)
        runs[fam] += 1
        c = fams.setdefault(fam, {k: Counter() for k in (
            "reached", "not_needed", "n/a", "furthest", "first_missing")})  # fmt: skip
        for name, m in as_dict(p.get("milestones")).items():
            status = str(as_dict(m).get("status"))
            if status in c:
                c[status][name] += 1
        for key in ("furthest", "first_missing"):  # None: nothing to count
            if (name := p.get(key)) is not None:
                c[key][str(name)] += 1
    return {
        "label": LABEL,
        "milestones": list(MILESTONES),
        "families": {
            f: {"runs": runs[f]} | {k: dict(sorted(n.items())) for k, n in c.items()}
            for f, c in sorted(fams.items())
        },
    }


def block(s: Mapping[str, object], group: str) -> str:
    """The human block diagnose prints per group, after the tiers."""
    kind, _, value = group.partition(":")
    out = [f"== progress {kind} {value[:12]} ({LABEL})"]
    for fam, c in as_dict(s["families"]).items():
        c = as_dict(c)
        reached = as_dict(c["reached"])
        cells = [f"{m}={reached.get(m, 0)}" for m in MILESTONES]
        out.append(" ".join([f"  {fam} runs={c['runs']}", *cells]))
        for key in ("not_needed", "n/a", "first_missing"):
            if n := as_dict(c[key]):
                out.append(
                    " ".join([f"    {key}", *(f"{k}={v}" for k, v in n.items())])
                )
    return "\n".join(out)
