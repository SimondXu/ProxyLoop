"""ADR-0012 (reduced by ADR-0016): the needs ledger, a pure fold of the log.
Per key: ``pending`` from a keyed ask, ``replied`` once a ``user.msg`` is newer
than the ask's voicing, ``answered`` once a ``fact.recorded`` exists. An echo
relay citing the old message is no reply. The ledger holds no text."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any

from proxyloop.contract.events import Event
from proxyloop.guard.needs import (
    Ledger,
    Need,
    ask_denial,
    fold,
    start_denial,
    step,
)

RUN = "r1"
L4, NAME = "account.last4", "account.holder_name"


class Log:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self._n = 0
        self.user("hello")  # r1:0, the cause the agent events cite

    def add(self, type_: str, actor: str, payload: dict[str, Any], *causes: str) -> str:
        seq = len(self.events)
        e = Event.model_validate(
            {"run_id": RUN, "seq": seq, "event_id": f"{RUN}:{seq}", "t_ms": 100 * seq,
             "wall": datetime(2026, 9, 27, tzinfo=UTC), "type": type_,
             "actor": actor, "stream": "agent", "cause_ids": causes or (),
             "epoch": 0, "payload": payload}
        )  # fmt: skip
        self.events.append(e)
        return e.event_id

    def ask(self, *keys: str, ok: bool = True) -> str:
        """Slow's ask_user and its s2f.msg; the msg id."""
        self._n += 1
        args: dict[str, Any] = {"tool": "ask_user", "text": "Your last 4?"}
        args |= {"keys": list(keys)} if keys else {}
        done = {"name": "ask_user", "args": args, "result_text": "", "ok": ok}
        tool = self.add("slow.tool", "slow", done, f"{RUN}:0")
        msg = f"s2f-{self._n}"
        if ok:
            ask = {"msg_id": msg, "lane": "user", "type": "ASK_USER", "text": "?"}
            self.add("s2f.msg", "guard", ask, tool)
        return msg

    def voiced(self, msg: str) -> None:
        self.add("s2f.voiced", "fast.user", {"msg_id": msg, "gen_id": "u-g1"}, "r1:0")

    def user(self, text: str = "It is 4821") -> str:
        return self.add("user.msg", "kernel", {"text": text})

    def echo(self, utt_ref: str) -> None:  # FastU relays an old message again
        relay = {"msg_id": f"{RUN}:{len(self.events)}", "lane": "user"}
        relay |= {"gen_id": "u-g2", "utt_ref": utt_ref, "type": "USER_UPDATE"}
        relay |= {"facts": [[L4, "4821"]]}
        self.add("f2s.msg", "fast.user", relay, "r1:0")

    def fact(self, key: str, scope: str = "public") -> None:
        fact = {"key": key, "value": "4821", "source_ref": None, "scope": scope}
        self.add("fact.recorded", "guard", fact | {"source": "user"}, "r1:0")

    def hold(self, reason: str | None = "fact_request") -> None:
        self.add("chan.hold", "fast.cp", {"lane": "cp", "reason": reason}, "r1:0")

    @property
    def ledger(self) -> Ledger:
        return fold(self.events)


def test_the_three_states() -> None:
    log = Log()
    log.user("hi")
    msg = log.ask(L4)
    assert log.ledger.state(L4) == "pending"
    log.voiced(msg)
    assert log.ledger.state(L4) == "pending"  # voiced, no reply yet
    log.user()
    assert log.ledger.state(L4) == "replied"
    log.fact(L4)
    assert log.ledger.state(L4) == "answered"
    assert log.ledger.state(NAME) is None  # never asked


def test_a_reply_needs_a_user_msg_newer_than_the_voicing() -> None:
    log = Log()
    old = log.user("my last 4 is 4821")  # before the ask
    msg = log.ask(L4)
    log.user("early")  # after the ask, before FastU voiced it
    assert log.ledger.state(L4) == "pending"
    log.voiced(msg)
    log.echo(old)  # the echo rule: a relay citing the old message
    assert log.ledger.state(L4) == "pending"
    log.user()
    assert log.ledger.state(L4) == "replied"


def test_a_re_ask_after_a_reply_is_pending_again() -> None:
    log = Log()
    log.voiced(log.ask(L4, NAME))
    log.user()
    assert log.ledger.states() == {L4: "replied", NAME: "replied"}
    assert ask_denial(log.ledger, [L4]) is None
    second = log.ask(L4)
    assert log.ledger.states() == {L4: "pending", NAME: "replied"}
    assert log.ledger.needs[L4].asks == 2
    log.voiced(second)
    log.user()
    assert log.ledger.state(L4) == "replied"


def test_a_pending_key_is_not_asked_again() -> None:
    log = Log()
    log.ask(L4)
    denied = ask_denial(log.ledger, [L4])
    assert denied is not None and L4 in denied
    mixed = ask_denial(log.ledger, [NAME, L4])  # A1: never twice while pending
    assert mixed is not None and L4 in mixed and NAME not in mixed
    assert ask_denial(log.ledger, [NAME]) is None
    assert ask_denial(log.ledger, []) is None  # keyless: counted, not deduped


def test_keyless_asks_are_counted_and_open_no_key() -> None:
    log = Log()
    log.ask()
    log.ask()
    log.ask(ok=False)  # a refused ask counts nothing
    assert log.ledger.keyless == 2
    assert log.ledger.needs == {}


def test_a_refused_ask_opens_no_need() -> None:
    log = Log()
    log.ask(L4, ok=False)
    assert log.ledger.state(L4) is None


def test_answered_without_an_ask_and_holds_counted() -> None:
    log = Log()
    log.fact(NAME, scope="private")
    log.hold()
    log.hold(None)  # the hold ends: not a hold
    log.hold("fact_request")
    assert log.ledger.state(NAME) == "answered"
    assert log.ledger.holds == 2


def test_start_needs_every_missing_key_asked_and_replied() -> None:
    log = Log()
    denied = start_denial(log.ledger, (NAME, L4))
    assert denied is not None and "not asked" in denied
    msg = log.ask(NAME, L4)
    denied = start_denial(log.ledger, (NAME, L4))
    assert denied is not None and "no reply" in denied
    log.voiced(msg)
    log.user()
    assert start_denial(log.ledger, (NAME, L4)) is None
    assert start_denial(Ledger(), ()) is None  # nothing missing


def test_the_fold_is_incremental_and_pure() -> None:
    log = Log()
    log.voiced(log.ask(L4))
    log.user()
    ledger = Ledger()
    for e in log.events:
        ledger = step(ledger, e)
    assert ledger == fold(log.events) == fold(log.events)


def test_the_ledger_holds_no_text() -> None:
    """Hygiene (ADR-0016): key names, states, seqs, times and counts only."""
    log = Log()
    log.voiced(log.ask(L4))
    log.user("SECRET-TEXT 4821")
    log.fact(L4)
    ledger = log.ledger
    assert [f.name for f in dataclasses.fields(Need)] == [
        "key", "state", "asks", "asked_seq", "asked_ms", "voiced_seq",
        "replied_seq", "answered_seq",
    ]  # fmt: skip
    assert "SECRET" not in repr(ledger) and "4821" not in repr(ledger)
    for need in ledger.needs.values():
        for f in dataclasses.fields(Need):
            value = getattr(need, f.name)
            assert value is None or isinstance(value, int) or f.name in ("key", "state")
