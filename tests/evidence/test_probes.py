"""The #118 review probes, as negative tests: each forgery of a well-formed
bundle is rejected, offline or under ``--claim``.

``real`` is scripted but labelled ``real_http``: it exercises the claim rules
and is never a claim. Passing ``--claim`` proves internal consistency and
chain completeness, not authenticity (see ``proxyloop.evidence.check``).
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.contract.samples import QWEN, SONNET
from tests.support.recorded import RUN_ID, write_fast_bundle

from proxyloop.contract.base import sha256_text
from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS, Manifest, RoleModel
from proxyloop.contract.llm import LLMRole
from proxyloop.evidence.check import Mode, check_path

RESPONSE = "Thanks, that helps. Could you read the full offer back to me?\n@hold offer"
TEXT = "I am an AI assistant calling for my customer."
Json = dict[str, Any]


def _edit_manifest(run: Path, **update: object) -> None:
    body = json.loads((run / MANIFEST).read_text("utf-8")) | update
    (run / MANIFEST).write_text(
        Manifest.model_validate(body).model_dump_json(), "utf-8"
    )


def _events(run: Path) -> list[Json]:
    return [json.loads(line) for line in (run / EVENTS).read_text("utf-8").splitlines()]


def _write(run: Path, events: list[Json]) -> None:
    (run / EVENTS).write_text("".join(json.dumps(e) + "\n" for e in events), "utf-8")


def _renumber(events: list[Json]) -> list[Json]:
    """Dense seqs; causes follow their event (a duplicated id: the first)."""
    new: dict[str, str] = {}
    for seq, e in enumerate(events):
        new.setdefault(e["event_id"], f"{RUN_ID}:{seq}")
        e.update(seq=seq, event_id=f"{RUN_ID}:{seq}")
    for e in events:
        e["cause_ids"] = [new.get(c, c) for c in e["cause_ids"]]
    return events


def _event(
    type_: str, actor: str, payload: Json, causes: list[str], id_: str = ""
) -> Json:
    stream = "ops" if type_ == "session.ended" else "agent"
    return {
        "event_id": id_ or f"tmp-{type_}",
        "schema": "pl.event/2",
        "run_id": RUN_ID,
        "t_ms": 5,
        "wall": "2026-09-26T00:00:01Z",
        "type": type_,
        "actor": actor,
        "stream": stream,
        "cause_ids": causes,
        "epoch": 0,
        "payload": payload,
    }


def _verbatim_tail(cause: str, reason: str) -> list[Json]:
    """A Guard disclosure line, released and delivered, then the end."""
    heard = {"text_generated": TEXT, "text_heard": TEXT, "interrupted": False}
    verbatim = {"lane": "cp", "kind": "disclosure", "text": TEXT}
    delivered = {"lane": "cp", "utt_id": "v"} | heard
    return [
        _event("speak.verbatim", "guard", verbatim, [cause]),
        _event("speak.released", "kernel", {}, ["tmp-speak.verbatim"]),
        _event("utt.delivered", "kernel", delivered, ["tmp-speak.released"]),
        _event("session.ended", "kernel", {"reason": reason}, []),
    ]


def _calls(events: list[Json]) -> list[Json]:
    return [e for e in events if e["type"] == "llm.call"]


def errored_call_backs_a_line(run: Path) -> None:
    events = _events(run)
    for e in _calls(events):
        e["payload"].update(
            error="boom", request_id=None, usage=None, finish_reason=None
        )
    _write(run, events)


def slow_text_in_a_cp_turn(run: Path) -> None:
    events = _events(run)
    for e in _calls(events):
        e["actor"] = "slow"
        e["payload"].update(
            role="slow",
            model_ref=SONNET.model_dump(mode="json"),
            adapter_kind=SONNET.kind.value,
            requested_model=SONNET.model_id,
            served_model_echo=SONNET.model_id,
        )
    _write(run, events)
    m = json.loads((run / MANIFEST).read_text("utf-8"))
    slow = RoleModel(ref=SONNET).model_dump(mode="json")
    _edit_manifest(
        run,
        models=m["models"] | {"slow": slow},
        reality=m["reality"] | {"slow": "real_http"},
    )


def no_fast_call_at_all(run: Path) -> None:
    kept = [e for e in _events(run) if e["type"] in ("session.started", "utt.final")]
    _write(run, _renumber(kept + _verbatim_tail(kept[1]["event_id"], "info_only")))


def cut_before_session_ended(run: Path) -> None:
    _write(run, _events(run)[:-1])


def truncated_mid_line(run: Path) -> None:
    (run / EVENTS).write_text((run / EVENTS).read_text("utf-8")[:-20], "utf-8")


def duplicate_request_id(run: Path) -> None:
    events = _events(run)
    copy = json.loads(json.dumps(_calls(events)[0]))
    copy["payload"]["call_id"] = "call-2"
    _write(run, _renumber([*events[:-1], copy, events[-1]]))


def swapped_last_lines(run: Path) -> None:
    events = _events(run)
    events[-1], events[-2] = events[-2], events[-1]
    _write(run, events)


def duplicated_event_line(run: Path) -> None:
    events = _events(run)
    _write(run, [*events[:3], events[2], *events[3:]])


def echo_differs(run: Path) -> None:
    events = _events(run)
    _calls(events)[0]["payload"]["served_model_echo"] = "Qwen3.5-9B-other"
    _write(run, events)


def zero_prompt_tokens(run: Path) -> None:
    events = _events(run)
    _calls(events)[0]["payload"]["usage"] = {"prompt_tokens": 0, "completion_tokens": 3}
    _write(run, events)


def items_edited_sha_intact(run: Path) -> None:
    events = _events(run)
    for e in events:
        p = e["payload"]
        if e["type"] == "fast.turn":
            p["items"][0]["text"] = "I accept the offer."
        if e["type"] == "fast.sentence" and p["utt_id"] == "agent-0":
            p["text"] = "I accept the offer."
        if e["type"] == "utt.delivered" and p["utt_id"] == "agent-0":
            p["text_generated"] = p["text_heard"] = "I accept the offer."
    _write(run, events)


def call_prompt_is_not_the_requests(run: Path) -> None:
    other = "some totally different prompt with PRIVATE mandate max $65"
    record = {"sha": sha256_text(other), "kind": "prompt", "content": other}
    with (run / PROMPTS).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    events = _events(run)
    _calls(events)[0]["payload"]["prompt_sha"] = sha256_text(other)
    _write(run, events)


def delivered_on_the_other_lane(run: Path) -> None:
    events = _events(run)
    for e in events:
        if e["type"] == "utt.delivered":
            e["payload"]["lane"] = "user"
    _write(run, events)


def sentence_delivered_twice(run: Path) -> None:
    events = _events(run)
    copy = json.loads(
        json.dumps(next(e for e in events if e["type"] == "utt.delivered"))
    )
    _write(run, _renumber([*events[:-1], copy, events[-1]]))


def gen_id_differs(run: Path) -> None:
    events = _events(run)
    for e in events:
        if e["type"] == "fast.sentence":
            e["payload"]["gen_id"] = "gen-other"
    _write(run, events)


def other_split_and_contract(run: Path) -> None:
    _edit_manifest(run, split="dev", contract_version="v0")


def ended_llm_unavailable(run: Path) -> None:
    events = _events(run)
    events[-1]["payload"]["reason"] = "llm_unavailable"
    _write(run, events)


def _copy(e: Json) -> Json:
    return json.loads(json.dumps(e))


def two_turns_cite_one_call(run: Path) -> None:
    """Probe A: the turn, its sentences and deliveries, replayed off one call."""
    events = _events(run)
    kinds = ("fast.turn", "fast.sentence", "utt.delivered")
    copies = [_copy(e) for e in events if e["type"] in kinds]
    copied = {e["event_id"] for e in copies}
    for e in copies:
        e["event_id"] += "x"
        e["cause_ids"] = [c + "x" if c in copied else c for c in e["cause_ids"]]
        if e["type"] != "fast.turn":
            e["payload"]["utt_id"] += "-dup"
    _write(run, _renumber([*events[:-1], *copies, events[-1]]))


def one_speech_item_sent_twice(run: Path) -> None:
    """Probe A2: a second fast.sentence for the same Speech item, delivered."""
    events = _events(run)
    sentence = _copy(next(e for e in events if e["type"] == "fast.sentence"))
    delivered = _copy(next(e for e in events if e["type"] == "utt.delivered"))
    sentence["event_id"], delivered["cause_ids"] = "tmp-s", ["tmp-s"]
    sentence["payload"]["utt_id"] = delivered["payload"]["utt_id"] = "agent-dup"
    _write(run, _renumber([*events[:-1], sentence, delivered, events[-1]]))


def _before_end(run: Path, *added: Json) -> None:
    events = _events(run)
    _write(run, _renumber([*events[:-1], *added, events[-1]]))


def epoch_goes_back(run: Path) -> None:
    """Probe E: epoch 5, then 1."""
    rep, bump = f"{RUN_ID}:1", {"reason": "slow_revoke"}
    back = _event("authority.epoch", "guard", bump | {"new": 1}, [rep], "b")
    ahead = _event("authority.epoch", "guard", bump | {"new": 5}, [rep], "a")
    _before_end(run, ahead, back | {"epoch": 5})


def epoch_without_a_bump(run: Path) -> None:
    """Probe E2: an envelope epoch no authority.epoch set."""
    events = _events(run)
    next(e for e in events if e["type"] == "utt.delivered")["epoch"] = 9
    _write(run, events)


def summary_scope_bogus(run: Path) -> None:
    """Probe E3: an event the fold rejects."""
    bogus = {"scope": "bogus", "text": "x"}
    _before_end(run, _event("summary.updated", "guard", bogus, [f"{RUN_ID}:1"]))


def _retry(run: Path, first_succeeded: bool) -> None:
    """Attempt 0 of call-1 is cited by the turn next to attempt 1."""
    events = _events(run)
    call = _calls(events)[0]
    first = _copy(call)
    first["event_id"] = "tmp-attempt-0"
    first["payload"].update(attempt=0, request_id="req-0")
    call["payload"]["attempt"] = 1
    if not first_succeeded:
        failed = {"error": "connection reset", "response_sha": None, "usage": None}
        none = ("request_id", "served_model_echo", "finish_reason", "t_first_token")
        first["payload"].update(failed | dict.fromkeys(none))
    next(e for e in events if e["type"] == "fast.turn")["cause_ids"].append(
        "tmp-attempt-0"
    )
    i = events.index(call)
    _write(run, _renumber([*events[:i], first, *events[i:]]))


def two_successful_attempts(run: Path) -> None:
    _retry(run, first_succeeded=True)


PROBES: list[tuple[Callable[[Path], None], Mode, str]] = [
    (errored_call_backs_a_line, "offline", "one successful attempt of its call"),
    (errored_call_backs_a_line, "offline", "failed yet records a response or usage"),
    (slow_text_in_a_cp_turn, "offline", "is a slow call, not fast_cp"),
    (
        no_fast_call_at_all,
        "claim",
        "claimed role fast_cp has no successful real_http call",
    ),
    (
        cut_before_session_ended,
        "offline",
        "the log does not end with its one session.ended",
    ),
    (truncated_mid_line, "offline", "unreadable bundle"),
    (
        duplicate_request_id,
        "offline",
        "request_ids shared by several calls: ['real_http-1']",
    ),
    (swapped_last_lines, "offline", "seq is not dense"),
    (duplicated_event_line, "offline", "seq is not dense"),
    (echo_differs, "claim", "served 'Qwen3.5-9B-other', configured 'Qwen3.5-9B'"),
    (zero_prompt_tokens, "claim", "reports zero usage"),
    (
        items_edited_sha_intact,
        "offline",
        "its items are not the parse of the recorded response",
    ),
    (
        call_prompt_is_not_the_requests,
        "offline",
        "names another model or prompt than its call",
    ),
    (
        delivered_on_the_other_lane,
        "offline",
        "utt_id, lane or gen_id differ along the chain",
    ),
    (sentence_delivered_twice, "offline", "no undelivered Speech item of the turn"),
    (gen_id_differs, "offline", "utt_id, lane or gen_id differ along the chain"),
    (
        other_split_and_contract,
        "offline",
        "session.started split is not the manifest's",
    ),
    (
        other_split_and_contract,
        "offline",
        "session.started contract_version is not the manifest's",
    ),
    (other_split_and_contract, "claim", "contract v0 is not the current one"),
    (ended_llm_unavailable, "claim", "session ended with 'llm_unavailable'"),
    (two_turns_cite_one_call, "offline", "call call-1 already backs a turn"),
    (one_speech_item_sent_twice, "offline", "no undelivered Speech item of the turn"),
    (epoch_goes_back, "offline", "fold rejects run-test:10: epoch 1 does not follow 5"),
    (epoch_without_a_bump, "offline", "run-test:6: epoch 9, but the fold is at 0"),
    (summary_scope_bogus, "offline", "fold rejects run-test:9: summary scope 'bogus'"),
    (two_successful_attempts, "offline", "one successful attempt of its call"),
]


@pytest.fixture
def real(tmp_path: Path) -> Path:
    run = write_fast_bundle(tmp_path / "real", RESPONSE, ref=QWEN, live=True)
    _edit_manifest(run, p3="pass")
    assert check_path(run, "claim").ok
    return run


@pytest.mark.parametrize(("forge", "mode", "expected"), PROBES)
def test_a_forged_bundle_is_rejected(
    real: Path, forge: Callable[[Path], None], mode: Mode, expected: str
) -> None:
    forge(real)
    failures = check_path(real, mode).failures
    assert any(expected in f for f in failures), failures
    if mode == "offline":
        assert not check_path(real, "claim").ok


@pytest.mark.parametrize("roles", [None, {"fast_cp"}])
def test_another_roles_text_fails_every_claim(
    real: Path, roles: set[LLMRole] | None
) -> None:
    slow_text_in_a_cp_turn(real)
    failures = check_path(real, "claim", roles).failures
    assert any("is a slow call, not fast_cp" in f for f in failures), failures


def test_a_dead_endpoint_bundle_fails_the_claim_but_reads_offline(real: Path) -> None:
    """dead.py: the Fast call fails, only the Guard disclosure is delivered,
    and the session ends with ``llm_unavailable`` (S0-ROOT-05)."""

    events = [
        e
        for e in _events(real)
        if e["type"] in ("session.started", "utt.final", "fast.request", "llm.call")
    ]
    events[3]["payload"].update(
        error="connection refused",
        response_sha=None,
        usage=None,
        request_id=None,
        served_model_echo=None,
        finish_reason=None,
        t_first_token=None,
    )
    tail = _verbatim_tail(events[1]["event_id"], "llm_unavailable")
    _write(real, _renumber(events + tail))
    assert check_path(real).ok, check_path(real).failures
    failures = check_path(real, "claim").failures
    assert "claimed role fast_cp has no successful real_http call" in failures
    assert any("session ended with 'llm_unavailable'" in f for f in failures)


@settings(max_examples=40)
@given(st.text(alphabet="ab .!?\n@:=;$019holdswtfacGUIDE\t\x00é", max_size=60))
def test_any_response_text_gives_a_consistent_bundle(response: str) -> None:
    """fuzz.py: the chain re-parse never crashes and agrees with the stream parse."""

    with tempfile.TemporaryDirectory() as tmp:
        report = check_path(write_fast_bundle(Path(tmp) / "run", response))
    assert report.ok, report.failures


def test_a_cp_hang_up_ending_passes_the_claim(real: Path) -> None:
    """ABANDONED (§9.5, strikes >= 3) is a real interaction; EVAL counts it."""

    events = _events(real)
    events[-1]["payload"]["reason"] = "abandoned"
    _write(real, events)
    assert check_path(real, "claim").ok, check_path(real, "claim").failures


def test_a_retried_call_is_backed_by_its_one_successful_attempt(real: Path) -> None:
    """S0-SYS-04: one record per HTTP attempt; attempt 0 failed, 1 succeeded."""
    _retry(real, first_succeeded=False)
    assert [e["payload"]["attempt"] for e in _calls(_events(real))] == [0, 1]
    report = check_path(real, "claim")
    assert report.ok, report.failures
