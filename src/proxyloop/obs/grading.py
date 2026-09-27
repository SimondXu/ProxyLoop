"""H5 grading detectors (ADR-0018): the agent harness v2 mechanics, per run.

ADVISORY ONLY: triage signals, never a metric, a claim or a merge gate (and
never imported by ``proxyloop.eval``). They register in ``DETECTORS``. Each
reports its raw value; ``h5_pass`` is ADR-0018's target applied to this one
run, advisory too (the battery-wide targets are the reader's); ``count`` is
the one number diagnose shows. A signal the bundle's code does not emit
yet (``chan.opened.ready``, ``ask_user`` keys, a ``slow.tool`` code) gives
None, never 0. The closing reply is found with Guard's closing cues on the
rep's lines, so the three ``close`` detectors run only with ``content``.
"""

from __future__ import annotations

from collections import Counter
from typing import cast

from proxyloop.contract.events import Event
from proxyloop.guard.readback import has_cue
from proxyloop.obs.detectors import Inputs, Value, as_dict, detector, safe
from proxyloop.obs.trace import TOOL_NAMES

# slow/tools.py ``_IDENTITY`` (obs cannot import slow, ADR-0008)
IDENTITY = ("account.holder_name", "account.last4")
_LEVER_MOVES = frozenset({"ask_discount", "cite_competitor", "mention_tenure",
                          "cancel_lever"})  # fmt: skip
_LEVER_FACTS = ("competitor", "tenure_years", "authorization.cancel_lever")
_UNCLOSED = frozenset({"timeout", "slow_step_cap"})


def _tools(x: Inputs, name: str | None = None) -> list[Event]:
    return [e for e in x.of("slow.tool") if name in (None, e.payload.get("name"))]


def _guides(x: Inputs, move: str) -> list[Event]:
    return [
        e
        for e in x.of("s2f.msg")
        if e.payload.get("lane") == "cp"
        and as_dict(e.payload.get("guide")).get("move") == move
    ]


@detector("identity.strikes")
def _strikes(x: Inputs) -> Value:
    """rep.policy IDENTIFY→ENDED (``abandoned``) and identity strikes: a
    chan.strike whose ``kind`` is ``identity`` (S1-SYS-43), or, before that
    key exists, whose cause chain reaches a rep.policy from IDENTIFY that a
    heard line caused (timer strikes come from causeless rep.policy events).
    None: no rep.policy."""
    policy = x.of("rep.policy")
    if not policy:
        return None
    strikes = x.of("chan.strike")
    typed = any("kind" in e.payload for e in strikes)
    seqs = [
        e.seq
        for e in strikes
        if (e.payload.get("kind") == "identity" if typed else _heard_identify(x, e))
    ]
    ends = [e.seq for e in policy if (e.payload["from"], e.payload["to"]) ==
            ("IDENTIFY", "ENDED")]  # fmt: skip
    return {
        "count": len(seqs) + len(ends),
        "strikes": seqs,
        "abandoned": ends[0] if ends else None,
        "kind_from": "payload" if typed else "causes",
        "h5_pass": not seqs and not ends,
    }


def _heard_identify(x: Inputs, e: Event) -> bool:
    for _ in range(4):  # chan.strike <- rep.mouth <- rep.policy
        if not e.cause_ids or (e := x.by_id[e.cause_ids[0]]).type == "rep.policy":
            break
    return (
        e.type == "rep.policy" and e.payload["from"] == "IDENTIFY" and bool(e.cause_ids)
    )


@detector("identity.cp_opened_ready")
def _opened(x: Inputs) -> Value:
    """The first ``chan.opened{lane: cp}``: its ``ready`` and the identity keys
    no public ``fact.recorded`` held before it. None: no cp chan.opened carries
    ``ready`` (S1-SYS-21)."""
    opened = [e for e in x.of("chan.opened") if e.payload.get("lane") == "cp"]
    if not opened or "ready" not in opened[0].payload:
        return None
    at = opened[0]
    public = {
        f.payload.get("key")
        for f in x.of("fact.recorded")
        if f.seq < at.seq and f.payload.get("scope") == "public"
    }
    missing = [k for k in IDENTITY if k not in public]
    ready = safe(at.payload["ready"])
    return {"count": len(missing), "seq": at.seq, "ready": ready,
            "missing": missing, "h5_pass": not missing}  # fmt: skip


@detector("identity.ask_user_per_key")
def _asks(x: Inputs) -> Value:
    """Successful ``ask_user`` slow.tool calls per identity key in
    ``args.keys``; ``count``: the most for one key. None: no ask_user carries
    ``keys`` (S1-SYS-21)."""
    asks = _tools(x, "ask_user")
    if not any("keys" in as_dict(e.payload.get("args")) for e in asks):
        return None
    n = Counter(
        k
        for e in asks
        if e.payload.get("ok") is True
        for k in cast(list[object], as_dict(e.payload["args"]).get("keys") or [])
        if k in IDENTITY
    )
    top = max(n.values(), default=0)
    return {"count": top, "by_key": dict(sorted(n.items())), "h5_pass": top <= 1}


@detector("end.status")
def _status(x: Inputs) -> Value:
    """The last status.changed ``status``; None: the case status never moved."""
    changed = x.of("status.changed")
    return safe(changed[-1].payload.get("status")) if changed else None


@detector("approval.path")
def _approval(x: Inputs) -> Value:
    """The first approval.requested, then the first status.changed to
    VERIFIED_COMPLETE after it; None: no approval was requested."""
    asked = x.of("approval.requested")
    if not asked:
        return None
    done = [
        e.seq
        for e in x.of("status.changed")
        if e.seq > asked[0].seq and e.payload.get("status") == "VERIFIED_COMPLETE"
    ]
    return {"requested": asked[0].seq, "verified_complete": done[0] if done else None,
            "h5_pass": bool(done)}  # fmt: skip


@detector("slow.invalid_args")
def _invalid(x: Inputs) -> Value:
    """slow.tool events whose ``code`` is ``invalid_args``, by tool name. None:
    no slow.tool carries ``code``: the refusal text is never parsed."""
    tools = _tools(x)
    if not any("code" in e.payload for e in tools):
        return None
    n = Counter(_name(e) for e in tools if e.payload.get("code") == "invalid_args")
    return {"count": n.total(), "by_tool": dict(sorted(n.items()))}


def _name(e: Event) -> str:
    name = e.payload.get("name")
    return name if isinstance(name, str) and name in TOOL_NAMES else "unknown"


@detector("slow.unknown_tool")
def _unknown(x: Inputs) -> Value:
    """slow.tool events whose ``name`` is none of Slow's tools (e.g. ``None``,
    a calls item without a tool). None: no slow.tool."""
    tools = _tools(x)
    if not tools:
        return None
    seqs = [e.seq for e in tools if _name(e) == "unknown"]
    return {"count": len(seqs), "seqs": seqs}


@detector("slow.lever_refusals")
def _levers(x: Inputs) -> Value:
    """Refused (``ok`` false) slow.tool calls of a lever: guide_fast with a
    lever ``args.move``, or share_fact of a competitor, tenure or cancel-lever
    ``args.key``; ``by``: move or key. None: no slow.tool."""
    tools = _tools(x)
    if not tools:
        return None
    by = Counter[str]()
    seqs: list[int] = []
    for e in tools:
        args, name = as_dict(e.payload.get("args")), e.payload.get("name")
        what = args.get("move") if name == "guide_fast" else args.get("key")
        lever = what in _LEVER_MOVES if name == "guide_fast" else (
            name == "share_fact" and str(what).startswith(_LEVER_FACTS))  # fmt: skip
        if lever and e.payload.get("ok") is False:
            seqs.append(e.seq)
            by[str(safe(what))] += 1
    return {"count": len(seqs), "seqs": seqs, "by": dict(sorted(by.items()))}


@detector("slow.finish_before_offer")
def _premature(x: Inputs) -> Value:
    """The first successful ``finish`` slow.tool, and whether it came before
    any offer.recorded (ADR-0018's premature-close risk). None: no finish."""
    done = [e for e in _tools(x, "finish") if e.payload.get("ok") is True]
    if not done:
        return None
    early = not any(o.seq < done[0].seq for o in x.of("offer.recorded"))
    return {"count": int(early), "seq": done[0].seq}


def _revisions(x: Inputs) -> dict[str, list[Event]]:
    offers: dict[str, list[Event]] = {}
    for o in x.of("offer.recorded"):
        offers.setdefault(str(o.payload["offer_ref"]), []).append(o)
    return offers


def _statuses(x: Inputs, o: Event, before: int | None = None) -> dict[str, str]:
    """A revision's slot statuses: its record's, then each readback.updated."""
    ref, rev = o.payload["offer_ref"], o.payload["revision"]
    out = {str(s["field"]): str(s["status"])
           for s in cast(list[dict[str, object]], o.payload["slots"])}  # fmt: skip
    for u in x.of("readback.updated"):
        p = u.payload
        same = (p["offer_ref"], p.get("revision")) == (ref, rev)
        if same and (before is None or u.seq < before):
            out |= {str(k): str(v) for k, v in as_dict(p["slot_statuses"]).items()}
    return out


def _asked(x: Inputs) -> dict[str, list[tuple[Event, Event]]]:
    """cp ask_readback GUIDEs per offer_ref cited in their slots
    (``offer:<ref>.<field>``), with the revision current at the ask."""
    offers, out = _revisions(x), dict[str, list[tuple[Event, Event]]]()
    for g in _guides(x, "ask_readback"):
        slots = cast(list[object], as_dict(g.payload.get("guide")).get("slots") or [])
        for ref in {str(s)[6:].partition(".")[0] for s in slots
                    if str(s).startswith("offer:")}:  # fmt: skip
            now = [o for o in offers.get(ref, []) if o.seq < g.seq]
            if now:
                out.setdefault(ref, []).append((g, now[-1]))
    return out


@detector("offer.required_unconfirmed_after_readback")
def _unconfirmed(x: Inputs) -> Value:
    """Per offer read back (an ask_readback cites its current revision): the
    latest revision's slots not ``confirmed`` at the log's end; ``unasked``:
    offers never read back. The task's mode is not in the bundle, so
    info_only offers are listed too. None: no offer.recorded."""
    offers = _revisions(x)
    if not offers:
        return None
    asked, out, unasked = _asked(x), dict[str, list[object]](), list[object]()
    for ref, revs in sorted(offers.items()):
        last = revs[-1]
        if not any(o is last for _, o in asked.get(ref, [])):
            unasked.append(safe(ref))
            continue
        left = [safe(f) for f, s in _statuses(x, last).items() if s != "confirmed"]
        out[f"{safe(ref)}@{last.payload['revision']}"] = left
    count = sum(map(len, out.values()))
    return {"count": count, "offers": out, "unasked": unasked, "h5_pass": not count}


@detector("slow.readback_asks_max_per_revision")
def _asks_per_revision(x: Inputs) -> Value:
    """ask_readback GUIDEs per (offer, revision) sent while that revision had
    a slot not ``confirmed``; ``count``: the most. None: no offer.recorded."""
    if not x.of("offer.recorded"):
        return None
    n = Counter(
        f"{safe(ref)}@{o.payload['revision']}"
        for ref, asks in _asked(x).items()
        for g, o in asks
        if any(s != "confirmed" for s in _statuses(x, o, g.seq).values())
    )
    top = max(n.values(), default=0)
    return {"count": top, "by": dict(sorted(n.items())), "h5_pass": top <= 2}


def _reply(x: Inputs) -> Event | None:
    """The rep's closing reply: its first cp line (utt.final, partner) after the
    first ask_final_offer GUIDE that Guard's closing cues match."""
    asked = _guides(x, "ask_final_offer")
    return next(
        (
            e
            for e in x.of("utt.final")
            if asked and e.seq > asked[0].seq and e.payload.get("lane") == "cp"
            and e.payload.get("speaker") == "partner"
            and has_cue(str(e.payload.get("text", "")), "closing")
        ),
        None,
    )  # fmt: skip


@detector("close.reply_to_finish_steps")
def _to_finish(x: Inputs) -> Value:
    """Slow steps (slow.step.started) after the closing reply up to the first
    successful ``finish`` after it (``finish_seq`` None: none; the steps then
    run to the log's end). None: no ``content``, or no closing reply."""
    reply = _reply(x) if x.content else None
    if reply is None:
        return None
    done = [e.seq for e in _tools(x, "finish") if e.payload.get("ok") is True
            and e.seq > reply.seq]  # fmt: skip
    stop = done[0] if done else len(x.events)
    steps = sum(reply.seq < e.seq < stop for e in x.of("slow.step.started"))
    return {"count": steps, "reply_seq": reply.seq, "finish_seq": stop if done
            else None, "h5_pass": bool(done) and steps <= 2}  # fmt: skip


@detector("end.unclosed_after_reply")
def _unclosed(x: Inputs) -> Value:
    """1 if session.ended's reason is timeout or slow_step_cap after the
    closing reply, else 0. None: no ``content``, no reply, or no end."""
    reply, ends = _reply(x) if x.content else None, x.of("session.ended")
    if reply is None or not ends:
        return None
    reason = ends[-1].payload.get("reason")
    return {"count": int(reason in _UNCLOSED), "reply_seq": reply.seq,
            "end_reason": safe(reason)}  # fmt: skip


@detector("user.told_terms")
def _told(x: Inputs) -> Value:
    """User-lane TELL_USER s2f.msg events after the closing reply that FastU
    voiced (s2f.voiced); what they said is not read. None: no ``content``, or
    no closing reply."""
    reply = _reply(x) if x.content else None
    if reply is None:
        return None
    voiced = {str(v.payload["msg_id"]) for v in x.of("s2f.voiced")}
    seqs = [
        e.seq
        for e in x.of("s2f.msg")
        if e.seq > reply.seq and e.payload.get("lane") == "user"
        and e.payload.get("type") == "TELL_USER"
        and str(e.payload.get("msg_id")) in voiced
    ]  # fmt: skip
    return {"count": len(seqs), "seqs": seqs, "reply_seq": reply.seq,
            "h5_pass": bool(seqs)}  # fmt: skip
