"""S1-SYS-46 follow-up (run cc160a): the full playbook defines a hard limit as
Guard's ``hard_violations`` classes, and the offers line says when a recorded
offer is outside the mandate (an approval can lift it) or breaks a hard limit
(none can). At 199 s Slow declined $78 against a $65 mandate as "a hard limit"
and never asked the user. Fixtures assert classes and Guard's own verdicts."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.slow import test_authority as auth
from tests.slow import test_close_levers as levers
from tests.slow.test_authority import HINT, Host

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.state import Mandate
from proxyloop.contract.views import view_slow
from proxyloop.guard.authorize import Denial, open_offer
from proxyloop.guard.mandate import hard_violations
from proxyloop.guard.policy import UNSUPPORTED_APPLIED_CHANGE
from proxyloop.guard.terms import NO_EXPIRY, Terms
from proxyloop.slow import prompt, state

_confirmed = auth._confirmed  # pyright: ignore[reportPrivateUsage]
_mandate = auth._mandate  # pyright: ignore[reportPrivateUsage]
_head = levers._head  # pyright: ignore[reportPrivateUsage]
OFFER = "I can offer a monthly price of 78.00 with a term of 24 months."  # cc160a
SLOTS = [
    {"field": "monthly_price", "value": "7800", "utt_ref": "cp-6"},
    {"field": "term_months", "value": "24", "utt_ref": "cp-6"},
]
RECORD = {"tool": "record_offer", "offer_ref": "offer-1", "offer_slots": SLOTS}
READBACK = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:offer-1"]}
CAP = {"max_term_months": 24, "max_one_time_fees_minor": 0}  # cc160a's mandate


def _offers_line(h: Host, mode: SlowViewMode = SlowViewMode.RELAY_ONLY) -> str:
    h.tools.readback()
    more = state.bar(h.bb, "full", h.tools)
    bar = prompt.status_bar(view_slow(h.bb, mode, "b"), h.now(), None, more)
    (line,) = [x for x in bar.splitlines() if x.startswith("offers: ")]
    return line


def _cc160a(tmp_path: Path, cap: int = 6500) -> Host:
    """r1 recorded 78/24 against a granted $65 mandate, read-back asked once."""
    h = Host(tmp_path)
    _mandate(h, cap, **CAP)
    h.call()
    h.rep("cp-6", OFFER)
    got = h.act(RECORD, READBACK)
    assert got[-1].endswith("read-back asked for offer-1 r1"), got
    return h


def test_hard_limits_are_exactly_guards_hard_violation_classes() -> None:
    """Every class ``hard_violations`` can return has plain words, and no more."""
    m = Mandate(
        mandate_id="m",
        mandate_hash="h",
        status="proposed",
        epoch=0,
        required_features=("unlimited_data",),
        forbidden_changes=("plan_change",),
    )
    worst = Terms(
        monthly_price_minor=0,
        currency="USD",
        term_months=0,
        features=(),
        fees=(),
        credits=(),
        applied_changes=("plan_change", "no_such_change"),
        total_cost_12m_minor=0,
        offer_id="o",
        offer_revision=1,
        expires_at=NO_EXPIRY,
    )
    assert set(hard_violations(worst, m)) == set(prompt.HARD_LIMITS)
    # the literal codes guard/mandate.py hard_violations appends (it exports none)
    codes = {"required_feature_missing", "forbidden_change_present"}
    assert set(prompt.HARD_LIMITS) == codes | {UNSUPPORTED_APPLIED_CHANGE}


@pytest.mark.parametrize("mode", list(SlowViewMode))
def test_cc160a_outside_the_mandate_is_not_a_hard_limit(
    tmp_path: Path, mode: SlowViewMode
) -> None:
    """cc160a at 199 s: the bar says the user decides once it is confirmed, and
    shows no hard class; the signal is the board's, so relay_only has it too."""
    h = _cc160a(tmp_path)
    line = _offers_line(h, mode)
    assert prompt.OUTSIDE_MANDATE in line
    assert prompt.HARD_LIMIT not in line and "decline" not in line
    head = _head("full")
    playbook = prompt.PLAYBOOK["full"]
    assert playbook in head
    assert all(words in playbook for words in prompt.HARD_LIMITS.values())
    outside = playbook.index("outside the mandate, not a hard limit")
    assert playbook.index("request_approval", outside) > outside


def test_an_offer_inside_the_mandate_shows_no_signal(tmp_path: Path) -> None:
    line = _offers_line(_cc160a(tmp_path, cap=8000))
    assert prompt.OUTSIDE_MANDATE not in line and prompt.HARD_LIMIT not in line


REP_CHANGE = "I can offer 78.00 a month for 24 months, with a plan change."


def test_a_forbidden_change_shows_the_hard_class_not_outside_mandate(
    tmp_path: Path,
) -> None:
    """Also $78 over $65: the hard class wins, since no approval can lift it."""
    h = Host(tmp_path)
    _mandate(h, 6500, forbidden_changes=["plan_change"], **CAP)
    h.call()
    h.rep("cp-6", REP_CHANGE)
    change = {"field": "applied_change:plan_change", "value": "true", "utt_ref": "cp-6"}
    got = h.act({**RECORD, "offer_slots": [*SLOTS, change]}, READBACK)
    assert got[-1].endswith("read-back asked for offer-1 r1"), got
    line = _offers_line(h)
    assert f"{prompt.HARD_LIMIT}: forbidden_change_present" in line
    assert prompt.OUTSIDE_MANDATE not in line


def test_a_confirmed_offer_outside_the_mandate_keeps_the_approval_hint(
    tmp_path: Path,
) -> None:
    """#166's hint covers the confirmed case: no second signal, no decline.
    S1-SYS-66: with the bar, an available lever comes first."""
    h = _confirmed(tmp_path)  # $69
    _mandate(h, 6500)
    line = _offers_line(h)
    assert "save-2 confirmed, outside mandate → first" in line
    assert "guide_fast(mention_tenure)" in line and HINT not in line
    assert prompt.OUTSIDE_MANDATE not in line and prompt.HARD_LIMIT not in line
    assert "decline" not in line


def test_a_confirmed_offer_that_breaks_a_hard_limit_shows_its_class(
    tmp_path: Path,
) -> None:
    """Guard refuses its card (policy_violation), so #166 hints nothing; the bar
    still says why."""
    h = _confirmed(tmp_path)
    _mandate(h, 6500, required_features=["unlimited_data"])
    line = _offers_line(h)
    assert f"{prompt.HARD_LIMIT}: required_feature_missing" in line
    assert "outside mandate" not in line


@pytest.mark.parametrize("feature", ["unlimited data", "x" * 41])
def test_a_required_feature_any_name_never_breaks_the_bar(
    tmp_path: Path, feature: str
) -> None:
    """#218 B1: propose_mandate takes any feature name; the bar must not
    build a read-back slot from it. Not yet stated is not yet missing."""
    h = Host(tmp_path)
    _mandate(h, 6500, required_features=[feature], **CAP)
    h.call()
    h.rep("cp-6", OFFER)
    h.act(RECORD, READBACK)
    line = _offers_line(h)
    assert prompt.OUTSIDE_MANDATE in line and prompt.HARD_LIMIT not in line


@pytest.mark.parametrize("why", ["offer_expired", "fence_raised"])
def test_no_outside_mandate_signal_when_guard_would_refuse_anyway(
    tmp_path: Path, why: str
) -> None:
    """#218 M1: only Guard's readback_not_confirmed means "once confirmed";
    an expired offer or a raised fence gets no approval either way."""
    h = _cc160a(tmp_path)
    view = view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b")
    (o,) = view.offers
    assert prompt.mandate_hint(view, o, h.now()) == prompt.OUTSIDE_MANDATE
    if why == "offer_expired":
        o = o.model_copy(update={"expires_ms": 1})
    else:
        view = view.model_copy(update={"fences": ("f-1",)})
    assert isinstance(open_offer(o, view.mandate, h.now(), bool(view.fences)), Denial)
    assert prompt.mandate_hint(view, o, h.now()) == ""


def test_a_complete_unconfirmed_revision_missing_a_feature_breaks_a_hard_limit(
    tmp_path: Path,
) -> None:
    """#218 r3: every term is stated but the required feature: a read-back
    cannot add it, so it is a hard limit now, not "approval once confirmed"."""
    h = Host(tmp_path)
    _mandate(h, 6500, required_features=["unlimited_data"])
    h.call()
    h.rep("cp-1", auth.TERMS)
    record = {"tool": "record_offer", "offer_ref": "save-2", "offer_slots": auth.SLOTS}
    ask = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:save-2"]}
    assert h.act(record, ask)[-1].endswith("read-back asked for save-2 r1")
    line = _offers_line(h)
    assert f"{prompt.HARD_LIMIT}: required_feature_missing" in line
    assert prompt.OUTSIDE_MANDATE not in line


@pytest.mark.parametrize("why", ["offer_expired", "fence_raised"])
def test_a_hard_limit_shows_even_when_fenced_or_expired(
    tmp_path: Path, why: str
) -> None:
    """#218 r3: a hard violation is permanent; only the approval signal waits
    on open_offer."""
    h = _confirmed(tmp_path)
    _mandate(h, 6500, required_features=["unlimited_data"])
    view = view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b")
    (o,) = view.offers
    if why == "offer_expired":
        o = o.model_copy(update={"expires_ms": 1})
    else:
        view = view.model_copy(update={"fences": ("f-1",)})
    got = prompt.mandate_hint(view, o, h.now())
    assert got == f"{prompt.HARD_LIMIT}: required_feature_missing"
