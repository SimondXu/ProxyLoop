"""H5 grading detectors (ADR-0018): the agent harness v2 mechanics, per run.

ADVISORY ONLY: triage signals, never a metric, a claim or a merge gate (and
never imported by ``proxyloop.eval``). They register in ``DETECTORS``. Each
reports its raw value; ``h5_pass`` is ADR-0018's target applied to this one
run, advisory too (the battery-wide targets are the reader's); ``count`` is
the one number diagnose shows. A signal the bundle's code does not emit
yet (``chan.opened.ready``, ``ask_user`` keys, a ``slow.tool`` code) gives
None, never 0. The closing reply follows Guard's rule (``closing_reply``)
on the rep's lines, so the three ``close`` detectors run only with
``content``.
"""

from __future__ import annotations

from collections import Counter
from typing import cast

from proxyloop.contract.events import Event
from proxyloop.guard.readback import has_cue
from proxyloop.guard.readiness import IDENTITY
from proxyloop.obs.detectors import Inputs, Value, as_dict, detector, safe
from proxyloop.obs.trace import TOOL_NAMES

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
    """rep.policy IDENTIFY→ENDED (``abandoned``: a hang-up, whether a heard
    line or a timer caused it) and identity strikes: a chan.strike whose
    ``kind`` is ``identity`` (S1-SYS-43), or, before that key exists, whose
    cause chain reaches a rep.policy from IDENTIFY that a heard line caused
    (timer strikes come from causeless rep.policy events). ``count``: the
    strikes plus an abandonment that no counted strike already stands for
    (an identity hang-up counts once). None: no rep.policy."""
    policy = x.of("rep.policy")
    if not policy:
        return None
    strikes = x.of("chan.strike")
    typed = any("kind" in e.payload for e in strikes)
    struck = {
        e.seq: _policy_of(x, e)
        for e in strikes
        if (e.payload.get("kind") == "identity" if typed else _heard_identify(x, e))
    }
    ends = [e for e in policy if (e.payload["from"], e.payload["to"]) ==
            ("IDENTIFY", "ENDED")]  # fmt: skip
    extra = bool(ends) and ends[0] not in struck.values()
    return {
        "count": len(struck) + extra,
        "strikes": list(struck),
        "abandoned": ends[0].seq if ends else None,
        "kind_from": "payload" if typed else "causes",
        "h5_pass": not struck and not ends,
    }


def _policy_of(x: Inputs, e: Event) -> Event | None:
    for _ in range(4):  # chan.strike <- rep.mouth <- rep.policy
        if not e.cause_ids or (e := x.by_id[e.cause_ids[0]]).type == "rep.policy":
            break
    return e if e.type == "rep.policy" else None


def _heard_identify(x: Inputs, e: Event) -> bool:
    p = _policy_of(x, e)
    return p is not None and p.payload["from"] == "IDENTIFY" and bool(p.cause_ids)


@detector("identity.cp_opened_ready")
def _opened(x: Inputs) -> Value:
    """The first ``chan.opened{lane: cp}``: its ``reason``, ``ready`` and
    ``missing`` list (``from`` ``payload``: the kernel's ``required()`` keys,
    the shareable IDENTITY keys plus learned rows); a payload without a
    ``missing`` list gets the IDENTITY keys no public ``fact.recorded`` held
    before it (``from`` ``facts``). The two measure different key sets: split
    cross-run tables by ``from``. ``h5_pass`` is None
    with ``no_intake`` (no user lane to ask: not applicable). None: no cp
    chan.opened carries ``ready`` (S1-SYS-21)."""
    opened = [e for e in x.of("chan.opened") if e.payload.get("lane") == "cp"]
    if not opened or "ready" not in opened[0].payload:
        return None
    at, source = opened[0], "payload"
    if isinstance(listed := at.payload.get("missing"), list):
        missing = [safe(k) for k in cast(list[object], listed)]
    else:
        source = "facts"
        public = {
            f.payload.get("key")
            for f in x.of("fact.recorded")
            if f.seq < at.seq and f.payload.get("scope") == "public"
        }
        missing = [k for k in IDENTITY if k not in public]
    reason, ready = at.payload.get("reason"), safe(at.payload["ready"])
    passed = None if reason == "no_intake" else not missing
    return {"count": len(missing), "seq": at.seq, "reason": safe(reason),
            "ready": ready, "missing": missing, "from": source,
            "h5_pass": passed}  # fmt: skip


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
    coded = _coded(x, "invalid_args")
    if coded is None:
        return None
    n = Counter(_name(e) for e in coded)
    return {"count": n.total(), "by_tool": dict(sorted(n.items()))}


def _coded(x: Inputs, code: str) -> list[Event] | None:
    """slow.tool events whose ``code`` is ``code``; None: no slow.tool carries
    ``code`` (a bundle from before S1-SYS-21). The switch is per bundle: once
    any slow.tool carries ``code``, an uncoded one (on main only slow/loop.py's
    ``_NO_TOOL``) is judged by its absent code, never by its name."""
    tools = _tools(x)
    if not any("code" in e.payload for e in tools):
        return None
    return [e for e in tools if e.payload.get("code") == code]


@detector("slow.act_shape")
def _act_shape(x: Inputs) -> Value:
    """slow.tool events whose ``code`` is ``act_shape``: an act refused whole
    (JSON or schema) or one malformed calls item. None: no ``code``."""
    coded = _coded(x, "act_shape")
    return None if coded is None else {"count": len(coded),
                                       "seqs": [e.seq for e in coded]}  # fmt: skip


def _name(e: Event) -> str:
    name = e.payload.get("name")
    return name if isinstance(name, str) and name in TOOL_NAMES else "unknown"


@detector("slow.unknown_tool")
def _unknown(x: Inputs) -> Value:
    """slow.tool events whose ``code`` is ``unknown_tool``; in a bundle
    without ``code``, those whose ``name`` is none of Slow's tools (e.g.
    ``None``, a calls item without a tool); ``from``: ``code`` or ``name``.
    None: no slow.tool."""
    tools, coded = _tools(x), _coded(x, "unknown_tool")
    if not tools:
        return None
    seen = coded if coded is not None else [e for e in tools if _name(e) == "unknown"]
    return {"count": len(seen), "seqs": [e.seq for e in seen],
            "from": "name" if coded is None else "code"}  # fmt: skip


@detector("slow.lever_refusals")
def _levers(x: Inputs) -> Value:
    """Refused (``ok`` false) slow.tool calls of a lever: guide_fast with a
    lever ``args.move``, or share_fact of a competitor, tenure or cancel-lever
    ``args.key``; ``by``: the move, or the key's ``_LEVER_FACTS`` prefix
    (never the model's raw key). None: no slow.tool."""
    tools = _tools(x)
    if not tools:
        return None
    by = Counter[str]()
    seqs: list[int] = []
    for e in tools:
        args, name = as_dict(e.payload.get("args")), e.payload.get("name")
        key = str(args.get("key"))
        if name == "guide_fast" and args.get("move") in _LEVER_MOVES:
            lever = str(args["move"])
        elif name == "share_fact":
            lever = next((f for f in _LEVER_FACTS if key.startswith(f)), None)
        else:
            lever = None
        if lever and e.payload.get("ok") is False:
            seqs.append(e.seq)
            by[lever] += 1
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


def _call(x: Inputs, seq: int) -> int:
    """The cp call open at ``seq``: the ``chan.opened{lane: cp}`` before it
    (Guard's ``_call``: a new cp call closes the earlier read-back windows)."""
    opened = x.of("chan.opened")
    return sum(e.seq < seq and e.payload.get("lane") == "cp" for e in opened)


def _reads_back(x: Inputs, g: Event, o: Event) -> bool:
    """Whether Slow's ask ``g`` (an ask_readback GUIDE citing o's offer, any
    revision) reads back revision ``o``: sent after o's record, while o was
    current (the per-revision rule), or in o's cp call (ADR-0020's per-offer
    window). "Asked" is Slow's attempt, deliberately not Guard's stricter
    heard anchor: ``h5_pass`` None means no read-back was attempted, and an
    ask that never reached the rep is a mechanic failure that must stay
    visible as unconfirmed slots (``ask_heard`` tells the two apart)."""
    return g.seq > o.seq or _call(x, g.seq) == _call(x, o.seq)


def _heard(x: Inputs, before: int | None = None) -> dict[str, int]:
    """The s2f msg ids Guard counts as heard (ADR-0020's anchor; Slow's
    ``_heard``, #219), from events alone, each with the seq of the last
    ``utt.delivered`` of its first heard voicing (event order): an
    ``s2f.voiced`` whose generation was never ``fast.cancelled`` and whose
    every ``fast.sentence`` (one at least) has an ``utt.delivered`` with
    ``interrupted`` false. Guard anchors at the first cp line after that
    delivery (an index into the transcript); the cp lines with a seq above
    the stored one are the same lines. ``before``: only events with a smaller
    seq count (Guard judges a finish with the events so far). Not every
    GUIDE the rep heard on bundles before #230, or when the GUIDE is no
    longer its lane's newest: one voiced by a verbatim-cancelled turn is then
    spoken by the re-run through ``guidance_cp`` with no ``s2f.voiced``, so
    ``guide_to_heard_ms`` may credit it heard while it is not here (#230's
    re-run voices it again, and its voicing counts here)."""
    upto = [e for e in x.events if before is None or e.seq < before]
    cut = {str(e.payload["gen_id"]) for e in upto if e.type == "fast.cancelled"}
    delivered = {str(e.payload["utt_id"]): e for e in upto if e.type == "utt.delivered"}
    utts: dict[str, list[str]] = {}
    for p in (e.payload for e in upto if e.type == "fast.sentence"):
        utts.setdefault(str(p["gen_id"]), []).append(str(p["utt_id"]))

    def end(gen: str) -> int | None:
        played = [delivered.get(u) for u in utts.get(gen, [])]
        whole = [
            d for d in played if d is not None and d.payload.get("interrupted") is False
        ]
        return (
            max(d.seq for d in whole) if whole and len(whole) == len(played) else None
        )

    out: dict[str, int] = {}
    for v in (e for e in upto if e.type == "s2f.voiced"):
        gen = str(v.payload["gen_id"])
        if gen not in cut and (at := end(gen)) is not None:
            out.setdefault(str(v.payload["msg_id"]), at)
    return out


@detector("offer.required_unconfirmed_after_readback")
def _unconfirmed(x: Inputs) -> Value:
    """Per offer read back (``_reads_back``: an ask_readback citing it after
    its latest revision's record, or in that record's cp call): the latest
    revision's slots not ``confirmed`` at the log's end, from its record and
    readback.updated (Guard's statuses, per-offer window from a5c897c on;
    the same detector reads per-revision statuses on earlier bundles);
    ``ask_heard``: whether Guard counts one of those asks heard (``_heard``;
    never changes ``count`` or ``h5_pass``; on bundles before #230, or once
    the ask is no longer its lane's newest GUIDE, an ask a verbatim-cancelled
    turn voiced and its re-run spoke is False here though
    ``guide_to_heard_ms`` may credit it heard); ``unasked``: offers whose latest
    revision was never read back (``unasked_n``; then ``h5_pass`` is None: an
    info_only task need not read back, and the mode is not in the bundle).
    None: no offer.recorded."""
    offers = _revisions(x)
    if not offers:
        return None
    asked, out, unasked = _asked(x), dict[str, list[object]](), list[object]()
    heard, ask_heard = _heard(x), dict[str, bool]()
    for ref, revs in sorted(offers.items()):
        last = revs[-1]
        mine = [g for g, _ in asked.get(ref, []) if _reads_back(x, g, last)]
        if not mine:
            unasked.append(safe(ref))
            continue
        left = [  # "fee:<suffix>" → "fee": the suffix is Slow's choice
            safe(f.partition(":")[0])
            for f, s in _statuses(x, last).items()
            if s != "confirmed"
        ]
        key = f"{safe(ref)}@{last.payload['revision']}"
        out[key] = left
        ask_heard[key] = any(str(g.payload["msg_id"]) in heard for g in mine)
    count = sum(map(len, out.values()))
    passed = None if unasked else not count
    return {"count": count, "offers": out, "ask_heard": ask_heard,
            "unasked": unasked, "unasked_n": len(unasked),
            "h5_pass": passed}  # fmt: skip


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


def closing_reply(x: Inputs, at: int) -> Event | None:
    """Guard's closing reply for a ``finish`` at seq ``at`` (verify_no_deal,
    S1-SYS-57; Slow's ``asked_final``, #227): the rep's last cp line
    (utt.final, partner) after the anchor, if Guard's closing cues match it.
    The anchor: the latest ``_heard`` end, with the events before ``at``, of
    the ask_final_offer GUIDEs sent before ``at``; an ask the rep did not hear
    (never voiced, cut, or cancelled) neither opens nor restarts the window.
    obs applies this heard anchor to every bundle: on one from before #227
    (Guard anchored at the ask's send) it can differ from the verdict Guard
    recorded then; grouping by slow_fp keeps those runs apart. None: no heard
    ask, the rep silent since it, or a last line that does not close (a
    retraction or concession after a closing line reopens it)."""
    heard = _heard(x, before=at)
    asks = [
        str(g.payload["msg_id"]) for g in _guides(x, "ask_final_offer") if g.seq < at
    ]
    anchor = max((heard[m] for m in asks if m in heard), default=None)
    said = [
        e
        for e in x.of("utt.final")
        if anchor is not None and anchor < e.seq < at
        and e.payload.get("lane") == "cp" and e.payload.get("speaker") == "partner"
    ]  # fmt: skip
    last = said[-1] if said else None
    return (
        last if last and has_cue(str(last.payload.get("text", "")), "closing") else None
    )


def _finish(x: Inputs) -> int | None:
    """The first successful ``finish(no_deal)`` slow.tool's seq: the one call
    verify_no_deal judged (a deal finish goes through verify_completion)."""
    done = [
        e.seq
        for e in _tools(x, "finish")
        if e.payload.get("ok") is True
        and as_dict(e.payload.get("args")).get("outcome") == "no_deal"
    ]
    return done[0] if done else None


def _reply(x: Inputs) -> Event | None:
    """The closing reply the three ``close`` detectors share: ``closing_reply``
    at the first successful ``finish(no_deal)`` (Guard judged it there), or at
    the log's end when there is none (asks and lines after the finish are
    ignored). None without ``content``."""
    if not x.content:
        return None
    done = _finish(x)
    return closing_reply(x, len(x.events) if done is None else done)


@detector("close.reply_to_finish_steps")
def _to_finish(x: Inputs) -> Value:
    """Slow steps (slow.step.started) after the closing reply up to the first
    successful ``finish(no_deal)``, which bounds the reply (``finish_seq``
    None: none, even with a deal finish; the steps then run to the log's
    end). None: no ``content``, or no closing reply."""
    reply = _reply(x)
    if reply is None:
        return None
    done = _finish(x)
    stop = len(x.events) if done is None else done
    steps = sum(reply.seq < e.seq < stop for e in x.of("slow.step.started"))
    return {"count": steps, "reply_seq": reply.seq, "finish_seq": done,
            "h5_pass": done is not None and steps <= 2}  # fmt: skip


@detector("end.unclosed_after_reply")
def _unclosed(x: Inputs) -> Value:
    """1 if session.ended's reason is timeout or slow_step_cap after the
    closing reply, else 0. None: no ``content``, no reply, or no end."""
    reply, ends = _reply(x), x.of("session.ended")
    if reply is None or not ends:
        return None
    reason = ends[-1].payload.get("reason")
    return {"count": int(reason in _UNCLOSED), "reply_seq": reply.seq,
            "end_reason": safe(reason)}  # fmt: skip


@detector("user.told_terms")
def _told(x: Inputs) -> Value:
    """User-lane TELL_USER s2f.msg events after the closing reply that FastU
    voiced (s2f.voiced); what they said is not read. Anchored to the closing
    reply Guard verified, so a tell before the final close is premature and
    not counted (527345). None: no ``content``, or no closing reply."""
    reply = _reply(x)
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
