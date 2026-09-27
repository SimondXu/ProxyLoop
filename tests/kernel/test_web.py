"""The live web case (S1-SYS-05): the kernel's ``Starter`` and ``Case`` over a
real ``run_session`` on virtual time. Scripted clients stand in for the models
(tests only, I8): they carry the cfg's ``real_http`` refs because the kernel
refuses any other in live mode, and their bundles stay in ``tmp_path``."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from collections.abc import Coroutine, Mapping
from pathlib import Path
from typing import Any, cast, get_args

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.concurrency.harness import NOTED, VirtualTime, settle, slots, terms
from tests.serve.client import ORIGIN, get, headers, login, post
from tests.support.fakes import RepeatingLLM
from tests.support.sessions import FakeTokenizer, ear

from proxyloop.contract.events import ApprovalPost, Event
from proxyloop.contract.llm import (
    AdapterKind,
    Endpoint,
    LLMClient,
    LLMRole,
    ModelRef,
    ToolCall,
)
from proxyloop.contract.state import ApprovalCard
from proxyloop.kernel import session, web
from proxyloop.kernel.channels import HumanWebChannel, Incoming
from proxyloop.kernel.session import ClientFactory, Kernel
from proxyloop.kernel.web import CATALOG, LUNA, TRAINING, Offer, Starter, WebCase
from proxyloop.llm.factory import make_client
from proxyloop.llm.http import RecordSink
from proxyloop.serve.api import create_app
from proxyloop.serve.bundles import find_run
from proxyloop.serve.cases import LaneKey, StartRefused
from proxyloop.serve.start import OPTION_ID, REASONS, TASK_REF, broken

REF = "cp-direct-discount@1"
USER_QWEN = "fast_user:vllm:Qwen3.5-9B"
SLOW_ID = "slow:teamrouter:gemini-3.8-flash"
ENDPOINTS: tuple[Endpoint, ...] = get_args(Endpoint)
SECRET = "sekrit-value"
SCRIPTS: Mapping[str, list[str]] = {
    "fast_user": ["Okay."],
    "fast_cp": ["Okay."],
    "slow": [NOTED],
    "ear": [ear("other")],
    "mouth": ["Okay."],
}


@pytest.fixture(autouse=True)
def endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    for endpoint in ENDPOINTS:  # values only a test uses; never a real endpoint
        prefix = f"PL_{endpoint.upper()}_"
        monkeypatch.setenv(prefix + "BASE_URL", "https://endpoint.invalid")
        monkeypatch.setenv(prefix + "API_KEY", SECRET)


def gated() -> httpx.MockTransport:
    """A vLLM server that never answers: P3 (before seq 0) hangs on it."""

    async def handle(request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    return httpx.MockTransport(handle)


def fakes(vt: VirtualTime, vllm: httpx.MockTransport | None = None) -> ClientFactory:
    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        if ref.endpoint == "vllm":  # the real adapter over a transport double
            now = vt.monotonic_ms
            return make_client(
                ref, live=False, clock=now, on_record=sink, transport=vllm
            )
        return RepeatingLLM(ref, SCRIPTS.get(role, ["unused"]), vt, False, sink)

    return make


def starter(
    tmp_path: Path, vt: VirtualTime, catalog: tuple[Offer, ...] = CATALOG
) -> Starter:
    vllm = gated()
    return Starter(
        tmp_path / "runs",
        catalog=catalog,
        clock=vt,
        sleep=vt.sleep,
        clients=fakes(vt, vllm),
    )


def kernel(case: WebCase) -> Kernel:
    return case._k  # pyright: ignore[reportPrivateUsage]


async def stop(case: WebCase) -> tuple[Event, ...]:
    run = case._run  # pyright: ignore[reportPrivateUsage]
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)
    return kernel(case).bus.events


def arun(case: Coroutine[Any, Any, None]) -> None:
    asyncio.run(asyncio.wait_for(case, timeout=30))


def of(events: tuple[Event, ...], type_: str, **match: object) -> list[Event]:
    return [
        e
        for e in events
        if e.type == type_ and all(e.payload.get(k) == v for k, v in match.items())
    ]


# Start: seq 0, the path, the defaults.


def test_start_returns_after_seq_0_at_runs_live_run_id_run_id(tmp_path: Path) -> None:
    async def case() -> None:
        s = starter(tmp_path, VirtualTime())
        case = await s.start_case(REF, {})
        events = tmp_path / "runs" / "live" / case.run_id / case.run_id / "events.jsonl"
        first = json.loads(events.read_text().splitlines()[0])
        assert (first["seq"], first["type"]) == (0, "session.started")
        assert first["payload"]["split"] == "train" and first["run_id"] == case.run_id
        assert find_run([tmp_path / "runs"], case.run_id) is not None  # servable
        ended = await stop(case)
        assert ended[-1].payload["reason"] == "stopped"

    arun(case())


def test_an_empty_models_map_gets_every_lanes_default(tmp_path: Path) -> None:
    async def case() -> None:
        case = await starter(tmp_path, VirtualTime()).start_case(REF, {})
        cfg = kernel(case).cfg
        assert cfg.live and cfg.fast_user == cfg.fast_cp
        assert (cfg.fast_user.endpoint, cfg.fast_user.model_id) == ("openrouter", LUNA)
        assert cfg.fast_user.reasoning_effort == "none"  # the CLI's OpenRouter rule
        assert (cfg.slow.endpoint, cfg.slow.model_id) == ("teamrouter", web.SLOW)
        assert cfg.slow.reasoning_effort == "low"  # the CLI's TeamRouter rule
        refs = [cfg.fast_user, cfg.fast_cp, cfg.slow, cfg.world.ear, cfg.world.mouth]
        assert {r.kind for r in refs} == {AdapterKind.REAL_HTTP}
        await stop(case)

    arun(case())


def test_each_fast_lane_gets_its_own_model_with_the_clis_effort() -> None:
    offers = {o.id: o for o in CATALOG}
    slow = offers[SLOW_ID]
    config = web._config  # pyright: ignore[reportPrivateUsage]
    qwen = config("cp-direct-discount", offers[USER_QWEN], slow)
    assert (qwen.fast_user.endpoint, qwen.fast_user.reasoning_effort) == ("vllm", None)


# Refusals: every reason reachable, and only the frozen ones.


def _refused(tmp_path: Path, task_ref: str, models: Mapping[str, str]) -> str:
    async def case() -> str:
        s = starter(tmp_path, VirtualTime(), (*CATALOG, BASELINE))
        with pytest.raises(StartRefused) as refused:
            await s.start_case(task_ref, cast(Mapping[LaneKey, str], models))
        assert refused.value.args == (refused.value.reason,)
        return refused.value.reason

    return asyncio.run(case())


BASELINE = Offer("fast_cp", None, "fsm", "FSM", kind=AdapterKind.BASELINE)
REFUSALS: dict[str, tuple[str, Mapping[str, str], str]] = {
    "not a task_ref": ("cp-direct-discount", {}, "unknown_task"),
    "another version": ("cp-direct-discount@9", {}, "unknown_task"),
    "no such mode": ("cp-direct-discount@1:nope", {}, "unknown_task"),
    "not a training family": ("x-held-out-family@1", {}, "unknown_task"),
    "unknown model": (REF, {"fast_user": "fast_user:vllm:gpt-2"}, "unknown_model"),
    "another lane's model": (REF, {"fast_user": SLOW_ID}, "wrong_lane"),
    "an unknown lane": (REF, {"teacher": SLOW_ID}, "wrong_lane"),
    "a baseline": (REF, {"fast_cp": BASELINE.id}, "not_live"),
}


@pytest.mark.parametrize("given", REFUSALS.values(), ids=REFUSALS.keys())
def test_a_refused_start_names_its_reason_and_writes_nothing(
    tmp_path: Path, given: tuple[str, Mapping[str, str], str]
) -> None:
    task_ref, models, reason = given
    assert _refused(tmp_path, task_ref, models) == reason
    assert reason in REASONS
    assert not (tmp_path / "runs").exists()


def test_a_held_out_family_is_never_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(web, "resolve", opened.append)  # any call is recorded
    assert _refused(tmp_path, "x-held-out-family@1", {}) == "unknown_task"
    assert opened == []


@pytest.mark.parametrize("endpoint", ["openrouter", "teamrouter"])
def test_a_missing_endpoint_variable_is_unavailable_without_its_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    monkeypatch.delenv(f"PL_{endpoint.upper()}_API_KEY")

    async def case() -> None:
        s = starter(tmp_path, VirtualTime())
        with pytest.raises(StartRefused) as refused:
            await s.start_case(REF, {})
        assert refused.value.reason == "unavailable"
        assert refused.value.__cause__ is None and refused.value.__suppress_context__
        assert SECRET not in repr(refused.value)

    arun(case())


def test_a_human_rep_needs_no_world_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PL_TEAMROUTER_API_KEY")  # the world's, and the Slow's
    catalog = (*CATALOG, Offer("slow", "relay", "claude-sonnet-5", "Sonnet"))

    async def case() -> None:
        s = starter(tmp_path, VirtualTime(), catalog)
        human = await s.start_case(REF, {"slow": "slow:relay:claude-sonnet-5"}, "human")
        assert "ear" not in kernel(human).clients
        await stop(human)
        with pytest.raises(StartRefused, match="unavailable"):  # the sim rep's world
            await s.start_case(REF, {"slow": "slow:relay:claude-sonnet-5"}, "sim")

    arun(case())


def test_a_second_start_is_busy_while_a_run_is_live(tmp_path: Path) -> None:
    async def case() -> None:
        s = starter(tmp_path, VirtualTime())
        first = await s.start_case(REF, {})
        with pytest.raises(StartRefused, match="busy"):
            await s.start_case(REF, {})
        both = await asyncio.gather(
            s.start_case(REF, {}), s.start_case(REF, {}), return_exceptions=True
        )
        assert all(isinstance(x, StartRefused) and x.reason == "busy" for x in both)
        await stop(first)
        second = await s.start_case(REF, {})  # the run ended: not busy
        assert second.run_id != first.run_id
        await stop(second)

    arun(case())


def test_concurrent_starts_start_one_run(tmp_path: Path) -> None:
    async def case() -> None:
        s = starter(tmp_path, VirtualTime())
        got = await asyncio.gather(
            s.start_case(REF, {}), s.start_case(REF, {}), return_exceptions=True
        )
        (started,) = [x for x in got if isinstance(x, WebCase)]
        (refused,) = [x for x in got if isinstance(x, StartRefused)]
        assert refused.reason == "busy"
        await stop(started)

    arun(case())


def test_a_start_cancelled_before_seq_0_is_invisible_and_leaves_nothing_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads: list[int] = []

    def load() -> FakeTokenizer:
        loads.append(1)
        return FakeTokenizer()

    monkeypatch.setattr(web, "load_tokenizer", load)
    web._tokenizer.cache_clear()  # pyright: ignore[reportPrivateUsage]

    async def case() -> None:
        s, seen = starter(tmp_path, VirtualTime()), set[Path]()
        for _ in range(2):  # a vLLM Fast: P3 hangs before seq 0
            start = asyncio.create_task(s.start_case(REF, {"fast_user": USER_QWEN}))
            await settle()
            assert not start.done()
            (run,) = set(_runs(tmp_path)) - seen
            seen.add(run)
            assert run.parent.name == run.name  # runs/live/<run_id>/<run_id>
            assert (run / "events.jsonl").read_text() == ""  # no seq 0 yet
            assert find_run([tmp_path / "runs"], run.name) is None  # invisible
            start.cancel()
            with pytest.raises(asyncio.CancelledError):
                await start
            assert (run / "events.jsonl").read_text() == ""  # never started
        after = await s.start_case(REF, {})  # nothing live: not busy
        await stop(after)

    try:
        arun(case())
    finally:
        web._tokenizer.cache_clear()  # pyright: ignore[reportPrivateUsage]
    assert loads == [1]  # the tokenizer is loaded once per process


def _runs(tmp_path: Path) -> list[Path]:
    return [p for p in (tmp_path / "runs" / "live").glob("*/*") if p.is_dir()]


def test_a_start_cancelled_after_seq_0_stops_its_run(tmp_path: Path) -> None:
    async def case() -> None:
        s = starter(tmp_path, VirtualTime())
        start = asyncio.create_task(s.start_case(REF, {}))
        while (
            not (runs := _runs(tmp_path))
            or not (runs[0] / "events.jsonl").stat().st_size
        ):
            await asyncio.sleep(0)  # until the run wrote seq 0
        assert not start.done()  # start_case has not resumed yet
        start.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start
        (run,) = _runs(tmp_path)
        lines = [json.loads(x) for x in (run / "events.jsonl").read_text().splitlines()]
        assert lines[0]["type"] == "session.started"
        assert lines[-1]["payload"]["reason"] == "stopped"  # closed, not orphaned
        await stop(await s.start_case(REF, {}))  # not busy

    arun(case())


# The ingress: messages, rep lines and approvals.


def test_a_user_message_and_a_human_rep_line_become_events(tmp_path: Path) -> None:
    async def case() -> None:
        vt = VirtualTime()
        case = await starter(tmp_path, vt).start_case(REF, {}, "human")
        await vt.run_for(5_000)  # past the disclosure
        case.user_message("Please lower my bill.")
        case.rep_utterance("We can do $68 a month.")
        await vt.run_for(100)
        events = kernel(case).bus.events
        (msg,) = of(events, "user.msg")
        assert msg.payload["text"] == "Please lower my bill." and msg.actor == "kernel"
        (line,) = of(events, "utt.final", speaker="partner")
        assert (line.payload["lane"], line.payload["text"]) == (
            "cp",
            "We can do $68 a month.",
        )
        with pytest.raises(ValueError, match="empty"):
            case.user_message("   ")
        await stop(case)
        with pytest.raises(RuntimeError, match="ended"):  # serve: 503
            case.user_message("Hello?")
        with pytest.raises(RuntimeError, match="ended"):
            case.rep_utterance("Hello?")

    arun(case())


def test_a_sim_rep_case_has_no_human_rep_ingress(tmp_path: Path) -> None:
    async def case() -> None:
        case = await starter(tmp_path, VirtualTime()).start_case(REF, {}, "sim")
        assert "ear" in kernel(case).clients
        with pytest.raises(RuntimeError, match="simulated"):
            case.rep_utterance("Hi.")
        await stop(case)

    arun(case())


def _act(k: Kernel, *calls: Mapping[str, object]) -> list[str]:
    assert k.slow is not None
    body = json.dumps({"private_summary": "digest", "calls": list(calls)})
    call = ToolCall(call_id="t", name="act", arguments=body)
    return k.slow.tools.act(call, [k.authority.root]).splitlines()[1:]


async def _card(case: WebCase, vt: VirtualTime) -> ApprovalCard:
    """The human rep states an offer and reads it back; Slow (played through
    the session's own tools) records it and asks for the card."""
    k = kernel(case)
    case.rep_utterance(terms(68))
    await vt.run_for(3_000)
    utt = [x for x in k.bus.bb.channels["cp"].lines if x.speaker == "partner"]
    record: dict[str, object] = {"tool": "record_offer", "offer_ref": "o1"}
    record["offer_slots"] = slots(68, utt[-1].utt_id)
    ask = {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:o1"]}
    _act(k, record, ask)
    await vt.run_for(3_000)
    case.rep_utterance(terms(68))
    await vt.run_for(3_000)
    assert k.slow is not None
    k.slow.tools.readback()
    (text,) = _act(k, {"tool": "request_approval", "offer_ref": "o1"})
    assert "sent to the user" in text, text
    card = k.bus.bb.private.pending_approval
    assert card is not None
    return card


def _post(card: ApprovalCard) -> ApprovalPost:
    return ApprovalPost(
        subject="approval",
        subject_id=card.approval_id,
        decision="granted",
        subject_hash=card.terms_hash,
        authority_epoch=card.authority_epoch,
    )


def test_a_ui_approval_is_decided_by_the_kernel_and_a_stale_one_denied(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        vt = VirtualTime()
        case = await starter(tmp_path, vt).start_case(REF, {}, "human")
        await vt.run_for(5_000)
        card = await _card(case, vt)
        assert case.blackboard().private.pending_approval == card
        case.post_approval(_post(card))  # enqueued only
        assert not of(kernel(case).bus.events, "approval.decided")
        await vt.run_for(100)
        events = kernel(case).bus.events
        (posted,) = of(events, "approval.post")
        (decided,) = of(events, "approval.decided")
        assert (posted.actor, decided.payload["by"]) == ("ui", "ui")
        assert decided.cause_ids == (posted.event_id,)
        case.post_approval(_post(card))  # stale: that card is decided
        await vt.run_for(100)
        events = kernel(case).bus.events
        (denied,) = of(events, "action.denied", intent="approval.post")
        (asked,) = of(events, "approval.requested")
        assert denied.actor == "kernel" and denied.cause_ids == (asked.event_id,)
        assert len(of(events, "approval.decided")) == 1
        await stop(case)
        with pytest.raises(RuntimeError, match="ended"):  # raises, never swallowed
            case.post_approval(_post(card))

    arun(case())


# Options: real_http only (N-1), training families only (rule 11).


def test_the_real_starter_offers_only_real_http_models(tmp_path: Path) -> None:
    real = Starter(tmp_path / "runs")
    options = real.model_options()
    by_id = {o.id: o for o in CATALOG}
    assert options and all(by_id[o.id].kind is AdapterKind.REAL_HTTP for o in options)
    assert all(o.endpoint in ENDPOINTS for o in options)
    assert all(re.fullmatch(OPTION_ID, o.id) for o in options)
    assert len({o.id for o in options}) == len(options)
    for lane in get_args(LaneKey):
        assert sum(o.default for o in options if o.lane == lane) == 1
    assert [o.id for o in options] == [o.id for o in real.model_options()]  # stable
    assert broken(options, real.task_options()) is None  # serve's own promises
    assert [o.model_id for o in options if o.lane == "slow"] == [web.SLOW]


def test_a_non_real_http_catalogue_entry_is_never_offered(tmp_path: Path) -> None:
    s = Starter(tmp_path / "runs", catalog=(*CATALOG, BASELINE))
    assert BASELINE.id not in {o.id for o in s.model_options()}


def test_task_options_are_the_training_families_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    loaded: list[str] = []
    load = web.load_task

    def spy(family: str) -> Any:
        loaded.append(family)
        return load(family)

    monkeypatch.setattr(web, "load_task", spy)
    s = Starter(tmp_path / "runs")
    tasks = s.task_options()
    assert tasks == s.task_options()  # stable
    assert [t.split("@")[0] for t in tasks] == list(TRAINING)
    assert all(re.fullmatch(TASK_REF, t) for t in tasks)
    assert set(loaded) == set(TRAINING)  # no other family file was opened


# The seam as serve drives it.


def _operator(http: TestClient) -> dict[str, str]:
    got = get(http, "/start", follow=False)
    assert got.status_code == 303, got.text
    cookies = dict(got.cookies)
    cast(Any, http).cookies.clear()
    return cookies


def _wait_for(path: Path, type_: str) -> list[dict[str, Any]]:
    for _ in range(500):
        lines = [json.loads(x) for x in path.read_text().splitlines()]
        if any(x["type"] == type_ for x in lines):
            return lines
        time.sleep(0.01)
    raise AssertionError(f"no {type_} in {path}")


async def _cancel(run: asyncio.Task[Any]) -> None:
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)


def test_serve_starts_a_case_and_its_posts_reach_the_kernel(tmp_path: Path) -> None:
    vt = VirtualTime()
    s = starter(tmp_path, vt)
    app = create_app([tmp_path / "runs"], [ORIGIN], start=s)
    with TestClient(app, base_url="http://127.0.0.1") as http:
        models = get(http, "/api/models").json()
        assert models["tasks"] == list(s.task_options())
        body: dict[str, object] = {"task_ref": REF, "models": {}, "rep": "human"}
        got = post(http, "/api/cases", body, headers(_operator(http)))
        assert got.status_code == 201, got.text
        case_id = got.json()["case_id"]
        run = tmp_path / "runs" / "live" / case_id / case_id / "events.jsonl"
        assert json.loads(run.read_text().splitlines()[0])["seq"] == 0
        again = post(http, "/api/cases", body, headers(_operator(http)))
        assert (again.status_code, again.json()["reason"]) == (409, "busy")
        said = {"text": "Can you lower my bill?"}
        user = headers(login(http, "user", case_id))
        assert post(http, f"/api/cases/{case_id}/messages", said, user).is_success
        cast(Any, http).portal.call(vt.run_for, 5_000)  # past the disclosure
        rep = headers(login(http, "rep", case_id))
        line = {"text": "We can do $68."}
        assert post(http, f"/api/cases/{case_id}/rep", line, rep).is_success
        lines = _wait_for(run, "utt.final")
        assert [x["payload"]["text"] for x in lines if x["type"] == "user.msg"] == [
            said["text"]
        ]
        live = s._run  # pyright: ignore[reportPrivateUsage]
        assert live is not None
        cast(Any, http).portal.call(_cancel, live)


def test_the_web_channel_queues_a_line_due_at_once() -> None:
    async def case() -> None:
        channel = HumanWebChannel()
        channel.say("Hello.")
        assert await channel.incoming.get() == Incoming((("Hello.", None),))
        assert not channel.busy  # N4: no composing signal from a web person

    arun(case())


def test_the_git_sha_is_read_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess("git", 0, stdout="abc123\n", stderr="")

    session._git_sha.cache_clear()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(subprocess, "run", spy)
    try:
        assert session._git_sha() == "abc123"  # pyright: ignore[reportPrivateUsage]
        assert session._git_sha() == "abc123"  # pyright: ignore[reportPrivateUsage]
    finally:
        session._git_sha.cache_clear()  # pyright: ignore[reportPrivateUsage]
    assert len(calls) == 1
