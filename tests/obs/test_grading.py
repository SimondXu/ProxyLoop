"""The H5 grading detectors (``obs.grading``) against hand counts on one
fixture bundle, with each event's seq in a comment (``t_ms = seq * 100``). It
carries the signals S1-SYS-21/43/45 add (``chan.opened.ready``, ``ask_user``
keys, ``slow.tool`` codes) to test the logic; without them the detectors are
None (``test_detectors``)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.obs.bundles import Log, manifest, write
from tests.obs.triage_bundle import P, s2f

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
    s2f(log, "s2f-f", "cp", "GUIDE", start, guide=final)  # 26
    step: P = {"basis_seq": 0, "wake_reasons": []}
    log.add("slow.step.started", "slow", "agent", step)  # 27
    _rep_line(log, "PRIV let me check")  # 28
    _rep_line(log, "PRIV that is our best and final offer")  # 29: the reply
    log.add("slow.step.started", "slow", "agent", step)  # 30
    told = s2f(log, "s2f-t", "user", "TELL_USER", start, text="PRIV-terms")  # 31
    voiced: P = {"msg_id": "s2f-t", "gen_id": "user-g1"}
    log.add("s2f.voiced", "fast.user", "agent", voiced, (told,))  # 32
    s2f(log, "s2f-u", "user", "TELL_USER", start, text="PRIV-unheard")  # 33
    log.add("slow.step.started", "slow", "agent", step)  # 34
    _tool(log, "finish", True, start, args={"outcome": "no_deal"})  # 35
    status: P = {"previous": "IN_CALL", "status": "VERIFIED_NO_DEAL"}
    log.add("status.changed", "guard", "agent", status, (start,))  # 36
    log.add("session.ended", "kernel", "ops", {"reason": "timeout"})  # 37
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
        "slow.finish_before_offer": {"count": 0, "seq": 35},
        # o1's expires and fee (shown without Slow's suffix) are still
        # "heard"; o2 was never read back
        "offer.required_unconfirmed_after_readback": {
            "count": 2, "offers": {"o1@1": ["expires", "fee"]}, "unasked": ["o2"],
            "unasked_n": 1, "h5_pass": None,  # o2 may be info_only: unknown
        },
        # 21, 23 and 24 all went out while expires was unconfirmed
        "slow.readback_asks_max_per_revision": {
            "count": 3, "by": {"o1@1": 3}, "h5_pass": False,
        },
        # 29, the rep's last line between the ask (26) and the finish (35),
        # matches Guard's closing cues;
        # steps 30 and 34 come before the finish (35)
        "close.reply_to_finish_steps": {
            "count": 2, "reply_seq": 29, "finish_seq": 35, "h5_pass": True,
        },
        "end.unclosed_after_reply": {
            "count": 1, "reply_seq": 29, "end_reason": "timeout",
        },
        "user.told_terms": {  # 33 was never voiced
            "count": 1, "seqs": [31], "reply_seq": 29, "h5_pass": True,
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


def _offer_log(run_id: str, revisions: int, asked: int) -> Log:
    """An offer recorded ``revisions`` times; revision ``asked`` read back."""
    log = Log(run_id)
    for rev in range(1, revisions + 1):
        made = _offer(log, "o1", ("monthly_price",), log.start)
        log.events[-1] = log.events[-1].model_copy(
            update={"payload": log.events[-1].payload | {"revision": rev}}
        )
        if rev == asked:
            _readback(log, made, "offer:o1")
    return log


def test_an_offer_never_read_back_does_not_pass(tmp_path: Path) -> None:
    for run_id, revisions, asked in (("rN", 1, 0), ("r2", 2, 1)):
        log = _offer_log(run_id, revisions, asked)
        run = write(tmp_path / run_id, log, manifest(run_id))
        value = _values(run)["offer.required_unconfirmed_after_readback"]
        assert value == {
            "count": 0, "offers": {}, "unasked": ["o1"], "unasked_n": 1,
            "h5_pass": None,
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
