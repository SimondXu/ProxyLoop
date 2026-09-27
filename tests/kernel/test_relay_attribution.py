"""S1-SYS-16 A: an ``f2s.msg``'s ``utt_ref`` is the newest partner line of the
view its prompt was built from, never a line that landed mid-generation (I2, I4).
A gate holds the first Fast call open while a second partner line lands."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from tests.kernel.test_session import SCRIPTS, UNTIL
from tests.support.sessions import act, only_bundle, run

from proxyloop.contract.bundle import Bundle
from proxyloop.contract.events import Event
from proxyloop.evidence.check import check_path
from proxyloop.kernel.channels import Channel, Incoming
from proxyloop.kernel.session import DISCLOSURE

WAIT = [act("Waiting.", {"tool": "wait", "seconds": 60})]
RELAYING = "Noted.\n@slow: fact monthly_price=75.00"


class Partner(Channel):
    """Says a first line when it hears ``opener`` (``None``: the lane opening);
    ``second`` queues a second line and returns on the next free floor, when
    that line is on the board; quits once it has heard ``replies`` agent lines."""

    def __init__(self, opener: str | None, replies: int) -> None:
        super().__init__()
        self.opener, self.replies = opener, replies
        self.landed, self._queued = asyncio.Event(), False

    def say(self, text: str) -> None:
        self.incoming.put_nowait(Incoming(((text, None),)))

    async def second(self, text: str) -> None:  # the gate on the first Fast call
        if not self._queued:
            self._queued = True
            self.say(text)
            await self.landed.wait()

    def floor(self, free: bool, t_ms: int) -> None:
        if free and self._queued:
            self.landed.set()

    async def send(self, text: str | None, utt_id: str, cause: str, t_ms: int) -> None:
        if text == self.opener:
            self.say("first line")
        elif text:
            self.replies -= 1
            if self.replies == 0:
                self.incoming.put_nowait(Incoming((), end="quit"))


def _of(events: tuple[Event, ...], type_: str, lane: str) -> list[Event]:
    return [e for e in events if e.type == type_ and e.payload.get("lane") == lane]


def assert_utt_refs_follow_the_request_view(bundle: Bundle) -> int:
    """Every ``f2s.msg.utt_ref`` is the newest partner line in the stored view
    of the ``fast.request`` behind its turn. Returns the relays checked."""
    by_id = {e.event_id: e for e in bundle.events}
    relays = [e for e in bundle.events if e.type == "f2s.msg"]
    for relay in relays:
        turn = by_id[relay.cause_ids[0]]
        ask = by_id[turn.cause_ids[0]]
        assert (turn.type, ask.type) == ("fast.turn", "fast.request")
        view = json.loads(bundle.prompts[str(ask.payload["view_sha"])].content)
        heard = [x["utt_id"] for x in view["transcript"] if x["speaker"] == "partner"]
        assert relay.payload["utt_ref"] == (heard or [None])[-1], relay
    return len(relays)


def test_a_user_line_landing_mid_generation_is_not_credited(tmp_path: Path) -> None:
    user, rep = Partner(None, replies=2), Channel()  # m1 at the lane's opening
    scripts = SCRIPTS | {"fast_user": [RELAYING], "slow": WAIT}
    result = run(
        tmp_path,
        scripts,
        channels={"user": user, "cp": rep},
        gates={"fast_user": lambda: user.second("second line")},
    )
    assert result.reason == "stopped"
    assert check_path(result.path, "offline").ok
    bundle = only_bundle(tmp_path)
    m1, m2 = [e for e in bundle.events if e.type == "user.msg"]
    ask = _of(bundle.events, "fast.request", "user")[0]
    relays = _of(bundle.events, "f2s.msg", "user")
    relay = next(e for e in relays if e.payload["gen_id"] == ask.payload["gen_id"])
    assert ask.seq < m2.seq < relay.seq  # m2 landed mid-generation
    assert relay.payload["utt_ref"] == m1.event_id != m2.event_id
    assert assert_utt_refs_follow_the_request_view(bundle) >= 2


def test_a_rep_line_landing_mid_generation_is_not_credited(tmp_path: Path) -> None:
    user, rep = Channel(), Partner(DISCLOSURE, replies=2)  # r1 after the disclosure
    scripts = SCRIPTS | {"fast_cp": [RELAYING], "slow": WAIT}
    result = run(
        tmp_path,
        scripts,
        channels={"user": user, "cp": rep},
        gates={"fast_cp": lambda: rep.second("second line")},
    )
    assert result.reason == "stopped"
    assert check_path(result.path, "offline").ok
    bundle = only_bundle(tmp_path)
    partner = [
        e
        for e in _of(bundle.events, "utt.final", "cp")
        if e.payload["speaker"] == "partner"
    ]
    r1, r2 = partner
    ask = _of(bundle.events, "fast.request", "cp")[0]
    relays = _of(bundle.events, "f2s.msg", "cp")
    relay = next(e for e in relays if e.payload["gen_id"] == ask.payload["gen_id"])
    assert ask.seq < r2.seq < relay.seq  # r2 landed mid-generation
    assert relay.payload["utt_ref"] == r1.payload["utt_id"] != r2.payload["utt_id"]
    assert assert_utt_refs_follow_the_request_view(bundle) >= 2


def test_a_full_session_credits_every_relay_to_its_request_view(
    tmp_path: Path,
) -> None:
    run(tmp_path, SCRIPTS, until=UNTIL)
    assert assert_utt_refs_follow_the_request_view(only_bundle(tmp_path)) >= 1
