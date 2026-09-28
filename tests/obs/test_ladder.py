"""The offer-ladder detectors (``obs.ladder``) on hand-built rep.* streams,
and against the real ``SimRep`` (scripted Ear and Mouth, the real Bus) driven
through a lever sequence."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast, get_args

from tests.env.bus_sink import BusSink
from tests.obs.bundles import Log
from tests.obs.triage_bundle import P
from tests.support.fakes import ScriptedLLM, fake_ref
from tests.support.sessions import ears

from proxyloop.contract.llm import TextRequest, ToolRequest
from proxyloop.env.counterparty.ear import Lever
from proxyloop.env.counterparty.policy import State
from proxyloop.env.counterparty.simrep import SimRep
from proxyloop.env.tasks.loader import load_task
from proxyloop.obs import detectors, ladder

NAMES = (
    "rungs_reached", "levers_heard", "repeated_lever_no_better",
    "no_deal_ladder_unfinished",
)  # fmt: skip


def _values(log: Log | BusSink) -> dict[str, object]:
    events = log.events if isinstance(log, Log) else log.bus.events
    x = detectors.Inputs(events, None, lambda _: None)
    return {name: detectors.DETECTORS[name](x) for name in NAMES}


def _ear(log: Log, act: str) -> str:
    payload: P = {"utt_id": f"u{len(log.events)}", "act": act, "args": {}}
    payload |= {"attempts": 1, "call_id": "ear:c:0"}
    return log.add("rep.ear", "world.ear", "world", payload, (log.start,))


def _policy(
    log: Log, kind: str, rung: int | None, *causes: str, move: str = "OFFER>OFFER"
) -> str:
    frm, _, to = move.partition(">")
    intent: P = {"kind": kind, "offer_ref": None, "say": [], "ask": []}
    payload: P = {"from": frm, "to": to, "intent": intent, "rung": rung}
    return log.add("rep.policy", "world.policy", "world", payload, causes)


def _pull(
    log: Log, act: str, kind: str, rung: int | None, move: str = "OFFER>OFFER"
) -> str:
    return _policy(log, kind, rung, _ear(log, act), move=move)


def _commit(log: Log, policy: str) -> None:
    heard: P = {"utt_id": "u", "offer_ref": "o1"}
    log.add("rep.commit_heard", "world.policy", "world", heard, (policy,))


def test_the_levers_are_the_ears() -> None:
    assert frozenset(get_args(Lever)) == ladder.LEVERS
    assert ladder.REACHABLE <= ladder.LEVERS


def test_the_identity_split_covers_the_policy_states() -> None:
    before, past = ladder.BEFORE_IDENTITY, ladder.PAST_IDENTITY
    assert before | past | {"TRANSFER", "ENDED"} == set(get_args(State))
    assert before.isdisjoint(past)


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
        "count": 1, "reason": "unfinished", "end_reason": "timeout",
        "unused": ["tenure"],
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
        "count": 0, "reason": "exhausted", "end_reason": "done", "unused": [],
    }  # fmt: skip


def test_a_commit_or_a_spent_ladder_is_no_unfinished_no_deal() -> None:
    committed = Log("r3")
    _commit(committed, _pull(committed, "ask_discount", "offer", 0))
    committed.end("done")
    flag = _values(committed)["no_deal_ladder_unfinished"]
    assert flag == {
        "count": 0, "reason": "committed", "end_reason": "done", "unused": ["tenure"],
    }  # fmt: skip

    spent = Log("r4")  # a one-rung ladder: the second new lever proves it
    _pull(spent, "ask_discount", "offer", 0)
    _pull(spent, "tenure", "no_better", 0)
    spent.end("timeout")
    values = _values(spent)
    assert values["rungs_reached"] == {
        "count": 1, "ladder_exhausted": True, "ladder_len": 1,
    }  # fmt: skip
    assert values["no_deal_ladder_unfinished"] == {
        "count": 0, "reason": "exhausted", "end_reason": "timeout", "unused": [],
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
        "count": 0, "reason": "all_pulled", "end_reason": "timeout", "unused": [],
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
        "count": 1, "reason": "unfinished", "end_reason": "timeout",
        "unused": ["ask_discount", "tenure"],
    }  # fmt: skip


def test_a_lever_before_identity_is_heard_not_pulled_and_no_ladder() -> None:
    """While identifying the rep answers a lever with ask_identity: heard,
    never taken, never a rung; abandoned there, the ladder never opened."""
    log = Log("r7")
    _pull(log, "ask_discount", "ask_identity", None, move="IDENTIFY>IDENTIFY")
    _policy(log, "hang_up", None, move="IDENTIFY>ENDED")  # a strike-out
    log.end("abandoned")
    values = _values(log)
    assert values["rungs_reached"] == {
        "count": 0, "ladder_exhausted": False, "ladder_len": None,
    }  # fmt: skip
    assert values["levers_heard"] == {
        "count": 1, "levers": ["ask_discount"], "taken": [],
    }  # fmt: skip
    assert values["repeated_lever_no_better"] == {"count": 0, "seqs": []}
    assert values["no_deal_ladder_unfinished"] == {
        "count": 0, "reason": "no_ladder", "end_reason": "abandoned", "unused": [],
    }  # fmt: skip


def test_a_transfer_while_identifying_is_no_ladder() -> None:
    log = Log("r11")
    _policy(log, "ask_identity", None, move="GREET>IDENTIFY")
    _policy(log, "transfer", None, move="IDENTIFY>TRANSFER")  # ask_supervisor
    log.end("done")
    assert _values(log)["no_deal_ladder_unfinished"] == {
        "count": 0, "reason": "no_ladder", "end_reason": "done", "unused": [],
    }  # fmt: skip


def test_a_lever_in_the_opening_line_is_heard_not_pulled() -> None:
    log = Log("r12")
    _pull(log, "tenure", "greet", None, move="GREET>IDENTIFY")
    _policy(log, "how_can_help", None, move="IDENTIFY>DISCOVER")
    log.end("timeout")
    values = _values(log)
    assert values["levers_heard"] == {"count": 1, "levers": ["tenure"], "taken": []}
    assert values["no_deal_ladder_unfinished"] == {
        "count": 1, "reason": "unfinished", "end_reason": "timeout",
        "unused": ["ask_discount", "tenure"],
    }  # fmt: skip


def test_a_malformed_payload_matches_nothing() -> None:
    log = Log("r13")
    ear = _ear(log, "ask_discount")
    intent: P = {"kind": ["offer"]}  # not a code: no take, no raise
    payload: P = {"from": ["OFFER"], "to": {"x": 1}, "intent": intent, "rung": None}
    log.add("rep.policy", "world.policy", "world", payload, (ear,))
    ear2 = _ear(log, ["tenure"])  # type: ignore[arg-type]
    _policy(log, "clarify", None, ear2, move="IDENTIFY>IDENTIFY")
    log.end("timeout")
    values = _values(log)
    assert values["levers_heard"] == {
        "count": 1, "levers": ["ask_discount"], "taken": [],
    }  # fmt: skip
    flag = values["no_deal_ladder_unfinished"]
    assert isinstance(flag, dict) and flag["reason"] == "no_ladder"


def test_a_lever_said_only_while_identifying_is_unused() -> None:
    log = Log("r10")
    _pull(log, "ask_discount", "ask_identity", None, move="IDENTIFY>IDENTIFY")
    _policy(log, "how_can_help", None, move="IDENTIFY>DISCOVER")  # identity passed
    log.end("timeout")
    values = _values(log)
    heard = values["levers_heard"]
    assert heard == {"count": 1, "levers": ["ask_discount"], "taken": []}
    assert values["no_deal_ladder_unfinished"] == {
        "count": 1, "reason": "unfinished", "end_reason": "timeout",
        "unused": ["ask_discount", "tenure"],
    }  # fmt: skip


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


class Echo(ScriptedLLM):
    """A Mouth that says the policy's template line (always faithful)."""

    async def _next(self, request: TextRequest | ToolRequest) -> tuple[str, int]:
        start = self._clock.monotonic_ms()
        self.calls += 1
        self._clock.advance(1)
        return request.messages[-1].content.split("Line: ", 1)[1], start


ID = {"act": "provide_fact", "facts": [
    {"key": "account.holder_name", "value": "Dana Reyes"},
    {"key": "account.last4", "value": "4821"},
]}  # fmt: skip
LINES: dict[str, dict[str, Any]] = {
    "The account holder is Dana Reyes, last four 4821.": ID,
    "Can you lower the price?": {"act": "ask_discount"},
    "Otherwise I will cancel the line.": {"act": "cancel_intent"},
    "Brightwave offers 60 dollars a month.": {
        "act": "cite_competitor", "price_usd": 60,
    },
}  # fmt: skip


class Gated(ScriptedLLM):
    """An Ear whose first call waits for ``release`` (``waiting`` set): the
    lines heard meanwhile queue behind it, whatever the machine's load."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.waiting, self.release = asyncio.Event(), asyncio.Event()

    async def _next(self, request: TextRequest | ToolRequest) -> tuple[str, int]:
        if self.calls == 0:
            self.waiting.set()
            await self.release.wait()
        return await super()._next(request)


async def _hear(
    sink: BusSink, rep: SimRep, lines: Sequence[str], t_ms: int, ear: Gated
) -> None:
    """``lines`` heard together: the first is in flight (its Ear call gated,
    on the first call only) while the rest queue behind it, so they reach the
    policy as one block."""
    heard = [sink.heard(text) for text in lines]
    say = [
        rep.on_agent_utterance(str(e.payload["utt_id"]), text, e.event_id, t_ms)
        for e, text in zip(heard, lines, strict=True)
    ]
    first = asyncio.ensure_future(say[0])
    if not ear.release.is_set():
        await ear.waiting.wait()
    rest = [asyncio.ensure_future(s) for s in say[1:]]
    for _ in range(5):
        await asyncio.sleep(0)  # each queued line is heard and waits for the turn
    ear.release.set()
    await asyncio.gather(first, *rest)


def test_the_detectors_read_the_real_simrep(tmp_path: Path) -> None:
    """The real SimRep on the two-rung ladder: identity, then the discount and
    its repeat heard as one backlog block, then cancel after loyal-1 expired
    (an uncaused offer_expired first), then a new lever past the last rung.
    Rungs, taken levers, identity and exhaustion read back from its events
    equal the policy's own state."""
    task = load_task("cp-direct-discount")
    identify, discount, cancel, compete = LINES
    sink = BusSink(tmp_path)
    script = [ears(ID), ears(LINES[discount], LINES[discount]),
              ears(LINES[cancel]), ears(LINES[compete])]  # fmt: skip
    ear = Gated(fake_ref(), script, on_record=sink.world.record)
    rep = SimRep(task, ear, Echo(fake_ref(), [], on_record=sink.world.record),
                 sink.world)  # fmt: skip
    ttl = int(1000 * task.counterparty.ladder[0].ttl_s)

    async def play() -> None:
        await _hear(sink, rep, [identify, discount, discount], 0, ear)
        await _hear(sink, rep, [cancel], ttl + 1, ear)
        await _hear(sink, rep, [compete], ttl + 2, ear)

    asyncio.run(play())
    sink.bus.emit("session.ended", "kernel", "ops", {"reason": "timeout"}, [])
    policy = rep.policy
    kinds = [detectors.as_dict(e.payload["intent"])["kind"]
             for e in sink.of("rep.policy")]  # fmt: skip
    assert kinds == ["how_can_help", "offer", "no_better", "offer_expired",
                     "final_offer", "no_better"]  # fmt: skip
    assert ear.calls == 4  # the discount and its repeat were one Ear call
    values = _values(sink)
    assert values["rungs_reached"] == {
        "count": policy.rung + 1, "ladder_exhausted": True,
        "ladder_len": len(task.counterparty.ladder),
    }  # fmt: skip
    heard = cast(dict[str, list[str]], values["levers_heard"])
    assert len(heard["taken"]) == len(policy.made())  # one offer per lever taken
    assert heard["levers"] == ["ask_discount", "cancel_intent", "cite_competitor"]
    assert values["repeated_lever_no_better"] == {
        "count": 1, "seqs": [sink.of("rep.policy")[2].seq],
    }  # fmt: skip
    # identified: the policy left identity; pulled: every lever after it
    assert policy.state in ladder.PAST_IDENTITY
    assert values["no_deal_ladder_unfinished"] == {
        "count": 0, "reason": "exhausted", "end_reason": "timeout",
        "unused": ["tenure"],
    }  # fmt: skip
