"""run_session end to end on fakes: the chain, disclosure, abort and live mode."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tests.contract.samples import session_config
from tests.support.fakes import RepeatingLLM, fake_ref
from tests.support.sessions import (
    Person,
    act,
    ear,
    fake,
    only_bundle,
    patient_task,
    reply,
    run,
)

from proxyloop.cli import main
from proxyloop.contract.events import Event
from proxyloop.contract.llm import (
    AdapterKind,
    LLMClient,
    LLMRole,
    LLMUnavailable,
    ModelRef,
)
from proxyloop.core.fold import fold
from proxyloop.evidence.check import check_path
from proxyloop.kernel.session import DISCLOSURE, run_session
from proxyloop.kernel.speaker import heard_prefix
from proxyloop.llm.factory import LiveModeError
from proxyloop.llm.http import RecordSink

NAME = "Dana Reyes"
SCRIPTS = {
    "simuser": [
        reply(
            f"Please get me a lower price. I am {NAME}.",
            **{"account.holder_name": NAME},
        )
    ],
    "fast_user": [
        f"Sure, I will call them now.\n@slow: fact account.holder_name={NAME}"
    ],
    "ear": [ear("other"), ear("ask_discount")],
    "mouth": ["Okay."],
    "fast_cp": ["Could you lower the monthly price?\n@slow: fact monthly_price=75.00"],
    "slow": [
        act(
            "The user wants a lower price.",
            {"tool": "tell_user", "text": "I am calling them now."},
            {"tool": "record_fact", "key": "account.holder_name", "value": NAME},
            public=f"Calling for {NAME}, who pays at most 70 a month.",
        ),
        act("Waiting for the call.", {"tool": "wait", "seconds": 5}),
    ],
}
FINISH = act("Done.", {"tool": "finish", "outcome": "info_only", "summary": "ok"})
UNTIL = {"slow": ("] cp_update", FINISH)}  # Slow ends once the call relayed


PERSON = ["Hi, I am calling about my bill.", "Can you lower my price?"]


def _of(events: tuple[Event, ...], type_: str) -> list[Event]:
    return [e for e in events if e.type == type_]


def test_a_full_session_runs_on_fakes_and_passes_the_offline_check(
    tmp_path: Path,
) -> None:
    result = run(tmp_path, SCRIPTS, until=UNTIL)
    assert result.reason == "info_only"
    report = check_path(result.path, "offline")
    assert report.ok, report.failures
    events = only_bundle(tmp_path).events
    kinds = {e.payload["lane"] for e in _of(events, "utt.delivered")}
    assert kinds == {"user", "cp"}  # both lanes spoke, and every line has its chain
    assert {e.payload["role"] for e in _of(events, "llm.call")} >= {
        "fast_cp",
        "slow",
        "ear",
    }
    assert _of(events, "user.sim") and _of(events, "rep.mouth")  # the world ran
    assert events[-1].payload["reason"] == "info_only"


def test_the_disclosure_is_the_first_cp_agent_utterance(tmp_path: Path) -> None:
    run(tmp_path, SCRIPTS, until=UNTIL)
    events = only_bundle(tmp_path).events
    by_id = {e.event_id: e for e in events}
    first = next(
        e for e in events if e.type == "utt.delivered" and e.payload["lane"] == "cp"
    )
    assert first.payload["text_heard"] == DISCLOSURE
    released = by_id[first.cause_ids[0]]
    verbatim = by_id[released.cause_ids[0]]
    assert (released.type, verbatim.type, verbatim.actor) == (
        "speak.released",
        "speak.verbatim",
        "guard",
    )
    assert verbatim.payload["kind"] == "disclosure"
    fast = [
        e for e in events if e.type == "fast.sentence" and e.payload["lane"] == "cp"
    ]
    assert fast and fast[0].seq > first.seq


def test_a_public_summary_with_a_private_bound_is_denied(tmp_path: Path) -> None:
    run(tmp_path, SCRIPTS, until=UNTIL)
    events = only_bundle(tmp_path).events
    (denied,) = _of(events, "declass.denied")
    assert denied.payload["violations"] == ["number 70 is not source-bound"]
    assert "70" not in fold(events).public.summary
    public = [
        e for e in _of(events, "summary.updated") if e.payload["scope"] == "public"
    ]
    assert public == []


def test_a_dead_endpoint_aborts_loudly_and_nothing_is_delivered_after(
    tmp_path: Path,
) -> None:
    with pytest.raises(LLMUnavailable):
        run(tmp_path, SCRIPTS | {"slow": [act("Waiting.")]}, dead=["fast_cp"])
    events = only_bundle(tmp_path).events
    assert events[-1].type == "session.ended"
    assert events[-1].payload["reason"] == "llm_unavailable"
    failed = next(e for e in _of(events, "llm.call") if e.payload["error"])
    assert failed.payload["role"] == "fast_cp"
    assert not [e for e in _of(events, "utt.delivered") if e.seq > failed.seq]


def test_live_mode_refuses_a_non_real_http_client_at_startup(tmp_path: Path) -> None:
    def fakes(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        return RepeatingLLM(fake(role), ["unused"], on_record=sink)

    live = session_config()  # every role real_http
    with pytest.raises(LiveModeError, match="test_fake"):  # an injected fake
        asyncio.run(run_session(live, patient_task(), runs_dir=tmp_path, clients=fakes))
    baseline = ModelRef(kind=AdapterKind.BASELINE, endpoint=None, model_id="fsm")
    cfg = session_config(fast_cp=baseline.model_dump())  # the contract allows it
    with pytest.raises(LiveModeError, match="fast_cp"):  # src/ cannot build it live
        asyncio.run(run_session(cfg, patient_task(), runs_dir=tmp_path))
    assert not list(tmp_path.iterdir())  # refused before anything was written
    with pytest.raises(ValueError, match="live mode refuses"):  # and the contract
        session_config(fast_cp=fake_ref().model_dump())


def test_rep_chat_is_a_session_with_a_person_speaking_for_the_agent(
    tmp_path: Path,
) -> None:
    person = Person([*PERSON, "/quit"])
    result = run(tmp_path, SCRIPTS, channels={"cp": "sim", "cp_agent": person})
    assert result.reason == "stopped"
    assert check_path(result.path, "offline").ok
    events = only_bundle(tmp_path).events
    said = [e for e in _of(events, "utt.final") if e.payload["speaker"] == "agent"]
    assert [e.payload["text"] for e in said] == PERSON
    ears = _of(events, "rep.ear")
    assert {c for e in ears for c in e.cause_ids} >= {e.event_id for e in said}
    assert all(
        any(c in {x.event_id for x in _of(events, "llm.call")} for c in e.cause_ids)
        for e in ears
    )
    roles = {e.payload["role"] for e in _of(events, "llm.call")}
    assert not roles & {"fast_user", "fast_cp"}  # no Fast lane ran
    assert person.heard  # the person read the rep's lines


def test_heard_prefix_cuts_on_words() -> None:
    text = "One two three four five."
    assert heard_prefix(text, 0.3) == ""
    assert heard_prefix(text, 1.0) == "One two"
    assert heard_prefix(text, 60) == text


def test_the_terminal_replay_reads_the_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(tmp_path, SCRIPTS, until=UNTIL)
    assert main(["replay", f"RUN={result.path}"]) == 0
    out = capsys.readouterr().out
    assert DISCLOSURE in out and "evidence-check offline: ok" in out


def test_guide_fast_changes_fastcs_rendered_view(tmp_path: Path) -> None:
    guide = act("Steer the call.", {"tool": "guide_fast", "move": "ask_discount"})
    scripts = SCRIPTS | {
        "slow": [guide, act("Waiting.", {"tool": "wait", "seconds": 5})]
    }
    result = run(tmp_path, scripts, until=UNTIL)
    assert check_path(result.path, "offline").ok
    bundle = only_bundle(tmp_path)
    move = "Ask whether they can lower the monthly price."
    requests = [
        e for e in _of(bundle.events, "fast.request") if e.payload["lane"] == "cp"
    ]
    seen = [
        move in bundle.prompts[str(e.payload["prompt_sha"])].content for e in requests
    ]
    assert any(seen), "FastC never rendered Slow's guidance"
    guided = [e for e in _of(bundle.events, "s2f.msg") if e.payload["type"] == "GUIDE"]
    voiced = {e.payload["msg_id"] for e in _of(bundle.events, "s2f.voiced")}
    assert guided and guided[0].payload["msg_id"] in voiced
