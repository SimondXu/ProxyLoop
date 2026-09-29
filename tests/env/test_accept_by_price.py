"""S1-SYS-88 Part 1 (F-b, X4): an accept the Ear heard with ``offer_ref``
null. It names an offer only by saying the monthly price or ref of exactly one
offer that is open and was listed to the Ear for its block (``listed``,
ADR-0021 ruling 1). Ambiguity always reads back, never commits; in CONFIRM, a
"yes" commits the pending offer unless another listed offer is named."""

from __future__ import annotations

from typing import Any

from proxyloop.env.counterparty.ear import EarAct
from proxyloop.env.counterparty.policy import Decision, Policy
from proxyloop.env.tasks.loader import load_task

TASK = load_task("cp-direct-discount")
CP = TASK.counterparty
NAME, LAST4 = "account.holder_name", "account.last4"
THIRD = CP.ladder[1].model_copy(
    update={
        "offer_ref": "loyal-3",
        "terms": {"monthly_price": "60.00", "term_months": "36"},
    }
)
# Guard's released accept line (x-out-of-envelope-approval): "Yes, we accept
# these terms: <readback_text>", the price among the terms
GUARD_68 = (
    "Yes, we accept these terms: $68 a month for 24 months, "
    "a one-time activation fee of $20."
)


def _step(
    p: Policy,
    act: str,
    t_ms: int = 0,
    heard: str = "",
    listed: frozenset[str] | None = None,
    **args: Any,
) -> Decision:
    """``listed`` defaults to every offer made so far: the Ear's listing when
    each utterance is heard alone (SimRep passes ``policy.made()``)."""
    if "facts" in args:
        args["facts"] = tuple({"key": k, "value": v} for k, v in args["facts"].items())
    ear = EarAct.model_validate({"act": act, **args})
    shown = frozenset(p.made()) if listed is None else listed
    return p.step(ear, f"u{t_ms}", heard, t_ms, listed=shown)[-1]


def _offers(n: int = 2, t_ms: int = 0) -> Policy:
    """Verified, with the first ``n`` rungs offered (the latest last); the
    ladder has at least two rungs."""
    ladder = [*CP.ladder, THIRD][: max(n, 2)]
    p = Policy(
        CP.model_copy(update={"ladder": ladder}),
        {k: TASK.profile.facts[k] for k in CP.identity},
    )
    _step(p, "other", t_ms)
    _step(p, "provide_fact", t_ms, facts={NAME: "Dana Reyes", LAST4: "4821"})
    for lever in ("ask_discount", "cancel_intent", "tenure")[:n]:
        _step(p, lever, t_ms)
    assert p.open_offers() == frozenset(s.offer_ref for s in ladder[:n])
    return p


def _read_back(d: Decision, ref: str) -> None:
    assert (d.to, d.intent.kind, d.intent.offer_ref) == (
        "CONFIRM",
        "confirm_accept",
        ref,
    )
    assert d.commit is None


def _committed(d: Decision, ref: str) -> None:
    assert (d.to, d.intent.kind) == ("CONFIRMED", "confirmed")
    assert d.commit is not None and d.commit.offer_ref == ref


# Row 2: offer_ref null, not in CONFIRM


def test_a_deictic_accept_with_several_offers_reads_back_rule_h() -> None:
    """Codebook rule (h): "we'll take that one" with several offers listed is
    an accept with offer_ref null and no price: the latest is read back."""
    p = _offers()
    _read_back(_step(p, "accept", heard="Great, we'll take that one."), "loyal-2")
    assert p.open_offers() == {"loyal-1", "loyal-2"} and p.state == "CONFIRM"


def test_guards_accept_line_commits_the_one_offer_whose_price_it_says() -> None:
    p = _offers()
    _committed(_step(p, "accept", heard=GUARD_68), "loyal-2")
    one = _offers(1)
    line = "Yes, we accept these terms: $75 a month for 12 months."
    _committed(_step(one, "accept", heard=line), "loyal-1")


def test_the_offer_ref_said_names_the_offer_too() -> None:
    p = _offers()
    _committed(_step(p, "accept", heard="We'll go with loyal-1."), "loyal-1")


def test_two_open_offers_named_read_back_never_commit() -> None:
    p = _offers()
    d = _step(p, "accept", heard="We accept, either the $75 or the $68 one.")
    _read_back(d, "loyal-2")
    assert p.open_offers() == {"loyal-1", "loyal-2"}


def test_a_price_that_differs_from_the_named_offer_reads_back() -> None:
    p = _offers()
    _read_back(_step(p, "accept", heard=GUARD_68, price_usd=75), "loyal-2")


def test_an_offer_not_listed_to_the_ear_is_never_a_candidate() -> None:
    """ADR-0021 ruling 1 in the policy: loyal-2 was unlocked in this block, so
    the caller could not have heard it; saying its price does not commit."""
    p = _offers()
    d = _step(p, "accept", heard=GUARD_68, listed=frozenset({"loyal-1"}))
    _read_back(d, "loyal-2")


def test_without_a_listing_no_price_names_an_offer() -> None:
    """The default: a caller with no Ear listing (env/reference.py) keeps the
    old rule, an accept with offer_ref null always reads back first."""
    p = _offers()
    ear = EarAct(act="accept")
    _read_back(p.step(ear, "u0", GUARD_68, 0)[-1], "loyal-2")


def test_a_lapsed_offers_price_is_not_a_candidate() -> None:
    ttl = int(CP.ladder[0].ttl_s * 1000)
    p = _offers(1)
    later = ttl + 1_000  # loyal-1 lapsed
    _step(p, "cancel_intent", later)  # loyal-2 made after it
    assert p.open_offers() == {"loyal-2"}
    d = _step(p, "accept", later, heard="We accept the $75 one.")
    _read_back(d, "loyal-2")  # the open latest, not the lapsed one named
    lone = _offers(1)
    d = _step(lone, "accept", later, heard="We accept the $75 one.")
    assert (d.intent.kind, d.intent.offer_ref, d.commit) == (
        "offer_unavailable",
        "loyal-1",
        None,
    )


# Row 3: offer_ref null, in CONFIRM with loyal-P pending


def _confirming(n: int = 2) -> Policy:
    p = _offers(n)
    latest = p.spec.ladder[n - 1].offer_ref
    _read_back(_step(p, "accept", heard="Okay, we'll take it."), latest)
    return p


def test_a_yes_or_the_pending_offer_named_commits_it() -> None:
    _committed(_step(_confirming(), "accept", heard="Yes."), "loyal-2")
    said = "Yes, $68 a month is fine."
    _committed(_step(_confirming(), "accept", heard=said), "loyal-2")


def test_another_offer_named_in_confirm_reads_it_back_never_commits_the_pending() -> (
    None
):
    p = _confirming()
    d = _step(p, "accept", heard="Actually, the $75 one.")
    _read_back(d, "loyal-1")
    _committed(_step(p, "accept", heard="Yes."), "loyal-1")


def test_the_pending_and_one_other_named_reads_the_other_back() -> None:
    p = _confirming()
    _read_back(_step(p, "accept", heard="Not the $68, the $75 one."), "loyal-1")


def test_two_other_offers_named_in_confirm_rereads_the_pending() -> None:
    p = _confirming(3)
    d = _step(p, "accept", heard="The $75 one, or maybe the $68 one.")
    _read_back(d, "loyal-3")
    assert p.open_offers() == {"loyal-1", "loyal-2", "loyal-3"}
