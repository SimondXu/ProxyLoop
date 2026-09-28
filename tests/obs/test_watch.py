"""Watch items (``obs.watch``, S1-SYS-86): each accepted risk counted per run
with the seqs that triggered it, table-driven from small synthetic logs, and
the per-family summary diagnose prints. A diagnostic, never a claim or a
metric. Parity with the emitters is pinned where obs restates a name: Slow's
refusal codes and offer_slots' naming refusal text."""

from __future__ import annotations

from typing import Any, get_args

import pytest
from tests.obs.path_bundle import P, Run

from proxyloop.contract.state import ReadbackSlot
from proxyloop.obs import watch
from proxyloop.slow import offer_slots
from proxyloop.slow.result import Code


def _item(r: Run, name: str) -> Any:
    items: Any = watch.run(r.inputs())["items"]
    return items[name]


def _granted(r: Run) -> str:
    return r.decide(r.request())


# B1: speak.revoked{fence} after a granted approval, and the re-accept.
@pytest.mark.parametrize(
    ("grant", "reason", "kind", "again", "count", "reaccepted"),
    [
        (True, "fence", "accept", True, 1, 1),
        (True, "fence", "accept", False, 1, 0),
        (False, "fence", "accept", True, 0, 0),  # no grant before it
        (True, "expired", "accept", True, 0, 0),  # not a fence
        (True, "fence", "decline", True, 0, 0),  # not an accept line
    ],
)
def test_revoked_after_grant(
    grant: bool, reason: str, kind: str, again: bool, count: int, reaccepted: int
) -> None:
    r = Run()
    auth = r.authorize(_granted(r) if grant else r.start)
    said = r.verbatim(auth)
    if kind != "accept":
        r.log.events[-1].payload["kind"] = kind
    revoked = r.revoke(said, reason)
    if again:
        r.release(r.verbatim(auth))
    got = _item(r, "revoked_after_grant")
    assert got["count"] == count and got["reaccepted"] == reaccepted
    assert got["seqs"] == ([r.seq(revoked)] if count else [])


# B2: an offer that expired while open, after a grant or during a read-back.
@pytest.mark.parametrize(
    ("grant", "ask", "expire", "count", "after_grant", "during_readback"),
    [
        (False, False, True, 1, 0, 0),
        (True, False, True, 1, 1, 0),
        (False, True, True, 1, 0, 1),
        (True, True, False, 0, 0, 0),
    ],
)
def test_ttl_lost(
    grant: bool, ask: bool, expire: bool, count: int, after_grant: int,
    during_readback: int,
) -> None:  # fmt: skip
    r = Run()
    r.identify()
    utt = r.offer("ask_discount", 0, "save-1")
    r.record(utt)
    if ask:
        r.guide("ask_readback", "offer:offer-1.monthly_price")
    if grant:
        _granted(r)
    lost = r.policy("OFFER", "OFFER", "offer_expired", "save-1", 0) if expire else ""
    got = _item(r, "ttl_lost")
    assert got["count"] == count
    assert got["after_grant"] == after_grant
    assert got["during_readback"] == during_readback
    assert got["seqs"] == ([r.seq(lost)] if expire else [])


def test_an_ask_before_the_offer_is_no_readback_in_progress() -> None:
    r = Run()
    r.guide("ask_readback", "offer:offer-0.monthly_price")  # an earlier offer's
    r.offer("ask_discount", 0, "save-1")
    r.policy("OFFER", "OFFER", "offer_expired", "save-1", 0)
    assert _item(r, "ttl_lost")["during_readback"] == 0


# B3: read-back asks per offer revision while a slot is unconfirmed; >= 2 flags.
@pytest.mark.parametrize(("asks", "confirm_after", "flagged"),
                         [(1, 9, 0), (2, 9, 1), (3, 1, 0), (3, 2, 1)])  # fmt: skip
def test_readback_asks(asks: int, confirm_after: int, flagged: int) -> None:
    r = Run()
    r.record(r.offer("ask_discount", 0, "save-1"))
    sent = list[str]()
    for n in range(asks):
        if n == confirm_after:
            r.confirmed()
        sent.append(r.guide("ask_readback", "offer:offer-1.monthly_price"))
    got = _item(r, "readback_asks")
    assert got["count"] == flagged
    counted = min(asks, confirm_after)
    assert got["by"] == {"offer-1@1": counted}
    assert got["seqs"] == ([r.seq(s) for s in sent[:counted]] if flagged else [])


# B4: identity strikes during IDENTIFY and the hang-up they caused.
def test_identity_strikes_and_their_hang_up() -> None:
    r = Run()
    r.policy("GREET", "IDENTIFY", "ask_identity", cause=r.start)
    s1 = r.log.add("chan.strike", "kernel", "agent", {"lane": "cp", "kind": "identity"})
    r.log.add("chan.strike", "kernel", "agent", {"lane": "cp", "kind": "timer"})
    end = r.policy("IDENTIFY", "ENDED", "hang_up", reason="identity", cause=r.start)
    got = _item(r, "identity_strikes")
    assert got["count"] == 2 and got["strikes"] == [r.seq(s1)]
    assert got["hang_up"] == r.seq(end) and got["hang_up_reason"] == "identity"
    assert got["seqs"] == [r.seq(s1), r.seq(end)]


def test_no_rep_policy_is_not_observable() -> None:
    assert _item(Run(), "identity_strikes") == {"count": None, "seqs": []}


# B5: Slow tool refusals by code and tool, S1-SYS-85 naming refusals apart.
def _naming_text(field: str, line: str) -> str:
    role = "credit" if field.startswith("credit:") else "one_time"
    slot = ReadbackSlot(field=field, value="500", unit="usd_minor", role=role,
                        status="unknown", source_utt="cp-1")  # fmt: skip
    problems = offer_slots._named(slot, line)  # pyright: ignore[reportPrivateUsage]
    assert problems
    return offer_slots.refused(problems)


def test_the_refusal_codes_are_slows() -> None:
    assert frozenset(get_args(Code)) == watch.CODES


def test_slow_refusals_break_out_naming() -> None:
    r = Run()
    r.tool("guide_fast", True, None)
    bad = r.tool("guide_fast", False, "invalid_args", "invalid arguments: move")
    generic = _naming_text("fee:activation_fee", "an activation fee of $5")
    unsaid = _naming_text("fee:porting", "an activation fee of $5")
    g = r.tool("record_offer", False, "invalid_args", generic)
    u = r.tool("record_offer", False, "invalid_args", unsaid)
    shape = r.tool("record_offer", False, "invalid_args", offer_slots.refused(
        ["unknown field 'x'"]))  # fmt: skip
    old = r.tool("finish", False, None)  # uncoded (before S1-SYS-21)
    got = _item(r, "slow_refusals")
    assert got["count"] == 5
    assert got["seqs"] == [r.seq(s) for s in (bad, g, u, shape, old)]
    assert got["by_code"] == {"invalid_args": 4, "none": 1}
    assert got["by_tool"] == {"finish": 1, "guide_fast": 1, "record_offer": 3}
    by = {"fee:generic_word": 1, "fee:not_said": 1}
    assert got["naming"] == {"count": 2, "seqs": [r.seq(g), r.seq(u)], "by": by}


def test_a_credit_naming_refusal_is_named_credit() -> None:
    r = Run()
    text = _naming_text("credit:paperless_credit", "a paperless credit of $5")
    refusal = r.tool("record_offer", False, "invalid_args", text)
    naming = _item(r, "slow_refusals")["naming"]
    assert naming == {"count": 1, "seqs": [r.seq(refusal)],
                      "by": {"credit:generic_word": 1}}  # fmt: skip


# B7: S1-SYS-72 activation: confirm_accept after a released accept, and a
# commit confirmed by free speech (tiers' temporary exception).
def _released_then_confirm(r: Run, heard_released: bool) -> str:
    r.record(r.offer("ask_discount", 0, "save-1"))
    utt = r.release(r.verbatim(r.authorize(_granted(r))))
    ear = r.ear("accept", utt if heard_released else "fast-own-words")
    return r.policy("OFFER", "CONFIRM", "confirm_accept", "save-1", 0, ear)


@pytest.mark.parametrize(("heard_released", "count"), [(True, 1), (False, 0)])
def test_confirm_accept_after_a_released_accept(
    heard_released: bool, count: int
) -> None:
    r = Run()
    confirm = _released_then_confirm(r, heard_released)
    got = _item(r, "sys72_activation")
    assert got["confirm_after_release"] == ([r.seq(confirm)] if count else [])
    assert got["count"] == count and got["confirmed_by_free_speech"] == []


def test_a_commit_confirmed_by_free_speech_is_listed() -> None:
    r = Run()
    confirm = _released_then_confirm(r, True)
    commit = r.commit("fast-yes", "save-1", frm="CONFIRM")
    binding: P = {"offer_ref": "save-1", "revision": 1, "term_months": 12,
                  "terms": {"monthly_price": "60.00"}}  # fmt: skip
    write: P = {"confirmation_id": "c1", "binding": binding}
    r.log.add("ledger.write", "world.policy", "world", write, (commit,))
    got = _item(r, "sys72_activation")
    assert got["confirmed_by_free_speech"] == [r.seq(commit)]
    assert got["count"] == 2 and got["seqs"] == [r.seq(confirm), r.seq(commit)]


# B8: the sim rep in CONFIRM, and how that ends (X4: wedged until the end).
@pytest.mark.parametrize(
    ("leave", "wedged", "to"),
    [("confirmed", 0, "CONFIRMED"), ("ack_decline", 0, "OFFER"), (None, 1, None)],
)
def test_rep_confirm(leave: str | None, wedged: int, to: str | None) -> None:
    r = Run()
    entered = r.policy("OFFER", "CONFIRM", "confirm_accept", "save-1", 0)
    r.policy("CONFIRM", "CONFIRM", "ok_hold", None, 0)  # still in CONFIRM
    left = r.policy("CONFIRM", str(to), leave, "save-1", 0) if leave else None
    r.end("timeout")
    got = _item(r, "rep_confirm")
    assert got["count"] == 1 and got["seqs"] == [r.seq(entered)]
    assert got["wedged"] == wedged and got["end_reason"] == "timeout"
    assert got["exits"] == [{"entered": r.seq(entered),
                             "left": r.seq(left) if left else None,
                             "to": to, "intent": leave}]  # fmt: skip


# B9: S1-SYS-84: stop delivery -> the sim approver's post, on runs with a stop.
def _stop(r: Run, card: str, kind: str = "stop") -> tuple[str, str]:
    sim: P = {"text": "PRIV", "revealed": {}, "delay_s": 1.0, "stop": kind}
    said = r.log.add("user.sim", "world.simuser", "world", sim, (card,))
    msg = r.log.add("user.msg", "kernel", "agent", {"text": "PRIV"}, (said,))
    return said, msg


@pytest.mark.parametrize("outcome", ["posted", "denied", "never"])
def test_stop_to_grant(outcome: str) -> None:
    r = Run()
    card = r.request()
    said, msg = _stop(r, card)
    r.log.add("user.msg", "kernel", "agent", {"text": "PRIV"})  # another message
    r.post(r.start, "granted", "sim_approver")  # a post for another subject
    at = None
    if outcome == "posted":
        at = r.post(card, "granted", "sim_approver")
    elif outcome == "denied":
        denied: P = {"intent": "approval.post", "reason": "stale_epoch"}
        at = r.log.add("action.denied", "kernel", "agent", denied, (card,))
    got = _item(r, "stop_to_grant")
    delay = None if at is None else 100 * (r.seq(at) - r.seq(msg))
    assert got["count"] == 1 and got["seqs"] == [r.seq(said)]
    assert got["stops"] == [{
        "stop": r.seq(said), "kind": "stop", "delivered": r.seq(msg),
        "post": None if at is None else r.seq(at),
        "outcome": {"posted": "granted", "denied": "denied:stale_epoch",
                    "never": None}[outcome],
        "delay_ms": delay,
    }]  # fmt: skip


def test_a_ui_post_is_no_sim_grant_and_no_stop_no_item() -> None:
    r = Run()
    card = r.request()
    _stop(r, card, "mind_change")
    r.post(card, "granted", "ui")
    got = _item(r, "stop_to_grant")
    assert got["count"] == 1 and got["stops"][0]["post"] is None
    assert _item(Run(), "stop_to_grant") == {"count": 0, "seqs": [], "stops": []}


def test_summary_per_family_lists_runs_and_totals() -> None:
    a, b = Run("r1"), Run("r2")
    a.tool("finish", False, None)
    a.tool("finish", False, None)
    rows = [
        {"run_id": "r1", "detectors": {"tier": {"family": "fam-a"}},
         "watch": watch.run(a.inputs())},
        {"run_id": "r2", "detectors": {"tier": {"family": "fam-a"}},
         "watch": watch.run(b.inputs())},
    ]  # fmt: skip
    s = watch.summary(rows)
    assert s["label"] == watch.LABEL
    fams: Any = s["families"]
    fam = fams["fam-a"]
    assert fam["runs"] == 2
    assert fam["slow_refusals"] == {"total": 2, "runs": ["r1"], "naming": 0}
    assert fam["identity_strikes"] == {"total": 0, "runs": [], "unknown": 2}
    text = watch.block(s, "git_sha:abc")
    assert text.splitlines()[0] == f"== watch git_sha abc ({watch.LABEL})"
    assert "slow_refusals=2 (1 runs)" in text
