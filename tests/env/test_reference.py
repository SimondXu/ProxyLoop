"""Reference completability (EVAL §3) over generated instances, and the
predicate's refusals."""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from proxyloop.env import world
from proxyloop.env.counterparty.ear import EarAct
from proxyloop.env.counterparty.policy import Policy
from proxyloop.env.reference import FAMILY_CHECKS, completable
from proxyloop.env.tasks.instances import instance
from proxyloop.env.tasks.loader import instance_hash, load_task
from proxyloop.env.tasks.schema import Task

SLICE = {  # the S1 slice: family -> mode
    "cp-direct-discount": "full",
    "cp-hidden-fee-readback": "full",
    "x-out-of-envelope-approval": "full",
    "x-user-mind-change": "full",
}


@pytest.mark.parametrize("family", sorted(SLICE))
def test_fifty_instances_per_family_are_completable(family: str) -> None:
    task = load_task(family, mode=SLICE[family])
    check = FAMILY_CHECKS.get(family, lambda _: True)
    hashes = set[str]()
    for seed in range(50):
        one = instance(task, seed)
        verdict = completable(one)
        assert verdict.ok, f"{one.id}: {verdict}"
        assert check(one), f"{one.id} lacks its family's hazard"
        hashes.add(instance_hash(one))
    assert len(hashes) == 50


Edit = Callable[[dict[str, Any]], object]


def _edit(family: str, edit: Edit) -> Task:
    data = load_task(family, mode="full").model_dump(mode="json")
    edit(data)
    return Task.model_validate(data)


def _ladder(d: dict[str, Any]) -> list[dict[str, Any]]:
    return d["counterparty"]["ladder"]


def test_an_instance_keeps_the_family_and_zero_is_the_file() -> None:
    task = load_task("cp-hidden-fee-readback")
    assert instance(task, 0) is task
    one = instance(task, 7)
    assert one.id == "cp-hidden-fee-readback-i7" and one.family == task.family
    assert one.profile.facts["budget.max_fees_usd"] == "0"  # "no fees" stays zero
    trap, fine = (o.all_terms for o in one.counterparty.ladder)
    assert Decimal(trap["fee:installation"]) >= 99 and fine["fees_none"] == "true"
    shift = Decimal(fine["monthly_price"]) - 62
    assert Decimal(one.profile.facts["budget.max_monthly_usd"]) - 65 == shift
    assert instance(task, 7) == one


def test_a_hidden_fee_on_every_offer_is_not_completable() -> None:
    task = _edit(
        "cp-hidden-fee-readback",
        lambda d: _ladder(d)[1]["hidden"].update({"fee:setup": "10.00"}),
    )
    verdict = completable(task)
    assert not verdict.ok and verdict.path[-1] == "no deal"


def test_the_trap_is_the_family_hazard() -> None:
    def no_trap(d: dict[str, Any]) -> None:
        _ladder(d)[0]["hidden"] = {k: v for k, v in _ladder(d)[1]["hidden"].items()}

    assert not FAMILY_CHECKS["cp-hidden-fee-readback"](
        _edit("cp-hidden-fee-readback", no_trap)
    )


def test_a_misquoting_ledger_outside_the_limits_is_not_completable() -> None:
    task = _edit(
        "cp-direct-discount", lambda d: d["counterparty"].update(ledger="misquote")
    )
    verdict = completable(task)
    assert not verdict.ok and "the ledger binds" in verdict.path[-1]


def test_an_absent_ledger_is_not_completable() -> None:
    task = _edit(
        "cp-direct-discount", lambda d: d["counterparty"].update(ledger="absent")
    )
    assert completable(task).path[-1] == "no ledger entry"


def test_a_read_back_missing_a_required_field_cannot_be_confirmed() -> None:
    def no_expiry(d: dict[str, Any]) -> None:
        for offer in _ladder(d):
            offer["hidden"].pop("expires")

    verdict = completable(_edit("cp-direct-discount", no_expiry))
    assert not verdict.ok
    assert "loyal-2 unconfirmable ['expires']" in verdict.path


def test_an_approval_that_outlasts_the_offer_is_not_completable() -> None:
    def short(d: dict[str, Any]) -> None:
        _ladder(d)[1]["ttl_s"] = 30  # read-back, then a 15 s hold

    verdict = completable(_edit("x-out-of-envelope-approval", short))
    assert not verdict.ok and "accept->offer_unavailable" in verdict.path


def test_a_stop_family_that_can_commit_before_the_stop_is_refused() -> None:
    def cheap(d: dict[str, Any]) -> None:
        _ladder(d)[0]["terms"]["monthly_price"] = "69.00"  # within the envelope

    verdict = completable(_edit("x-user-mind-change", cheap))
    assert not verdict.ok and verdict.path[-1] == "commits before the stop fires"


def test_a_mind_change_after_the_card_is_completed_under_the_new_limit() -> None:
    def change(d: dict[str, Any]) -> None:
        d["stop"]["change"] = {"budget.max_monthly_usd": "74"}
        d["gold"]["check"] = "ledger"

    verdict = completable(_edit("x-user-mind-change", change))
    assert verdict.ok, verdict
    # keep-1 ($76) got a card, then the change put it out; keep-2 ($73) is
    # within the changed envelope, under its re-granted mandate
    at = verdict.path.index("stop@card")
    assert verdict.path[at + 1 :] == [
        "mandate granted",
        "tenure->final_offer",
        "ask_readback->readback",
        "accept->confirmed",
        "ledger",
    ]


def test_after_offer_is_refused_when_an_offer_price_is_a_known_number() -> None:
    def after_offer(d: dict[str, Any]) -> None:
        d["stop"]["trigger"] = "after_offer"
        d["profile"]["facts"]["competitor.price_usd"] = "76"  # keep-1's price

    verdict = completable(_edit("x-user-mind-change", after_offer))
    assert not verdict.ok and "profile number" in verdict.path[-1]


def test_after_turn_k_and_after_offer_stops_are_reachable() -> None:
    def trigger(name: str, k: int | None) -> Edit:
        return lambda d: d["stop"].update(trigger=name, k=k)

    for name, k in (("after_turn_k", 2), ("after_offer", None)):
        verdict = completable(_edit("x-user-mind-change", trigger(name, k)))
        assert verdict.ok and verdict.path[-1].startswith("stop@")


def test_info_only_has_no_gold_outcome_to_reach() -> None:
    with pytest.raises(ValueError, match="info_only"):
        completable(load_task("cp-direct-discount"))


def test_the_hidden_fee_is_said_only_on_the_read_back() -> None:
    task = load_task("cp-hidden-fee-readback")
    cp = task.counterparty
    p = Policy(cp, {k: task.profile.facts[k] for k in cp.identity})

    def say(act: str, **args: Any) -> dict[str, str]:
        ear = EarAct.model_validate({"act": act, **args})
        return dict(p.step(ear, "u", "", 0)[-1].intent.say)

    ids = tuple({"key": k, "value": task.profile.facts[k]} for k in cp.identity)
    say("provide_fact", facts=ids)
    assert p.state == "DISCOVER"
    offered = say("ask_discount")
    assert offered == {"monthly_price": "55.00", "term_months": "12"}
    assert say("ask_readback", offer_ref="promo-1")["fee:installation"] == "99.00"


def _money(task: Task) -> set[Decimal]:
    """Every offer's non-zero money amounts."""
    return {
        Decimal(v)
        for o in task.counterparty.ladder
        for k, v in o.all_terms.items()
        if k == "monthly_price" or k.startswith(("fee:", "credit:"))
        if Decimal(v) != 0
    }


def _known(task: Task) -> set[Decimal]:
    """Every number the user knows or the approver judges by."""
    values = [*task.profile.facts.values()]
    if task.principal is not None and task.principal.limits is not None:
        values += [str(v) for v in task.principal.limits.model_dump().values() if v]
    if task.stop is not None:
        values += [*(task.stop.change or {}).values()]
    return {n for v in values for n in world.numbers(v)}


@pytest.mark.parametrize("family", sorted(SLICE))
def test_instances_state_one_limit_and_offers_never_echo_a_known_number(
    family: str,
) -> None:
    task = load_task(family, mode=SLICE[family])
    for seed in range(50):
        one = instance(task, seed)
        refs = re.findall(r"\{([^}]*)\}", one.user_goal)
        assert refs and not re.search(r"\d", re.sub(r"\{[^}]*\}", "", one.user_goal))
        stated = set[Decimal]().union(
            *(world.numbers(one.profile.facts[k]) for k in refs)
        )
        assert world.numbers(one.goal(one.profile.facts)) == stated, one.id
        assert not _money(one) & _known(one), one.id
