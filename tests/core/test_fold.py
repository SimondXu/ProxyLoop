"""The fold: coverage of the registry, reducers, and determinism (property)."""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from hypothesis import given
from hypothesis import strategies as st
from tests.support.manual_clock import ManualClock

from proxyloop.contract.bundle import EVENTS
from proxyloop.contract.events import EVENT_TYPES, Event, Stream
from proxyloop.contract.state import Blackboard, CaseStatus
from proxyloop.core.bus import Bus
from proxyloop.core.fold import RECORD_ONLY, REDUCERS, WORLD_OPS, apply, fold

RUN = "r1"
_STARTED = EVENT_TYPES["session.started"].payload_keys


def test_every_registry_type_has_a_reducer_or_is_world_or_ops() -> None:
    assert set(REDUCERS) | WORLD_OPS == set(EVENT_TYPES)
    assert not set(REDUCERS) & WORLD_OPS
    assert set(REDUCERS) >= RECORD_ONLY
    world_ops = {"session.started", "session.ended", "spend.charged", "user.sim"}
    assert world_ops | {"parity.checked", "rep.ear", "ledger.write"} <= WORLD_OPS


# One step = (type, actor, stream, payload); derived types cite the event before.
Step = tuple[str, str, str, dict[str, object]]
_TEXT = st.text(alphabet="abc $1.", min_size=1, max_size=12)
_LANE = st.sampled_from(["user", "cp"])


def _steps() -> st.SearchStrategy[Step]:
    k = "kernel"
    return st.one_of(
        _TEXT.map(lambda t: ("user.msg", k, "agent", {"text": t})),
        st.tuples(_LANE, _TEXT).map(
            lambda a: (
                "utt.final",
                k,
                "agent",
                {"lane": a[0], "speaker": "partner", "utt_id": "u", "text": a[1]},
            )
        ),
        st.tuples(_LANE, _TEXT, st.booleans()).map(
            lambda a: (
                "utt.delivered",
                k,
                "agent",
                {
                    "lane": a[0],
                    "utt_id": "d",
                    "text_generated": a[1],
                    "text_heard": a[1] if a[2] else "",
                    "interrupted": not a[2],
                },
            )
        ),
        _TEXT.map(
            lambda t: (
                "f2s.msg",
                "fast.user",
                "agent",
                {
                    "msg_id": t,
                    "lane": "user",
                    "gen_id": "g",
                    "utt_ref": None,
                    "type": "NOTE",
                },
            )
        ),
        st.integers(0, 3).map(
            lambda i: (
                "s2f.msg",
                "slow",
                "agent",
                {"msg_id": f"s{i}", "lane": "user", "type": "TELL_USER", "text": "ok"},
            )
        ),
        st.integers(0, 3).map(
            lambda i: (
                "s2f.voiced",
                "fast.user",
                "agent",
                {"msg_id": f"s{i}", "gen_id": "g"},
            )
        ),
        st.tuples(st.sampled_from(["public", "private"]), _TEXT).map(
            lambda a: (
                "summary.updated",
                "guard",
                "agent",
                {"scope": a[0], "text": a[1]},
            )
        ),
        st.tuples(st.sampled_from(["raised", "cleared"]), st.integers(0, 2)).map(
            lambda a: (
                "authority.fence",
                k,
                "agent",
                {"op": a[0], "fence_id": f"f{a[1]}", "utt_id": "u"},
            )
        ),
        st.integers(1, 5).map(
            lambda n: (
                "authority.epoch",
                "guard",
                "agent",
                {"new": n, "reason": "slow_revoke"},  # an increment: see _emit_all
            )
        ),
        st.sampled_from(list(CaseStatus)).map(
            lambda s: (
                "status.changed",
                "guard",
                "agent",
                {"previous": "INTAKE", "status": s.value},
            )
        ),
        st.just(
            (
                "fast.cancelled",
                "fast.cp",
                "agent",
                {"gen_id": "g", "reason": "barge_in"},
            )
        ),
        st.just(
            (
                "rep.policy",
                "world.policy",
                "world",
                {"from": "a", "to": "b", "intent": "offer", "rung": 1},
            )
        ),
    )


def _emit_all(path: Path, steps: list[tuple[Step, int]]) -> Bus:
    clock = ManualClock()
    bus = Bus(path, RUN, clock)
    bus.emit("session.started", "kernel", "ops", {k: "" for k in _STARTED})
    for (type_, actor, stream, payload), advance in steps:
        clock.advance(advance)
        spec = EVENT_TYPES[type_]
        causes = [bus.events[-1].event_id] if spec.cause_required else []
        if type_ == "authority.epoch":  # epochs only increase (§9.4)
            payload = payload | {"new": bus.bb.epoch + cast(int, payload["new"])}
        bus.emit(type_, actor, cast(Stream, stream), payload, causes)
    return bus


@given(
    st.lists(st.tuples(_steps(), st.integers(0, 50)), max_size=25), st.integers(0, 26)
)
def test_fold_is_deterministic(steps: list[tuple[Step, int]], cut: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bus = _emit_all(Path(tmp) / EVENTS, steps)
        bus.close()
        events = bus.events
        lines = (Path(tmp) / EVENTS).read_text("utf-8").splitlines()
    from_disk = tuple(Event.model_validate_json(line) for line in lines)
    whole = fold(events)
    assert whole == bus.bb  # incremental, while emitting == batch
    assert fold(from_disk) == whole  # the JSONL form folds the same
    assert fold(events) == whole  # repeatable
    assert fold(events[cut:], fold(events[:cut])) == whole  # any split point
    assert whole.seq == len(events) - 1


def _event(
    seq: int, type_: str, payload: Mapping[str, object], actor: str = "kernel"
) -> Event:
    return Event.model_validate(
        {
            "run_id": RUN,
            "seq": seq,
            "event_id": f"{RUN}:{seq}",
            "t_ms": seq,
            "wall": "2026-09-26T00:00:00Z",
            "type": type_,
            "actor": actor,
            "stream": "agent",
            "cause_ids": [f"{RUN}:0"] if seq else [],
            "epoch": 0,
            "payload": payload,
        }
    )


def test_fences_raise_and_clear() -> None:
    raised = {"op": "raised", "fence_id": "f1", "utt_id": "u9"}
    bb = fold(
        [_event(0, "user.msg", {"text": "stop"}), _event(1, "authority.fence", raised)]
    )
    assert [(f.fence_id, f.raised_seq) for f in bb.fences] == [("f1", 1)]
    cleared = raised | {"op": "cleared"}
    assert apply(bb, _event(2, "authority.fence", cleared)).fences == ()


def test_the_transcript_holds_what_was_heard() -> None:
    delivered = {
        "lane": "cp",
        "utt_id": "a1",
        "text_generated": "Could you hold on?",
        "text_heard": "Could you",
        "interrupted": True,
    }
    bb = fold(
        [_event(0, "user.msg", {"text": "x"}), _event(1, "utt.delivered", delivered)]
    )
    assert [(line.speaker, line.text) for line in bb.channels["cp"].lines] == [
        ("agent", "Could you")
    ]
    assert bb.channels["user"].lines[0].utt_id == f"{RUN}:0"


def test_offers_and_voiced_messages() -> None:
    offer = {
        "offer_ref": "o1",
        "revision": 1,
        "slots": [
            {
                "field": "monthly_price",
                "value": "4500",
                "unit": "usd_minor",
                "role": "recurring",
            }
        ],
        "terms_hash": None,
    }
    tell = {"msg_id": "s1", "lane": "user", "type": "TELL_USER", "text": "Done."}
    bb = fold(
        [
            _event(0, "user.msg", {"text": "x"}),
            _event(1, "offer.recorded", offer, actor="guard"),
            _event(2, "s2f.msg", tell, actor="slow"),
        ]
    )
    assert bb.public.offers["o1"].slots[0].value == "4500"
    assert [m.msg_id for m in bb.s2f_pending["user"]] == ["s1"]
    voiced = apply(
        bb, _event(3, "s2f.voiced", {"msg_id": "s1", "gen_id": "g"}, "fast.user")
    )
    assert voiced.s2f_pending["user"] == ()


def test_record_only_and_world_events_change_only_seq_and_time() -> None:
    bb = fold([_event(0, "user.msg", {"text": "x"})])
    cancelled = apply(
        bb, _event(1, "fast.cancelled", {"gen_id": "g", "reason": "r"}, "fast.cp")
    )
    assert cancelled == Blackboard.model_validate(dict(bb) | {"seq": 1, "t_ms": 1})
