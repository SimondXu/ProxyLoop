"""World-model selection, PR2a (S1-MOD-09): the replay through the production world
code, offline. Clients come from the real factory (the relay adapter over an
httpx.MockTransport); the bundle is a hand-built rep log (tests/serving/
test_world_select.Log) holding one recorded Ear, Mouth and SimUser call, on the
manifest of one fake session."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from tests.kernel.test_session import SCRIPTS, UNTIL
from tests.llm.wire import HOSTS, KEY, chat_chunks, set_env, sse, stream_response
from tests.llm.wire import tool_body as wire_tool_body
from tests.serving.test_world_select import OFFER, Log, manifest, run_dir
from tests.support.sessions import run as run_session

from proxyloop.contract.base import sha256_text
from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS
from proxyloop.contract.llm import (
    AdapterKind,
    LLMUnavailable,
    ModelRef,
    ToolCall,
    request_content,
    tool_response_content,
)
from proxyloop.env import world
from proxyloop.env.counterparty.ear import Ear, Heard
from proxyloop.env.counterparty.mouth import Mouth, template
from proxyloop.env.counterparty.policy import PublicIntent
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.user.simuser import SimUser
from scripts.mod import world_select as ws
from scripts.mod import world_select_run as wsr

Json = dict[str, Any]
GEMINI = ModelRef(
    kind=AdapterKind.REAL_HTTP,
    endpoint="teamrouter",
    model_id="gemini-3.8-flash",
    reasoning_effort="low",
)
INCUMBENT, CANDIDATE = (
    "teamrouter:gemini-3.8-flash@low",
    "teamrouter:deepseek-flash@low",
)
ECHO = (
    "deepseek-v4-1-flash-260910"  # deepseek-flash's served echo: recorded, not an error
)
HEARD = "Could you do any better on the monthly price?"
INTENT = PublicIntent(
    kind="offer", offer_ref="loyal-1", say=(("monthly_price", "75.00"),)
)
BLOCK = ["I am calling for Dana.", "Could you read back loyal-1 in full?"]
ACTS = json.dumps({"acts": [{"act": "other"}, {"act": "ask_readback"}]})
SINGLE = json.dumps({"acts": [{"act": "ask_discount"}]})
REPLY = json.dumps({"text": "I pay 70 now.", "revealed": {}})
ASKED = "Assistant: What do you pay now?"
SIMS: list[tuple[str, list[str], dict[str, str]]] = [
    ("s0", [], {}),  # the opening (no chat yet), the profile's facts
    ("s1", [ASKED], {}),
    ("s2", ["Assistant: hi"], {"account.pin": "0000"}),
]


@pytest.fixture(scope="module")
def like(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One fake session: its manifest is the hand-built bundle's."""
    root = tmp_path_factory.mktemp("like")
    run_session(root / "a", SCRIPTS, until=UNTIL)
    return run_dir(root, "a")


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, "teamrouter")


def call(log: Log, role: str, cause: str, sha: str, response: str | None = None) -> str:
    """A recorded world ``llm.call`` by the incumbent."""
    record: Json = {"call_id": f"{role}:{cause}:0", "role": role, "attempt": 0}
    record |= {"model_ref": GEMINI.model_dump(mode="json"), "adapter_kind": "real_http"}
    record |= {"requested_model": GEMINI.model_id, "served_model_echo": "gemini"}
    record |= {"request_id": None, "prompt_sha": sha, "finish_reason": "stop"}
    record |= {"response_sha": response and sha256_text(response)}
    record |= {"usage": {"prompt_tokens": 300, "completion_tokens": 20}}
    record |= {"t_start": 0, "t_first_token": None, "t_end": 5}
    return log.emit("llm.call", f"world.{role}", record, [cause], 5)


def build(tmp: Path, like: Path) -> Path:
    """The items file and its bundle (``tmp/runs``): a recorded Ear single, Mouth
    and SimUser item, and a constructed Ear block, Mouth and SimUser item."""
    m = manifest(like)
    task = ws.task_of(m["task_ref"])
    cp = task.counterparty
    log = Log("r-1")
    u1 = log.say(HEARD, 0)
    ear = log.emit(
        "rep.ear", "world.ear", ear_payload(u1), [u1, call(log, "ear", u1, "e")], 6
    )
    intent = INTENT.model_dump(mode="json")
    policy = log.emit(
        "rep.policy",
        "world.policy",
        {"from": "A", "to": "B", "rung": 0, "intent": intent},
        [ear],
        7,
    )
    mouth_sha = sha256_text(
        request_content(
            Mouth(wsr.UNUSED, wsr.UNUSED, cp).request(INTENT, HEARD, "x", 0)
        )
    )
    said = "I can offer 75.00 a month."
    line = {"intent": intent, "text": said, "fidelity_ok": True, "attempts": 1}
    rep_mouth = log.emit(
        "rep.mouth",
        "world.mouth",
        line,
        [policy, call(log, "mouth", policy, mouth_sha)],
        8,
    )
    response = tool_response_content(
        "", (ToolCall(call_id="t", name="reply", arguments=REPLY),)
    )
    sims: list[Json] = []
    for item_id, chat, facts in SIMS:  # s2: facts the task never had, no rebuild
        builder = SimUser(task, wsr.UNUSED, wsr.UNUSED, 0)
        content = request_content(
            builder.request(chat, facts or dict(task.profile.facts), None, "c", 0)
        )
        sim_call = call(log, "simuser", u1, sha256_text(content), response)
        out: Json = {"text": "I pay 70 now.", "revealed": {}, "delay_s": 1.0}
        log.emit("user.sim", "world.simuser", out, [u1, sim_call], 9)
        recorded = {"llm_calls": [sim_call], "response_shas": [sha256_text(response)]}
        recorded |= {"run_id": "r-1", "output": {"text": "I pay 70 now."}}
        sims.append({"item_id": item_id, "prompt_sha": sha256_text(content)})
        sims[-1] |= {"occurrences": [recorded], "content": content}
    runs = tmp / "runs"
    d = log.write(runs, like)
    models = m["models"] | {
        r: {"ref": GEMINI.model_dump(mode="json")} for r in ws.ROLES
    }
    (d / MANIFEST).write_text(json.dumps(manifest(d) | {"models": models}), "utf-8")
    prompts = [("response", response)] + [("messages", i.pop("content")) for i in sims]
    (d / PROMPTS).write_text(
        "".join(
            json.dumps({"sha": sha256_text(c), "kind": k, "content": c}) + "\n"
            for k, c in prompts
        )
    )
    occ = {"run_id": "r-1"}
    items: Json = {
        "ear": [
            {
                "item_id": "e1",
                "kind": "single",
                "company": cp.company,
                "identity_keys": list(cp.identity),
                "offers": [{"ref": "loyal-1", "terms": OFFER, "open": False}],
                "utterances": [HEARD],
                "occurrences": [occ | {"rep_ear": ear, "heard": [u1]}],
            }
        ],
        "mouth": [
            {
                "item_id": "m1",
                "company": cp.company,
                "heard": HEARD,
                "intent": intent,
                "persona_sha": sha256_text(cp.persona.strip()),
                "occurrences": [
                    occ
                    | {
                        "event_id": rep_mouth,
                        "prompt_sha": mouth_sha,
                        "output": said,
                        "fidelity_ok": True,
                        "attempts": 1,
                    }
                ],
            }
        ],
        "simuser": sims,
    }
    say = {"term_months": "12", "monthly_price": "75.00"}
    made_intent = PublicIntent(
        kind="offer", offer_ref="loyal-1", say=tuple(sorted(say.items(), reverse=True))
    )
    made: Json = {
        "ear": [
            {
                "item_id": "c-e1",
                "constructed": True,
                "kind": "block",
                "company": cp.company,
                "identity_keys": list(cp.identity),
                "family": task.family,
                "offers": {"loyal-1": dict(OFFER)},
                "open_offers": ["loyal-1"],
                "block": BLOCK,
            }
        ],
        "mouth": [
            {
                "item_id": "c-m1",
                "name": "c-mouth-1",
                "constructed": True,
                "family": task.family,
                "intent": "offer",
                "offer_ref": "loyal-1",
                "say": dict(sorted(say.items())),
                "ask": [],
                "heard": HEARD,
                "template": template(
                    made_intent, load_task(task.family).counterparty.company
                ),
            }
        ],
        "simuser": [
            {"item_id": "c-s1", "constructed": True, "situation": "prose only"}
        ],
    }
    events = hashlib.sha256((d / EVENTS).read_bytes()).hexdigest()
    bundles = [{"run_id": "r-1", "task_ref": m["task_ref"], "events_sha256": events}]
    ids = sorted(
        i["item_id"] for part in (items, made) for r in ws.ROLES for i in part[r]
    )
    doc: Json = {"bundles": bundles, "items": items, "constructed": made}
    doc["root_hash"] = sha256_text("\n".join(ids))
    path = tmp / "items.json"
    path.write_text(json.dumps(doc), "utf-8")
    return path


def answer(body: Json) -> str:
    """The Ear's valid acts for the item the body is about."""
    return ACTS if "Dana" in json.dumps(body) else SINGLE


def ear_payload(utt: str) -> Json:
    return {"utt_id": utt, "act": "ask_discount", "args": {}, "call_id": "ear:x:0"}


def tool_body(model: str, name: str, arguments: str, echo: str | None = None) -> Json:
    body = wire_tool_body(GEMINI.model_copy(update={"model_id": model}), arguments)
    body["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = name
    return body | {"model": echo or model}


class Wire:
    """The endpoint: every body it received; per request, the next reply its role's
    script holds, or gives for the body (Ear and SimUser: tool arguments; Mouth:
    streamed text), or an ``httpx.Response`` to send as it is."""

    def __init__(self, echo: str | None = None, **scripts: Any) -> None:
        self.bodies: list[Json] = []
        self.scripts, self.echo = scripts, echo

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: Json = json.loads(request.content)
        self.bodies.append(body)
        role = (
            "mouth" if body.get("stream") else body["tool_choice"]["function"]["name"]
        )
        script = self.scripts[role]
        got = script(body) if callable(script) else script.pop(0)
        reply = cast(str | httpx.Response, got)
        if isinstance(reply, httpx.Response):
            return reply
        if role == "mouth":
            ref = GEMINI.model_copy(update={"model_id": self.echo or body["model"]})
            return stream_response(sse(*chat_chunks(ref, [reply])))
        return httpx.Response(
            200, json=tool_body(body["model"], role, reply, self.echo)
        )

    def transports(self) -> dict[str, httpx.AsyncBaseTransport]:
        return {"teamrouter": httpx.MockTransport(self)}


def args(
    items: Path, tmp: Path, *extra: str, arms: tuple[str, ...] = (INCUMBENT,)
) -> argparse.Namespace:
    argv = [
        "--items",
        str(items),
        "--runs",
        str(tmp / "runs"),
        "--out-dir",
        str(tmp / "out"),
    ]
    return wsr.parser().parse_args(
        [*argv, *[a for arm in arms for a in ("--arm", arm)], *extra]
    )


def rows(tmp: Path, arm: str = INCUMBENT) -> list[Json]:
    path = tmp / "out" / wsr.parse_arm(arm).file
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def by_item(tmp: Path, arm: str = INCUMBENT) -> dict[str, Json]:
    return {r["item_id"]: r for r in rows(tmp, arm)}


@pytest.fixture
def items(tmp_path: Path, like: Path) -> Iterator[Path]:
    yield build(tmp_path, like)


def test_the_ear_request_is_ear_request_to_the_byte(
    items: Path, tmp_path: Path
) -> None:
    wire = Wire(classify=answer)
    wsr.run(args(items, tmp_path, "--roles", "ear"), transports=wire.transports())
    doc = json.loads(items.read_text("utf-8"))
    item = doc["constructed"]["ear"][0]
    block = [Heard(utt_id="u", text=t, event_id="e", t_ms=0) for t in BLOCK]
    ear = Ear(wsr.UNUSED, wsr.UNUSED, item["company"], item["identity_keys"])
    expected = ear.request(block, {"loyal-1": dict(OFFER)}, ["loyal-1"], 0)
    sent = next(b for b in wire.bodies if "Dana" in json.dumps(b))
    assert sent["messages"] == [
        {"role": m.role, "content": m.content} for m in expected.messages
    ]
    assert sent["tools"] == [
        {"type": "function", "function": t.model_dump(mode="json")}
        for t in expected.tools
    ]
    assert (sent["max_tokens"], sent["temperature"]) == (world.MAX_TOKENS, 0)
    row = by_item(tmp_path)["c-e1"]
    assert row["request_sha"] == sha256_text(request_content(expected))
    assert row["attempts"][0]["records"][0]["prompt_sha"] == row["request_sha"]
    assert row["status"] == "ok" and row["result"]["acts"] == json.loads(ACTS)["acts"]


def test_regeneration_follows_the_production_bound(items: Path, tmp_path: Path) -> None:
    bad = json.dumps({"acts": [{"act": "other"}]})  # one act for two utterances
    wire = Wire(classify=[SINGLE, bad, "not json", ACTS])
    wsr.run(
        args(items, tmp_path, "--roles", "ear", "--concurrency", "1"),
        transports=wire.transports(),
    )
    got = by_item(tmp_path)
    assert got["e1"]["status"] == "ok" and len(got["e1"]["attempts"]) == 1
    tries = got["c-e1"]["attempts"]
    assert got["c-e1"]["status"] == "ok" and [t["valid"] for t in tries] == [
        False,
        False,
        True,
    ]
    assert tries[0]["reason"] == "1 acts for 2 utterances"
    assert (
        tries[1]["reason"].startswith("schema")
        and tries[1]["raw"][0]["arguments"] == "not json"
    )
    wire = Wire(classify=[bad] * world.MAX_REGENERATIONS + [bad, bad])  # never valid
    (tmp_path / "out").rename(tmp_path / "first")
    wsr.run(
        args(items, tmp_path, "--roles", "ear", "--concurrency", "1"),
        transports=wire.transports(),
    )
    row = by_item(tmp_path)["c-e1"]
    assert row["status"] == "exhausted" and row["result"] is None
    assert len(row["attempts"]) == world.MAX_REGENERATIONS + 1 == len(wire.bodies) - 1


def test_a_timeout_bounds_the_whole_call(items: Path, tmp_path: Path) -> None:
    async def stall(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        raise AssertionError("unreachable")

    transport = {"teamrouter": httpx.MockTransport(stall)}
    wsr.run(args(items, tmp_path, "--roles", "ear", "--limit", "1"), 0.05, transport)
    (row,) = rows(tmp_path)
    assert row["status"] == "timeout" and len(row["attempts"]) == 1
    assert row["attempts"][0]["records"][0]["error"] == "cancelled"


def test_every_arm_calls_the_mouth_the_incumbent_too(
    items: Path, tmp_path: Path, like: Path
) -> None:
    wrong = "I can offer 80 a month."  # fails fidelity: the template stands in
    full, short = "Our offer is 75.00 a month for 12 months.", "It is 75.00 a month."
    wire = Wire(echo=ECHO, mouth=[short, full, short, wrong, wrong, wrong])
    arms = (INCUMBENT, CANDIDATE)
    report = wsr.run(
        args(items, tmp_path, "--roles", "mouth", "--concurrency", "1", arms=arms),
        transports=wire.transports(),
    )
    assert len(wire.bodies) == 2 + 1 + 3  # no recorded output stands in for a call
    cp = ws.task_of(manifest(like)["task_ref"]).counterparty
    built = Mouth(wsr.UNUSED, wsr.UNUSED, cp).request(INTENT, HEARD, "x", 0)
    sent = wire.bodies[0]
    assert sent["messages"] == [
        {"role": m.role, "content": m.content} for m in built.messages
    ]
    assert (sent["temperature"], sent["max_tokens"]) == (
        built.temperature,
        built.max_tokens,
    )
    mine = by_item(tmp_path)
    assert mine["m1"]["status"] == "ok" and mine["m1"]["prompt_sha_match"] is True
    assert mine["m1"]["result"]["text"] == short and "reused" not in mine["m1"]
    recorded = mine["m1"]["recorded_ref"]  # informational: the recorded output's sha
    assert recorded == [{"run_id": "r-1", "response_shas": [None]}]
    assert (
        mine["c-m1"]["prompt_sha_match"] is None and mine["c-m1"]["recorded_ref"] == []
    )
    theirs = by_item(tmp_path, CANDIDATE)
    assert theirs["m1"]["result"] == {
        "text": short,
        "fidelity_ok": True,
        "fallback": False,
        "attempts": 1,
    }
    assert theirs["m1"]["attempts"][0]["records"][0]["echo"] == ECHO
    fell = theirs["c-m1"]
    assert fell["result"]["fallback"] is True
    assert fell["result"]["text"].startswith("I can offer you this:")
    assert [t["valid"] for t in fell["attempts"]] == [False] * 3
    assert fell["status"] == "ok"
    assert report[INCUMBENT] == {"skipped_final": 0, "mouth:ok": 2}


def test_a_mouth_sha_mismatch_is_recorded(items: Path, tmp_path: Path) -> None:
    doc = json.loads(items.read_text("utf-8"))
    older = "0" * 64  # an older Mouth's prompt
    doc["items"]["mouth"][0]["occurrences"][0]["prompt_sha"] = older
    items.write_text(json.dumps(doc), "utf-8")
    wire = Wire(mouth=["Our offer is 75.00 a month."])
    wsr.run(
        args(items, tmp_path, "--roles", "mouth", "--limit", "1"),
        transports=wire.transports(),
    )
    row = by_item(tmp_path)["m1"]
    assert row["prompt_sha_match"] is False and row["status"] == "ok"
    plan = wsr.run(args(items, tmp_path, "--roles", "mouth", "--plan"))
    assert plan["mouth_prompt_sha_mismatch"] == 1


def test_simuser_rebuilds_the_recorded_request_for_every_arm(
    items: Path, tmp_path: Path, like: Path
) -> None:
    wire = Wire(reply=always(REPLY))
    arms = (INCUMBENT, CANDIDATE)
    wsr.run(
        args(items, tmp_path, "--roles", "simuser", arms=arms),
        transports=wire.transports(),
    )
    task = ws.task_of(manifest(like)["task_ref"])
    built = SimUser(task, wsr.UNUSED, wsr.UNUSED, 0).request(
        [ASKED], dict(task.profile.facts), None, "c", 0
    )
    assert len(wire.bodies) == 2 * 3  # both arms; the constructed item makes no call
    sent = [b for b in wire.bodies if ASKED in json.dumps(b)]
    assert len(sent) == 2 and all(
        b["messages"]
        == [{"role": m.role, "content": m.content} for m in built.messages]
        for b in sent
    )
    for arm in arms:
        rows_ = by_item(tmp_path, arm)
        prose, row = rows_["c-s1"], rows_["s1"]
        assert prose["status"] == "not_replayable" and prose["attempts"] == []
        assert prose["result"] is None and prose["constructed"] is True
        assert row["request_source"] == "rebuilt" and row["check"] == "full"
        assert row["request_sha"] == sha256_text(request_content(built))
        reply: Json = {"silent": False, "text": "I pay 70 now.", "revealed": {}}
        assert row["result"] == {"reply": reply}
        assert row["recorded_ref"][0]["response_shas"][0] is not None
        assert rows_["s0"]["check"] == "full" and rows_["s2"]["check"] == "partial"
        assert rows_["s2"]["request_source"] == "recorded"
        assert "does not rebuild" in rows_["s2"]["check_reason"]
    again = wsr.run(
        args(items, tmp_path, "--roles", "simuser", "--resume", arms=(CANDIDATE,))
    )  # every row is final, not_replayable too: no call
    assert again[CANDIDATE] == {"skipped_final": 4}
    prompts = tmp_path / "runs" / "r-1" / PROMPTS
    moved = prompts.read_text("utf-8").replace("What do you pay", "What do you owe")
    prompts.write_text(moved, "utf-8")
    (tmp_path / "out").rename(tmp_path / "first")
    with pytest.raises(SystemExit, match="the replayed request differs"):
        wsr.run(args(items, tmp_path, "--roles", "simuser", arms=(CANDIDATE,)))


def always(reply: str) -> Callable[[Json], str]:
    return lambda _: reply


def replies(*arguments: str) -> httpx.Response:
    """One tool response holding a ``reply`` call per argument (none: no call)."""
    body = tool_body(GEMINI.model_id, "reply", "{}")
    call = body["choices"][0]["message"]["tool_calls"][0]
    calls = [call | {"id": f"t{i}", "function": {"name": "reply", "arguments": a}}
             for i, a in enumerate(arguments)]  # fmt: skip
    body["choices"][0]["message"]["tool_calls"] = calls
    return httpx.Response(200, json=body)


def test_simuser_replies_go_through_check_reply_under_the_bound(
    items: Path, tmp_path: Path
) -> None:
    silent = json.dumps({"silent": True, "revealed": {}})
    unknown = json.dumps(
        {"text": "My pin is 0000.", "revealed": {"account.pin": "0000"}}
    )
    script = {  # per item: its attempts, in order
        "s0": [silent, "not json", REPLY],  # the opening: silent is invalid
        "s1": [replies(), replies(REPLY, REPLY), unknown],  # the task has no pin
        "s2": [unknown],  # partial: no facts to hold the reveal against
    }

    def reply(body: Json) -> str | httpx.Response:
        text = json.dumps(body)
        key = "s1" if ASKED in text else "s2" if "Assistant: hi" in text else "s0"
        return script[key].pop(0)

    wire = Wire(reply=reply)
    wsr.run(
        args(items, tmp_path, "--roles", "simuser", "--limit", "3"),
        transports=wire.transports(),
    )
    got = by_item(tmp_path)
    opening = got["s0"]["attempts"]
    assert [t["valid"] for t in opening] == [False, False, True]
    assert opening[0]["reason"] == "the opening request cannot be silent"
    assert opening[1]["reason"].startswith("schema")
    assert got["s0"]["status"] == "ok"
    tries = got["s1"]["attempts"]
    assert (
        got["s1"]["status"] == "exhausted" and len(tries) == world.MAX_REGENERATIONS + 1
    )
    assert [t["reason"] for t in tries] == [
        "expected exactly one reply call",
        "expected exactly one reply call",
        "revealed unknown keys ['account.pin']",
    ]
    assert tries[1]["raw"] == [{"name": "reply", "arguments": REPLY}] * 2
    assert got["s2"]["status"] == "ok" and got["s2"]["check"] == "partial"
    assert got["s2"]["result"]["reply"]["revealed"] == {"account.pin": "0000"}
    assert all(not v for v in script.values())


def test_plan_makes_no_call_and_needs_no_key(
    items: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PL_TEAMROUTER_API_KEY")
    monkeypatch.delenv("PL_TEAMROUTER_BASE_URL")
    wire = Wire()
    arms = (INCUMBENT, CANDIDATE)
    plan = wsr.run(
        args(
            items, tmp_path, "--plan", "--repeat-subset", "1", "--seed", "3", arms=arms
        ),
        transports=wire.transports(),
    )
    assert wire.bodies == [] and not (tmp_path / "out").exists()
    assert plan["simuser_not_replayable"] == 1
    for arm in arms:  # plain calls: the incumbent calls as every arm does
        assert plan["arms"][arm]["calls"] == {"ear": 3, "mouth": 2, "simuser": 3}
    assert plan["arms"][CANDIDATE]["max_calls"] == {"ear": 9, "mouth": 6, "simuser": 9}
    tokens = plan["arms"][CANDIDATE]["tokens"]["ear"]
    assert tokens["with_usage"] in (1, 2) and tokens["prompt_tokens"] == 300 * 3


def test_resume_skips_final_rows_and_reruns_the_rest(
    items: Path, tmp_path: Path
) -> None:
    wire = Wire(classify=[SINGLE])
    wsr.run(
        args(items, tmp_path, "--roles", "ear", "--limit", "1"),
        transports=wire.transports(),
    )
    with pytest.raises(SystemExit, match="--resume"):
        wsr.run(args(items, tmp_path, "--roles", "ear"), transports=wire.transports())
    wire = Wire(classify=answer, echo=ECHO)
    again = ("--roles", "ear", "--resume", "--repeat-subset", "1", "--seed", "0")
    report = wsr.run(args(items, tmp_path, *again), transports=wire.transports())
    assert report[INCUMBENT]["skipped_final"] == 1 and len(wire.bodies) == 2
    keys = [(r["item_id"], r["repeat"]) for r in rows(tmp_path)]
    assert {("e1", 1), ("c-e1", 1)} < set(keys) and [k[1] for k in keys].count(2) == 1
    assert all(
        r["attempts"][0]["records"][0]["echo"] == ECHO for r in rows(tmp_path)[1:]
    )


def test_a_dead_endpoint_aborts_with_a_partial_file_and_no_secret(
    items: Path, tmp_path: Path
) -> None:
    dead = httpx.Response(
        503, text=f"upstream https://{HOSTS['teamrouter']} key {KEY} down"
    )
    wire = Wire(classify=[SINGLE, dead])
    with pytest.raises(LLMUnavailable):
        wsr.run(
            args(items, tmp_path, "--roles", "ear", "--concurrency", "1"),
            transports=wire.transports(),
        )
    first, died = rows(tmp_path)
    assert first["status"] == "ok" and died["status"] == "unavailable"
    assert died["attempts"][0]["records"][0]["error"].startswith(
        "EndpointError: HTTP 503"
    )
    text = (tmp_path / "out" / wsr.parse_arm(INCUMBENT).file).read_text("utf-8")
    assert (
        KEY not in text and HOSTS["teamrouter"] not in text and "https://" not in text
    )
    wire = Wire(classify=[ACTS])  # resume re-runs the aborted item only
    wsr.run(
        args(items, tmp_path, "--roles", "ear", "--resume"),
        transports=wire.transports(),
    )
    assert len(wire.bodies) == 1 and rows(tmp_path)[-1]["status"] == "ok"


def test_the_cli_dispatches_run_and_refuses_a_moved_item(
    items: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws.main(
        [
            "run",
            "--items",
            str(items),
            "--runs",
            str(tmp_path / "runs"),
            "--arm",
            INCUMBENT,
            "--plan",
        ]
    )
    assert json.loads(capsys.readouterr().out)["items_root_hash"]
    doc = json.loads(items.read_text("utf-8"))
    doc["items"]["ear"][0]["item_id"] = "moved"
    items.write_text(json.dumps(doc), "utf-8")
    with pytest.raises(SystemExit, match="root_hash"):
        wsr.run(args(items, tmp_path, "--plan"))


def test_a_constructed_say_order_survives_a_rewording() -> None:
    """The frozen template of a ``confirmed`` item predates S1-SYS-73's wording: the
    order still comes from where each term stands in it; the line is today's."""
    stale = (
        "Done, the offer is accepted. Your confirmation number is: confirmation: "
        "048213; monthly price: 76.00."
    )
    item: Json = {"constructed": True, "name": "c", "intent": "confirmed", "ask": []}
    item |= {"offer_ref": "keep-1", "template": stale}
    item["say"] = {"confirmation": "048213", "monthly_price": "76.00"}  # key-sorted
    intent = wsr.mouth_intent(item, "Summit")
    assert intent.say == (("confirmation", "048213"), ("monthly_price", "76.00"))
    assert template(intent, "Summit").endswith(
        "number is 048213; monthly price: 76.00."
    )
    item["say"] = {"monthly_price": "99.00"}  # a term its template does not show
    with pytest.raises(SystemExit, match="no say order"):
        wsr.mouth_intent(item, "Summit")
