"""Pull-through's label-source selector (S1-MOD-07): hosted Fast turns as labels.

The bundle comes from a real kernel session over the test seams: both Fast lanes on a
``real_http`` OpenRouter ref answered by the ``tests/support`` scripted double, so every
Fast request goes the kernel's messages path (no vLLM, no tokenizer). Rows are built
and P5-checked under the pinned Qwen tokenizer, exactly as the base-9B source does."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.kernel.test_session import SCRIPTS, UNTIL
from tests.serving.test_config import make
from tests.support.sessions import fake_config, run
from tests.training.test_pull_through import (
    FPS,
    SPEECH_AFTER_PAUSE,
    cp_saying,
    tok,
    with_calls,
)

from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.contract.bundle import Bundle, read_bundle
from proxyloop.contract.config import SessionConfig
from proxyloop.contract.llm import (
    AdapterKind,
    ModelRef,
    TextRequest,
    request_content,
)
from proxyloop.contract.protocol import render_messages, render_prompt
from proxyloop.contract.views import FastView
from proxyloop.training import pull_through as pt

LUNA = ModelRef(
    kind=AdapterKind.REAL_HTTP,
    endpoint="openrouter",
    model_id="openai/gpt-6-luna",
    reasoning_effort="none",
)
LABEL_MODEL = "openrouter:openai/gpt-6-luna"
HOSTED = pt.label_source("hosted", LABEL_MODEL)
Json = dict[str, Any]


@pytest.fixture(scope="module")
def hosted(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("hosted")
    roles = dict.fromkeys(("fast_user", "fast_cp"), LUNA)
    cfg = SessionConfig.model_validate(fake_config().model_dump() | roles)
    run(root / "luna", SCRIPTS, cfg=cfg, until=UNTIL)
    return root


def luna(hosted: Path) -> Bundle:
    (run_dir,) = (hosted / "luna").iterdir()
    return read_bundle(run_dir)


def lane_of(t: pt.Turn) -> str:
    return str(json.loads(t.view)["lane"])


def test_a_hosted_session_yields_rows_that_pass_p5_with_their_provenance(
    hosted: Path,
):
    b = luna(hosted)
    turns, funnel = pt.select([b], FPS, HOSTED)
    assert turns and funnel["selected"] == len(turns)
    assert {lane_of(t) for t in turns} == {"user", "cp"}
    for t in turns:  # the recorded sha is the messages sha, never a Qwen prompt's
        messages = render_messages(FastView.model_validate_json(t.view), t.profile)
        request = TextRequest(
            call_id="x", role="fast_cp", messages=messages, max_tokens=1, temperature=0
        )
        assert t.prompt_sha == sha256_text(request_content(request))
        qwen = render_prompt(FastView.model_validate_json(t.view), t.profile, tok())
        assert sha256_text(qwen) != t.prompt_sha
    doc = pt.rows_doc(turns, funnel, FPS, tok(), HOSTED)
    assert doc["p5"] == {
        "ok": True,
        "rows": len(turns),
        "failed": [],
        "dropped_prompt_mismatch": 0,
    }
    assert doc["source"] == "hosted openrouter:openai/gpt-6-luna (teacher_exec)"
    assert doc["rows"] == [[t.profile, t.view, t.raw] for t in turns]
    assert doc["dataset_hash"] == sha256_text(canonical_json(doc["rows"]))
    by_id = {e.event_id: e for e in b.events}
    calls = {e.payload["call_id"]: e.payload for e in b.events if e.type == "llm.call"}
    for t, prov in zip(turns, doc["provenance"], strict=True):
        call = calls[by_id[t.event_id].payload["call_id"]]
        assert call["request_id"]
        assert prov == {
            "run_id": b.manifest.run_id,
            "event_id": t.event_id,
            "lane": lane_of(t),
            "profile": t.profile,
            "model_ref": {
                "endpoint": "openrouter",
                "model_id": "openai/gpt-6-luna",
                "reasoning_effort": "none",
            },
            "served_model_echo": "openai/gpt-6-luna",
            "request_id": call["request_id"],
            "sampling_sent": call["sampling_sent"],
            "resamples": None,  # no TeacherRepair in this session
            "attempt": 0,
        }
    assert pt.provenance_summary(doc) == {
        "label_models": [LUNA.model_dump(mode="json", exclude={"kind"})],
        "rows": len(turns),
        "run_ids": [b.manifest.run_id],
    }
    repaired = tuple(  # a TeacherRepair turn notes its resamples (kernel/lanes.py)
        e.model_copy(update={"payload": e.payload | {"resamples": 2}})
        if e.type == "fast.turn"
        else e
        for e in b.events
    )
    again, _ = pt.label_turns(Bundle(b.manifest, repaired, b.prompts), HOSTED)
    assert [t.provenance["resamples"] for t in again] == [2] * len(turns)


def test_the_select_command_takes_the_source_explicitly(
    hosted: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(pt, "load_tokenizer", tok)
    args = ["select", "--dir", str(tmp_path), "--evidence", str(hosted)]
    assert pt.main([*args, "--source", "hosted", "--label-model", LABEL_MODEL]) == 0
    doc = json.loads((tmp_path / "rows.json").read_text("utf-8"))
    assert doc["p5"]["ok"] and len(doc["provenance"]) == len(doc["rows"]) > 0
    assert doc["source"] == HOSTED.label
    for bad in (
        [],  # no source at all
        ["--source", "hosted"],  # no label model
        ["--source", "fsm"],  # a closed choice
        ["--source", "base_9b", "--label-model", LABEL_MODEL],
        ["--source", "hosted", "--label-model", "openai/gpt-6-luna"],  # no endpoint
        ["--source", "hosted", "--label-model", "nowhere:openai/gpt-6-luna"],
        ["--source", "hosted", "--label-model", "vllm:Qwen3.5-9B"],  # base_9b's
    ):
        with pytest.raises(SystemExit):
            pt.main([*args[:2], str(tmp_path / "bad"), *args[3:], *bad])
    assert not (tmp_path / "bad").exists()


def test_the_base_source_takes_nothing_from_a_hosted_bundle(hosted: Path):
    turns, funnel = pt.select([luna(hosted)], FPS, pt.BASE_9B)
    assert not turns and funnel["not_base_real_http"] > 0


def with_views(b: Bundle, lane: str, change: Callable[[Json], Json]) -> Bundle:
    """``b`` with every ``lane`` view stored for a request edited (a copy)."""
    shas = {
        str(e.payload["view_sha"])
        for e in b.events
        if e.type == "fast.request" and e.payload["lane"] == lane
    }
    prompts = {
        s: r.model_copy(update={"content": json.dumps(change(json.loads(r.content)))})
        if s in shas
        else r
        for s, r in b.prompts.items()
    }
    return Bundle(b.manifest, b.events, prompts)


def with_requests(b: Bundle, lane: str, **update: object) -> Bundle:
    """``b`` with every ``lane`` fast.request payload updated (a copy)."""
    events = tuple(
        e.model_copy(update={"payload": e.payload | update})
        if e.type == "fast.request" and e.payload["lane"] == lane
        else e
        for e in b.events
    )
    return Bundle(b.manifest, events, b.prompts)


def skipped(b: Bundle) -> tuple[list[pt.Turn], dict[str, int]]:
    turns, counts = pt.label_turns(b, HOSTED)
    return turns, dict(counts)


def test_hosted_turns_from_another_model_or_unclean_are_skipped_and_counted(
    hosted: Path,
):
    b = luna(hosted)
    clean, none = skipped(b)
    n, n_cp = len(clean), sum(lane_of(t) == "cp" for t in clean)
    assert n and n_cp and not none
    other = LUNA.model_dump(mode="json") | {"model_id": "openai/gpt-6-sol"}
    replay = LUNA.model_dump(mode="json") | {"kind": "recorded_replay"}
    for update in (
        {"model_ref": other, "requested_model": "openai/gpt-6-sol"}
        | {"served_model_echo": "openai/gpt-6-sol"},
        {"model_ref": LUNA.model_dump(mode="json") | {"endpoint": "relay"}},
        {"model_ref": replay, "adapter_kind": "recorded_replay"},  # same id and echo
    ):
        turns, counts = skipped(with_calls(b, **update))
        assert not turns and counts["not_label_model"] >= n
    turns, counts = skipped(with_calls(b, served_model_echo="openai/gpt-6-luna-0901"))
    assert not turns and counts["echo_mismatch"] >= n
    turns, counts = skipped(with_calls(b, finish_reason="length"))
    assert not turns and counts["finish_length"] >= n
    turns, counts = skipped(cp_saying(b, SPEECH_AFTER_PAUSE))  # pl_cp_v3: not clean
    assert not [t for t in turns if lane_of(t) == "cp"]
    assert counts["empty_or_parse_issue"] >= n_cp
    turns, counts = skipped(with_calls(b, prompt_sha=sha256_text("other request")))
    assert not turns and counts == {"call_prompt_mismatch": n}
    for update in ({"error": "cancelled"}, {"response_sha": None}):
        turns, counts = skipped(with_calls(b, **update))
        assert not turns and counts["cancelled_or_no_response"] >= n
    turns, counts = skipped(cancelled_after_its_turn(b, clean[0]))
    assert turns == clean[1:] and counts == {"cancelled_or_no_response": 1}


def cancelled_after_its_turn(b: Bundle, t: pt.Turn) -> Bundle:
    """``b`` with ``t``'s generation cancelled after its turn: its line lost the floor
    to a verbatim line (S1-SYS-59's ``fast.cancelled{verbatim}``). A copy."""
    turn = next(e for e in b.events if e.event_id == t.event_id)
    last = b.events[-1]
    cancel = turn.model_copy(
        update={
            "seq": last.seq + 1,
            "event_id": f"{b.manifest.run_id}:{last.seq + 1}",
            "type": "fast.cancelled",
            "cause_ids": (turn.event_id,),
            "payload": {"gen_id": turn.payload["gen_id"], "reason": "verbatim"},
        }
    )
    return Bundle(b.manifest, (*b.events, cancel), b.prompts)


def test_a_hosted_turn_whose_view_or_sent_messages_differ_is_skipped(hosted: Path):
    b = luna(hosted)
    clean, _ = skipped(b)
    n_cp = sum(lane_of(t) == "cp" for t in clean)
    edited = with_views(b, "cp", lambda v: v | {"brief": v["brief"] + " Be brief."})
    sha = sha256_text("other messages")
    asked = with_requests(b, "cp", prompt_sha=sha)  # its record still hashes the view's
    turns, counts = skipped(asked)
    assert {lane_of(t) for t in turns} == {"user"}
    assert counts == {"call_prompt_mismatch": n_cp}
    answered = tuple(  # the record agrees with the request, the view does not
        e.model_copy(update={"payload": e.payload | {"prompt_sha": sha}})
        if e.type == "llm.call" and e.payload["role"] == "fast_cp"
        else e
        for e in asked.events
    )
    for changed in (edited, Bundle(b.manifest, answered, b.prompts)):
        turns, counts = skipped(changed)
        assert {lane_of(t) for t in turns} == {"user"}
        assert counts == {"messages_sha_mismatch": n_cp}
    # pl_cp_v2 renders as pl_cp_v3 does (only the grammar differs): the identity
    # holds, and the turn is parsed under the recorded profile.
    turns, counts = skipped(with_requests(b, "cp", profile="pl_cp_v2"))
    assert len(turns) == len(clean) and "messages_sha_mismatch" not in counts
    assert {t.profile for t in turns if lane_of(t) == "cp"} == {"pl_cp_v2"}


def test_make_full_needs_an_explicit_label_source_even_under_dry_run():
    blank = {"PT_SOURCE": "", "PT_LABEL_MODEL": ""}
    for argv, needs in (
        ((), "PT_SOURCE"),
        (("PT_SOURCE=fsm",), "PT_SOURCE"),
        (("PT_SOURCE=hosted",), "PT_LABEL_MODEL"),
        (("PT_SOURCE=base_9b", f"PT_LABEL_MODEL={LABEL_MODEL}"), "PT_LABEL_MODEL"),
    ):
        with pytest.raises(subprocess.CalledProcessError) as failed:
            make("pull-through", "MODE=full", *argv, env=blank)
        assert needs in failed.value.stderr and "modal run" not in failed.value.stdout
    hosted = make(
        "pull-through",
        "MODE=full",
        "PT_SOURCE=hosted",
        f"PT_LABEL_MODEL={LABEL_MODEL}",
        "PT_EVIDENCE=evidence/s1/pull-through",
        env=blank,
    )
    assert f"--source hosted --label-model {LABEL_MODEL}" in hosted
    assert "--evidence evidence/s1/pull-through" in hosted
    base = make("pull-through", "MODE=full", "PT_SOURCE=base_9b", env=blank)
    assert "--source base_9b" in base and "--label-model" not in base
    verify = make("pull-through", "MODE=verify", env=blank)  # no select, no source
    assert " select " not in verify and "--mode verify" in verify
