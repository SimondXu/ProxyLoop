"""EventLog (single writer, dense seq, re-validation) and Bus (isolation, order)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.support.manual_clock import ManualClock

from proxyloop.contract.events import Event
from proxyloop.core.bus import Bus
from proxyloop.core.log import EventLog

RUN = "r1"


def _bus(tmp_path: Path) -> Bus:
    return Bus(EventLog(tmp_path / "events.jsonl", RUN), ManualClock())


def _user_msg(seq: int, text: str = "hi", t_ms: int = 0) -> Event:
    return Event.model_validate(
        {
            "run_id": RUN,
            "seq": seq,
            "event_id": f"{RUN}:{seq}",
            "t_ms": t_ms,
            "wall": "2026-09-26T00:00:00Z",
            "type": "user.msg",
            "actor": "kernel",
            "stream": "agent",
            "epoch": 0,
            "payload": {"text": text},
        }
    )


def _lines(tmp_path: Path) -> list[str]:
    return (tmp_path / "events.jsonl").read_text("utf-8").splitlines()


def test_a_second_writer_cannot_open_the_same_log(tmp_path: Path) -> None:
    EventLog(tmp_path / "events.jsonl", RUN)
    with pytest.raises(FileExistsError):
        EventLog(tmp_path / "events.jsonl", RUN)


def test_seq_must_be_dense_and_the_run_single(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl", RUN)
    log.append(_user_msg(0))
    with pytest.raises(ValueError, match="seq 2 appended, 1 expected"):
        log.append(_user_msg(2))
    other = _user_msg(1).model_dump() | {"run_id": "r2", "event_id": "r2:1"}
    with pytest.raises(ValueError, match="event of run 'r2'"):
        log.append(Event.model_validate(other))
    log.append(_user_msg(1))
    assert len(_lines(tmp_path)) == 2


def test_t_ms_may_not_go_back(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl", RUN)
    log.append(_user_msg(0, t_ms=5))
    with pytest.raises(ValueError, match="t_ms went backwards"):
        log.append(_user_msg(1, t_ms=4))


def test_a_model_construct_event_is_revalidated_at_append(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl", RUN)
    good = _user_msg(0)
    values = good.model_dump(by_alias=False) | {"type": "made.up"}
    forged = Event.model_construct(set(values), **values)
    with pytest.raises(ValidationError, match="unregistered event type"):
        log.append(forged)
    emptied = good.model_copy(update={"payload": {}})  # skips validation
    with pytest.raises(ValidationError, match="lacks"):
        log.append(emptied)
    assert _lines(tmp_path) == []


def test_the_stored_event_is_not_the_callers_object(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl", RUN)
    event = _user_msg(0)
    returned = log.append(event)
    event.payload["text"] = "changed by the caller"
    returned.payload["text"] = "changed by a subscriber"
    assert log.events[0].payload["text"] == "hi"


def test_a_decision_must_cite_the_post_it_decides(tmp_path: Path) -> None:
    bus = _bus(tmp_path)
    post = bus.emit(
        "approval.post",
        "ui",
        "agent",
        {
            "subject": "approval",
            "subject_id": "a1",
            "decision": "denied",
            "subject_hash": "h",
            "authority_epoch": 0,
        },
    )
    with pytest.raises(ValueError, match=r"must cite the approval\.post"):
        bus.emit(
            "approval.decided",
            "kernel",
            "agent",
            {"approval_id": "a1", "decision": "granted", "by": "ui"},
            [post.event_id],
        )
    assert len(_lines(tmp_path)) == 1


def test_a_failing_subscriber_is_isolated(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bus = _bus(tmp_path)
    seen: list[int] = []

    def broken(event: Event) -> None:
        raise RuntimeError("exporter down")

    bus.subscribe(broken)
    bus.subscribe(lambda e: seen.append(e.seq))
    with caplog.at_level(logging.ERROR):
        bus.emit("user.msg", "kernel", "agent", {"text": "a"})
        bus.emit("user.msg", "kernel", "agent", {"text": "b"})
    assert seen == [0, 1]
    assert bus.subscriber_errors == 2
    assert "exporter down" in caplog.text


def test_an_emit_from_a_subscriber_is_delivered_in_log_order(tmp_path: Path) -> None:
    bus = _bus(tmp_path)
    order: list[tuple[str, int]] = []

    def echo(event: Event) -> None:
        order.append(("echo", event.seq))
        if event.type == "user.msg":
            bus.emit("chan.strike", "kernel", "agent", {})

    bus.subscribe(echo)
    bus.subscribe(lambda e: order.append(("last", e.seq)))
    bus.emit("user.msg", "kernel", "agent", {"text": "a"})
    assert order == [("echo", 0), ("last", 0), ("echo", 1), ("last", 1)]
    assert [e.seq for e in bus.log.events] == [0, 1]


def test_an_event_the_fold_rejects_is_never_written(tmp_path: Path) -> None:
    bus = _bus(tmp_path)
    bus.emit("user.msg", "kernel", "agent", {"text": "a"})
    before = bus.bb
    with pytest.raises(ValueError, match="summary scope"):
        bus.emit(
            "summary.updated",
            "guard",
            "agent",
            {"scope": "bogus", "text": "x"},
            [f"{RUN}:0"],
        )
    assert bus.bb == before and len(_lines(tmp_path)) == 1


def test_emit_stamps_clock_and_epoch(tmp_path: Path) -> None:
    clock = ManualClock()
    bus = Bus(EventLog(tmp_path / "events.jsonl", RUN), clock)
    first = bus.emit("user.msg", "kernel", "agent", {"text": "a"})
    clock.advance(250)
    bump = bus.emit(
        "authority.epoch",
        "guard",
        "agent",
        {"new": 1, "reason": "f2s_revoke"},
        [first.event_id],
    )
    after = bus.emit("user.msg", "kernel", "agent", {"text": "b"})
    assert (bump.t_ms, bump.epoch, after.epoch, bus.bb.epoch) == (250, 0, 1, 1)
