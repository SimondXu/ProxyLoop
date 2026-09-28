"""A verbatim line queued while FastC holds the floor (S1-SYS-56, run 45d7ed
seq 502). There the rep's Ear lagged FastC by 1 to 4 lines: a rep turn was
pending every time FastC's line ended, and FastC's next line made the rep
compose again, so the decline starved. Now FastC starts no new turn while a
verbatim line waits for the floor: the rep's backlog drains and the line takes
the floor through the unchanged partner-turn fence (S1-SYS-23) and
revalidation. Negatives: a rep turn begun, queued or composed still goes
first, and an accept is revalidated after it takes the floor."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest
from tests.concurrency.harness import LONG, Sim, granted
from tests.concurrency.test_cases import arun
from tests.support.sessions import ear

from proxyloop.contract.events import Event
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.tasks.schema import Patience
from proxyloop.evidence.check import check_path
from proxyloop.kernel.channels import Channel, Incoming
from proxyloop.kernel.speaker import speech_s

ELSE = "Anything else?"
REPLY = "Sorry, one more thing."
BEST = "That is our best offer."
LAG_MS = 14_000  # the rep's turn: Ear and Mouth, one heard line at a time
FAST_MS = round(1000 * speech_s(LONG))  # each FastC turn: ten seconds
SILENCE_MS = round(1000 * Patience.model_fields["silence_s"].default)
GEN_MS = 1_000  # a fresh FastC generation (the fakes take a tick; S1-SYS-59)


class HearingRep(Channel):
    """Busy from each send until ``heard`` is set (it is, unless the test
    clears it); ``answer`` is queued in the send, as the agent's line ends."""

    def __init__(self) -> None:
        super().__init__()
        self.heard = asyncio.Event()
        self.heard.set()
        self.answer: str | None = None

    def send(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, text: str | None, utt_id: str, cause: str, t_ms: int
    ) -> Coroutine[Any, Any, None]:
        self.composing(1)
        if text and self.answer is not None:
            self.incoming.put_nowait(Incoming(((self.answer, None),)))
            self.answer = None

        async def hear() -> None:
            try:
                await self.heard.wait()
            finally:
                self.composing(-1)

        return hear()


class LaggingRep(Channel):
    """As ``SimRepChannel`` with a slow Ear (45d7ed): busy from each send, it
    hears the agent's turns one at a time, ``LAG_MS`` each, and answers each
    with BEST. Silent until ``sleep`` is set; ``backlog``: turns not yet
    answered."""

    def __init__(self) -> None:
        super().__init__()
        self.sleep: Callable[[float], Awaitable[None]] | None = None
        self.backlog = 0
        self._turn = asyncio.Lock()

    def send(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, text: str | None, utt_id: str, cause: str, t_ms: int
    ) -> Coroutine[Any, Any, None]:
        sleep = self.sleep
        if sleep is None or not text:
            return super().send(text, utt_id, cause, t_ms)
        self.composing(1)
        self.backlog += 1

        async def hear() -> None:
            try:
                async with self._turn:
                    await sleep(LAG_MS / 1000)
                    self.incoming.put_nowait(Incoming(((BEST, None),)))
            finally:
                self.backlog -= 1
                self.composing(-1)

        return hear()


async def _fastc_holds_the_floor(sim: Sim, accept: bool = True) -> Event:
    """FastC answers the rep with ten seconds of speech; the rep is idle."""
    await sim.start()
    if accept:
        await granted(sim)
    else:
        await sim.offer()
    for _ in range(60):  # FastC has answered the offer's lines
        await sim.vt.run_for(1_000)
        if not sim.k.speakers["cp"].speaking:
            break
    sim.rep_says(ELSE)
    await sim.vt.run_for(500)
    assert sim.k.speakers["cp"].speaking and not sim.rep.busy
    (said,) = sim.of("utt.final", text=ELSE)
    fast = sim.of("fast.sentence", lane="cp")[-1]
    assert fast.seq > said.seq  # FastC's answer to it
    return fast


def _heard(sim: Sim, line: Event) -> Event:
    (e,) = sim.of("utt.delivered", utt_id=line.payload["utt_id"])
    return e


def _ends(sim: Sim) -> list[Event]:  # of the accept or decline line
    kinds = ("accept", "decline")
    lines = {e.event_id for k in kinds for e in sim.of("speak.verbatim", kind=k)}
    ends = sim.of("speak.released") + sim.of("speak.revoked")
    return [e for e in ends if e.cause_ids[0] in lines]


def _said(sim: Sim, kind: str) -> Event:
    (e,) = sim.of("speak.verbatim", kind=kind)
    return e


async def _fastc_resumes(sim: Sim, released: Event) -> Event:
    """FastC's first line heard after the verbatim line ``released``: it ends
    no later than that line's speech plus one FastC generation and line after
    the release (the end of FastC's pause; a turn held behind the line is
    stale and generated again, S1-SYS-59)."""
    (said,) = [e for e in sim.events if e.event_id == released.cause_ids[0]]
    line_ms = round(1000 * speech_s(str(said.payload["text"])))
    bound = released.t_ms + line_ms + GEN_MS + FAST_MS
    await sim.vt.run_for(bound - sim.vt.monotonic_ms())
    fast = [
        e
        for e in sim.of("utt.delivered", lane="cp")
        if e.seq > released.seq and str(e.payload["utt_id"]).startswith("cp-g")
    ]
    assert fast, f"FastC is still silent at {bound} ms"
    return fast[0]


@pytest.mark.parametrize("kind", ["decline", "accept"])
def test_a_verbatim_queued_while_fastc_holds_the_floor_is_released(
    tmp_path: Path, kind: str
) -> None:
    """The rep is idle but for hearing FastC's line: the line takes the floor
    once the rep has heard it, and FastC's next turn waits for it."""

    async def case() -> None:
        rep = HearingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        fast = await _fastc_holds_the_floor(sim, accept=kind == "accept")
        rep.heard.clear()  # from here the rep is still hearing FastC's line
        rep.answer = REPLY  # and answers it: FastC would speak again
        tool = "accept_offer" if kind == "accept" else "decline_offer"
        out = sim.act({"tool": tool, "offer_ref": "o1"})
        assert "queued" in out[0], out
        await sim.vt.run_for(15_000)
        heard = _heard(sim, fast)
        assert _ends(sim) == [] and rep.busy  # the rep hears FastC's line
        (said,) = sim.of("utt.final", text=REPLY)
        rep.heard.set()
        await sim.vt.run_for(100)
        (released,) = _ends(sim)
        assert released.type == "speak.released"
        assert released.seq > said.seq > heard.seq
        resumed = await _fastc_resumes(sim, released)  # the line, then FastC
        (line,) = sim.of("utt.delivered", utt_id=f"{kind}-{_said(sim, kind).seq}")
        assert line.payload["interrupted"] is False
        after = [e for e in sim.of("fast.sentence", lane="cp") if e.seq > said.seq]
        assert after and not any(_heard_before(sim, e, line.seq) for e in after)
        assert any(_heard_before(sim, e, resumed.seq + 1) for e in after)
        if kind == "accept":
            assert sim.of("status.changed", status="COMMITTED")
        await sim.stop()

    arun(case())


@pytest.mark.parametrize("partner", ["begun", "queued", "composed"])
def test_an_accept_still_waits_for_a_pending_rep_turn(
    tmp_path: Path, partner: str
) -> None:
    """begun: the rep's line cuts FastC's; queued: it is queued as FastC's
    line ends; composed: the rep composes past it. No floor for the accept
    until the rep's turn has landed (or ended)."""

    async def case() -> None:
        rep = HearingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        fast = await _fastc_holds_the_floor(sim)
        if partner == "composed":
            sim.rep_composes()
        elif partner == "queued":
            rep.answer = REPLY
        assert sim.accept().startswith("accept_offer: accept line queued")
        if partner == "begun":
            await sim.vt.run_for(1_000)
            sim.rep_says(REPLY)
        await sim.vt.run_for(12_000)
        assert sim.of("utt.delivered", utt_id=fast.payload["utt_id"])
        if partner == "composed":
            assert _ends(sim) == [] and sim.rep.busy
            sim.rep_done(REPLY)
            await sim.vt.run_for(100)
        (said,) = sim.of("utt.final", text=REPLY)
        assert all(e.seq > said.seq for e in _ends(sim)), _ends(sim)
        await sim.stop()

    arun(case())


def test_the_accept_is_revalidated_after_it_takes_the_floor(tmp_path: Path) -> None:
    """An epoch bump while the accept waits for the floor: it is revalidated
    there and revoked ``epoch``, never released."""

    async def case() -> None:
        rep = HearingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        fast = await _fastc_holds_the_floor(sim)
        rep.heard.clear()
        assert sim.accept().startswith("accept_offer: accept line queued")
        await sim.vt.run_for(1_000)
        sim.revoke()
        await sim.vt.run_for(12_000)
        heard = _heard(sim, fast)
        assert _ends(sim) == []  # still waiting: the rep hears FastC's line
        rep.heard.set()
        await sim.vt.run_for(100)
        (revoked,) = _ends(sim)
        assert revoked.type == "speak.revoked" and revoked.payload["reason"] == "epoch"
        assert revoked.seq > heard.seq
        await sim.stop()

    arun(case())


async def _chatter(sim: Sim, rep: LaggingRep, accept: bool = False) -> None:
    """FastC and a lagging rep talk past each other (45d7ed): a second rep
    line while the rep still hears FastC's first answer puts the rep's Ear a
    line behind, and each reply it lands makes FastC speak again."""
    await sim.start()
    await (granted(sim) if accept else sim.offer())
    await sim.vt.run_for(30_000)  # FastC has answered the offer's lines
    rep.sleep = sim.vt.sleep
    sim.rep_says(ELSE)
    await sim.vt.run_for(FAST_MS + 2_000)
    assert rep.busy and not sim.k.speakers["cp"].speaking
    sim.rep_says(ELSE)
    await sim.vt.run_for(60_000)


def _silent_ms(sim: Sim) -> int:
    """The floor is free and the rep idle: silence its policy would time."""
    rep, speaker = sim.rep, sim.k.speakers["cp"]
    free = not (speaker.speaking or rep.busy or not rep.incoming.empty())
    return 100 if free else 0


def test_a_decline_queued_while_the_rep_lags_is_released(tmp_path: Path) -> None:
    """The 45d7ed shape: the decline takes the floor once FastC's turn in
    progress ends and the rep has answered the turns it had heard, within
    FAST_MS + (backlog + 1) x LAG_MS; FastC starts no turn meanwhile, and the floor
    is never free and silent for long enough to strike."""

    async def case() -> None:
        rep = LaggingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        await _chatter(sim, rep)
        backlog, queued_at = rep.backlog, sim.vt.monotonic_ms()
        assert 1 <= backlog <= 4 and rep.busy
        started = {e.payload["gen_id"] for e in sim.of("fast.sentence", lane="cp")}
        out = sim.act({"tool": "decline_offer", "offer_ref": "o1"})
        assert "queued" in out[0], out
        silent = most = 0
        for _ in range(1_000):  # 100 s in 100 ms steps
            if _ends(sim):
                break
            silent = silent + _silent_ms(sim) if _silent_ms(sim) else 0
            most = max(most, silent)
            await sim.vt.run_for(100)
        (released,) = _ends(sim)
        assert released.type == "speak.released"
        waited = released.t_ms - queued_at
        assert waited <= FAST_MS + (backlog + 1) * LAG_MS, (waited, backlog)
        assert most < SILENCE_MS, most  # no silence strike (policy.tick)
        before = [
            e
            for e in sim.of("fast.sentence", lane="cp")
            if e.payload["gen_id"] not in started
            and _heard_before(sim, e, released.seq)
        ]
        assert before == []  # FastC started no turn while the decline waited
        await sim.stop()

    arun(case())


def _heard_before(sim: Sim, line: Event, seq: int) -> bool:
    heard = sim.of("utt.delivered", utt_id=line.payload["utt_id"])
    return bool(heard) and heard[0].seq < seq


def test_fastc_is_held_silent_at_most_the_rep_s_backlog(tmp_path: Path) -> None:
    """The bound on FastC's pause: from the end of FastC's last line before
    the decline to the decline taking the floor, at most the rep's turns
    pending then (the backlog when the decline was queued, plus FastC's line
    in progress) times the rep's turn; and the decline takes the floor the
    instant the rep's last answer lands."""

    async def case() -> None:
        rep = LaggingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        await _chatter(sim, rep)
        backlog = rep.backlog
        sim.act({"tool": "decline_offer", "offer_ref": "o1"})
        await sim.vt.run_for(FAST_MS + (backlog + 1) * LAG_MS)
        (released,) = _ends(sim)
        fast = [e for e in sim.of("utt.delivered", lane="cp") if e.seq < released.seq]
        paused = released.t_ms - fast[-1].t_ms
        assert 0 < paused <= (backlog + 1) * LAG_MS, (paused, backlog)
        last = [e for e in sim.of("utt.final", text=BEST) if e.seq < released.seq]
        assert released.t_ms == last[-1].t_ms  # no free floor in between
        await _fastc_resumes(sim, released)  # and FastC's pause ends
        await sim.stop()

    arun(case())


def test_an_accept_queued_while_the_rep_lags_ends(tmp_path: Path) -> None:
    """An accept in the 45d7ed shape takes the floor (on main it never did:
    the case stayed on ``accept_in_flight``) and ends in exactly one terminal
    event after revalidation. (Today that is ``expired``: while the partner
    fence its rep lines raise holds it (S1-SYS-23, unchanged), FastC speaks,
    so its capability runs out first; fail closed.)"""

    async def case() -> None:
        rep = LaggingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        await _chatter(sim, rep, accept=True)
        assert sim.accept().startswith("accept_offer: accept line queued")
        await sim.vt.run_for(60_000)
        (end,) = _ends(sim)
        assert end.seq > _said(sim, "accept").seq
        await sim.stop()

    arun(case())


class MouthClock:
    """The real rep's Mouth calls wait here: held (the rep is still composing)
    until ``go`` is set, then ``LAG_MS`` each (45d7ed's slow Ear and Mouth)."""

    def __init__(self) -> None:
        self.go = asyncio.Event()
        self.sleep: Callable[[float], Awaitable[None]] | None = None

    async def __call__(self) -> None:
        await self.go.wait()
        assert self.sleep is not None
        await self.sleep(LAG_MS / 1000)


ME = "This is Dana Reyes, the account ending 4821."  # FastC's first line
IDENTIFIED = ear(  # the rep's Ear on it (the disclosure before it: other)
    "provide_fact",
    facts=[
        {"key": "account.holder_name", "value": "Dana Reyes"},
        {"key": "account.last4", "value": "4821"},
    ],
)


def test_the_real_rep_does_not_strike_while_a_decline_waits(tmp_path: Path) -> None:
    """The 45d7ed shape on the world's SimRep and its Policy, with the
    family's own patience (``silence_s`` 6, not the tests' patient rep): the
    rep's Ear falls behind while its Mouth is held, then answers one heard
    line per LAG_MS. The decline is released; the rep never strikes or hangs
    up."""

    async def case() -> None:
        clock = MouthClock()
        scripts = {"fast_cp": [ME, LONG], "ear": [ear("other"), IDENTIFIED]}
        scripts["ear"] += [ear("other")]
        scripts |= {"mouth": ["Sorry, how can I help with your account?"]}
        task = load_task("cp-direct-discount")
        assert task.counterparty.patience.silence_s == SILENCE_MS / 1000
        sim = Sim(tmp_path, scripts, task=task, rep="sim", gates={"mouth": clock})
        clock.sleep = sim.vt.sleep
        await sim.start()
        await sim.offer(wait=12_000)  # the rep is still voicing its greeting
        await sim.vt.run_for(20_000)
        clock.go.set()
        await sim.vt.run_for(40_000)
        assert sim.rep.busy and len(sim.of("rep.mouth")) >= 2
        out = sim.act({"tool": "decline_offer", "offer_ref": "o1"})
        assert "queued" in out[0], out
        for _ in range(200):
            await sim.vt.run_for(1_000)
            if _ends(sim):
                break
        (released,) = _ends(sim)
        assert released.type == "speak.released"
        assert sim.of("chan.strike") == [] and sim.of("chan.closed") == []
        intents = [str(e.payload["intent"]) for e in sim.of("rep.policy")]
        assert not [i for i in intents if "hang_up" in i or "check_in" in i]
        await sim.stop()

    arun(case())


def test_fastc_waiting_behind_a_verbatim_yields_to_the_next(tmp_path: Path) -> None:
    """FastC already waits for the floor behind a verbatim line being said
    when a second one queues: as the first ends, FastC re-checks and yields,
    so the second line takes the floor then, before FastC's turn (which is
    then stale behind it and cancelled, S1-SYS-59)."""

    async def case() -> None:
        sim = Sim(tmp_path)
        await sim.start()
        await sim.offer("o1", 68)
        await sim.offer("o2", 75)
        await sim.vt.run_for(10_000)
        assert not sim.k.speakers["cp"].speaking
        assert "queued" in sim.act({"tool": "decline_offer", "offer_ref": "o1"})[0]
        await sim.vt.run_for(500)  # the first decline has the floor
        guide = {"tool": "guide_fast", "move": "ask_final_offer"}
        assert "guide" in sim.act(guide)[0]
        await sim.vt.run_for(100)  # FastC's turn waits for the floor
        (turn,) = [
            e
            for e in sim.of("fast.sentence", lane="cp")
            if not _heard_before(sim, e, len(sim.events))
        ]
        assert "queued" in sim.act({"tool": "decline_offer", "offer_ref": "o2"})[0]
        await sim.vt.run_for(20_000)
        first, second = _ends(sim)
        assert first.type == second.type == "speak.released"
        (line,) = [e for e in sim.events if e.event_id == first.cause_ids[0]]
        (said,) = sim.of("utt.delivered", utt_id=f"decline-{line.seq}")
        assert second.t_ms == said.t_ms and said.seq < second.seq
        # its turn predates the second line: cancelled after it, never said
        (cancelled,) = sim.of("fast.cancelled", gen_id=turn.payload["gen_id"])
        assert cancelled.payload["reason"] == "verbatim"
        assert cancelled.cause_ids[1] == second.event_id
        assert not sim.of("utt.delivered", utt_id=turn.payload["utt_id"])
        await sim.stop()

    arun(case())


def test_a_session_end_while_fastc_waits_on_a_verbatim_ends_cleanly(
    tmp_path: Path,
) -> None:
    """The rep hangs up while a decline waits for the floor and FastC's turn
    waits behind it: the session ends (S1-SYS-55's end), nothing hangs, and
    neither line is said."""

    async def case() -> None:
        rep = LaggingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        await _chatter(sim, rep)
        sim.act({"tool": "decline_offer", "offer_ref": "o1"})
        waiting: list[Event] = []
        for _ in range(300):  # until FastC's next turn waits behind it
            await sim.vt.run_for(100)
            if waiting := _unheard(sim):
                break
        assert waiting and _ends(sim) == [] and rep.busy
        rep.incoming.put_nowait(Incoming((), end="hangup"))
        await sim.vt.run_for(5 * LAG_MS)
        assert sim.k.ended
        (ended,) = sim.of("session.ended")
        assert ended.payload["reason"] == "abandoned"
        assert _ends(sim) == [] and _unheard(sim) == waiting
        await sim.stop()

    arun(case())


def _unheard(sim: Sim) -> list[Event]:  # FastC lines generated, not said
    lines = sim.of("fast.sentence", lane="cp")
    return [e for e in lines if not sim.of("utt.delivered", utt_id=e.payload["utt_id"])]


def _gen(utt_id: object) -> str:  # a FastC line's generation
    return str(utt_id).rsplit("-u", 1)[0]


def _basis(sim: Sim, gen: str) -> int:  # the seq its request saw
    (asked,) = sim.of("fast.request", gen_id=gen)
    return int(str(asked.payload["basis_seq"]))


def test_a_held_fastc_turn_older_than_a_released_decline_is_cancelled(
    tmp_path: Path,
) -> None:
    """S1-SYS-59, the 45d7ed shape: FastC's turn generated while the decline
    waits is held behind it (S1-SYS-56). Released after it, it would be heard
    right after "No, thank you" on a board that had no decline. It is
    cancelled (``fast.cancelled{reason: verbatim}``, citing its turn and the
    release), never said, and its trigger runs again on the new basis."""

    async def case() -> None:
        rep = LaggingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        await _chatter(sim, rep)
        sim.act({"tool": "decline_offer", "offer_ref": "o1"})
        for _ in range(1_000):
            await sim.vt.run_for(100)
            if _ends(sim):
                break
        (released,) = _ends(sim)
        assert released.type == "speak.released"
        held = {_gen(e.payload["utt_id"]) for e in _unheard(sim)}
        assert held, "no FastC turn waited behind the decline"
        assert all(_basis(sim, g) < released.seq for g in held)
        resumed = await _fastc_resumes(sim, released)
        after = [
            e
            for e in sim.of("utt.delivered", lane="cp")
            if e.seq > released.seq and str(e.payload["utt_id"]).startswith("cp-g")
        ]
        assert after and after[0] == resumed
        assert all(_basis(sim, _gen(e.payload["utt_id"])) > released.seq for e in after)
        for gen in held:
            (turn,) = sim.of("fast.turn", gen_id=gen)
            (cancelled,) = sim.of("fast.cancelled", gen_id=gen)
            assert cancelled.payload["reason"] == "verbatim"
            assert cancelled.cause_ids == (turn.event_id, released.event_id)
            assert cancelled.seq > released.seq
            (asked,) = sim.of("fast.request", gen_id=gen)
            asks = sim.of("fast.request", lane="cp")
            again = next(e for e in asks if e.seq > cancelled.seq)
            assert again.payload["trigger"] == asked.payload["trigger"]
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def test_a_held_fastc_turn_behind_a_revoked_line_is_said(tmp_path: Path) -> None:
    """Only a line the rep heard makes a held turn stale: behind an accept
    revoked on the floor (``epoch``, nothing said) FastC's turn is said."""

    async def case() -> None:
        rep = HearingRep()
        sim = Sim(tmp_path, {"fast_cp": [LONG]}, rep=rep)
        await _fastc_holds_the_floor(sim)
        rep.heard.clear()
        rep.answer = REPLY  # FastC answers it while the accept waits
        assert sim.accept().startswith("accept_offer: accept line queued")
        await sim.vt.run_for(1_000)
        sim.revoke()
        await sim.vt.run_for(12_000)
        held = _unheard(sim)
        assert held and _ends(sim) == []
        rep.heard.set()
        await sim.vt.run_for(2 * FAST_MS)  # the rep's reply lands, then FastC's
        (revoked,) = _ends(sim)
        assert revoked.type == "speak.revoked"
        assert all(_heard_before(sim, e, len(sim.events)) for e in held)
        assert not [
            e for e in sim.of("fast.cancelled") if e.payload["reason"] == "verbatim"
        ]
        await sim.stop()

    arun(case())
