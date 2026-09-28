"""World health (``obs.world_health``, S1-SYS-89): per world role counts over
the whole run, and the per-run flag of world artefacts in the failure window,
on F/F-infra/E/X only (no tier change). Table-driven from small synthetic
logs; parity with the emitters is pinned where obs restates a name: the
world's actor, the empty-output hashes of the real adapter, the kernel's
world_error head and the agent actors."""

from __future__ import annotations

import asyncio
import itertools
import json
from pathlib import Path
from typing import Any, get_args

import httpx
import pytest
from tests.contract.samples import GEMINI
from tests.llm.wire import Recorder, counter_clock, set_env, sse, stream_response
from tests.obs.bundles import LIVE_REFS, Log, manifest, write
from tests.obs.path_bundle import Run, success

from proxyloop.contract.base import sha256_text
from proxyloop.contract.events import EVENT_TYPES
from proxyloop.contract.llm import (
    ChatMessage,
    LLMCallRecord,
    LLMRole,
    TextRequest,
    ToolRequest,
    ToolSpec,
    Usage,
    tool_response_content,
)
from proxyloop.env import world
from proxyloop.kernel import session
from proxyloop.llm.factory import make_client
from proxyloop.obs import detectors, diagnose, world_health
from proxyloop.obs.detectors import Inputs

TEXT_EMPTY = sha256_text("")
TOOLS_EMPTY = sha256_text(tool_response_content("", ()))
_AGENT = {"fast_user": "fast.user", "fast_cp": "fast.cp", "slow": "slow"}
K = dict[str, Any]


def call(
    log: Log,
    role: LLMRole = "ear",
    *,
    finish: str = "stop",
    sha: str | None = "visible",
    error: str | None = None,
    reasoning: int | None = None,
    ms: int = 10,
    call_id: str | None = None,
) -> int:
    """One llm.call as its writer emits it (world: ``world.<role>``)."""
    ref = LIVE_REFS[role]
    usage = Usage(prompt_tokens=1, completion_tokens=1, reasoning_tokens=reasoning)
    record = LLMCallRecord(
        call_id=call_id or f"{role}:{len(log.events)}", role=role, model_ref=ref,
        adapter_kind=ref.kind, requested_model=ref.model_id, served_model_echo=None,
        request_id=None, prompt_sha="p", response_sha=sha, usage=usage, t_start=5,
        t_first_token=None, t_end=5 + ms, finish_reason=None if error else finish,
        attempt=0, error=error,
    )  # fmt: skip
    world_role = role not in _AGENT
    actor = f"world.{role}" if world_role else _AGENT[role]
    payload = record.model_dump(mode="json")
    log.add("llm.call", actor, "world" if world_role else "agent", payload,
            (log.start,))  # fmt: skip
    return len(log.events) - 1


def result(log: Log, type_: str, attempts: int, **more: object) -> int:
    actor = {"rep.ear": "world.ear", "rep.mouth": "world.mouth",
             "user.sim": "world.simuser"}[type_]  # fmt: skip
    payload = _stub(type_) | {"attempts": attempts, **more}
    log.add(type_, actor, "world", payload, (log.start,))
    return len(log.events) - 1


def _stub(type_: str) -> dict[str, object]:
    """The payload keys the contract requires, unset: obs reads none of them."""
    out: dict[str, object] = {}
    out.update(dict.fromkeys(EVENT_TYPES[type_].payload_keys))
    return out


def fallback(log: Log) -> int:
    return result(log, "rep.mouth", 3, fidelity_ok=False)


def agent(log: Log, type_: str = "llm.call", actor: str = "slow") -> int:
    """An event Slow or Fast writes; an llm.call is a real record."""
    if type_ == "llm.call":
        return call(log, "slow" if actor == "slow" else "fast_cp")
    log.add(type_, actor, "agent", _stub(type_), (log.start,))
    return len(log.events) - 1


def end(log: Log, reason: str = "abandoned", message: str | None = None) -> int:
    payload: dict[str, object] = {"reason": reason}
    if message is not None:
        payload["world_error"] = {"type": "WorldError", "message": message}
    log.add("session.ended", "kernel", "ops", payload)
    return len(log.events) - 1


def status(log: Log, to: str) -> int:
    changed: dict[str, object] = {"previous": "IN_CALL", "status": to}
    log.add("status.changed", "guard", "agent", changed, (log.start,))
    return len(log.events) - 1


def inputs(log: Log) -> Inputs:
    return Inputs(log.events, None, lambda _: None)


def art(seq: int, kind: str, role: str, detail: str | None = None) -> K:
    """An artefact in the window that is not the failure event itself."""
    return {"seq": seq, "kind": kind, "role": role, "detail": detail, "self": False}


def roles(log: Log) -> Any:
    return world_health.roles(inputs(log))


# -- parity with the emitters -------------------------------------------------


def test_roles_are_the_world_llm_roles_and_their_actor() -> None:
    assert set(world_health.ROLES) == set(get_args(LLMRole)) - {*_AGENT, "teacher"}
    emitted: list[tuple[str, str]] = []

    class Sink:
        def emit(self, type_: str, actor: str, payload: object, causes: object) -> str:
            emitted.append((type_, actor))
            return "e"

        def store(self, kind: str, content: str) -> None:
            pass

    w = world.World(Sink())
    for role in world_health.ROLES:
        record = LLMCallRecord.model_validate(_record(role))
        w._causes[record.call_id] = "c"  # pyright: ignore[reportPrivateUsage]
        w.record(record)
    assert emitted == [("llm.call", f"world.{r}") for r in world_health.ROLES]


def _record(role: LLMRole) -> dict[str, object]:
    log = Log("r")
    call(log, role)
    return log.events[-1].payload


def test_agent_actors_are_the_kernels() -> None:
    actors = session._ACTOR.values()  # pyright: ignore[reportPrivateUsage]
    assert frozenset(actors) == world_health.AGENT


REQUEST = TextRequest(
    call_id="mouth:c:0", role="mouth", max_tokens=8, temperature=0.7,
    messages=(ChatMessage(role="user", content="U"),),
)  # fmt: skip
TOOLS = ToolRequest(
    call_id="ear:c:0", role="ear", max_tokens=8,
    messages=(ChatMessage(role="user", content="U"),),
    tools=(ToolSpec(name="classify", description="d", parameters={}),),
)  # fmt: skip


def test_empty_hashes_are_what_the_real_adapter_records(monkeypatch: Any) -> None:
    """A reasoning-only stream and a tool response with no text and no call,
    both cut at the cap, through the real ChatClient (transport double)."""
    model = GEMINI.model_id
    usage: dict[str, Any] = {"prompt_tokens": 3, "completion_tokens": 8}
    usage["completion_tokens_details"] = {"reasoning_tokens": 8}
    thinking: dict[str, Any] = {"index": 0, "delta": {"reasoning": "hm"}}
    cut: dict[str, Any] = {"index": 0, "delta": {}, "finish_reason": "length"}
    chunks: list[dict[str, Any]] = [
        {"id": "x", "model": model, "choices": [c]} for c in (thinking, cut)
    ]
    chunks[-1]["usage"] = usage
    message = {"role": "assistant", "content": None}  # no text, no tool call
    choice = {"index": 0, "message": message, "finish_reason": "length"}
    body = {"id": "y", "model": model, "usage": usage, "choices": [choice]}
    wire = Recorder(stream_response(sse(*chunks)), httpx.Response(200, json=body))
    set_env(monkeypatch, "teamrouter")
    records: list[LLMCallRecord] = []
    client = make_client(
        GEMINI, live=True, clock=counter_clock(), on_record=records.append,
        transport=wire.transport(),
    )  # fmt: skip

    async def go() -> list[str]:
        said = [x async for x in client.stream_text(REQUEST) if isinstance(x, str)]
        await client.chat_tools(TOOLS)
        return said

    assert asyncio.run(go()) == []
    assert [r.finish_reason for r in records] == ["length", "length"]
    assert [r.response_sha for r in records] == [TEXT_EMPTY, TOOLS_EMPTY]
    empty = world_health._EMPTY  # pyright: ignore[reportPrivateUsage]
    assert {TEXT_EMPTY, TOOLS_EMPTY} == empty


def _world_error(what: str, timeout: bool) -> dict[str, str] | None:
    async def attempt(n: int) -> int:
        if timeout:
            await asyncio.sleep(1)
        return n

    def check(n: int) -> int:
        raise world.Invalid("no")

    async def go() -> None:
        await world.bounded(attempt, check, what=what,
                            timeout_s=0.01 if timeout else 5)  # fmt: skip

    with pytest.raises(world.WorldError) as caught:
        asyncio.run(go())
    return session._world_error(caught.value)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("role", ["ear", "mouth", "simuser"])
@pytest.mark.parametrize(("timeout", "detail"), [(False, "exhausted"),
                                                 (True, "timeout")])  # fmt: skip
def test_world_error_head_is_the_kernels(role: str, timeout: bool, detail: str) -> None:
    log = Log("r")
    err = _world_error(role, timeout)
    assert err is not None
    seq = end(log, "world_error", err["message"])
    got = world_health.artefacts(inputs(log))
    assert got == [{"seq": seq, "kind": "world_error", "role": role, "detail": detail}]


# -- the whole run's counts ---------------------------------------------------

COUNTS: list[tuple[str, list[K], str, str, object]] = [
    ("each record, a retry too", [{}, {"call_id": "ear:x"}, {"call_id": "ear:x"}],
     "ear", "calls", 3),
    ("per role", [{"role": "mouth"}, {"role": "simuser"}], "ear", "calls", 0),
    ("agent calls are not the world's", [{"role": "fast_cp", "finish": "length",
     "sha": TEXT_EMPTY}], "ear", "finish_length", 0),
    ("finish_length", [{"finish": "length"}, {}], "ear", "finish_length", 1),
    ("length with visible text is not empty", [{"finish": "length"}], "ear",
     "length_empty", 0),
    ("length, empty text", [{"role": "mouth", "finish": "length", "sha": TEXT_EMPTY}],
     "mouth", "length_empty", 1),
    ("length, empty tool response", [{"finish": "length", "sha": TOOLS_EMPTY}], "ear",
     "length_empty", 1),
    ("empty but not cut is not length_empty", [{"sha": TEXT_EMPTY}], "ear",
     "length_empty", 0),
    ("errors", [{"error": "HTTP 500"}, {"error": "x"}, {"error": "cancelled"}], "ear",
     "errors", 2),
    ("cancelled is no error", [{"error": "cancelled"}], "ear", "cancelled", 1),
    ("reasoning p50", [{"reasoning": 30}, {"reasoning": 10}, {"reasoning": 20},
     {}], "ear", "reasoning_tokens_p50", 20),
    ("reasoning n", [{"reasoning": 3}, {}], "ear", "reasoning_n", 1),
    ("reasoning none", [{}], "ear", "reasoning_tokens_p50", None),
    ("latency p50 over ok calls", [{"ms": 100}, {"ms": 300}, {"ms": 200},
     {"ms": 9000, "error": "HTTP 500"}], "ear", "latency_p50_ms", 200),
    ("latency skips cancelled", [{"ms": 100}, {"ms": 9000, "error": "cancelled"}],
     "ear", "latency_p95_ms", 100),
    ("latency p95 nearest rank", [{"ms": m} for m in range(1, 21)], "ear",
     "latency_p95_ms", 19),
    ("latency n", [{}, {"error": "cancelled"}, {"error": "x"}], "ear", "latency_n",
     1),
    ("latency none", [{"error": "x"}], "ear", "latency_p50_ms", None),
]  # fmt: skip


@pytest.mark.parametrize(("why", "calls", "role", "key", "want"), COUNTS,
                         ids=[c[0] for c in COUNTS])  # fmt: skip
def test_call_counts(
    why: str, calls: list[K], role: str, key: str, want: object
) -> None:
    log = Log("r")
    for kw in calls:
        call(log, **kw)
    assert roles(log)[role][key] == want


RESULTS: list[tuple[str, list[tuple[str, int, K]], str, int]] = [
    ("one ear call classifies a block: once", [("rep.ear", 3, {"call_id": "e1"}),
     ("rep.ear", 3, {"call_id": "e1"}), ("rep.ear", 1, {"call_id": "e2"})], "ear", 1),
    ("two ear calls", [("rep.ear", 2, {"call_id": "e1"}),
     ("rep.ear", 2, {"call_id": "e2"})], "ear", 2),
    ("mouth", [("rep.mouth", 2, {"fidelity_ok": True}),
     ("rep.mouth", 1, {"fidelity_ok": True})], "mouth", 1),
    ("simuser", [("user.sim", 2, {}), ("user.sim", 3, {})], "simuser", 2),
    ("one attempt is not more", [("user.sim", 1, {})], "simuser", 0),
    ("per role", [("rep.mouth", 3, {"fidelity_ok": True})], "ear", 0),
]  # fmt: skip


@pytest.mark.parametrize(("why", "events", "role", "want"), RESULTS,
                         ids=[c[0] for c in RESULTS])  # fmt: skip
def test_attempts_over_one(
    why: str, events: list[tuple[str, int, K]], role: str, want: int
) -> None:
    log = Log("r")
    for type_, attempts, more in events:
        result(log, type_, attempts, **more)
    assert roles(log)[role]["attempts_gt1"] == want


EXHAUSTED: list[tuple[str, str | None, str, object]] = [
    ("ear exhausted", "ear: invalid after 2 regenerations", "ear", 1),
    ("not the simuser", "ear: invalid after 2 regenerations", "simuser", 0),
    ("a timeout is not exhausted", "simuser: no answer within 60.0 s", "simuser", 0),
    ("no head: unknown", None, "ear", None),
    ("no head: unknown simuser", None, "simuser", None),
    ("the mouth: its fallbacks, not the end", None, "mouth", 1),
]  # fmt: skip


@pytest.mark.parametrize(("why", "message", "role", "want"), EXHAUSTED,
                         ids=[c[0] for c in EXHAUSTED])  # fmt: skip
def test_exhausted(why: str, message: str | None, role: str, want: object) -> None:
    log = Log("r")
    fallback(log)
    result(log, "rep.mouth", 1, fidelity_ok=True)
    end(log, "world_error", message)
    assert roles(log)[role]["exhausted"] == want


def test_no_world_error_end_is_none_exhausted() -> None:
    log = Log("r")
    end(log, "abandoned")
    assert [roles(log)[r]["exhausted"] for r in world_health.ROLES] == [0, 0, 0]


def test_fidelity_fallback_seqs() -> None:
    log = Log("r")
    result(log, "rep.mouth", 1, fidelity_ok=True)
    a, b = fallback(log), fallback(log)
    assert roles(log)["mouth"]["fidelity_fallback"] == {"count": 2, "seqs": [a, b]}
    assert "fidelity_fallback" not in roles(log)["ear"]


# -- the failure window -------------------------------------------------------


def window(log: Log, tier: object = "F") -> Any:
    return world_health.window(inputs(log), tier)


def test_the_window_inside_and_the_nearest_before() -> None:
    log = Log("r")
    call(log, finish="length", sha=TOOLS_EMPTY)  # 1: far before
    agent(log, "fast.request", "fast.cp")  # 2: a turn begins
    near = fallback(log)  # 3: just outside
    agent(log, "slow.step.started")  # 4: a turn begins
    edge = agent(log)  # 5: Slow's last event (an llm.call)
    inside = fallback(log)  # 6: just inside
    fail = end(log)  # 7
    got = window(log)
    assert (got["failure"], got["failure_seq"], got["after_seq"]) == (
        "session.ended", fail, edge,
    )  # fmt: skip
    assert got["count"] == 1 and got["seqs"] == [inside]
    assert got["artefacts"] == [art(inside, "fidelity_fallback", "mouth")]
    assert got["nearest_before"] == {"seq": near, "kind": "fidelity_fallback",
                                     "role": "mouth", "detail": None,
                                     "agent_turns": 1}  # fmt: skip


def test_turns_counted_after_the_nearest_only() -> None:
    log = Log("r")
    agent(log, "slow.step.started")  # before the artefact: not counted
    a = call(log, "simuser", finish="length", sha=TOOLS_EMPTY)
    agent(log, "fast.request", "fast.user")
    agent(log, "fast.sentence", "fast.user")  # an agent event, no turn start
    agent(log, "fast.request", "fast.cp")
    end(log)
    near = window(log)["nearest_before"]
    assert (near["seq"], near["kind"], near["role"], near["agent_turns"]) == (
        a, "length_empty", "simuser", 2,
    )  # fmt: skip
    assert window(log)["count"] == 0


def test_a_world_event_is_not_the_edge() -> None:
    log = Log("r")
    agent(log, "fast.turn", "fast.cp")
    a = fallback(log)
    result(log, "rep.mouth", 1, fidelity_ok=True)  # world, not agent
    call(log, "ear")  # a world call, not agent
    end(log)
    assert window(log)["seqs"] == [a]


def test_an_agent_call_cut_empty_is_no_world_artefact() -> None:
    log = Log("r")
    call(log, "fast_cp", finish="length", sha=TEXT_EMPTY)
    call(log, "slow", finish="length", sha=TOOLS_EMPTY)
    assert world_health.artefacts(inputs(log)) == []


def test_no_agent_event_opens_at_the_start() -> None:
    log = Log("r")
    a = call(log, "mouth", finish="length", sha=TEXT_EMPTY)
    fail = end(log, "world_error", "ear: invalid after 2 regenerations")
    got = window(log, "F-infra")
    assert got["after_seq"] is None and got["seqs"] == [a, fail]
    assert got["nearest_before"] is None
    assert got["artefacts"][1] == {"seq": fail, "kind": "world_error", "role": "ear",
                                   "detail": "exhausted", "self": True}  # fmt: skip
    assert got["artefacts"][0]["self"] is False


def test_a_terminal_status_first_is_the_failure() -> None:
    log = Log("r")
    agent(log)
    status(log, "IN_CALL")  # not terminal
    a = fallback(log)
    fail = status(log, "VERIFIED_NO_DEAL")
    fallback(log)  # after the failure: out
    end(log, "world_error")
    got = window(log, "E")
    assert (got["failure"], got["failure_seq"], got["seqs"]) == (
        "status.changed", fail, [a],
    )  # fmt: skip


def test_the_first_terminal_status_is_the_failure() -> None:
    log = Log("r")
    agent(log)
    a = fallback(log)
    fail = status(log, "VERIFIED_NO_DEAL")
    fallback(log)
    status(log, "CLOSED_NO_ACTION")  # a second terminal status: not the failure
    end(log, "no_deal")
    got = window(log, "E")
    assert (got["failure_seq"], got["seqs"]) == (fail, [a])


def test_the_end_first_is_the_failure() -> None:
    log = Log("r")
    agent(log)
    a = fallback(log)
    fail = end(log)
    status(log, "ESCALATED")  # after the end: never the failure
    got = window(log)
    assert (got["failure_seq"], got["seqs"]) == (fail, [a])


def test_an_agent_event_after_the_failure_is_no_edge() -> None:
    log = Log("r")
    edge = agent(log)
    a = fallback(log)
    end(log)
    agent(log)  # a late Slow llm.call after the end
    got = window(log)
    assert (got["after_seq"], got["seqs"]) == (edge, [a])


def test_no_failure_event_is_unknown() -> None:
    log = Log("r")
    fallback(log)
    got = window(log, "X")
    assert got["count"] is None and got["failure_seq"] is None and got["seqs"] == []


@pytest.mark.parametrize(
    ("tier", "flagged"),
    [("F", True), ("F-infra", True), ("E", True), ("X", True), ("A", False),
     ("B", False), ("C", False), ("D", False), ("S", False), (None, False)],
)  # fmt: skip
def test_the_flag_runs_on_failing_tiers_only(tier: object, flagged: bool) -> None:
    log = Log("r")
    fallback(log)
    end(log)
    got = window(log, tier)
    assert (got is not None) == flagged
    if flagged:
        assert got["tier"] == tier and got["count"] == 1


def _tier(r: Run) -> object:
    return detectors.DETECTORS["tier"](r.inputs())


def test_run_reads_the_tier_and_never_changes_it() -> None:
    x = Run()  # X: an accept heard with no authorization
    x.commit(x.spoken("u-1"))
    fallback(x.log)
    x.end("abandoned")
    before = _tier(x)
    got: Any = world_health.run(x.inputs())
    assert got["label"] == "DIAGNOSTIC — not a claim or metric"
    assert as_tier(got) == "X" and got["window"]["count"] == 1
    assert _tier(x) == before
    ok = success()  # A or B: no flag
    assert world_health.run(ok.inputs())["window"] is None


def as_tier(got: Any) -> object:
    return got["window"]["tier"]


# -- diagnose ------------------------------------------------------------------


def _bundle(root: Path, run_id: str, where: str | None) -> None:
    """An F run (``abandoned``): a fallback ``before`` or ``in`` the window."""
    log = Log(run_id)
    log.events[0].payload["task_ref"] = "fam-a@1"
    call(log, "ear", reasoning=4)
    if where == "before":
        fallback(log)
    agent(log)
    if where == "in":
        fallback(log)
    end(log, "abandoned")
    write(root / run_id, log, manifest(run_id))


def test_diagnose_shows_the_flag_beside_the_tier(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _bundle(tmp_path, "rW", "in")
    _bundle(tmp_path, "rB", "before")
    _bundle(tmp_path, "rQ", None)
    assert diagnose.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out.splitlines()

    def beside(run_id: str) -> list[str]:
        row = next(line for line in out if f" {run_id} " in line).split()
        at = next(i for i, c in enumerate(row) if c.startswith("tier="))
        return list(
            itertools.takewhile(lambda c: c.startswith("artefact_"), row[at + 1 :])
        )

    assert beside("rW") == ["artefact_window=3"]
    assert beside("rB") == ["artefact_before=2:fidelity_fallback:0t"]
    assert beside("rQ") == []
    head = f"== world git_sha g ({world_health.LABEL})"
    block = out[out.index(head) :]
    assert block[1] == f"  legend: {world_health.LEGEND}"
    assert "length_empty" in block[1] and "fidelity_ok false" in block[1]
    assert block[2] == (
        "  fam-a runs=3 flagged=3 in_window=1 world_failure=0 nearest_before=1"
    )
    assert block[3].split()[:3] == ["ear", "calls=3", "finish_length=0"]
    assert "    window rW seqs=[3]" in block
    assert "    before rB 2:fidelity_fallback:0t" in block
    assert diagnose.main(["--root", str(tmp_path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    fam = doc["world"]["git_sha:g"]["families"]["fam-a"]
    assert fam["in_window"] == {"rW": [3]} and fam["roles"]["ear"]["calls"] == 3
    rows = {r["run_id"]: r for r in doc["runs"]}
    assert rows["rW"]["world"]["roles"]["ear"]["reasoning_tokens_p50"] == 4


def test_summary_counts_unknowns_apart() -> None:
    rows: list[dict[str, Any]] = [
        {"run_id": "r1", "detectors": {"tier": {"family": "fam"}},
         "world": {"roles": {"ear": {"calls": 2, "exhausted": None}}, "window": None}},
        {"run_id": "r2", "detectors": {"tier": {"family": "fam"}},
         "world": {"roles": {"ear": {"calls": 1, "exhausted": 1}},
                   "window": {"tier": "F", "count": 0, "seqs": [], "artefacts": [],
                              "nearest_before": {"seq": 4, "kind": "k",
                                                 "agent_turns": 2}}}},
    ]  # fmt: skip
    families: Any = world_health.summary(rows)["families"]
    fam = families["fam"]
    assert fam["runs"] == 2 and fam["flagged"] == 1 and fam["in_window"] == {}
    assert fam["nearest_before"] == {"r2": {"seq": 4, "kind": "k", "agent_turns": 2}}
    ear = fam["roles"]["ear"]
    assert (ear["calls"], ear["exhausted"], ear["exhausted_unknown"]) == (3, 1, 1)


# -- rev-273: the rulings and the review fixes --------------------------------

TAILS = [
    "ear: invalid after 2 regenerations: ear: invalid after 2 regenerations",
    "simuser: no answer within 60.0 s; model said simuser: no answer within 1 s",
    "model text ear: invalid after 2 regenerations",
    "mouth: invalid after 2 regenerations.",
]


@pytest.mark.parametrize("message", TAILS)
def test_model_text_around_a_head_matches_nothing(message: str) -> None:
    """R1: only a whole kernel-authored head is read; a tail after it (an
    Invalid's reason may quote model output) voids it."""
    log = Log("r")
    seq = end(log, "world_error", message)
    got = world_health.artefacts(inputs(log))
    assert got == [{"seq": seq, "kind": "world_error", "role": None, "detail": None}]
    assert roles(log)["ear"]["exhausted"] is None


def _dies(log: Log, role: LLMRole, recovered: LLMRole | None = None) -> int:
    """``recovered`` fails once and succeeds on its retry; ``role`` fails for
    good; the session ends llm_unavailable after a teardown cancellation."""
    if recovered is not None:
        call(log, recovered, error="ConnectTimeout: ", call_id="again")
        call(log, recovered, call_id="again")
    seq = call(log, role, error="ConnectError: All connection attempts failed")
    call(log, "slow", error="cancelled")
    end(log, "llm_unavailable")
    return seq


@pytest.mark.parametrize("role", ["ear", "mouth", "simuser"])
def test_a_world_endpoint_dying_is_an_artefact(role: LLMRole) -> None:
    """R2: the failing call is a world actor's."""
    log = Log("r")
    agent(log)
    call(log, "fast_cp", error="cancelled")  # a cancellation is no failure
    dead = _dies(log, role)
    got = window(log, "F-infra")
    assert got["artefacts"] == [art(dead, "llm_unavailable", role)]


@pytest.mark.parametrize("role", ["fast_cp", "fast_user", "slow"])
def test_an_agent_endpoint_dying_never_is(role: LLMRole) -> None:
    """R2: the failing call is the agent's, even after a world call that a
    retry recovered."""
    log = Log("r")
    _dies(log, role, recovered="ear")
    assert world_health.artefacts(inputs(log)) == []
    assert window(log, "F-infra")["count"] == 0


def test_a_world_call_failing_is_no_artefact_without_the_end() -> None:
    log = Log("r")
    call(log, "mouth", error="ConnectError: x")
    end(log, "abandoned")
    assert world_health.artefacts(inputs(log)) == []


def test_teardown_cancellations_are_no_edge() -> None:
    """The reviewer's log: the Mouth fallback is in the window, not behind a
    cancelled call the teardown wrote."""
    log = Log("r")
    edge = agent(log, "fast.request", "fast.cp")
    fell = fallback(log)
    call(log, "fast_cp", error="cancelled")
    fail = end(log, "abandoned")
    got = window(log)
    assert (got["after_seq"], got["seqs"], got["failure_seq"]) == (edge, [fell], fail)


def test_a_fast_cancelled_is_no_edge() -> None:
    log = Log("r")
    edge = agent(log)
    fell = fallback(log)
    agent(log, "fast.cancelled", "fast.user")
    call(log, "slow", error="cancelled")
    end(log)
    assert (window(log)["after_seq"], window(log)["seqs"]) == (edge, [fell])


def test_an_agent_call_that_failed_is_an_edge() -> None:
    log = Log("r")
    fallback(log)
    edge = call(log, "fast_cp", error="ConnectError: x")
    end(log, "llm_unavailable")
    assert (window(log, "F-infra")["after_seq"], window(log)["count"]) == (edge, 0)


def test_no_turn_after_a_terminal_status_counts() -> None:
    log = Log("r")
    call(log, "ear", finish="length", sha=TOOLS_EMPTY)
    agent(log, "fast.request", "fast.cp")
    fail = status(log, "VERIFIED_NO_DEAL")
    agent(log, "fast.request", "fast.cp")  # after the failure event
    end(log, "no_deal")
    got = window(log, "E")
    assert got["failure_seq"] == fail and got["nearest_before"]["agent_turns"] == 1


def test_a_rep_mouth_without_fidelity_ok_is_no_fallback() -> None:
    log = Log("r")
    result(log, "rep.mouth", 3)  # legacy: fidelity_ok unset
    assert roles(log)["mouth"]["fidelity_fallback"] == {"count": 0, "seqs": []}
    assert world_health.artefacts(inputs(log)) == []


def test_zero_reasoning_tokens_count() -> None:
    log = Log("r")
    call(log, reasoning=0)
    call(log, reasoning=0)
    call(log, reasoning=8)
    got = roles(log)["ear"]
    assert (got["reasoning_n"], got["reasoning_tokens_p50"]) == (3, 0)


def test_an_unknown_window_shows_a_question_mark() -> None:
    log = Log("r")
    fallback(log)
    flag = window(log, "X")  # no failure event yet
    assert world_health.cells({"window": flag}) == ["artefact_window=?"]


def test_the_failure_itself_is_marked_self() -> None:
    log = Log("r")
    agent(log)
    fell = fallback(log)
    fail = end(log, "world_error", "mouth: no answer within 60.0 s")
    flag = window(log, "F-infra")
    assert world_health.cells({"window": flag}) == [
        f"artefact_window={fell},{fail}:self"
    ]
    rows: list[Any] = [{"run_id": "r", "detectors": {"tier": {"family": "f"}},
                        "world": {"roles": {}, "window": flag}}]  # fmt: skip
    families: Any = world_health.summary(rows)["families"]
    fam = families["f"]
    assert (fam["in_window"], fam["world_failure"]) == ({"r": [fell]}, ["r"])
    alone = Log("r")
    agent(alone)
    end(alone, "world_error", "mouth: no answer within 60.0 s")
    rows[0]["world"]["window"] = window(alone, "F-infra")
    families = world_health.summary(rows)["families"]
    fam = families["f"]
    assert (fam["in_window"], fam["world_failure"]) == ({}, ["r"])


def test_a_rep_ear_without_call_id_makes_attempts_unknown() -> None:
    log = Log("r")
    result(log, "rep.ear", 3, call_id="e1")
    result(log, "rep.ear", 1, call_id=None)
    result(log, "rep.ear", 2, call_id=None)
    result(log, "rep.mouth", 2, fidelity_ok=True)
    got = world_health.roles(inputs(log))
    assert got["ear"]["attempts_gt1"] is None and got["mouth"]["attempts_gt1"] == 1
