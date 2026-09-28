"""The SimRep hears its whole backlog (ADR-0021): the agent turns heard while a
rep turn is in flight make one block, classified by one Ear call with one act
per utterance, and the policy steps every act in order, exactly as it would
step them one turn at a time (the HARD CONDITION: nothing authority-bearing is
dropped). Scripted fakes, writing through the real Bus."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine, Sequence
from pathlib import Path
from typing import Any, cast, get_args

import pytest
from tests.env.bus_sink import BusSink
from tests.support.fakes import ScriptedLLM, fake_ref
from tests.support.sessions import ears

from proxyloop.contract.llm import (
    LLMCallRecord,
    LLMClient,
    ModelRef,
    TextRequest,
    ToolRequest,
    ToolResponse,
)
from proxyloop.env.counterparty import ear
from proxyloop.env.counterparty.ear import Ear, Heard
from proxyloop.env.counterparty.simrep import RepTurn, SimRep
from proxyloop.env.tasks.loader import load_task
from proxyloop.kernel.channels import Incoming, SimRepChannel

TASK = load_task("cp-direct-discount")
NAME, LAST4 = "account.holder_name", "account.last4"
Line = tuple[str, dict[str, Any]]  # what the agent said, and the Ear's act for it

ID: Line = (
    "The account holder is Dana Reyes, last four 4821.",
    {
        "act": "provide_fact",
        "facts": [
            {"key": NAME, "value": "Dana Reyes"},
            {"key": LAST4, "value": "4821"},
        ],
    },
)
NAME_ONLY: Line = (
    "The account holder is Dana Reyes.",
    {"act": "provide_fact", "facts": [{"key": NAME, "value": "Dana Reyes"}]},
)
OTHER: Line = ("Hmm, let me think.", {"act": "other"})
DISCOUNT: Line = ("Can you lower the price?", {"act": "ask_discount"})
COMPETITOR: Line = (
    "Brightwave offers 60 dollars a month.",
    {"act": "cite_competitor", "price_usd": 60},
)
CANCEL: Line = ("Otherwise I will cancel the line.", {"act": "cancel_intent"})
READBACK: Line = (
    "Could you read back every term of that offer?",
    {"act": "ask_readback"},
)
ACCEPT1: Line = (  # by name: loyal-1 must be made before its Ear call
    "We accept loyal-1 at $75.00 a month.",
    {"act": "accept", "offer_ref": "loyal-1", "price_usd": 75},
)
YES: Line = ("Yes, we accept.", {"act": "accept"})
ACCEPT68: Line = (  # loyal-2's price; loyal-2 is unlocked in the same block
    "We accept, at $68 a month.",
    {"act": "accept", "price_usd": 68},
)
DECLINE: Line = ("No, thank you.", {"act": "decline"})
REFUSE: Line = ("I'd rather not say.", {"act": "refuse_fact"})
HOLD: Line = ("One moment please.", {"act": "hold_request"})
SUPERVISOR: Line = ("Can I talk to a supervisor?", {"act": "ask_supervisor"})
COMPOUND = (  # the H2 risk: a read-back ask and a best-and-final ask in one
    "Could you please read back every term of that offer? "
    "And is that your best and final offer?"
)


class Held:
    """An Ear client whose call number ``hold`` waits for ``release``: the
    turns heard meanwhile queue behind it. It keeps every request it got."""

    def __init__(self, inner: ScriptedLLM, hold: int | None) -> None:
        self._inner, self._hold = inner, hold
        self.requests: list[ToolRequest] = []
        self.waiting, self.release = asyncio.Event(), asyncio.Event()

    @property
    def ref(self) -> ModelRef:
        return self._inner.ref

    def stream_text(self, request: TextRequest) -> AsyncIterator[str | LLMCallRecord]:
        raise AssertionError("the Ear only calls tools")

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        self.requests.append(request)
        if len(self.requests) - 1 == self._hold:
            self.waiting.set()
            await self.release.wait()
        return await self._inner.chat_tools(request)

    def heard(self, n: int) -> str:
        """What the Ear's call ``n`` was told the caller said."""
        return self.requests[n].messages[-1].content.split("The caller said:", 1)[1]


class Echo(ScriptedLLM):
    """A Mouth that says the policy's template line (always faithful)."""

    async def _next(self, request: TextRequest | ToolRequest) -> tuple[str, int]:
        start = self._clock.monotonic_ms()
        self.calls += 1
        self._clock.advance(1)
        return request.messages[-1].content.split("Line: ", 1)[1], start


class Play:
    """One SimRep over ``lines``: the first ``alone`` lines are heard one turn
    at a time; then one line is in flight (its Ear call held) and the rest are
    heard while it is, so they queue behind it; then each of ``after`` alone.
    ``alone = len(lines)``: every line alone (the sequential reference)."""

    def __init__(
        self,
        tmp_path: Path,
        lines: Sequence[Line],
        alone: int,
        gap_ms: int = 1000,
        after: Sequence[Line] = (),
    ) -> None:
        self.sink = sink = BusSink(tmp_path)
        items = [act for _, act in lines]
        script = [ears(a) for a in items[: alone + 1]]
        if alone + 1 < len(items):
            script.append(ears(*items[alone + 1 :]))
        script += [ears(act) for _, act in after]
        hold = alone if alone < len(lines) else None
        self.ear = Held(sink.llm(*script), hold)
        self.mouth = Echo(fake_ref(), [], on_record=sink.world.record)
        self.rep = SimRep(TASK, cast(LLMClient, self.ear), self.mouth, sink.world)
        self.lines = [*lines, *after]
        self.heard = [sink.heard(text) for text, _ in self.lines]  # in order
        self.alone, self.gap, self.block = alone, gap_ms, len(lines)
        self.turns: list[RepTurn] = []

    def utt(self, i: int) -> str:
        return str(self.heard[i].payload["utt_id"])

    def _say(self, i: int) -> Coroutine[Any, Any, RepTurn]:
        return self.rep.on_agent_utterance(
            self.utt(i), self.lines[i][0], self.heard[i].event_id, i * self.gap
        )

    async def _run(self) -> list[RepTurn]:
        turns = [await self._say(i) for i in range(min(self.alone, self.block))]
        if self.alone < self.block:
            first = asyncio.ensure_future(self._say(self.alone))
            await self.ear.waiting.wait()
            rest = [
                asyncio.ensure_future(self._say(i))
                for i in range(self.alone + 1, self.block)
            ]
            for _ in range(5):
                await asyncio.sleep(0)  # each queued turn is heard and waits
            self.ear.release.set()
            turns += await asyncio.gather(first, *rest)
        return turns + [await self._say(i) for i in range(self.block, len(self.lines))]

    def run(self) -> list[RepTurn]:
        self.turns = asyncio.run(self._run())
        return self.turns

    def of(self, type_: str) -> list[Any]:
        return self.sink.of(type_)

    def snapshot(self) -> dict[str, object]:
        """The policy state, every decision, commit and ledger write, and what
        the kernel gets: its ``chan.strike`` count and how the call ends."""
        state: dict[str, object] = {
            k: v for k, v in vars(self.rep.policy).items() if k != "ledger"
        }
        decisions = [
            (e.payload["from"], e.payload["to"], e.payload["intent"])
            for e in self.of("rep.policy")
        ]
        strikes, end = kernel_view(self.turns)
        assert strikes == self.rep.policy.strikes  # exact, not one per turn
        return state | {
            "decisions": decisions,
            "commits": [e.payload for e in self.of("rep.commit_heard")],
            "ledger": [e.payload for e in self.of("ledger.write")],
            "strikes": self.rep.policy.strikes,
            "chan.strike": strikes,
            "end": end,
        }


def incoming(turn: RepTurn, kind: str = "heard") -> Incoming | None:
    """What ``SimRepChannel`` queues for the kernel from one rep turn."""

    class Rep:
        async def on_agent_utterance(self, *args: object) -> RepTurn:
            return turn

        async def tick(self, t_ms: int) -> RepTurn:
            return turn

    channel = SimRepChannel(cast(SimRep, Rep()))
    run = channel.send("x", "u", "c", 0) if kind == "heard" else channel.tick(0)
    asyncio.run(run)
    return None if channel.incoming.empty() else channel.incoming.get_nowait()


def kernel_view(turns: Sequence[RepTurn]) -> tuple[int, str]:
    """The kernel's outcome of a run's rep turns: one ``chan.strike`` per
    strike (kernel/session.py ``_turn``), and the first end, the one it acts on."""
    queued = [inc for t in turns if (inc := incoming(t)) is not None]
    return sum(i.strikes for i in queued), next((i.end for i in queued if i.end), "")


def _both(
    tmp_path: Path, lines: Sequence[Line], alone: int, gap_ms: int = 1000
) -> tuple[Play, Play]:
    """The same lines one turn at a time, and with ``lines[alone + 1:]`` queued."""
    (tmp_path / "seq").mkdir()
    (tmp_path / "block").mkdir()
    seq = Play(tmp_path / "seq", lines, len(lines), gap_ms)
    block = Play(tmp_path / "block", lines, alone, gap_ms)
    seq.run()
    block.run()
    return seq, block


def _intents(play: Play, type_: str) -> list[str]:
    return [cast(dict[str, str], e.payload["intent"])["kind"] for e in play.of(type_)]


def test_t1_the_queued_turns_are_one_ear_call_and_the_read_back_is_answered(
    tmp_path: Path,
) -> None:
    play = Play(tmp_path, [ID, DISCOUNT, DISCOUNT, READBACK], alone=1)
    turns = play.run()
    assert len(play.ear.requests) == 3  # the identity turn, turn 1, turns 2 and 3
    block = play.ear.heard(2)
    assert block == f"\n1. {DISCOUNT[0]}\n2. {READBACK[0]}"
    assert _intents(play, "rep.policy") == [
        "how_can_help",
        "offer",
        "no_better",
        "readback",
    ]
    assert turns[3] == RepTurn((), 0, "")  # already heard with turn 2
    *_, answer = turns[2].lines
    assert answer[0].startswith("Here are the full terms:")
    assert "fee activation: 20.00" in answer[0]  # the hidden term, on read-back


def test_t1_one_heard_turn_reads_as_a_block_of_one(tmp_path: Path) -> None:
    play = Play(tmp_path, [DISCOUNT], alone=1)
    play.run()
    assert play.ear.heard(0) == f"\n1. {DISCOUNT[0]}"


def test_t2_a_queued_accept_is_committed_before_the_read_back(
    tmp_path: Path,
) -> None:
    lines = [ID, DISCOUNT, OTHER, ACCEPT1, READBACK]
    seq, block = _both(tmp_path, lines, alone=2)
    assert len(block.ear.requests) == 4  # the accept and the read-back: one call
    (commit,) = block.of("rep.commit_heard")
    (write,) = block.of("ledger.write")
    accept_ear = next(
        e for e in block.of("rep.ear") if e.payload["utt_id"] == block.utt(3)
    )
    policy = block.of("rep.policy")[-1]
    assert commit.payload == {"utt_id": block.utt(3), "offer_ref": "loyal-1"}
    assert commit.cause_ids == (accept_ear.event_id, policy.event_id)
    assert write.cause_ids == (commit.event_id,)
    assert block.rep.policy.state == "CONFIRMED" and block.turns[3].end == "closed"
    assert block.turns[4] == RepTurn((), 0, "")  # the call was already over
    assert block.snapshot() == seq.snapshot()


def test_t3_a_queued_disclosure_is_verified_then_the_discount_handled(
    tmp_path: Path,
) -> None:
    seq, block = _both(tmp_path, [OTHER, ID, DISCOUNT], alone=0)
    assert len(block.ear.requests) == 2
    policy = block.rep.policy
    assert policy.state == "OFFER" and "loyal-1" in policy.offers
    assert policy.strikes == 0
    assert block.snapshot() == seq.snapshot()


def test_t4_a_queued_decline_and_cancellation_are_stepped(tmp_path: Path) -> None:
    lines = [ID, DISCOUNT, OTHER, YES, DECLINE, CANCEL, READBACK]
    seq, block = _both(tmp_path, lines, alone=2)
    assert len(block.ear.requests) == 4
    assert _intents(block, "rep.policy")[-4:] == [
        "confirm_accept",
        "ack_decline",
        "final_offer",
        "readback",
    ]
    policy = block.rep.policy
    assert policy.state == "FINAL" and policy.rung == 1
    assert block.snapshot() == seq.snapshot()


EQUIVALENT: list[tuple[str, list[Line], int, int]] = [
    ("identify with strikes", [OTHER, NAME_ONLY, DISCOUNT, REFUSE], 0, 1000),
    ("identity strike-out", [OTHER, REFUSE, REFUSE, REFUSE, DISCOUNT], 0, 1000),
    ("identify then levers", [ID, DISCOUNT, CANCEL, READBACK], 0, 1000),
    ("disclosure queued", [OTHER, ID, DISCOUNT], 0, 1000),
    ("repeated asks", [ID, DISCOUNT, DISCOUNT, DISCOUNT, READBACK], 1, 1000),
    ("accept by name", [ID, DISCOUNT, READBACK, ACCEPT1, READBACK], 2, 1000),
    ("confirm then yes", [ID, DISCOUNT, OTHER, YES, YES, DISCOUNT], 2, 1000),
    ("decline, accept", [ID, DISCOUNT, OTHER, YES, DECLINE, YES, YES], 2, 1000),
    ("holds", [ID, HOLD, HOLD, OTHER, HOLD, DISCOUNT], 1, 1000),
    ("two levers", [ID, OTHER, COMPETITOR, DISCOUNT, DISCOUNT, READBACK], 1, 1000),
    ("an expiry inside", [ID, DISCOUNT, OTHER, READBACK, DISCOUNT], 2, 100_000),
    ("a transfer ends it", [ID, DISCOUNT, OTHER, SUPERVISOR, CANCEL], 2, 1000),
    ("a strike, then a transfer", [OTHER, REFUSE, SUPERVISOR], 0, 1000),
    ("two strikes in one block", [OTHER, REFUSE, REFUSE, ID], 0, 1000),
    ("three strikes in one block", [OTHER, REFUSE, REFUSE, REFUSE], 0, 1000),
]


@pytest.mark.parametrize(
    ("lines", "alone", "gap_ms"),
    [
        pytest.param(lines, alone, gap, id=name)
        for name, lines, alone, gap in EQUIVALENT
    ],
)
def test_t5_coalesced_stepping_equals_stepping_each_turn_alone(
    tmp_path: Path, lines: list[Line], alone: int, gap_ms: int
) -> None:
    seq, block = _both(tmp_path, lines, alone, gap_ms)
    assert len(block.ear.requests) <= alone + 2  # the queued lines: one call
    assert block.snapshot() == seq.snapshot()
    heard = [e.payload["utt_id"] for e in block.of("rep.ear")]
    one_by_one = [e.payload["utt_id"] for e in seq.of("rep.ear")]
    assert heard[: len(one_by_one)] == one_by_one  # the same labels, in order;
    # a queued line after the call ended is labelled too, but never stepped
    assert heard == one_by_one or block.rep.policy.done


def test_t5_a_strike_then_a_transfer_closes_the_call_it_does_not_hang_up(
    tmp_path: Path,
) -> None:
    seq, block = _both(tmp_path, [OTHER, REFUSE, SUPERVISOR], alone=0)
    assert [(t.strikes, t.end) for t in seq.turns] == [(0, ""), (1, ""), (0, "closed")]
    assert [(t.strikes, t.end) for t in block.turns] == [
        (0, ""),
        (1, "closed"),
        (0, ""),
    ]
    inc = incoming(block.turns[1])
    assert inc is not None
    assert (inc.strike, inc.strikes, inc.strike_kind, inc.end) == (
        True,
        1,
        "identity",
        "closed",
    )  # a transfer: chan.closed, not ABANDONED


@pytest.mark.parametrize("k", [2, 3])
def test_t5_k_strikes_in_one_block_are_k_strikes_for_the_kernel(
    tmp_path: Path, k: int
) -> None:
    seq, block = _both(tmp_path, [OTHER, *[REFUSE] * k, ID], alone=0)
    (turn,) = [t for t in block.turns if t.strikes]
    assert turn.strikes == k and turn.end == ("hangup" if k == 3 else "")
    inc = incoming(turn)
    assert inc is not None and inc.strikes == k and inc.end == turn.end
    assert kernel_view(block.turns) == kernel_view(seq.turns) == (k, turn.end)


def test_t5_a_timer_strike_is_one_strike_and_a_timer_strike_out_hangs_up(
    tmp_path: Path,
) -> None:
    play = Play(tmp_path, [ID], alone=1)
    play.run()
    channel = SimRepChannel(play.rep)
    silence = int(TASK.counterparty.patience.silence_s * 1000)

    async def ticks() -> list[Incoming]:
        out: list[Incoming] = []
        t = 1000
        for _ in range(TASK.counterparty.patience.strikes):
            channel.floor(True, t)
            t += silence
            await channel.tick(t)
            out.append(channel.incoming.get_nowait())
        return out

    got = [(i.strikes, i.strike_kind, i.end) for i in asyncio.run(ticks())]
    assert got == [(1, "timer", ""), (1, "timer", ""), (1, "timer", "hangup")]


def test_t5_an_accept_of_an_offer_unlocked_in_the_same_block_is_read_back(
    tmp_path: Path,
) -> None:
    """ADR-0021 (ruling 1): the accept was said before the caller could hear
    the offer its block unlocked, so it does not commit; the rep reads the
    terms back and asks to confirm, and a following confirm commits."""
    lines = [ID, DISCOUNT, OTHER, CANCEL, ACCEPT68]
    play = Play(tmp_path, lines, alone=2, after=[YES])
    turns = play.run()
    assert len(play.ear.requests) == 5  # ID, DISCOUNT, OTHER, the block, YES
    assert _intents(play, "rep.policy")[-3:] == [
        "final_offer",
        "confirm_accept",
        "confirmed",
    ]
    assert turns[3].end == "" and not turns[3].strikes
    *_, confirm = turns[3].lines
    assert confirm[0].startswith("To confirm, do you accept these terms?")
    assert "fee activation: 20.00" in confirm[0]  # every term, read back
    yes_ear = next(e for e in play.of("rep.ear") if e.payload["utt_id"] == play.utt(5))
    (commit,) = play.of("rep.commit_heard")
    (write,) = play.of("ledger.write")
    assert commit.payload == {"utt_id": play.utt(5), "offer_ref": "loyal-2"}
    assert commit.cause_ids[0] == yes_ear.event_id
    assert write.cause_ids == (commit.event_id,)
    assert turns[5].end == "closed"


def test_t6_equal_decisions_in_a_row_are_voiced_once(tmp_path: Path) -> None:
    lines = [ID, DISCOUNT, CANCEL, OTHER, *[DISCOUNT] * 5]
    play = Play(tmp_path, lines, alone=3)
    turns = play.run()
    assert _intents(play, "rep.policy")[-5:] == ["no_better"] * 5
    assert _intents(play, "rep.mouth")[-2:] == ["clarify", "no_better"]
    assert len(turns[4].lines) == 1
    last = play.of("rep.policy")[-1]  # the line answers the last of the run
    assert play.of("rep.mouth")[-1].cause_ids[0] == last.event_id


def test_t6_a_commit_is_always_voiced(tmp_path: Path) -> None:
    lines = [ID, DISCOUNT, OTHER, READBACK, READBACK, ACCEPT1]
    play = Play(tmp_path, lines, alone=2)
    turns = play.run()
    assert _intents(play, "rep.mouth")[-2:] == ["readback", "confirmed"]
    confirmation = str(play.of("ledger.write")[0].payload["confirmation_id"])
    assert confirmation in turns[3].lines[-1][0]


def test_t7_one_rep_ear_per_utterance_names_the_block(tmp_path: Path) -> None:
    play = Play(tmp_path, [ID, DISCOUNT, DISCOUNT, READBACK], alone=1)
    play.run()
    calls = play.of("llm.call")
    ear_calls = [e for e in calls if e.actor == "world.ear"]
    *_, two, three = play.of("rep.ear")
    block = [play.utt(2), play.utt(3)]
    for rep_ear, i in ((two, 2), (three, 3)):
        assert rep_ear.payload["utt_id"] == play.utt(i)
        assert rep_ear.payload["heard_utt_ids"] == block
        assert rep_ear.cause_ids == (play.heard[i].event_id, ear_calls[-1].event_id)
        assert rep_ear.payload["call_id"] == ear_calls[-1].payload["call_id"]
    assert (two.payload["act"], three.payload["act"]) == (
        "ask_discount",
        "ask_readback",
    )
    first = play.of("rep.ear")[1]
    assert first.payload["heard_utt_ids"] == [play.utt(1)]


def test_t8_a_compound_ask_labelled_read_back_gets_the_terms(tmp_path: Path) -> None:
    play = Play(tmp_path, [ID, DISCOUNT, (COMPOUND, {"act": "ask_readback"})], 3)
    turns = play.run()
    system = play.ear.requests[-1].messages[0].content
    assert (
        "If one utterance does several things, its act is the first of them in "
        "this order: accept (only of an offer you made that is still open), "
        "decline, provide_fact, ask_readback, then ask_discount, "
        "cite_competitor, cancel_intent, tenure, then the rest."
    ) in system
    assert system == ear.SYSTEM.format(company=TASK.counterparty.company)
    intent = cast(dict[str, Any], play.of("rep.policy")[-1].payload["intent"])
    assert intent["kind"] == "readback"
    assert ["fee:activation", "20.00"] in intent["say"]
    assert turns[2].lines[0][0].startswith("Here are the full terms:")


FACTS = [{"key": NAME, "value": "Dana Reyes"}, {"key": LAST4, "value": "4821"}]


@pytest.mark.parametrize(
    ("texts", "wrong", "right"),
    [
        pytest.param(
            ["Dana Reyes, last four 4821.", "Can you lower the price?"],
            [{"act": "other"}, {"act": "provide_fact", "facts": FACTS}],
            [{"act": "provide_fact", "facts": FACTS}, {"act": "ask_discount"}],
            id="facts said in another utterance",
        ),
        pytest.param(
            ["Brightwave offers 60 dollars a month.", "Can you lower the price?"],
            [{"act": "ask_discount"}, {"act": "cite_competitor", "price_usd": 60}],
            [{"act": "cite_competitor", "price_usd": 60}, {"act": "ask_discount"}],
            id="a price said in another utterance",
        ),
    ],
)
def test_f4_each_act_is_checked_against_its_own_utterance(
    tmp_path: Path,
    texts: list[str],
    wrong: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> None:
    """Checking against the block's joined text would take ``wrong``."""
    sink = BusSink(tmp_path)
    block = [
        Heard(str(e.payload["utt_id"]), text, e.event_id, 0)
        for text, e in ((t, sink.heard(t)) for t in texts)
    ]
    cp = TASK.counterparty
    listener = Ear(
        sink.llm(ears(*wrong), ears(*right)), sink.world, cp.company, cp.identity
    )
    out = asyncio.run(listener.classify(block, {}, ()))
    assert [a.act for a, _ in out] == [item["act"] for item in right]
    assert [e.payload["attempts"] for e in sink.of("rep.ear")] == [2, 2]


def _act_enum(request: ToolRequest) -> list[str]:
    params = cast(dict[str, Any], request.tools[0].parameters)
    return list(params["properties"]["acts"]["items"]["properties"]["act"]["enum"])


def test_f7_the_ear_may_say_accept_only_while_an_offer_is_open(
    tmp_path: Path,
) -> None:
    play = Play(tmp_path, [OTHER, ID, DISCOUNT, READBACK], alone=4)
    play.run()
    acts = list(get_args(ear.Act))
    without = [a for a in acts if a != "accept"]
    assert [_act_enum(r) for r in play.ear.requests] == [
        without,  # GREET
        without,  # IDENTIFY
        without,  # DISCOVER: no offer made yet
        acts,  # loyal-1 is open
    ]
    prompts = [r.messages[-1].content for r in play.ear.requests]
    assert prompts[2].startswith("Offers you made: none\n")
    assert prompts[3].startswith(
        "Offers you made: loyal-1 (open): monthly_price 75.00, term_months 12\n"
    )
    system = play.ear.requests[0].messages[0].content
    assert "accept (an offer you made that is still open:" in system


def test_f7_an_accept_with_no_open_offer_is_regenerated_and_the_facts_verified(
    tmp_path: Path,
) -> None:
    """ "Sure, yes, it's Dana Reyes, 4821" while identifying is a disclosure:
    no offer is open, so an accept is invalid (a counted regeneration) and
    the facts are verified, with no identity strike."""
    sink = BusSink(tmp_path)
    said = "Sure, yes, it's Dana Reyes, 4821."
    script = [ears(OTHER[1]), ears({"act": "accept"})]
    script.append(ears({"act": "provide_fact", "facts": FACTS}))
    mouth = Echo(fake_ref(), [], on_record=sink.world.record)
    rep = SimRep(TASK, sink.llm(*script), mouth, sink.world)
    for i, text in enumerate([OTHER[0], said]):
        e = sink.heard(text)
        asyncio.run(
            rep.on_agent_utterance(str(e.payload["utt_id"]), text, e.event_id, i)
        )
    *_, disclosed = sink.of("rep.ear")
    assert (disclosed.payload["act"], disclosed.payload["attempts"]) == (
        "provide_fact",
        2,
    )
    assert rep.policy.state == "DISCOVER" and rep.policy.strikes == 0
