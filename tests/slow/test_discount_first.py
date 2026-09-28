"""S1-SYS-82 (success-path audit on c3d39a8, root decision 2026-09-29): Slow
opens with the discount ask, levers wait for the first offer (F-a), a granted
approval names accept_offer (F-d), a worse open offer defers to a better one
(F-e), and propose_mandate carries every bound the user stated, fees
included (F-f). Each state is a status-bar snapshot of a train family's
minimal trajectory (cp-direct-discount, cp-hidden-fee-readback,
x-out-of-envelope-approval, x-user-mind-change), and each shows one next
step. The test plays the kernel; the wording is generic (rule 12)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.slow import test_authority as auth
from tests.slow import test_negotiate as neg
from tests.slow.test_authority import Host

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.state import CaseStatus
from proxyloop.contract.views import view_slow
from proxyloop.slow import prompt, state

_mandate = auth._mandate  # pyright: ignore[reportPrivateUsage]
_granted = auth._granted  # pyright: ignore[reportPrivateUsage]
_deny = neg._deny  # pyright: ignore[reportPrivateUsage]
_reply = neg._reply  # pyright: ignore[reportPrivateUsage]
TENURE = neg.TENURE
LAST4 = {"tool": "guide_fast", "move": "identify", "slots": ["fact:account.last4"]}
DISCOUNT = {"tool": "guide_fast", "move": "ask_discount"}
REFUSED = f"{neg.COMPETITOR}; {neg.CANCELLING}"
ASK_DISCOUNT = "guide_fast(ask_discount)"
ASKED = "; read-back asked 1×"  # noqa: RUF001 (the note's facts)
# a step Slow could take: a tool call the bar names with its arguments
STEP = re.compile(
    r"(?:guide_fast|request_approval|accept_offer|decline_offer)\([^)]*\)"
    r"|ask_final_offer|propose_mandate"
)


def _bar(h: Host, mode: SlowViewMode = SlowViewMode.RELAY_ONLY) -> str:
    h.tools.readback()
    more = state.bar(h.bb, "full", h.tools)
    return prompt.status_bar(view_slow(h.bb, mode, "b"), h.now(), None, more)


def _line(h: Host, head: str) -> str:
    (line,) = [x for x in _bar(h).splitlines() if x.startswith(head)]
    return line


def _steps(h: Host) -> set[str]:
    """Every step the bar names, but the close line's finish verdict."""
    return set(STEP.findall(_bar(h)))


def _terms(price: int, term: int) -> str:
    return (
        f"It is ${price} a month on a {term}-month term, no fees, no other "
        "changes, and the offer does not expire."
    )


def _slots(price: int, term: int, utt: str) -> list[dict[str, str]]:
    minor = str(price * 100)
    return [
        s
        | {
            "utt_ref": utt,
            **({"value": minor} if s["field"] == "monthly_price" else {}),
        }
        | ({"value": str(term)} if s["field"] == "term_months" else {})
        for s in auth.SLOTS
    ]


def _offer(h: Host, ref: str, price: int, term: int) -> None:
    """The rep states ``ref``'s terms and Slow records them."""
    utt = f"cp-{len(h.bb.channels['cp'].lines) + 1}"
    h.rep(utt, _terms(price, term))
    record = {"tool": "record_offer", "offer_ref": ref}
    (got,) = h.act(record | {"offer_slots": _slots(price, term, utt)})
    assert got.startswith(f"record_offer: recorded {ref} r"), got


def _read_back(h: Host, ref: str, price: int, term: int) -> None:
    ask = {"tool": "guide_fast", "move": "ask_readback", "slots": [f"offer:{ref}"]}
    (got,) = h.act(ask)
    assert got.endswith(f"read-back asked for {ref} r1"), got
    h.voice()
    h.rep(f"cp-{len(h.bb.channels['cp'].lines) + 1}", _terms(price, term))
    h.tools.readback()
    assert {s.status for s in h.bb.public.offers[ref].slots} == {"confirmed"}


def _tenure_answered(h: Host) -> None:
    """mention_tenure sent, heard, and answered by the rep: no lever left."""
    h.act(TENURE)
    h.voice()
    _reply(h)


def _verified(tmp_path: Path, cap: int = 6500, **bounds: int) -> Host:
    """identify: every trajectory's first step. The mandate granted in the
    intake (``cap`` and ``bounds``), the last 4 public, the call open, the
    identify heard, and the rep has answered since."""
    h = Host(tmp_path)
    _mandate(h, cap, **bounds)
    said = h.emit("user.msg", "kernel", {"text": "My last 4 are 4821."})
    record = {"tool": "record_fact", "key": "account.last4", "value": "4821"}
    h.act(record | {"utt_ref": said.event_id})
    h.call()
    h.act(LAST4)
    h.voice()
    h.rep("cp-1", "Thank you, the account is verified. How can I help?")
    return h


# (1) verified, no offer -> guide_fast(ask_discount); no lever before an offer


VERIFIED = (
    "request: once the rep has verified the account, the one next phone step: "
    "guide_fast(ask_discount) (ask for a lower monthly price)"
)
ANSWERED = "identify: heard by the rep, who has answered since"
NOT_YET = f"levers: after the first offer: mention_tenure; {REFUSED}"


@pytest.mark.parametrize("mode", list(SlowViewMode), ids=str)
def test_1_verified_no_offer_the_one_step_is_ask_discount(
    tmp_path: Path, mode: SlowViewMode
) -> None:
    h = _verified(tmp_path)
    bar = _bar(h, mode).splitlines()
    assert ANSWERED in bar and VERIFIED in bar and NOT_YET in bar, bar
    assert _steps(h) == {ASK_DISCOUNT}


def test_1_before_the_identify_is_answered_no_ask_discount(tmp_path: Path) -> None:
    h = Host(tmp_path)
    _mandate(h, 6500)
    said = h.emit("user.msg", "kernel", {"text": "My last 4 are 4821."})
    record = {"tool": "record_fact", "key": "account.last4", "value": "4821"}
    h.act(record | {"utt_ref": said.event_id})
    h.call()
    h.act(LAST4)
    h.voice()  # heard, the rep has not answered yet
    assert "identify: heard by the rep, not answered yet (wait)" in _bar(h)
    assert "request: " not in _bar(h)
    assert _steps(h) == set()
    assert NOT_YET in _bar(h).splitlines()


@pytest.mark.parametrize(
    ("heard", "want"),
    [
        (False, "sent, not heard yet (wait; do not send it again)"),
        (True, "heard by the rep, not answered yet (wait)"),
    ],
)
def test_1_ask_discount_sent_is_not_proposed_again(
    tmp_path: Path, heard: bool, want: str
) -> None:
    h = _verified(tmp_path)
    (sent,) = h.act(DISCOUNT)
    assert sent.startswith("guide_fast: sent"), sent
    if heard:
        h.voice()
    bar = _bar(h).splitlines()
    assert ANSWERED in bar and f"request: ask_discount {want}" in bar, bar
    assert _steps(h) == set()


def test_1_the_first_offer_ends_the_discount_step_and_frees_the_levers(
    tmp_path: Path,
) -> None:
    h = _verified(tmp_path)
    h.act(DISCOUNT)
    h.voice()
    _offer(h, "save-1", 78, 24)
    bar = _bar(h).splitlines()
    assert ANSWERED in bar, bar
    assert not [x for x in bar if "ask_discount" in x or "request: " in x], bar
    assert f"levers: available: mention_tenure; {REFUSED}" in bar, bar


def test_1_the_system_prompt_opens_with_the_discount_ask() -> None:
    for mode in SlowViewMode:
        flat = " ".join(prompt.system(mode).split())
        rule = flat[flat.index("Once the representative has verified the account") :]
        assert rule.startswith(
            "Once the representative has verified the account, your first request "
            "is guide_fast(ask_discount)"
        ), rule
        assert "a lever only after the first offer (the levers line)" in rule


# (2) first offer outside the mandate, a lever free -> mention_tenure


def test_2_first_offer_outside_with_a_lever_free_is_mention_tenure(
    tmp_path: Path,
) -> None:
    """x-out-of-envelope-approval: save-1 ($78) against $65/24/0."""
    h = _verified(tmp_path, 6500, max_term_months=24, max_one_time_fees_minor=0)
    h.act(DISCOUNT)
    h.voice()
    _offer(h, "save-1", 78, 24)
    offers = _line(h, "offers: ")
    assert offers.endswith(
        f"{prompt.OUTSIDE_MANDATE} → first one lever: guide_fast(mention_tenure); "
        "ask_readback only once none is left"
    ), offers
    assert _steps(h) == {"guide_fast(mention_tenure)"}


# (3) a second offer inside the mandate while the first is outside


DEFER_INSIDE = (
    "outside mandate; no step for it now: loyal-2 (inside the granted mandate) "
    "comes first → "
)


def _direct(tmp_path: Path) -> Host:
    """cp-direct-discount: loyal-1 ($75/12) outside $70/24/$25, mention_tenure
    answered, loyal-2 ($68/24) inside."""
    h = _verified(tmp_path, 7000, max_term_months=24, max_one_time_fees_minor=2500)
    h.act(DISCOUNT)
    h.voice()
    _offer(h, "loyal-1", 75, 12)
    h.act(TENURE)
    h.voice()
    _offer(h, "loyal-2", 68, 24)  # the rep's answer to the lever
    return h


def test_3_an_inside_offer_comes_first_its_read_back(tmp_path: Path) -> None:
    h = _direct(tmp_path)
    offers = _line(h, "offers: ")
    loyal_1 = offers.split("; loyal-2 r1", 1)[0]
    step = 'guide_fast(ask_readback, ["offer:loyal-2"]), then accept_offer(loyal-2)'
    assert loyal_1.endswith(DEFER_INSIDE + step), offers
    assert "first one lever" not in offers and "request_approval" not in offers
    assert _steps(h) == {
        'guide_fast(ask_readback, ["offer:loyal-2"])',
        "accept_offer(loyal-2)",
    }


def test_3_the_inside_offer_asked_then_confirmed_is_accept(tmp_path: Path) -> None:
    h = _direct(tmp_path)
    ask = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:loyal-2"]}
    h.act(ask)
    offers = _line(h, "offers: ")
    assert (
        DEFER_INSIDE + "read-back asked: accept_offer(loyal-2) once confirmed" in offers
    )
    assert _steps(h) == {"accept_offer(loyal-2)"}
    h.voice()
    h.rep("cp-9", _terms(68, 24))
    offers = _line(h, "offers: ")
    assert offers.split("; loyal-2 r1", 1)[0].endswith(
        DEFER_INSIDE + "accept_offer(loyal-2)"
    )
    assert _steps(h) == {"accept_offer(loyal-2)"}
    (accepted,) = h.act({"tool": "accept_offer", "offer_ref": "loyal-2"})
    assert "accept line queued" in accepted, accepted
    offers = _line(h, "offers: ")  # the accept is on its way: no step for loyal-1
    assert offers.split("; loyal-2 r1", 1)[0].endswith(
        "loyal-2 (inside the granted mandate) comes first"
    ), offers
    assert _steps(h) == set()


def test_3_hidden_fee_request_approval_of_the_worse_offer_is_gone(
    tmp_path: Path,
) -> None:
    """cp-hidden-fee-readback's hazard: the bar kept request_approval(promo-1)
    after promo-2 was open. promo-1 confirmed outside, no lever left, then
    promo-2 recorded inside the mandate."""
    h = _verified(tmp_path, 6500, max_term_months=12, max_one_time_fees_minor=0)
    _offer(h, "promo-1", 66, 12)
    _read_back(h, "promo-1", 66, 12)
    _tenure_answered(h)
    assert _steps(h) == {"request_approval(promo-1)"}
    _offer(h, "promo-2", 62, 12)
    offers = _line(h, "offers: ")
    assert "request_approval" not in offers, offers
    assert "promo-2 (inside the granted mandate) comes first" in offers, offers
    assert _steps(h) == {
        'guide_fast(ask_readback, ["offer:promo-2"])',
        "accept_offer(promo-2)",
    }


# (4) a confirmed outside offer, no lever left -> request_approval


def _envelope(tmp_path: Path) -> Host:
    """x-out-of-envelope-approval: save-1 ($78) and save-2 ($69, confirmed)
    both outside $65/24/0, mention_tenure answered."""
    h = _verified(tmp_path, 6500, max_term_months=24, max_one_time_fees_minor=0)
    h.act(DISCOUNT)
    h.voice()
    _offer(h, "save-1", 78, 24)
    h.act(TENURE)
    h.voice()
    _offer(h, "save-2", 69, 24)
    _read_back(h, "save-2", 69, 24)
    return h


DEFER_CHEAPER = (
    "outside mandate; no step for it now: save-2 (cheaper, confirmed) comes first"
)


def test_4_a_confirmed_outside_offer_with_no_lever_left_is_request_approval(
    tmp_path: Path,
) -> None:
    h = _envelope(tmp_path)
    offers = _line(h, "offers: ")
    save_1 = offers.split("; save-2 r1", 1)[0]
    assert save_1.endswith(DEFER_CHEAPER), offers
    assert offers.endswith(
        f"save-2 confirmed, outside mandate → request_approval(save-2){ASKED}"
    ), offers
    assert _steps(h) == {"request_approval(save-2)"}


# (5) the approval granted -> accept_offer(<ref>)


def test_5_a_granted_approval_names_accept_offer(tmp_path: Path) -> None:
    h = _envelope(tmp_path)
    _granted(h)
    offers = _line(h, "offers: ")
    assert offers.endswith(
        f"save-2 confirmed, approved → accept_offer(save-2){ASKED}"
    ), offers
    assert offers.split("; save-2 r1", 1)[0].endswith(DEFER_CHEAPER), offers
    assert _steps(h) == {"accept_offer(save-2)"}
    (accepted,) = h.act({"tool": "accept_offer", "offer_ref": "save-2"})
    assert "accept line queued" in accepted, accepted
    assert h.bb.public.status is CaseStatus.COMMIT_AUTHORIZED
    assert "accept_offer" not in _line(h, "offers: ")  # queued: not again
    assert _steps(h) == set()


def test_5_without_the_bar_the_granted_approval_still_names_accept(
    tmp_path: Path,
) -> None:
    h = auth._confirmed(tmp_path)  # pyright: ignore[reportPrivateUsage]
    _mandate(h, 6500)
    _granted(h)
    view = view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b")
    bar = prompt.status_bar(view, h.now())
    assert "save-2 confirmed, approved → accept_offer(save-2)" in bar, bar


def test_5_a_denied_approval_names_no_accept(tmp_path: Path) -> None:
    h = auth._confirmed(tmp_path)  # pyright: ignore[reportPrivateUsage]
    _mandate(h, 6500)
    _tenure_answered(h)
    h.act({"tool": "request_approval", "offer_ref": "save-2"})
    _deny(h)
    assert "accept_offer" not in _bar(h)


# (6) the user denied an offer while a better open offer exists


def test_6_after_a_denial_a_better_open_offer_s_step_wins(tmp_path: Path) -> None:
    h = auth._confirmed(tmp_path)  # pyright: ignore[reportPrivateUsage]
    _mandate(h, 6500, max_term_months=24, max_one_time_fees_minor=0)
    _tenure_answered(h)
    h.act({"tool": "request_approval", "offer_ref": "save-2"})
    _deny(h)
    _offer(h, "save-3", 62, 24)
    bar = _bar(h)
    offers = _line(h, "offers: ")
    assert offers.split("; save-3 r1", 1)[0].endswith(
        "outside mandate; no step for it now: save-3 (inside the granted mandate) "
        'comes first → guide_fast(ask_readback, ["offer:save-3"]), then '
        f"accept_offer(save-3){ASKED}"
    ), offers
    assert "decline_offer" not in bar and "ask_final_offer" not in bar, bar
    assert _steps(h) == {
        'guide_fast(ask_readback, ["offer:save-3"])',
        "accept_offer(save-3)",
    }


def test_6_the_after_denial_rule_defers_to_a_better_open_offer() -> None:
    pb = prompt.PLAYBOOK["full"]
    denied = pb.index("After the user denies an offer")
    better = pb.index("another open offer comes first", denied)
    assert (
        better < pb.index("available lever", denied) < pb.index("decline_offer", denied)
    )


def test_6_a_denied_cheaper_offer_is_not_better(tmp_path: Path) -> None:
    """save-2 ($69) confirmed and denied; save-1 ($78) recorded later: the
    denied one is no better offer, save-1 keeps its own step."""
    h = auth._confirmed(tmp_path)  # pyright: ignore[reportPrivateUsage]
    _mandate(h, 6500, max_term_months=24, max_one_time_fees_minor=0)
    _tenure_answered(h)
    h.act({"tool": "request_approval", "offer_ref": "save-2"})
    _deny(h)
    _offer(h, "save-1", 78, 24)
    offers = _line(h, "offers: ")
    assert "comes first" not in offers, offers
    assert 'guide_fast(ask_readback, ["offer:save-1"])' in offers, offers


# (7) intake: the user stated limits, fees included, and no mandate yet


MANDATE_NONE = (
    "mandate: none (once the user has stated limits: propose_mandate with every "
    "bound they stated, fees included)"
)


def test_7_no_mandate_names_propose_mandate_with_every_bound(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.emit("user.msg", "kernel", {"text": "At most $65 a month, 24 months, no fees."})
    case = _line(h, "case: ")
    assert MANDATE_NONE in case, case
    assert _steps(h) == {"propose_mandate"}
    envelope = {"max_monthly_price_minor": 6500, "max_term_months": 24}
    envelope |= {"max_one_time_fees_minor": 0}
    (got,) = h.act({"tool": "propose_mandate", "envelope": envelope})
    assert "proposed" in got, got
    assert MANDATE_NONE not in _bar(h) and "propose_mandate" not in _bar(h)


def test_7_the_prompt_asks_for_every_stated_bound_fees_included() -> None:
    for mode in SlowViewMode:
        flat = " ".join(prompt.system(mode).split())
        doc = flat[flat.index("- propose_mandate(envelope)") :]
        assert doc.startswith(
            "- propose_mandate(envelope): every bound the user stated, fees included"
        ), doc[:120]
        assert "a stated no-fees limit is max_one_time_fees_minor 0" in doc
        assert "leave out a bound the user did not state" in doc
        ready = flat[flat.index("Readiness:") :]
        assert (
            "Once the user has stated their limits and no mandate is proposed, "
            "propose_mandate with every bound they stated, fees included" in ready
        )


def test_7_info_only_cases_are_not_told_to_propose_a_mandate(tmp_path: Path) -> None:
    h = Host(tmp_path)
    more = state.bar(h.bb, "info_only", h.tools)
    bar = prompt.status_bar(
        view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b"), h.now(), None, more
    )
    assert "propose_mandate" not in bar and "mandate: none;" in bar, bar
