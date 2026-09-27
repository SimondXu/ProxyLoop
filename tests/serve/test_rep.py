"""The human rep's stream (I4, AGENTS rule 8): /ws/rep/{case_id} sends only
the allow-listed public fields of cp-lane speech and channel events, rebuilt,
and only to the rep's own cookie. The fixture holds every registered event
type, with a private-looking value wherever a payload has a string."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from tests.contract.samples import call_record
from tests.serve.client import ORIGIN, client, connect, frames, headers, login
from tests.support.api_cases import StoredCase

from proxyloop.contract.bundle import EVENTS
from proxyloop.contract.events import EMITTERS, EVENT_TYPES, Event

RUN = "case-rep"
S = "SECRET"  # never in a frame
CAP = {
    "cap_id": S,
    "business_action_id": S,
    "intent": "accept_offer",
    "terms_hash": S,
    "epoch": 0,
    "expires_ms": 9,
}
CARD = {
    "approval_id": S,
    "offer_ref": "o1",
    "revision": 1,
    "terms_hash": S,
    "readback_text": S,
    "authority_epoch": 0,
    "expires_ms": 9,
    "binding": {
        "offer_ref": "o1",
        "revision": 1,
        "account_ref": S,
        "principal_ref": S,
        "purpose": S,
        "authority_epoch": 0,
    },
}
TYPED: dict[str, dict[str, Any]] = {
    "llm.call": call_record(call_id=S, request_id=S).model_dump(mode="json"),
    "f2s.msg": {"msg_id": S, "lane": "cp", "gen_id": S, "utt_ref": S,
                "type": "CP_UPDATE", "facts": [["monthly_price", S]], "text": S},
    "s2f.msg": {"msg_id": S, "lane": "user", "type": "TELL_USER", "text": S},
    "approval.post": {"subject": "approval", "subject_id": S, "decision": "granted",
                      "subject_hash": S, "authority_epoch": 0},
    "approval.decided": {"approval_id": S, "decision": "granted", "by": "ui"},
    "approval.requested": CARD,
    "mandate.proposed": {"mandate_id": S, "mandate_hash": S, "status": "proposed",
                         "epoch": 0, "max_monthly_price_minor": 7000},
    "mandate.decided": {"mandate_id": S, "mandate_hash": S, "decision": "granted",
                        "by": "ui"},
    "authority.epoch": {"new": 1, "reason": "slow_revoke"},
    "action.authorized": {"intent": "accept_offer", "capability": CAP},
    "status.changed": {"previous": "IN_CALL", "status": "AWAITING_APPROVAL"},
    "completion.decided": {"verdict": "ok", "reasons": [S]},
}  # fmt: skip
CHANNEL = ["chan.opened", "chan.closed", "chan.hold", "chan.strike", "chan.barge_in"]
# (type, payload, the frame's payload or None when it must not be sent)
SPEECH: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = [
    ("utt.final", {"lane": "cp", "speaker": "partner", "utt_id": "cp-1",
                   "text": "Hi, this is Sam.", "note": S},
     {"lane": "cp", "speaker": "partner", "utt_id": "cp-1",
      "text": "Hi, this is Sam."}),
    ("utt.final", {"lane": "cp", "speaker": "agent", "utt_id": "cp_agent-2",
                   "text": S}, None),
    ("utt.final", {"lane": "user", "speaker": "partner", "utt_id": "u-1",
                   "text": S}, None),
    ("utt.delivered", {"lane": "cp", "utt_id": "a-1", "text_generated": S,
                       "text_heard": "We would like a lower", "interrupted": True},
     {"lane": "cp", "utt_id": "a-1", "text_heard": "We would like a lower",
      "interrupted": True}),
    ("utt.delivered", {"lane": "user", "utt_id": "a-2", "text_generated": S,
                       "text_heard": S, "interrupted": False}, None),
    ("utt.delivered", {"lane": "cp", "utt_id": "a-3", "text_generated": S,
                       "text_heard": {"private": S}, "interrupted": False}, None),
    *[(kind, {"lane": "cp", "reason": S, "count": 3}, {"lane": "cp"})
      for kind in CHANNEL],
    *[(kind, {"lane": "user", "reason": S}, None) for kind in CHANNEL],
    ("summary.updated", {"scope": "public", "text": S}, None),
    ("summary.updated", {"scope": "private", "text": S}, None),
]  # fmt: skip


def _stream(kind: str) -> str:
    return EVENT_TYPES[kind].streams[0]


def _actor(kind: str) -> str:
    stream = _stream(kind)
    if stream == "world":
        return "world.ear"
    return "kernel" if stream == "ops" else min(EMITTERS.get(kind, {"guard"}))


def _events() -> list[tuple[str, dict[str, Any], dict[str, Any] | None]]:
    """session.started, the speech rows, one of every other type, the end."""
    started = dict.fromkeys(EVENT_TYPES["session.started"].payload_keys, S)
    rows = [("session.started", started | {"split": "train"}, None), *SPEECH]
    done = {kind for kind, _, _ in rows} | {"session.ended"}
    for kind, spec in EVENT_TYPES.items():
        if kind not in done:
            filler = dict.fromkeys(spec.payload_keys, S) | {"lane": "cp", "x": S}
            rows.append((kind, TYPED.get(kind, filler), None))
    return [*rows, ("session.ended", {"reason": "stopped"}, None)]


def _line(seq: int, kind: str, payload: dict[str, Any]) -> bytes:
    event = Event.model_validate(
        {
            "run_id": RUN,
            "seq": seq,
            "event_id": f"{RUN}:{seq}",
            "t_ms": 10 * seq,
            "wall": "2026-09-26T00:00:00Z",
            "type": kind,
            "actor": _actor(kind),
            "stream": _stream(kind),
            "cause_ids": [f"{RUN}:{seq - 1}"] if seq else [],
            "epoch": 0,
            "payload": payload,
        }
    )
    return event.model_dump_json(by_alias=True).encode() + b"\n"


@dataclass
class Rep:
    http: TestClient
    expected: list[dict[str, Any]]  # every frame, in order


@pytest.fixture
def rep(tmp_path: Path) -> Iterator[Rep]:
    root = tmp_path / "runs"
    (root / RUN).mkdir(parents=True)
    rows = _events()
    assert {kind for kind, _, _ in rows} == set(EVENT_TYPES)  # every type
    (root / RUN / EVENTS).write_bytes(
        b"".join(_line(seq, kind, p) for seq, (kind, p, _) in enumerate(rows))
    )
    expected = [
        {"seq": seq, "t_ms": 10 * seq, "type": kind, "payload": frame}
        for seq, (kind, _, frame) in enumerate(rows)
        if frame is not None
    ]
    cases = {RUN: StoredCase(RUN)}
    yield Rep(client(root, cases=cases.get), expected)


def _rep_headers(http: TestClient, case_id: str = RUN) -> dict[str, str]:
    hdrs = headers(login(http, "rep", case_id))
    del hdrs["x-csrf-token"]  # a browser WebSocket sends cookies and Origin only
    return hdrs


def test_the_rep_gets_exactly_the_allow_listed_frames(rep: Rep) -> None:
    got, code = frames(rep.http, f"/ws/rep/{RUN}", _rep_headers(rep.http))
    assert code == 1000
    assert [json.loads(f) for f in got] == rep.expected
    assert len(rep.expected) == 2 + len(CHANNEL)
    assert all(S not in f for f in got)


def test_from_seq_is_the_original_seq(rep: Rep) -> None:
    start = rep.expected[1]["seq"]  # the cp utt.delivered
    path = f"/ws/rep/{RUN}?from_seq={start}"
    got, code = frames(rep.http, path, _rep_headers(rep.http))
    assert code == 1000
    assert [json.loads(f) for f in got] == rep.expected[1:]


def test_the_rep_stream_needs_the_rep_cookie(rep: Rep) -> None:
    user = headers(login(rep.http, "user", RUN))
    del user["x-csrf-token"]
    no_cookie = {"origin": ORIGIN}
    bare_session = _rep_headers(rep.http)
    bare_session["cookie"] = bare_session["cookie"].split(";")[0]
    for hdrs in (no_cookie, user, bare_session):
        assert frames(rep.http, f"/ws/rep/{RUN}", hdrs) == ([], 4403)


@pytest.mark.parametrize("origin", [None, "http://evil.example"])
def test_the_rep_stream_needs_an_allowed_origin(rep: Rep, origin: str | None) -> None:
    hdrs = _rep_headers(rep.http)
    del hdrs["origin"]
    if origin is not None:
        hdrs["origin"] = origin
    with (  # refused before accept
        pytest.raises(WebSocketDisconnect) as closed,
        connect(rep.http, f"/ws/rep/{RUN}", hdrs),
    ):
        pass
    assert closed.value.code == 4403


def test_a_run_without_its_seq_0_is_an_unknown_case(rep: Rep, tmp_path: Path) -> None:
    hdrs = _rep_headers(rep.http)
    (tmp_path / "runs" / RUN / EVENTS).write_bytes(b"")  # as before session.started
    assert frames(rep.http, f"/ws/rep/{RUN}", hdrs) == ([], 4404)
    assert frames(client(tmp_path / "runs"), f"/ws/rep/{RUN}", hdrs) == ([], 4404)


def test_the_live_stream_still_serves_the_operator(rep: Rep) -> None:
    got, code = frames(rep.http, f"/ws/live/{RUN}")  # no cookie, no Origin
    assert code == 1000 and len(got) == len(_events())
