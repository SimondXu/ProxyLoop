"""The live web case (S1-SYS-05): the kernel's ``Starter`` and ``Case`` over a
real ``run_session`` on virtual time. Scripted clients stand in for the models
(tests only, I8): they carry the cfg's ``real_http`` refs because the kernel
refuses any other in live mode, and their bundles stay in ``tmp_path``."""

from __future__ import annotations

import asyncio
import json
import logging
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
    LLMUnavailable,
    ModelRef,
    ToolCall,
)
from proxyloop.contract.state import ApprovalCard
from proxyloop.core.bus import Bus
from proxyloop.env.tasks.loader import load_task, resolve, task_ref_of
from proxyloop.kernel import calls, session, web
from proxyloop.kernel.channels import HumanWebChannel, Incoming
from proxyloop.kernel.session import ClientFactory, Kernel, RunResult
from proxyloop.kernel.web import CATALOG, LUNA, TRAINING, Offer, Starter, WebCase
from proxyloop.llm.factory import make_client
from proxyloop.llm.http import RecordSink
from proxyloop.serve.api import create_app
from proxyloop.serve.bundles import find_run
from proxyloop.serve.cases import LaneKey, NotOpen, StartRefused
from proxyloop.serve.start import OPTION_ID, REASONS, TASK_REF, broken

REF = "cp-direct-discount@1"
CALLED_MS = 1000 * calls.INTAKE_S + 5_000  # the intake ran out; the disclosure said
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
        await vt.run_for(CALLED_MS)  # no identity given: the deadline opens it
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


def test_a_human_rep_line_before_the_call_opens_is_refused(tmp_path: Path) -> None:
    async def case() -> None:
        vt = VirtualTime()
        case = await starter(tmp_path, vt).start_case(REF, {}, "human")
        k = kernel(case)
        assert not of(k.bus.events, "chan.opened", lane="cp")  # the intake runs
        before = k.bus.events
        with pytest.raises(NotOpen):  # serve: 409 not_open
            case.rep_utterance("Hello, who is this?")
        assert k.bus.events == before
        await vt.run_for(CALLED_MS)  # the deadline opens the call
        assert of(k.bus.events, "chan.opened", lane="cp")
        assert not of(k.bus.events, "utt.final", speaker="partner")  # never late
        case.rep_utterance("Hello, who is this?")  # now accepted
        await vt.run_for(100)
        (line,) = of(k.bus.events, "utt.final", speaker="partner")
        assert line.payload["text"] == "Hello, who is this?"
        await stop(case)

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
    return k.slow.tools.act(call, [k.authority.root], basis=k.bb.seq).splitlines()[1:]


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
        await vt.run_for(CALLED_MS)
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


# The principal's role card (S1-SYS-65): an allow-list over a training instance.

CARD_KEYS = {"company", "persona", "goal", "facts", "approval", "stop"}
FACT_KEYS = {"key", "value", "identity", "shareable"}
LIMIT_KEYS = {"max_monthly_price_usd", "max_term_months", "max_one_time_fees_usd"}
STOP_KEYS = {"trigger", "text_hint", "change"}


def _card_refs() -> list[str]:
    """Every training family's offered ref, a seeded instance of it (shifted
    prices and limits), and cp-direct-discount's full mode."""
    refs: list[str] = []
    for family in TRAINING:
        version = load_task(family).version
        refs += [task_ref_of(family, version, None, s) for s in (0, 3)]
    return [*refs, task_ref_of("cp-direct-discount", 1, "full", 0)]


CARD_REFS = _card_refs()


def test_a_role_card_of_a_held_out_family_is_refused_unopened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = Starter(tmp_path / "runs")  # its own training loads happen here
    opened: list[str] = []
    monkeypatch.setattr(web, "resolve", opened.append)  # any call is recorded
    monkeypatch.setattr(web, "load_task", opened.append)
    with pytest.raises(StartRefused) as refused:
        s.role_card("x-held-out-family@1")
    assert (refused.value.reason, opened) == ("unknown_task", [])


@pytest.mark.parametrize(
    "task_ref", ["cp-direct-discount", "cp-direct-discount@9", "cp-direct-discount@1:x"]
)
def test_a_role_card_of_a_bad_ref_is_unknown_task(
    tmp_path: Path, task_ref: str
) -> None:
    with pytest.raises(StartRefused) as refused:
        Starter(tmp_path / "runs").role_card(task_ref)
    assert refused.value.reason == "unknown_task"


def _leaves(value: object) -> list[str]:
    """Every string and number in a JSON value (booleans are its flags)."""
    if isinstance(value, dict):
        return [x for v in cast(dict[str, object], value).values() for x in _leaves(v)]
    if isinstance(value, list):
        return [x for v in cast(list[object], value) for x in _leaves(v)]
    if isinstance(value, bool) or value is None:
        return []
    return [str(value)]


def _said(value: str, texts: list[str]) -> bool:
    """``value`` appears in ``texts`` as a whole token ("24" in "24 months",
    never in "4821"; "75.00" or its "75" never inside "175" or "75.5")."""
    token = re.compile(rf"(?<![\w.]){re.escape(value)}(?![\w]|\.\d)")
    return any(token.search(t) for t in texts)


def _cp_values(task_ref: str) -> set[str]:
    """The counterparty's values, apart from its company's name: the ladder's
    refs, terms and hidden fields (their names and values, and a price's
    whole dollars), its persona, patience and ledger; plus gold, probes and
    the three briefs."""
    task = resolve(task_ref)
    cp = task.counterparty.model_dump(mode="json", exclude={"company", "identity"})
    values = set(_leaves(cp))
    for offer in task.counterparty.ladder:
        values |= set(offer.all_terms)  # "fee:installation" names a hidden fee
    values |= {v.split(".")[0] for v in set(values) if re.fullmatch(r"\d+\.\d+", v)}
    values |= {task.gold.check, *task.probes}
    return values | {task.fast_brief_user, task.fast_brief_cp, task.slow_brief}


def _principal_knows(task_ref: str) -> list[str]:
    """What the principal legitimately knows, from the task itself: the fact
    values, the approval limits, and the words of its persona, goal and stop."""
    task = resolve(task_ref)
    known = [*task.profile.facts.values(), task.profile.persona]
    known.append(task.goal(task.profile.facts))
    if task.principal is not None:
        known += _leaves(task.principal.model_dump(mode="json"))
    if task.stop is not None:
        known += _leaves(task.stop.model_dump(mode="json"))
    return known


@pytest.mark.parametrize("task_ref", CARD_REFS)
def test_the_role_card_keys_are_exactly_the_allow_list(
    tmp_path: Path, task_ref: str
) -> None:
    card = Starter(tmp_path / "runs").role_card(task_ref).model_dump(mode="json")
    assert set(card) == CARD_KEYS
    assert card["facts"] and all(set(f) == FACT_KEYS for f in card["facts"])
    assert card["approval"] is None or set(card["approval"]) == LIMIT_KEYS
    assert card["stop"] is None or set(card["stop"]) == STOP_KEYS


def test_the_allow_list_covers_an_approval_and_a_stop(tmp_path: Path) -> None:
    cards = [Starter(tmp_path / "runs").role_card(r) for r in CARD_REFS]
    assert any(c.approval is not None for c in cards)
    assert any(c.stop is not None for c in cards)
    assert any(c.approval is None for c in cards)  # information only


@pytest.mark.parametrize("task_ref", CARD_REFS)
def test_no_counterparty_value_reaches_the_role_card(
    tmp_path: Path, task_ref: str
) -> None:
    """Rule: a counterparty value the principal also knows (a fact, a limit, a
    word of its own persona, goal or stop; e.g. the term "24" of a 24-month
    budget) is not evidence of a leak and is left out; every other one must
    not appear, as a whole token, in any string or number of the card."""
    card = Starter(tmp_path / "runs").role_card(task_ref).model_dump(mode="json")
    texts, known = _leaves(card), _principal_knows(task_ref)
    checked = {v for v in _cp_values(task_ref) if not _said(v, known)}
    task = resolve(task_ref)
    for offer in task.counterparty.ladder:  # the prices are checked, never excused
        assert offer.all_terms["monthly_price"] in checked
    assert task.counterparty.persona in checked
    leaked = sorted(v for v in checked if _said(v, texts))
    assert leaked == []
    price = task.counterparty.ladder[0].all_terms["monthly_price"]
    assert _said(price, [*texts, f"an offer at {price} a month"])  # it would see one


def test_the_role_card_is_the_principal_s_view_of_the_instance(
    tmp_path: Path,
) -> None:
    s = Starter(tmp_path / "runs")
    info = s.role_card(REF)  # information only: nothing to approve
    assert (info.company, info.approval, info.stop) == ("Northwind Mobile", None, None)
    assert info.persona.startswith("Dana Reyes, a busy nurse")
    flags = {f.key: (f.identity, f.shareable) for f in info.facts}
    assert flags["account.last4"] == (True, True)
    assert flags["competitor.price_usd"] == (False, True)
    assert flags["plan.current_price_usd"] == (False, False)
    hidden_fee = s.role_card("cp-hidden-fee-readback@1").approval  # the envelope
    assert hidden_fee is not None
    assert hidden_fee.model_dump() == {
        "max_monthly_price_usd": "65",
        "max_term_months": 12,
        "max_one_time_fees_usd": "0",
    }
    out = s.role_card("x-out-of-envelope-approval@1").approval  # the limits
    assert out is not None and out.max_monthly_price_usd == "72.00"
    stop = s.role_card("x-user-mind-change@1").stop
    assert stop is not None and (stop.trigger, stop.change) == ("after_card", None)
    seeded = "cp-hidden-fee-readback@1#3"  # the instance's shifted numbers
    task = resolve(seeded)
    card = s.role_card(seeded)
    assert card.goal == task.goal(task.profile.facts).strip()
    assert {f.key: f.value for f in card.facts} == task.profile.facts


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
        cast(Any, http).portal.call(vt.run_for, CALLED_MS)  # the call is open
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


def test_serve_refuses_a_rep_line_before_the_call_opens(tmp_path: Path) -> None:
    vt = VirtualTime()
    s = starter(tmp_path, vt)
    app = create_app([tmp_path / "runs"], [ORIGIN], start=s)
    with TestClient(app, base_url="http://127.0.0.1") as http:
        body: dict[str, object] = {"task_ref": REF, "models": {}, "rep": "human"}
        got = post(http, "/api/cases", body, headers(_operator(http)))
        case_id = got.json()["case_id"]
        run = tmp_path / "runs" / "live" / case_id / case_id / "events.jsonl"
        rep, url = headers(login(http, "rep", case_id)), f"/api/cases/{case_id}/rep"
        line = {"text": "Hello?"}
        before = run.read_text()
        got = post(http, url, line, rep)
        assert (got.status_code, got.json()) == (409, {"error": "not_open"})
        assert run.read_text() == before  # nothing appended
        cast(Any, http).portal.call(vt.run_for, CALLED_MS)  # the call is open
        assert post(http, url, line, rep).is_success
        said = [x["payload"] for x in _wait_for(run, "utt.final")]
        heard = [p["text"] for p in said if p.get("speaker") == "partner"]
        assert heard == [line["text"]]
        live = s._run  # pyright: ignore[reportPrivateUsage]
        assert live is not None
        cast(Any, http).portal.call(_cancel, live)


def test_serve_gives_the_role_card_of_a_training_task_and_of_a_started_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vt = VirtualTime()
    s = starter(tmp_path, vt)
    app = create_app([tmp_path / "runs"], [ORIGIN], start=s)
    card = s.role_card(REF).model_dump(mode="json")
    with TestClient(app, base_url="http://127.0.0.1") as http:
        op = headers(_operator(http))
        opened: list[str] = []
        with monkeypatch.context() as m:  # rule 11: a held-out ref opens nothing
            m.setattr(web, "resolve", opened.append)
            got = get(http, "/api/tasks/card?ref=x-held-out-family@1", op)
            assert (got.status_code, got.json()["reason"]) == (400, "unknown_task")
        assert opened == []
        got = get(http, f"/api/tasks/card?ref={REF}", op)
        assert (got.status_code, got.json()) == (200, card)
        body: dict[str, object] = {"task_ref": REF, "models": {}, "rep": "human"}
        case_id = post(http, "/api/cases", body, op).json()["case_id"]
        url = f"/api/cases/{case_id}/card"
        got = get(http, url, headers(login(http, "rep", case_id)))
        assert got.status_code == 403
        got = get(http, url, headers(login(http, "user", case_id)))
        assert (got.status_code, got.json()) == (200, card)  # its seq 0's task_ref
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


# Review round 2 (#179): D1 no upstream text in the server log, D2 the bus
# closes on a cancelled start, D4 an ended kernel takes no more lines.


def test_a_failed_session_logs_no_upstream_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    upstream = "bad gateway at endpoint.invalid key " + SECRET

    async def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=upstream)

    wire = httpx.MockTransport(answer)

    async def case() -> None:
        vt = VirtualTime()
        scripted = fakes(vt)

        def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
            if role != "fast_cp":
                return scripted(role, ref, sink)
            now = vt.monotonic_ms
            return make_client(
                ref, live=False, clock=now, on_record=sink, transport=wire
            )

        s = Starter(tmp_path / "runs", clock=vt, sleep=vt.sleep, clients=make)
        case = await s.start_case(REF, {})
        await vt.run_for(CALLED_MS + 15_000)  # FastC's first call fails
        run = case._run  # pyright: ignore[reportPrivateUsage]
        await asyncio.gather(run, return_exceptions=True)
        await asyncio.sleep(0)  # the done-callback logs
        assert isinstance(run.exception(), LLMUnavailable)

    with caplog.at_level(logging.DEBUG, logger="proxyloop.kernel.web"):
        arun(case())
    logged = caplog.text
    assert "LLMUnavailable" in logged
    assert SECRET not in logged and "endpoint.invalid" not in logged
    assert all(r.exc_info is None for r in caplog.records)


def test_an_unexpected_session_error_logs_its_type_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fail() -> RunResult:
        raise KeyError(f"https://endpoint.invalid {SECRET}")

    async def case() -> None:
        run = asyncio.create_task(fail())
        await asyncio.gather(run, return_exceptions=True)
        web._ended(run)  # pyright: ignore[reportPrivateUsage]

    with caplog.at_level(logging.DEBUG, logger="proxyloop.kernel.web"):
        arun(case())
    assert "KeyError" in caplog.text
    assert SECRET not in caplog.text and "endpoint.invalid" not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)


def test_a_start_cancelled_before_seq_0_closes_its_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    buses: list[Bus] = []
    close = Bus.close

    def spy(self: Bus) -> None:
        buses.append(self)
        close(self)

    monkeypatch.setattr(Bus, "close", spy)
    monkeypatch.setattr(web, "load_tokenizer", FakeTokenizer)
    web._tokenizer.cache_clear()  # pyright: ignore[reportPrivateUsage]

    async def case() -> None:
        s = starter(tmp_path, VirtualTime())
        start = asyncio.create_task(s.start_case(REF, {"fast_user": USER_QWEN}))
        await settle()  # P3 hangs on the gated vLLM
        start.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start

    try:
        arun(case())
    finally:
        web._tokenizer.cache_clear()  # pyright: ignore[reportPrivateUsage]
    (bus,) = set(buses)
    assert bus._log._file.closed  # pyright: ignore[reportPrivateUsage]


def test_an_ended_kernel_takes_no_more_lines(tmp_path: Path) -> None:
    async def case() -> None:
        case = await starter(tmp_path, VirtualTime()).start_case(REF, {}, "human")
        k = kernel(case)
        k._ended = True  # pyright: ignore[reportPrivateUsage]
        for say in (case.user_message, case.rep_utterance):  # _close ran; the
            with pytest.raises(RuntimeError, match="ended"):  # task has not
                say("Hello?")  # finished yet
        k._ended = False  # pyright: ignore[reportPrivateUsage]
        await stop(case)

    arun(case())
