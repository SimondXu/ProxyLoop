"""The offer-ladder detectors (``obs.ladder``) on hand-built rep.* streams,
and against the real env ``Policy`` driven through a lever sequence."""

from __future__ import annotations

from typing import get_args

from tests.obs.bundles import Log
from tests.obs.triage_bundle import P

from proxyloop.env.counterparty.ear import EarAct, Lever
from proxyloop.env.counterparty.policy import Decision, Policy
from proxyloop.env.tasks.loader import load_task
from proxyloop.obs import detectors, ladder

NAMES = (
    "rungs_reached", "levers_heard", "repeated_lever_no_better",
    "no_deal_ladder_unfinished",
)  # fmt: skip


def _values(log: Log) -> dict[str, object]:
    x = detectors.Inputs(log.events, None, lambda _: None)
    return {name: detectors.DETECTORS[name](x) for name in NAMES}


def _ear(log: Log, act: str) -> str:
    payload: P = {"utt_id": f"u{len(log.events)}", "act": act, "args": {}}
    payload |= {"attempts": 1, "call_id": "ear:c:0"}
    return log.add("rep.ear", "world.ear", "world", payload, (log.start,))


def _policy(log: Log, kind: str, rung: int | None, *causes: str) -> str:
    intent: P = {"kind": kind, "offer_ref": None, "say": [], "ask": []}
    payload: P = {"from": "OFFER", "to": "OFFER", "intent": intent, "rung": rung}
    return log.add("rep.policy", "world.policy", "world", payload, causes)


def _pull(log: Log, act: str, kind: str, rung: int | None) -> str:
    return _policy(log, kind, rung, _ear(log, act))


def _commit(log: Log, policy: str) -> None:
    heard: P = {"utt_id": "u", "offer_ref": "o1"}
    log.add("rep.commit_heard", "world.policy", "world", heard, (policy,))


def test_the_levers_are_the_ears() -> None:
    assert frozenset(get_args(Lever)) == ladder.LEVERS
    assert ladder.REACHABLE <= ladder.LEVERS


def test_a_repeated_lever_is_no_better_and_proves_nothing() -> None:
    log = Log("r1")
    _pull(log, "ask_discount", "offer", 0)  # 1, 2
    _pull(log, "ask_discount", "no_better", 0)  # 3, 4: a repeat
    log.end("timeout")
    values = _values(log)
    assert values["rungs_reached"] == {
        "count": 1, "ladder_exhausted": False, "ladder_len": None,
    }  # fmt: skip
    assert values["levers_heard"] == {
        "count": 1, "levers": ["ask_discount"], "taken": ["ask_discount"],
    }  # fmt: skip
    assert values["repeated_lever_no_better"] == {"count": 1, "seqs": [4]}
    # no commit, not exhausted, tenure never heard
    assert values["no_deal_ladder_unfinished"] == {
        "count": 1, "end_reason": "timeout", "unused": ["tenure"],
    }  # fmt: skip


def test_a_new_lever_past_the_last_rung_shows_the_ladder_length() -> None:
    log = Log("r2")
    _pull(log, "ask_discount", "offer", 0)
    _pull(log, "tenure", "final_offer", 1)
    _pull(log, "cancel_intent", "no_better", 1)  # new, the ladder is spent
    log.end("done")
    values = _values(log)
    assert values["rungs_reached"] == {
        "count": 2, "ladder_exhausted": True, "ladder_len": 2,
    }  # fmt: skip
    assert values["levers_heard"] == {
        "count": 3, "levers": ["ask_discount", "cancel_intent", "tenure"],
        "taken": ["ask_discount", "tenure"],
    }  # fmt: skip
    assert values["repeated_lever_no_better"] == {"count": 0, "seqs": []}
    assert values["no_deal_ladder_unfinished"] == {
        "count": 0, "end_reason": "done", "unused": [],
    }  # fmt: skip


def test_a_commit_or_a_spent_ladder_is_no_unfinished_no_deal() -> None:
    committed = Log("r3")
    _commit(committed, _pull(committed, "ask_discount", "offer", 0))
    committed.end("done")
    flag = _values(committed)["no_deal_ladder_unfinished"]
    assert flag == {"count": 0, "end_reason": "done", "unused": ["tenure"]}

    spent = Log("r4")  # a one-rung ladder: the second new lever proves it
    _pull(spent, "ask_discount", "offer", 0)
    _pull(spent, "tenure", "no_better", 0)
    spent.end("timeout")
    values = _values(spent)
    assert values["rungs_reached"] == {
        "count": 1, "ladder_exhausted": True, "ladder_len": 1,
    }  # fmt: skip
    assert values["no_deal_ladder_unfinished"] == {
        "count": 0, "end_reason": "timeout", "unused": [],
    }  # fmt: skip


def test_both_reachable_levers_heard_is_no_unfinished_no_deal() -> None:
    log = Log("r5")
    _pull(log, "ask_discount", "offer", 0)
    _pull(log, "tenure", "offer", 1)  # a longer ladder, not yet spent
    log.end("timeout")
    values = _values(log)
    assert values["rungs_reached"] == {
        "count": 2, "ladder_exhausted": False, "ladder_len": None,
    }  # fmt: skip
    assert values["no_deal_ladder_unfinished"] == {
        "count": 0, "end_reason": "timeout", "unused": [],
    }  # fmt: skip


def test_an_unreachable_lever_is_heard_but_never_unused() -> None:
    log = Log("r6")
    _pull(log, "cite_competitor", "offer", 0)
    log.end("timeout")
    values = _values(log)
    heard = values["levers_heard"]
    assert heard == {
        "count": 1, "levers": ["cite_competitor"], "taken": ["cite_competitor"],
    }  # fmt: skip
    assert values["no_deal_ladder_unfinished"] == {
        "count": 1, "end_reason": "timeout", "unused": ["ask_discount", "tenure"],
    }  # fmt: skip


def test_a_lever_before_identity_is_heard_not_pulled() -> None:
    """While identifying the rep answers a lever with ask_identity: heard,
    never taken, never a rung."""
    log = Log("r7")
    _pull(log, "ask_discount", "ask_identity", None)
    log.end("abandoned")
    values = _values(log)
    assert values["rungs_reached"] == {
        "count": 0, "ladder_exhausted": False, "ladder_len": None,
    }  # fmt: skip
    assert values["levers_heard"] == {
        "count": 1, "levers": ["ask_discount"], "taken": [],
    }  # fmt: skip
    assert values["repeated_lever_no_better"] == {"count": 0, "seqs": []}


def test_no_rep_policy_is_unknown_and_no_end_leaves_the_flag_unknown() -> None:
    log = Log("r8")
    _ear(log, "ask_discount")  # heard, but no rep.policy: no world policy
    log.end("timeout")
    assert _values(log) == dict.fromkeys(NAMES)

    running = Log("r9")
    _pull(running, "ask_discount", "offer", 0)  # no session.ended yet
    values = _values(running)
    assert values["no_deal_ladder_unfinished"] is None
    assert values["rungs_reached"] == {
        "count": 1, "ladder_exhausted": False, "ladder_len": None,
    }  # fmt: skip


def _emit(log: Log, decisions: list[Decision], ear: str) -> None:
    """``SimRep._run``'s rep.policy (and rep.commit_heard) for one step."""
    for d in decisions:
        payload: P = {"from": d.from_, "to": d.to, "rung": d.rung}
        payload["intent"] = d.intent.model_dump(mode="json")
        causes = () if d.intent.kind == "offer_expired" else (ear,)
        ev = log.add("rep.policy", "world.policy", "world", payload, causes)
        if d.commit is not None:
            _commit(log, ev)


def test_the_detectors_read_the_real_policy() -> None:
    """The real Policy on a two-rung ladder: the rungs, the taken levers and
    the exhaustion read back from its rep.* events equal its own state."""
    task = load_task("cp-direct-discount")
    cp = task.counterparty
    assert len(cp.ladder) == 2
    policy = Policy(cp, {k: task.profile.facts[k] for k in cp.identity})
    log = Log("rP")
    identity = [{"key": k, "value": task.profile.facts[k]} for k in cp.identity]
    acts: list[dict[str, object]] = [
        {"act": "other"},
        {"act": "provide_fact", "facts": tuple(identity)},
        {"act": "ask_discount"},  # rung 0
        {"act": "ask_discount"},  # a repeat
        {"act": "tenure"},  # rung 1, the last
        {"act": "cite_competitor"},  # new, the ladder is spent
    ]
    for n, act in enumerate(acts):
        ear = EarAct.model_validate(act)
        _emit(log, policy.step(ear, f"u{n}", "", 1000 * n), _ear(log, ear.act))
    log.end("timeout")
    values = _values(log)
    assert values["rungs_reached"] == {
        "count": policy.rung + 1, "ladder_exhausted": True,
        "ladder_len": len(cp.ladder),
    }  # fmt: skip
    heard = values["levers_heard"]
    assert isinstance(heard, dict) and heard["taken"] == sorted(policy._levers)  # pyright: ignore[reportPrivateUsage]
    assert heard["levers"] == ["ask_discount", "cite_competitor", "tenure"]
    assert values["repeated_lever_no_better"] == {"count": 1, "seqs": [8]}
