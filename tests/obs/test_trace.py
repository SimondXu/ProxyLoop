"""The offline span mapping (ADR-0008): causes, services, timing, privacy and
rule 11, on fixture bundles built with the real contract models."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from tests.contract.samples import GEMINI, QWEN, SONNET
from tests.obs.bundles import Log, manifest, write

from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS, PromptRecord
from proxyloop.contract.llm import LLMCallRecord, LLMRole, ModelRef, Usage
from proxyloop.obs import trace
from proxyloop.obs.trace import Refused, SpanRecord

_ACTOR = {"fast_user": "fast.user", "fast_cp": "fast.cp", "slow": "slow"}
PRIVATE = "PRIV"  # every private string below carries it
PUBLIC_CP = ("CP-REP-LINE", "CP-AGENT-HEARD", "CP-PROMPT-PUBLIC")


def llm(
    log: Log,
    role: LLMRole,
    ref: ModelRef,
    t: tuple[int, int],
    cause: str,
    prompt_sha: str = "p",
    error: str | None = None,
) -> str:
    record = LLMCallRecord(
        call_id=f"{role}:{len(log.events)}",
        role=role,
        model_ref=ref,
        adapter_kind=ref.kind,
        requested_model=ref.model_id,
        served_model_echo=None if error else f"{ref.model_id}-served",
        request_id=None,
        prompt_sha=prompt_sha,
        response_sha=None if error else "r",
        usage=None if error else Usage(prompt_tokens=10, completion_tokens=3),
        t_start=t[0],
        t_first_token=None,
        t_end=t[1],
        finish_reason=None if error else "stop",
        attempt=0,
        error=error,
    )
    actor = _ACTOR.get(role, f"world.{role}")
    stream = "world" if actor.startswith("world.") else "agent"
    return log.add("llm.call", actor, stream, record.model_dump(mode="json"), (cause,))


def collect(run: Path, content: bool = False, follow: bool = False) -> list[SpanRecord]:
    out: list[SpanRecord] = []
    trace.export(run, out.extend, content, follow)
    return out


def private_bundle(path: Path) -> Path:
    """Distinctive private strings in every place ADR-0008 must keep out."""
    log = Log("rP")
    user = log.add("chan.opened", "kernel", "agent", {"lane": "user"}, (log.start,))
    msg = log.add("user.msg", "kernel", "agent", {"text": "PRIV-USERMSG"})
    rep = log.add(
        "utt.final",
        "kernel",
        "agent",
        {"lane": "cp", "speaker": "rep", "utt_id": "cp-1", "text": "CP-REP-LINE"},
    )
    f2s: dict[str, object] = {
        "msg_id": "f1",
        "lane": "user",
        "gen_id": "user-g1",
        "utt_ref": None,
        "type": "USER_UPDATE",
        "facts": [["account.last4", "PRIV-FACT-4821"]],
        "text": "PRIV-F2S-TEXT",
    }
    log.add("f2s.msg", "fast.user", "agent", f2s, (msg,))
    tool: dict[str, object] = {
        "name": "act",
        "args": {"x": "PRIV-TOOL-ARG"},
        "result_text": "PRIV-TOOL-RESULT",
        "ok": True,
    }
    log.add("slow.tool", "slow", "agent", tool, (msg,))
    summary: dict[str, object] = {"scope": "private", "text": "PRIV-SUMMARY"}
    log.add("summary.updated", "guard", "agent", summary, (msg,))
    s2f: dict[str, object] = {
        "msg_id": "s1",
        "lane": "user",
        "type": "TELL_USER",
        "text": "PRIV-S2F",
    }
    log.add("s2f.msg", "guard", "agent", s2f, (msg,))
    guide: dict[str, object] = {"move": "ask_discount", "slots": []}
    s2f_cp: dict[str, object] = {
        "msg_id": "s2",
        "lane": "cp",
        "type": "GUIDE",
        "guide": guide,
    }
    log.add("s2f.msg", "guard", "agent", s2f_cp, (rep,))
    for lane, text in (("user", "PRIV-USER-UTT"), ("cp", "CP-AGENT-HEARD")):
        heard: dict[str, object] = {
            "lane": lane,
            "utt_id": f"{lane}-g1-u0",
            "text_generated": f"{text}-generated-{PRIVATE}",
            "text_heard": text,
            "interrupted": False,
        }
        log.add("utt.delivered", "kernel", "agent", heard, (user,))
    mandate: dict[str, object] = {
        "mandate_id": "PRIV-MANDATE",
        "mandate_hash": "h",
        "status": "proposed",
        "epoch": 0,
        "max_monthly_price_minor": 4821,
        "required_features": ["PRIV-FEATURE"],
    }
    log.add("mandate.proposed", "guard", "agent", mandate, (msg,))
    log.add("declass.denied", "guard", "agent", {"violations": ["PRIV-DECL"]}, (msg,))
    free: dict[str, object] = {  # a tool name is the Slow model's choice
        "name": "card 4821 PRIV",
        "args": {},
        "result_text": "unknown tool",
        "ok": False,
    }
    log.add("slow.tool", "slow", "agent", free, (msg,))
    denied: dict[str, object] = {"intent": "x", "reason": "PRIV free text"}
    log.add("action.denied", "guard", "agent", denied, (msg,))
    llm(log, "fast_user", QWEN, (100, 400), msg, "sha-user")
    llm(log, "fast_cp", QWEN, (150, 500), rep, "sha-cp")
    llm(log, "slow", SONNET, (200, 600), msg, "sha-slow")
    log.end("done")
    write(path, log, manifest("rP"))
    prompts = [
        PromptRecord(sha="sha-user", kind="prompt", content="PRIV-FASTUSER-PROMPT"),
        PromptRecord(sha="sha-cp", kind="prompt", content="CP-PROMPT-PUBLIC"),
        PromptRecord(sha="sha-slow", kind="messages", content="PRIV-SLOW-PROMPT"),
    ]
    (path / PROMPTS).write_text(
        "".join(p.model_dump_json() + "\n" for p in prompts), "utf-8"
    )
    return path


def test_private_values_never_reach_a_span(tmp_path: Path) -> None:
    run = private_bundle(tmp_path / "rP")
    plain = trace.to_json(collect(run))
    rich = trace.to_json(collect(run, content=True))
    assert PRIVATE not in plain and PRIVATE not in rich
    assert not any(text in plain for text in PUBLIC_CP)
    assert all(text in rich for text in PUBLIC_CP)
    assert '"pl.move": "ask_discount"' in plain and '"pl.scope": "private"' in plain
    tools = [s.attributes["pl.name"] for s in collect(run) if s.name == "slow.tool"]
    assert tools == ["act", "unknown"]


def test_parents_links_services_and_times(tmp_path: Path) -> None:
    log = Log("rT")
    msg = log.add("user.msg", "kernel", "agent", {"text": "hi"})
    rep = log.add("chan.strike", "kernel", "agent", {"lane": "cp"})
    both = log.add("chan.hold", "fast.cp", "agent", {"lane": "cp"}, (rep, msg))
    call = llm(log, "ear", GEMINI, (250, 900), both, error="HTTP 503")
    tool: dict[str, object] = {
        "name": "wait",
        "args": {},
        "result_text": "",
        "ok": True,
    }
    log.add("slow.tool", "slow", "agent", tool, (call,))
    log.end("done")
    run = write(tmp_path / "rT", log, manifest("rT"))
    spans = collect(run)

    assert [s.name for s in spans] == [e.type for e in log.events]
    root, *rest = spans
    assert root.parent_id is None and root.service == "kernel"
    assert {s.trace_id for s in spans} == {trace.trace_id("rT")}
    for event, span in zip(log.events[1:], rest, strict=True):
        assert span.span_id == trace.span_id(event.event_id)
        causes = [trace.span_id(c) for c in event.cause_ids] or [root.span_id]
        assert (span.parent_id, *span.links) == tuple(causes)
    by = {s.name: s for s in spans}
    assert by["chan.hold"].service == "cp" and by["slow.tool"].service == "slow"
    ear = by["llm.call"]
    assert ear.service == "ear" and ear.status == "ERROR"
    assert ear.end_ns - ear.start_ns == 650 * 10**6
    assert ear.start_ns - root.start_ns == 250 * 10**6  # root is at t_ms 0 here
    assert ear.attributes["gen_ai.request.model"] == GEMINI.model_id
    assert "gen_ai.response.model" not in ear.attributes
    assert by["slow.tool"].attributes["pl.name"] == "wait"
    assert collect(run) == spans  # the same bundle, the same trace


def test_llm_attributes_and_world_service(tmp_path: Path) -> None:
    run = private_bundle(tmp_path / "rP")
    calls = [s for s in collect(run) if s.name == "llm.call"]
    assert [c.service for c in calls] == ["fast_user", "fast_cp", "slow"]
    slow = calls[2].attributes
    assert slow["gen_ai.response.model"] == f"{SONNET.model_id}-served"
    assert slow["pl.endpoint"] == SONNET.endpoint
    assert (slow["gen_ai.usage.input_tokens"], slow["gen_ai.usage.output_tokens"]) == (
        10,
        3,
    )
    log = Log("rW")
    policy: dict[str, object] = {"from": 0, "to": 1, "intent": "x", "rung": 0}
    log.add("rep.policy", "world.policy", "world", policy)
    assert collect(write(tmp_path / "rW", log, None))[1].service == "world"


def test_a_partial_last_line_waits_unless_the_bundle_is_finished(
    tmp_path: Path,
) -> None:
    log = Log("rL")
    log.end("done")
    run = write(tmp_path / "rL", log, None)
    lines = (run / EVENTS).read_text("utf-8").splitlines()
    (run / EVENTS).write_text(lines[0] + "\n" + lines[1][:40], "utf-8")
    assert [s.name for s in collect(run)] == ["session.started"]  # being written
    (run / MANIFEST).write_text(manifest("rL").model_dump_json(), "utf-8")
    with pytest.raises(ValueError, match="partial line"):
        collect(run)


def test_time_starts_at_session_started_wall(tmp_path: Path) -> None:
    log = Log("rO")
    log.events[0] = start = log.events[0].model_copy(update={"t_ms": 109})
    llm(log, "slow", SONNET, (200, 300), log.start)
    log.end("done")
    root, call, _ = collect(write(tmp_path / "rO", log, manifest("rO")))
    wall = trace._ns(start.wall)  # pyright: ignore[reportPrivateUsage]
    assert root.start_ns == wall
    assert (call.start_ns, call.end_ns) == (wall + 91 * 10**6, wall + 191 * 10**6)


def test_follow_tails_until_session_ended(tmp_path: Path) -> None:
    log = Log("rF")
    log.add("user.msg", "kernel", "agent", {"text": "hi"})
    log.end("done")
    run = tmp_path / "rF"
    run.mkdir()
    lines = [e.model_dump_json() + "\n" for e in log.events]

    def writer() -> None:
        with (run / EVENTS).open("a", encoding="utf-8") as f:
            for line in lines:
                for part in (line[:30], line[30:]):  # a line in two writes
                    f.write(part)
                    f.flush()
                    time.sleep(0.05)

    batches: list[list[SpanRecord]] = []
    thread = threading.Thread(target=writer)
    thread.start()
    trace.export(run, lambda b: batches.append(list(b)), follow=True)
    thread.join()
    assert [s.name for b in batches for s in b] == [e.type for e in log.events]


def _refused(run: Path, follow: bool = False) -> None:
    out: list[SpanRecord] = []
    with pytest.raises(Refused):
        trace.export(run, out.extend, follow=follow)
    assert out == []


def test_a_sealed_path_is_refused(tmp_path: Path) -> None:
    log = Log("rS")
    log.end("done")
    _refused(write(tmp_path / "evidence" / "s4" / "test" / "rS", log, manifest("rS")))
    _refused(tmp_path / "evidence" / "S4" / "Test" / "rS")  # case-folded
    (tmp_path / "link").symlink_to(tmp_path / "evidence" / "s4")
    _refused(tmp_path / "link" / "test" / "rS")


def test_a_test_split_is_refused(tmp_path: Path) -> None:
    log = Log("rX", split="test")
    log.end("done")
    _refused(write(tmp_path / "noman", log, None))
    _refused(write(tmp_path / "tail", log, None), follow=True)
    train = Log("rY")
    train.end("done")
    _refused(write(tmp_path / "man", train, manifest("rY", split="test")))
    _refused(write(tmp_path / "lie", log, manifest("rX")))  # session.started: test
    for i, split in enumerate(("TEST", "", "holdout")):  # an allow-list, not "test"
        other = Log(f"rZ{i}", split=split)
        other.end("done")
        _refused(write(tmp_path / f"z{i}", other, None))


def test_follow_refuses_a_log_that_appears_inside_the_seal(tmp_path: Path) -> None:
    log = Log("rQ")
    log.end("done")
    sealed = write(tmp_path / "evidence" / "s4" / "test" / "rQ", log, None)
    run = tmp_path / "rQ"
    run.mkdir()
    sealed.chmod(0)  # opening the log through the link would raise, not refuse

    def link() -> None:
        time.sleep(0.3)
        (run / EVENTS).symlink_to(sealed / EVENTS)

    thread = threading.Thread(target=link)
    thread.start()
    try:
        _refused(run, follow=True)
    finally:
        thread.join()
        sealed.chmod(0o755)


def test_an_unknown_split_or_a_hard_link_is_refused(tmp_path: Path) -> None:
    log = Log("rU")
    log.end("done")
    run = write(tmp_path / "rU", log, None)
    first, second = (run / EVENTS).read_text("utf-8").splitlines()
    (run / EVENTS).write_text(second + "\n" + first + "\n", "utf-8")
    _refused(run)
    linked = write(tmp_path / "rH", log, manifest("rU"))
    os.link(linked / EVENTS, tmp_path / "elsewhere")
    _refused(linked)


def test_the_cli_refuses_and_writes_json(tmp_path: Path) -> None:
    log = Log("rC", split="test")
    run = write(tmp_path / "rC", log, None)
    out = tmp_path / "spans.json"
    assert trace.main([str(run), "--json", str(out)]) == 2
    assert not out.exists()
    (run / MANIFEST).write_text(manifest("rC").model_dump_json(), "utf-8")
    (run / EVENTS).unlink()
    ok = Log("rC")
    ok.end("done")
    (run / EVENTS).write_text(ok.events[0].model_dump_json() + "\n", "utf-8")
    assert trace.main([str(run), "--json", str(out)]) == 0
    assert [s["name"] for s in json.loads(out.read_text("utf-8"))] == [
        "session.started"
    ]
