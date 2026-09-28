"""The H5 grading detectors (``obs.grading``) against hand counts on one
fixture bundle, with each event's seq in a comment (``t_ms = seq * 100``). It
carries the signals S1-SYS-21/43/45 add (``chan.opened.ready``, ``ask_user``
keys, ``slow.tool`` codes) to test the logic; without them the detectors are
None (``test_detectors``)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from tests.obs.bundles import Log, manifest, write
from tests.obs.triage_bundle import P, heard, s2f, sentence, turn

from proxyloop.obs import detectors, grading, runs, triage


def _policy(log: Log, frm: str, to: str, kind: str, *causes: str) -> str:
    intent: P = {"kind": kind, "offer_ref": None, "say": [], "ask": []}
    payload: P = {"from": frm, "to": to, "intent": intent, "rung": None}
    return log.add("rep.policy", "world.policy", "world", payload, causes)


def _strike(log: Log, policy: str) -> None:
    mouth: P = {"intent": {}, "text": "PRIV-mouth", "fidelity_ok": True}
    said = log.add(
        "rep.mouth", "world.mouth", "world", mouth | {"attempts": 1}, (policy,)
    )
    log.add("chan.strike", "kernel", "agent", {"lane": "cp"}, (said,))


def _tool(log: Log, name: str, ok: bool, cause: str, **extra: object) -> str:
    args = extra.pop("args", {})
    payload: P = {"name": name, "args": args, "result_text": "PRIV-r", "ok": ok}
    return log.add("slow.tool", "slow", "agent", payload | extra, (cause,))


def _offer(log: Log, ref: str, fields: tuple[str, ...], cause: str) -> str:
    slots = [{"field": f, "value": "1", "status": "unknown"} for f in fields]
    payload: P = {"offer_ref": ref, "revision": 1, "slots": slots, "terms_hash": None}
    return log.add("offer.recorded", "guard", "agent", payload, (cause,))


def _readback(log: Log, cause: str, *slots: str) -> str:
    guide: P = {"move": "ask_readback", "slots": list(slots)}
    return s2f(log, f"rb-{len(log.events)}", "cp", "GUIDE", cause, guide=guide)


def _rep_line(log: Log, text: str) -> str:
    said: P = {"lane": "cp", "speaker": "partner", "utt_id": "cp-9", "text": text}
    return log.add("utt.final", "kernel", "agent", said)


def h5_bundle(root: Path) -> Path:
    log = Log("rH")  # 0
    start = log.start
    log.add("chan.opened", "kernel", "agent", {"lane": "user"}, (start,))  # 1
    fact: P = {"key": "account.holder_name", "value": "PRIV-name", "scope": "public"}
    log.add("fact.recorded", "guard", "agent", fact, (start,))  # 2
    opened: P = {"lane": "cp", "call": 1, "reason": "intake_deadline"}
    opened |= {"missing": ["account.last4"], "ready": False}
    log.add("chan.opened", "kernel", "agent", opened, (start,))  # 3: last4 missing
    heard: P = {"lane": "cp", "utt_id": "u", "text_generated": "PRIV-g"}
    heard |= {"text_heard": "PRIV-h", "interrupted": False}
    line = log.add("utt.delivered", "kernel", "agent", heard, (start,))  # 4
    _strike(log, _policy(log, "IDENTIFY", "IDENTIFY", "ask_identity", line))  # 5-7
    _strike(log, _policy(log, "IDENTIFY", "IDENTIFY", "check_in"))  # 8-10: timer
    _policy(log, "IDENTIFY", "ENDED", "hang_up")  # 11: abandoned
    keys = {"text": "PRIV-q", "keys": ["account.last4"]}
    _tool(log, "ask_user", True, start, args=keys)  # 12
    both = {"text": "PRIV-q", "keys": ["account.last4", "account.holder_name"]}
    _tool(log, "ask_user", True, start, args=both)  # 13
    _tool(log, "ask_user", False, start, args=keys)  # 14: refused, not counted
    _tool(log, "None", False, start, code="unknown_tool")  # 15
    _tool(log, "record_offer", False, start, code="invalid_args")  # 16
    _tool(log, "guide_fast", False, start, args={"move": "cite_competitor"})  # 17
    _tool(log, "share_fact", False, start, args={"key": "tenure_years"})  # 18
    _tool(log, "share_fact", False, start, args={"key": "account.last4"})  # 19
    o1 = _offer(log, "o1", ("monthly_price", "expires", "fee:PRIV9"), start)  # 20
    _readback(log, o1, "offer:o1.monthly_price")  # 21: ask 1
    statuses: P = {"monthly_price": "confirmed", "expires": "heard"}
    statuses["fee:PRIV9"] = "heard"  # listed as "fee"
    update: P = {"offer_ref": "o1", "revision": 1, "slot_statuses": statuses}
    log.add("readback.updated", "guard", "agent", update, (o1,))  # 22
    _readback(log, o1, "offer:o1.expires")  # 23: ask 2
    _readback(log, o1, "offer:o1")  # 24: ask 3
    _offer(log, "o2", ("monthly_price",), start)  # 25: never read back
    final: P = {"move": "ask_final_offer", "slots": []}
    ask = s2f(log, "s2f-f", "cp", "GUIDE", start, guide=final)  # 26
    _voice(log, ask, "cp-gf", False, False)  # 27-30: heard, delivered at 30
    step: P = {"basis_seq": 0, "wake_reasons": []}
    log.add("slow.step.started", "slow", "agent", step)  # 31
    _rep_line(log, "PRIV let me check")  # 32
    _rep_line(log, "PRIV that is our best and final offer")  # 33: the reply
    log.add("slow.step.started", "slow", "agent", step)  # 34
    told = s2f(log, "s2f-t", "user", "TELL_USER", start, text="PRIV-terms")  # 35
    voiced: P = {"msg_id": "s2f-t", "gen_id": "user-g1"}
    log.add("s2f.voiced", "fast.user", "agent", voiced, (told,))  # 36
    s2f(log, "s2f-u", "user", "TELL_USER", start, text="PRIV-unheard")  # 37
    log.add("slow.step.started", "slow", "agent", step)  # 38
    _tool(log, "finish", True, start, args={"outcome": "no_deal"})  # 39
    status: P = {"previous": "IN_CALL", "status": "VERIFIED_NO_DEAL"}
    log.add("status.changed", "guard", "agent", status, (start,))  # 40
    log.add("session.ended", "kernel", "ops", {"reason": "timeout"})  # 41
    return write(root / "rH", log, manifest("rH"))


def _values(run: Path, content: bool = False) -> dict[str, object]:
    x = triage.read(run, runs.Seal(), content=content)[1]
    return {k: v for k, v in detectors.run_all(x).items() if "." in k}


def test_every_h5_detector_equals_the_hand_count(tmp_path: Path) -> None:
    values = _values(h5_bundle(tmp_path), content=True)
    assert values == {
        # 7: its policy (5) was caused by a heard line; 10's (8) by a timer
        "identity.strikes": {
            "count": 2, "strikes": [7], "abandoned": 11, "kind_from": "causes",
            "h5_pass": False,
        },
        "identity.cp_opened_ready": {
            "count": 1, "seq": 3, "reason": "intake_deadline", "ready": False,
            "missing": ["account.last4"], "from": "payload", "h5_pass": False,
        },
        # 12 and 13 ask for last4, 13 for the holder name too; 14 was refused
        "identity.ask_user_per_key": {
            "count": 2, "by_key": {"account.holder_name": 1, "account.last4": 2},
            "h5_pass": False,
        },
        "end.status": "VERIFIED_NO_DEAL",
        "approval.path": None,  # no approval.requested
        "slow.invalid_args": {"count": 1, "by_tool": {"record_offer": 1}},
        "slow.act_shape": {"count": 0, "seqs": []},
        "slow.unknown_tool": {"count": 1, "seqs": [15], "from": "code"},
        # 19 is identity, not a lever
        "slow.lever_refusals": {
            "count": 2, "seqs": [17, 18],
            "by": {"cite_competitor": 1, "tenure_years": 1},
        },
        "slow.finish_before_offer": {"count": 0, "seq": 39},
        # neither o1 (read back) nor o2 was sent for approval or accepted:
        # out of scope (test_a_levered_offer_is_superseded_and_the_sent_one_graded
        # grades a committed one)
        "offer.required_unconfirmed_after_readback": {
            "count": 0, "offers": {}, "ask_heard": {}, "unasked": [], "unasked_n": 0,
            "h5_pass": None, "superseded_by_lever": [], "not_committed": ["o1", "o2"],
        },
        # 21, 23 and 24 all went out while expires was unconfirmed
        "slow.readback_asks_max_per_revision": {
            "count": 3, "by": {"o1@1": 3}, "h5_pass": False,
        },
        # 33, the rep's last line between the ask's delivery (30: heard) and
        # the finish (39), matches Guard's closing cues;
        # steps 34 and 38 come before the finish (39)
        "close.reply_to_finish_steps": {
            "count": 2, "reply_seq": 33, "finish_seq": 39, "h5_pass": True,
        },
        "end.unclosed_after_reply": {
            "count": 1, "reply_seq": 33, "end_reason": "timeout",
        },
        "user.told_terms": {  # 37 was never voiced
            "count": 1, "seqs": [35], "reply_seq": 33, "h5_pass": True,
        },
    }  # fmt: skip


def test_close_detectors_read_text_only_with_content(tmp_path: Path) -> None:
    values = _values(h5_bundle(tmp_path))
    for name in (
        "close.reply_to_finish_steps", "end.unclosed_after_reply", "user.told_terms",
    ):  # fmt: skip
        assert values[name] is None, name


def test_a_typed_strike_kind_wins_over_causes(tmp_path: Path) -> None:
    log = Log("rK")
    policy = _policy(log, "IDENTIFY", "IDENTIFY", "check_in")  # 1: a timer
    log.add("chan.strike", "kernel", "agent", {"lane": "cp", "kind": "identity"},
            (policy,))  # fmt: skip
    value = _values(write(tmp_path / "rK", log, manifest("rK")))["identity.strikes"]
    assert value == {
        "count": 1, "strikes": [2], "abandoned": None, "kind_from": "payload",
        "h5_pass": False,
    }  # fmt: skip


def test_a_timer_kind_is_no_identity_strike(tmp_path: Path) -> None:
    """The kernel's shape (kernel/session.py ``_turn``): ``{lane, kind}``; a
    ``timer`` strike is not counted even when its cause chain looks heard."""
    log = Log("rT")
    said: P = {"lane": "cp", "speaker": "agent", "utt_id": "u", "text": "PRIV"}
    line = log.add("utt.final", "kernel", "agent", said)  # 1
    policy = _policy(log, "IDENTIFY", "IDENTIFY", "ask_identity", line)  # 2
    for kind in ("timer", "identity"):  # 3, 4
        struck: P = {"lane": "cp", "kind": kind}
        log.add("chan.strike", "kernel", "agent", struck, (policy,))
    value = _values(write(tmp_path / "rT", log, manifest("rT")))["identity.strikes"]
    assert value == {
        "count": 1, "strikes": [4], "abandoned": None, "kind_from": "payload",
        "h5_pass": False,
    }  # fmt: skip


def test_approval_path_and_premature_finish(tmp_path: Path) -> None:
    log = Log("rA")
    card: P = {"approval_id": "a1", "offer_ref": "o1", "revision": 1}
    card |= {"terms_hash": "h", "readback_text": "PRIV", "authority_epoch": 0}
    card["expires_ms"] = 9
    binding: P = {"offer_ref": "o1", "revision": 1, "authority_epoch": 0}
    card["binding"] = binding | {
        "account_ref": "a",
        "principal_ref": "p",
        "purpose": "x",
    }
    _tool(log, "finish", True, log.start)  # 1: no offer.recorded before it
    log.add("approval.requested", "guard", "agent", card, (log.start,))  # 2
    status: P = {"previous": "IN_CALL", "status": "VERIFIED_COMPLETE"}
    log.add("status.changed", "guard", "agent", status, (log.start,))  # 3
    values = _values(write(tmp_path / "rA", log, manifest("rA")))
    assert values["approval.path"] == {
        "requested": 2, "verified_complete": 3, "h5_pass": True,
    }  # fmt: skip
    assert values["slow.finish_before_offer"] == {"count": 1, "seq": 1}


def test_refusal_codes_win_over_tool_names(tmp_path: Path) -> None:
    log = Log("rC")
    _tool(log, "act", False, log.start, code="act_shape")  # 1: refused whole
    _tool(log, "act", False, log.start, code="act_shape")  # 2: an item
    _tool(log, "frobnicate", False, log.start, code="unknown_tool")  # 3
    _tool(log, "None", False, log.start, code="act_shape")  # 4: not unknown_tool
    _tool(log, "share_fact", False, log.start, code=None)  # 5: a Guard denial
    values = _values(write(tmp_path / "rC", log, manifest("rC")))
    assert values["slow.act_shape"] == {"count": 3, "seqs": [1, 2, 4]}
    assert values["slow.unknown_tool"] == {"count": 1, "seqs": [3], "from": "code"}
    assert values["slow.invalid_args"] == {"count": 0, "by_tool": {}}


def test_no_intake_is_not_graded(tmp_path: Path) -> None:
    log = Log("rO")
    opened: P = {"lane": "cp", "call": 1, "reason": "no_intake"}
    opened |= {"missing": list(grading.IDENTITY), "ready": False}
    log.add("chan.opened", "kernel", "agent", opened, (log.start,))  # 1
    value = _values(write(tmp_path / "rO", log, manifest("rO")))
    assert value["identity.cp_opened_ready"] == {
        "count": 2, "seq": 1, "reason": "no_intake", "ready": False,
        "missing": list(grading.IDENTITY), "from": "payload", "h5_pass": None,
    }  # fmt: skip


def test_cp_opened_prefers_the_kernel_readiness(tmp_path: Path) -> None:
    log = Log("rR")
    fact: P = {"key": "account.last4", "value": "PRIV-4", "scope": "public"}
    log.add("fact.recorded", "guard", "agent", fact, (log.start,))  # 1
    # the kernel needs only what the task may share: nothing missing
    opened: P = {"lane": "cp", "call": 1, "reason": "ready"}
    opened |= {"missing": [], "ready": True}
    log.add("chan.opened", "kernel", "agent", opened, (log.start,))  # 2
    value = _values(write(tmp_path / "rR", log, manifest("rR")))
    assert value["identity.cp_opened_ready"] == {
        "count": 0, "seq": 2, "reason": "ready", "ready": True, "missing": [],
        "from": "payload", "h5_pass": True,
    }  # fmt: skip


@pytest.mark.parametrize(
    "extra", [{}, {"missing": None}, {"missing": "account.last4"}]
)  # no missing (before the payload had it), or one that is not a list
def test_cp_opened_without_a_missing_list_reads_the_facts(
    tmp_path: Path, extra: P
) -> None:
    log = Log("rF")
    fact: P = {"key": "account.last4", "value": "PRIV-4", "scope": "public"}
    log.add("fact.recorded", "guard", "agent", fact, (log.start,))  # 1
    opened: P = {"lane": "cp", "ready": "ready"} | extra
    log.add("chan.opened", "kernel", "agent", opened, (log.start,))  # 2
    value = _values(write(tmp_path / "rF", log, manifest("rF")))
    assert value["identity.cp_opened_ready"] == {
        "count": 1, "seq": 2, "reason": None, "ready": "ready",
        "missing": ["account.holder_name"], "from": "facts", "h5_pass": False,
    }  # fmt: skip


def _rev(log: Log, ref: str, revision: int) -> str:
    """Revision ``revision`` of offer ``ref``, one ``monthly_price`` slot."""
    made = _offer(log, ref, ("monthly_price",), log.start)
    log.events[-1] = log.events[-1].model_copy(
        update={"payload": log.events[-1].payload | {"revision": revision}}
    )
    return made


def _call(log: Log) -> None:
    log.add("chan.opened", "kernel", "agent", {"lane": "cp"}, (log.start,))


_UNASKED: P = {"count": 0, "offers": {}, "ask_heard": {}, "unasked": ["o1"],
               "unasked_n": 1, "h5_pass": False}  # fmt: skip
_OUT: P = {"superseded_by_lever": [], "not_committed": []}


def _send(log: Log, ref: str, revision: int) -> str:
    """Slow sends ``ref``'s ``revision`` for approval (approval.requested)."""
    card: P = {"approval_id": f"a-{len(log.events)}", "offer_ref": ref}
    card |= {"revision": revision, "terms_hash": "h", "readback_text": "PRIV"}
    card |= {"authority_epoch": 0, "expires_ms": 10**9}
    binding: P = {"offer_ref": ref, "revision": revision, "authority_epoch": 0}
    card["binding"] = binding | {"account_ref": "a", "principal_ref": "p",
                                 "purpose": "x"}  # fmt: skip
    return log.add("approval.requested", "guard", "agent", card, (log.start,))


def _grade(tmp_path: Path, log: Log, send: bool = True) -> object:
    """The detector's value, ``send``: with the latest revision of every
    offer sent for approval first (in scope), and the out-of-scope lists
    (``_OUT``, empty then) left out."""
    if send:
        latest: dict[str, int] = {}
        for e in log.events:
            if e.type == "offer.recorded":
                latest[str(e.payload["offer_ref"])] = int(str(e.payload["revision"]))
        for ref, revision in sorted(latest.items()):
            _send(log, ref, revision)
    run = write(tmp_path / log.run_id, log, manifest(log.run_id))
    value = _values(run)["offer.required_unconfirmed_after_readback"]
    if send:
        assert isinstance(value, dict)
        value = cast(dict[str, object], value)
        assert {k: value.pop(k) for k in _OUT} == _OUT
    return value


def test_an_offer_never_read_back_does_not_pass(tmp_path: Path) -> None:
    """Never asked (rN); asked only in an earlier cp call (rC: a
    chan.opened{cp} closes the earlier windows, ADR-0020)."""
    log = Log("rN")
    _rev(log, "o1", 1)  # 1
    assert _grade(tmp_path, log) == _UNASKED
    log = Log("rC")
    _call(log)  # 1
    _readback(log, _rev(log, "o1", 1), "offer:o1")  # 2-3: call 1
    _call(log)  # 4
    _rev(log, "o1", 2)  # 5: call 2, no ask of its own
    assert _grade(tmp_path, log) == _UNASKED


def test_an_earlier_revisions_ask_in_the_same_call_grades_the_latest(
    tmp_path: Path,
) -> None:
    """ADR-0020 (21988c's shape): r1 is asked, the answer makes Slow record
    r2 with no ask of its own; the ask is in r2's call, so r2 is graded on its
    own statuses (here still ``unknown``)."""
    log = Log("rW")
    _call(log)  # 1
    _readback(log, _rev(log, "o1", 1), "offer:o1.monthly_price")  # 2-3
    _rev(log, "o1", 2)  # 4
    assert _grade(tmp_path, log) == {
        "count": 1, "offers": {"o1@2": ["monthly_price"]},
        "ask_heard": {"o1@2": False}, "unasked": [], "unasked_n": 0,
        "h5_pass": False,
    }  # fmt: skip


def test_an_ask_after_the_record_in_a_later_call_reads_it_back(
    tmp_path: Path,
) -> None:
    """The per-revision rule has no call filter: r1, recorded in call 1, is
    read back by an ask in call 2; r2, recorded after that ask in call 2, is
    read back by the same ask through the per-offer window."""
    for run_id, last in (("rL", 1), ("rL2", 2)):
        log = Log(run_id)
        _call(log)  # 1
        _rev(log, "o1", 1)  # 2: call 1
        _call(log)  # 3
        _readback(log, log.start, "offer:o1")  # 4: call 2, r1 current
        if last == 2:
            _rev(log, "o1", 2)  # 5: call 2, after the ask
        assert _grade(tmp_path, log) == {
            "count": 1, "offers": {f"o1@{last}": ["monthly_price"]},
            "ask_heard": {f"o1@{last}": False}, "unasked": [], "unasked_n": 0,
            "h5_pass": False,
        }, run_id  # fmt: skip


def test_a_user_lane_open_does_not_split_the_cp_call(tmp_path: Path) -> None:
    log = Log("rU")
    _call(log)  # 1
    _readback(log, _rev(log, "o1", 1), "offer:o1")  # 2-3
    log.add("chan.opened", "kernel", "agent", {"lane": "user"}, (log.start,))  # 4
    _rev(log, "o1", 2)  # 5: still cp call 1
    assert _grade(tmp_path, log) == {
        "count": 1, "offers": {"o1@2": ["monthly_price"]},
        "ask_heard": {"o1@2": False}, "unasked": [], "unasked_n": 0,
        "h5_pass": False,
    }  # fmt: skip


def test_a_latest_revision_the_window_confirmed_passes(tmp_path: Path) -> None:
    log = Log("rP")
    _readback(log, _rev(log, "o1", 1), "offer:o1")  # 1-2
    r2 = _rev(log, "o1", 2)  # 3
    update: P = {"offer_ref": "o1", "revision": 2,
                 "slot_statuses": {"monthly_price": "confirmed"}}  # fmt: skip
    log.add("readback.updated", "guard", "agent", update, (r2,))  # 4
    assert _grade(tmp_path, log) == {
        "count": 0, "offers": {"o1@2": []}, "ask_heard": {"o1@2": False},
        "unasked": [], "unasked_n": 0, "h5_pass": True,
    }  # fmt: skip


def test_another_offers_ask_does_not_read_back(tmp_path: Path) -> None:
    log = Log("rO")
    _rev(log, "o1", 1)  # 1
    _readback(log, _rev(log, "o2", 1), "offer:o2")  # 2-3: o2 only
    _rev(log, "o1", 2)  # 4
    assert _grade(tmp_path, log) == {
        "count": 1, "offers": {"o2@1": ["monthly_price"]},
        "ask_heard": {"o2@1": False}, "unasked": ["o1"], "unasked_n": 1,
        "h5_pass": False,  # o1 was sent for approval with no read-back
    }  # fmt: skip


def _lever(log: Log) -> str:
    guide: P = {"move": "ask_discount", "slots": []}
    return s2f(log, f"lv-{len(log.events)}", "cp", "GUIDE", log.start, guide=guide)


def _confirm(log: Log, ref: str, cause: str, **statuses: str) -> str:
    update: P = {"offer_ref": ref, "revision": 1, "slot_statuses": statuses}
    return log.add("readback.updated", "guard", "agent", update | {"terms_hash": "t"},
                   (cause,))  # fmt: skip


def test_a_levered_offer_is_superseded_and_the_sent_one_graded(
    tmp_path: Path,
) -> None:
    """a806fc after #238: save-1 (offer-1) is levered before its read-back,
    the better save-2 arrives as offer-2, is read back and sent for approval:
    offer-1 is out of scope (superseded_by_lever), offer-2 graded."""
    log = Log("rS")
    _offer(log, "offer-1", ("monthly_price",), log.start)  # 1
    _lever(log)  # 2: ask_discount
    o2 = _offer(log, "offer-2", ("monthly_price", "fee:PRIV9"), log.start)  # 3
    _readback(log, o2, "offer:offer-2")  # 4
    _confirm(log, "offer-2", o2, monthly_price="confirmed", **{"fee:PRIV9": "heard"})
    _send(log, "offer-2", 1)  # 6
    assert _grade(tmp_path, log, send=False) == {
        "count": 1, "offers": {"offer-2@1": ["fee"]},
        "ask_heard": {"offer-2@1": False}, "unasked": [], "unasked_n": 0,
        "h5_pass": False, "superseded_by_lever": ["offer-1"], "not_committed": [],
    }  # fmt: skip


def test_only_offers_sent_or_accepted_are_graded(tmp_path: Path) -> None:
    """Never sent nor accepted, not levered past: not_committed, and no offer
    in scope is None; an accepted offer (its capability's terms_hash on its
    readback.updated) with no read-back ask fails; one sent for approval and
    then levered past stays in scope."""
    idle = Log("rI")
    _readback(idle, _offer(idle, "o1", ("monthly_price",), idle.start), "offer:o1")
    assert _grade(tmp_path, idle, send=False) == {
        "count": 0, "offers": {}, "ask_heard": {}, "unasked": [], "unasked_n": 0,
        "h5_pass": None, "superseded_by_lever": [], "not_committed": ["o1"],
    }  # fmt: skip

    took = Log("rT")
    o1 = _offer(took, "o1", ("monthly_price",), took.start)  # 1
    _confirm(took, "o1", o1, monthly_price="heard")  # 2: terms_hash "t"
    capability: P = {"cap_id": "c", "business_action_id": "b", "terms_hash": "t"}
    capability |= {"intent": "accept_offer", "epoch": 0, "expires_ms": 10**9}
    auth: P = {"intent": "accept_offer", "capability": capability}
    took.add("action.authorized", "guard", "agent", auth, (took.start,))  # 3
    graded = _grade(tmp_path, took, send=False)
    assert isinstance(graded, dict)
    assert (graded["unasked"], graded["h5_pass"]) == (["o1"], False)

    kept = Log("rK")
    _readback(kept, _rev(kept, "o1", 1), "offer:o1")  # 1-2
    _send(kept, "o1", 1)  # 3
    _lever(kept)  # 4
    _rev(kept, "o2", 1)  # 5
    graded = _grade(tmp_path, kept, send=False)
    assert isinstance(graded, dict)
    assert graded["offers"] == {"o1@1": ["monthly_price"]}
    assert (graded["superseded_by_lever"], graded["not_committed"]) == ([], ["o2"])


def test_superseded_needs_a_lever_after_the_record_and_another_ref(
    tmp_path: Path,
) -> None:
    """Not superseded: a new revision of the same ref after the lever, or a
    lever before the offer's record; the committed revision is graded, not a
    later one."""
    same = Log("rS1")
    _rev(same, "o1", 1)  # 1
    _lever(same)  # 2
    _rev(same, "o1", 2)  # 3: the same ref
    graded = _grade(tmp_path, same, send=False)
    assert isinstance(graded, dict)
    assert (graded["superseded_by_lever"], graded["not_committed"]) == ([], ["o1"])

    early = Log("rS2")
    _lever(early)  # 1: before o1's record
    _rev(early, "o1", 1)  # 2
    _rev(early, "o2", 1)  # 3
    graded = _grade(tmp_path, early, send=False)
    assert isinstance(graded, dict)
    assert (graded["superseded_by_lever"], graded["not_committed"]) == (
        [], ["o1", "o2"],
    )  # fmt: skip

    sent = Log("rS3")
    r1 = _rev(sent, "o1", 1)  # 1
    _readback(sent, r1, "offer:o1")  # 2
    _confirm(sent, "o1", r1, monthly_price="confirmed")  # 3
    _send(sent, "o1", 1)  # 4: r1 sent
    _call(sent)  # 5: a new call closes r1's window
    _rev(sent, "o1", 2)  # 6: r2, never sent, never read back
    assert _grade(tmp_path, sent, send=False) == {
        "count": 0, "offers": {"o1@1": []}, "ask_heard": {"o1@1": False},
        "unasked": [], "unasked_n": 0, "h5_pass": True,
        "superseded_by_lever": [], "not_committed": [],
    }  # fmt: skip


def _voice(
    log: Log, ask: str, gen: str, cut: bool, cancel: bool, speaks: bool = True
) -> None:
    """FastC voices the ask (s2f.voiced) in ``gen`` and speaks one sentence
    (none unless ``speaks``), delivered whole unless ``cut``; with ``cancel``
    the turn is cancelled."""
    msg = str(next(e for e in log.events if e.event_id == ask).payload["msg_id"])
    turn(log, "cp", gen, f"c-{gen}", ask)
    voiced: P = {"msg_id": msg, "gen_id": gen}
    log.add("s2f.voiced", "fast.cp", "agent", voiced, (log.events[-1].event_id,))
    if not speaks:
        return
    s = sentence(log, "cp", gen, 0, "PRIV-read", log.events[-1].event_id)
    if cancel:
        cancelled: P = {"gen_id": gen, "reason": "verbatim"}
        log.add("fast.cancelled", "fast.cp", "agent", cancelled, (s,))
    else:
        heard(log, "cp", f"{gen}-u0", "PRIV-read", cut, s)


def test_ask_heard_tells_an_unheard_ask_from_an_unanswered_one(
    tmp_path: Path,
) -> None:
    """``ask_heard``: an ask voiced by a turn never cancelled whose every
    sentence (one at least; rS has none) was delivered uncut; it never
    changes ``count`` or ``h5_pass``."""
    for run_id, cut, cancel, speaks, heard_ in (
        ("rH", False, False, True, True), ("rX", True, False, True, False),
        ("rZ", False, True, True, False), ("rS", False, False, False, False),
    ):  # fmt: skip
        log = Log(run_id)
        ask = _readback(log, _rev(log, "o1", 1), "offer:o1")  # 1-2
        _voice(log, ask, "cp-g1", cut, cancel, speaks)
        _rev(log, "o1", 2)
        assert _grade(tmp_path, log) == {
            "count": 1, "offers": {"o1@2": ["monthly_price"]},
            "ask_heard": {"o1@2": heard_}, "unasked": [], "unasked_n": 0,
            "h5_pass": False,
        }, run_id  # fmt: skip


def test_an_identity_hang_up_counts_once(tmp_path: Path) -> None:
    log = Log("rI")
    heard: P = {"lane": "cp", "utt_id": "u", "text_generated": "g"}
    heard |= {"text_heard": "h", "interrupted": False}
    line = log.add("utt.delivered", "kernel", "agent", heard, (log.start,))  # 1
    _strike(log, _policy(log, "IDENTIFY", "IDENTIFY", "ask_identity", line))  # 2-4
    _strike(log, _policy(log, "IDENTIFY", "ENDED", "hang_up", line))  # 5-7
    value = _values(write(tmp_path / "rI", log, manifest("rI")))["identity.strikes"]
    assert value == {
        "count": 2, "strikes": [4, 7], "abandoned": 5, "kind_from": "causes",
        "h5_pass": False,
    }  # fmt: skip


def test_lever_keys_are_bucketed_never_raw(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = Log("rL")
    key = {"key": "competitor.price_usd:64.99"}  # a model-written key
    _tool(log, "share_fact", False, log.start, args=key)  # 1
    run = write(tmp_path / "rL", log, manifest("rL"))
    value = _values(run)["slow.lever_refusals"]
    assert value == {"count": 1, "seqs": [1], "by": {"competitor": 1}}
    for args in ([], ["--json"]):
        assert triage.main([str(run), *args]) == 0
        assert "64.99" not in capsys.readouterr().out


def test_a_heard_ask_that_does_not_read_back_leaves_ask_heard_false(
    tmp_path: Path,
) -> None:
    """A (heard) is in call 1; B (never voiced) in call 2 reads back r2, so
    r2 is graded but ``ask_heard`` is False: A does not read r2 back."""
    log = Log("rE")
    _call(log)  # 1
    a = _readback(log, _rev(log, "o1", 1), "offer:o1")  # 2-3
    _voice(log, a, "cp-g1", False, False)  # 4-7: heard
    _call(log)  # 8
    _readback(log, log.start, "offer:o1")  # 9: B
    _rev(log, "o1", 2)  # 10: call 2
    assert _grade(tmp_path, log) == {
        "count": 1, "offers": {"o1@2": ["monthly_price"]},
        "ask_heard": {"o1@2": False}, "unasked": [], "unasked_n": 0,
        "h5_pass": False,
    }  # fmt: skip


def _revoiced(log: Log, ask: str) -> str:
    """#230's shape: FastC voices ``ask`` in cp-g1, which is cancelled
    (``verbatim``) before any line is delivered; its re-run cp-g2 (the same
    lane and trigger, ``basis_seq`` at the cancellation) voices it again and
    is delivered whole. Returns cp-g2's sentence id (its delivery comes
    after the caller's lines)."""
    msg = str(next(e for e in log.events if e.event_id == ask).payload["msg_id"])
    run: P = {"lane": "cp", "trigger": "guidance", "view_sha": "v"}
    run |= {"prompt_sha": "p", "profile": "pl_cp_v3", "model_ref": {}}
    said = ""
    for gen in ("cp-g1", "cp-g2"):
        basis = len(log.events) - 1  # cp-g2: the fast.cancelled
        request = run | {"gen_id": gen, "basis_seq": basis}
        asked = log.add("fast.request", "fast.cp", "agent", request, (ask,))
        spoke = turn(log, "cp", gen, f"c-{gen}", asked)
        voiced: P = {"msg_id": msg, "gen_id": gen}
        log.add("s2f.voiced", "fast.cp", "agent", voiced, (spoke,))
        said = sentence(log, "cp", gen, 0, "PRIV-read", spoke)
        if gen == "cp-g1":
            cancelled: P = {"gen_id": gen, "reason": "verbatim"}
            log.add("fast.cancelled", "fast.cp", "agent", cancelled, (said,))
    return said


def test_a_revoiced_guide_is_heard_once_through_its_second_voicing(
    tmp_path: Path,
) -> None:
    """After #230 a GUIDE has two s2f.voiced: the cancelled turn's and the
    re-run's. ``guide_to_heard_ms`` counts it once, from the re-run's first
    delivery (1200 - 200); ``_heard`` anchors it there, as an ask_readback
    (``ask_heard``) and as an ask_final_offer (the closing reply's window)."""
    log = Log("rV")
    ask = _readback(log, _rev(log, "o1", 1), "offer:o1")  # 1-2 (t=200)
    s = _revoiced(log, ask)  # 3-7 cp-g1 (7: cancelled), 8-11 cp-g2
    heard(log, "cp", "cp-g2-u0", "PRIV-read", False, s)  # 12 (t=1200)
    _rev(log, "o1", 2)  # 13
    run = write(tmp_path / "rV", log, manifest("rV"))
    x = triage.read(run, runs.Seal(), 0.3)[1]
    assert detectors.run_all(x)["guide_to_heard_ms"] == {
        "count": 1, "p50": 1000, "p90": 1000, "unheard": 0, "unknown": 0,
        "cancelled": 1, "superseded": 0, "ms": [1000],
    }  # fmt: skip
    assert _grade(tmp_path / "g", log) == {
        "count": 1, "offers": {"o1@2": ["monthly_price"]},
        "ask_heard": {"o1@2": True}, "unasked": [], "unasked_n": 0,
        "h5_pass": False,
    }  # fmt: skip

    log = Log("rF")
    final: P = {"move": "ask_final_offer", "slots": []}
    ask = s2f(log, "s2f-f", "cp", "GUIDE", log.start, guide=final)  # 1
    s = _revoiced(log, ask)  # 2-6 cp-g1 (6: cancelled), 7-10 cp-g2
    _rep_line(log, "PRIV that is our best offer")  # 11: before cp-g2 is heard
    heard(log, "cp", "cp-g2-u0", "PRIV-read", False, s)  # 12
    run = write(tmp_path / "rF", log, manifest("rF"))
    x = triage.read(run, runs.Seal(), content=True)[1]
    assert grading.closing_reply(x, len(log.events)) is None  # 11 is early
    _rep_line(log, "PRIV that is our best offer")  # 13
    run = write(tmp_path / "rF2", log, manifest("rF"))
    x = triage.read(run, runs.Seal(), content=True)[1]
    reply = grading.closing_reply(x, len(log.events))
    assert reply is not None and reply.seq == 13


def test_a_user_lane_message_delivered_whole_is_not_heard(tmp_path: Path) -> None:
    """Only cp deliveries count (Slow's ``fates``): a TELL_USER FastU voiced
    and delivered whole on the user lane is not in ``_heard``."""
    log = Log("rU")
    told = s2f(log, "s2f-t", "user", "TELL_USER", log.start, text="PRIV")  # 1
    spoke = turn(log, "user", "user-g1", "c-u1", told)  # 2
    voiced: P = {"msg_id": "s2f-t", "gen_id": "user-g1"}
    log.add("s2f.voiced", "fast.user", "agent", voiced, (spoke,))  # 3
    said = sentence(log, "user", "user-g1", 0, "PRIV", spoke)  # 4
    heard(log, "user", "user-g1-u0", "PRIV", False, said)  # 5
    x = triage.read(write(tmp_path / "rU", log, manifest("rU")), runs.Seal())[1]
    assert grading._heard(x) == {}  # pyright: ignore[reportPrivateUsage]
