"""The same-state Fast probe (S1-MOD-08) without keys or GPU: a bundle from the real
kernel (FastC on the vLLM adapter, FastU on the relay adapter, both over transport
doubles) is probed through the production adapters over transport doubles."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import shutil
from collections.abc import Collection
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from tests.contract.samples import QWEN
from tests.kernel.test_p3 import vllm as kernel_vllm
from tests.kernel.test_session import SCRIPTS, UNTIL
from tests.llm.wire import (
    chat_chunks,
    completion_chunks,
    set_env,
    sse,
    stream_response,
)
from tests.support.manual_clock import ScaledClock
from tests.support.sessions import FakeTokenizer, clients, fake_config, patient_task

from proxyloop.contract import protocol as fp
from proxyloop.contract.bundle import Bundle
from proxyloop.contract.config import SessionConfig
from proxyloop.contract.llm import (
    AdapterKind,
    LLMClient,
    LLMRole,
    LLMUnavailable,
    ModelRef,
)
from proxyloop.contract.protocol import render_messages, render_prompt
from proxyloop.kernel.session import run_session
from proxyloop.llm.factory import make_client
from proxyloop.llm.http import Clock, RecordSink
from proxyloop.training import pull_through as pt
from scripts.mod import probe_same_state as pss

SONNET = ModelRef(
    kind=AdapterKind.REAL_HTTP, endpoint="relay", model_id="claude-sonnet-5"
)
GEMINI = ModelRef(
    kind=AdapterKind.REAL_HTTP,
    endpoint="teamrouter",
    model_id="gemini-3.8-flash",
    reasoning_effort="none",
)
USER_REPLY = SCRIPTS["fast_user"][0]
Sent = dict[str, list[bytes]]


def recording(
    sent: Sent, endpoint: str, reply: list[str], broken: Collection[str] = ()
) -> httpx.MockTransport:
    """The endpoint's stream for ``reply``; every generation body it received is kept.
    vLLM's /tokenize answers as FakeTokenizer, except for a ``broken`` prompt."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tokenize":
            body: dict[str, Any] = json.loads(request.content)
            sent.setdefault("tokenize", []).append(request.content)
            chat = body.get("messages")
            text = FakeTokenizer().apply_chat_template(chat) if chat else body["prompt"]
            bad = [0] if not chat and body["prompt"] in broken else []
            return httpx.Response(200, json={"tokens": FakeTokenizer.ids(text) + bad})
        sent.setdefault(endpoint, []).append(request.content)
        if endpoint == "vllm":
            return stream_response(sse(*completion_chunks(QWEN, reply)))
        ref = SONNET if endpoint == "relay" else GEMINI
        return stream_response(sse(*chat_chunks(ref, reply)))

    return httpx.MockTransport(handle)


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Sent]:
    """One train bundle from the kernel, and the Fast bodies the kernel sent."""
    root, sent, mp = tmp_path_factory.mktemp("evidence"), Sent(), pytest.MonkeyPatch()
    for endpoint in ("vllm", "relay"):
        set_env(mp, endpoint)
    inner = kernel_vllm()  # P3's /tokenize and /pl/attest, and the completions

    def vllm_handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/completions":
            sent.setdefault("vllm", []).append(request.content)
        return cast(httpx.Response, inner.handler(request))  # a sync handler

    clock, relay = ScaledClock(100), recording(sent, "relay", [USER_REPLY])
    base = clients(SCRIPTS, clock, (), UNTIL, httpx.MockTransport(vllm_handle))

    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        if ref.endpoint != "relay":
            return base(role, ref, sink)
        now = clock.monotonic_ms
        return make_client(ref, live=False, clock=now, on_record=sink, transport=relay)

    cfg = fake_config().model_dump() | {"fast_cp": QWEN, "fast_user": SONNET}
    session = run_session(
        SessionConfig.model_validate(cfg),
        patient_task(),
        None,
        runs_dir=root,
        clock=clock,
        sleep=clock.sleep,
        clients=make,
        tokenizer=FakeTokenizer(),
    )
    asyncio.run(asyncio.wait_for(session, timeout=30))
    mp.undo()
    return root, sent


def views(root: Path) -> list[pss.View]:
    found, funnel = pss.collect(pt.load_bundles(root), pt.current_fingerprints(), 100)
    assert funnel["bundles"] == 1 and funnel["selected"] == len(found) > 0
    return found


def older(b: Bundle, run_id: str) -> Bundle:
    """The same run, a day earlier, under another run id."""
    day = timedelta(days=1)
    events = tuple(e.model_copy(update={"wall": e.wall - day}) for e in b.events)
    manifest = b.manifest.model_copy(update={"run_id": run_id})
    return Bundle(manifest=manifest, events=events, prompts=b.prompts)


def test_a_small_cap_takes_whole_runs_newest_first_in_their_own_order(
    evidence: tuple[Path, Sent],
) -> None:
    """Not the newest run's closing turns: its opening ones, then the next run's."""
    (new,) = pt.load_bundles(evidence[0])
    run_id, fps = new.manifest.run_id, pt.current_fingerprints()
    turns = [e.event_id for e in new.events if e.type == "fast.turn"]
    both = [older(new, "run-older"), new]
    found, funnel = pss.collect(both, fps, 2)
    assert [v.turn for v in found] == turns[:2] and len(turns) > 2
    assert {v.run_id for v in found} == {run_id}
    found, funnel = pss.collect(both, fps, len(turns) + 1)
    assert [(v.run_id, v.turn) for v in found][-1] == ("run-older", turns[0])
    assert funnel["dropped_over_cap"] == len(turns) - 1
    comp = funnel["composition"]
    lanes = {ln: sum(v.lane == ln for v in found[:-1]) for ln in pss.LANES}
    assert comp[run_id] == {"taken": len(turns), "available": len(turns)} | lanes
    one = {"user": 0, "cp": 0} | {found[-1].lane: 1}
    assert comp["run-older"] == {"taken": 1, "available": len(turns)} | one


def test_each_request_is_the_one_the_kernel_would_send(
    evidence: tuple[Path, Sent], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, kernel = evidence
    found, tok = views(root), FakeTokenizer()
    assert {v.lane for v in found} == {"user", "cp"}
    for endpoint in ("vllm", "relay"):
        set_env(monkeypatch, endpoint)
    sent = Sent()
    seams = {e: recording(sent, e, ["Okay."]) for e in ("vllm", "relay")}
    models = {"vllm:Qwen3.5-9B": QWEN, "relay:claude-sonnet-5": SONNET}
    report = asyncio.run(pss.probe(found, models, tok, {}, seams))
    assert len(report["rows"]) == 3 * len(found) and "aborted" not in report
    # The kernel's own lane/endpoint pairs: byte for byte, matched by the call's seed.
    own = {"vllm": "cp", "relay": "user"}
    for endpoint, lane in own.items():
        by_seed = {json.loads(b)["seed"]: b for b in kernel[endpoint]}
        mine = [v for v in found if v.lane == lane]
        bodies = [b for b in sent[endpoint] if json.loads(b)["seed"] in by_seed]
        assert len(bodies) == len(mine) > 0
        assert all(b == by_seed[json.loads(b)["seed"]] for b in bodies)
    # Every body: the contract's render for its endpoint, the recorded sampling.
    order = [(v, m) for v in found for m in pss.arm_order(v, list(models))]
    queues = {e: list(sent[e]) for e in sent}
    for v, m in order:
        body = json.loads(queues[models[m].endpoint or ""].pop(0))
        assert (body["seed"], body["max_tokens"], body["top_p"]) == (v.seed, 160, 0.9)
        assert body["temperature"] == 0.3
        if m.startswith("vllm"):
            assert body["prompt"] == render_prompt(v.view, v.profile, tok)
        else:
            chat = render_messages(v.view, v.profile)
            assert body["messages"] == [
                m.model_dump(include={"role", "content"}) for m in chat
            ]


def test_metrics_on_a_hand_built_answer_set(evidence: tuple[Path, Sent]) -> None:
    v = next(v for v in views(evidence[0]) if v.lane == "cp")
    assert "45" not in pss.numbers(pss.view_text(v))
    rec = v.reference
    answers = [
        ("Could you do 45 a month?\n@slow: fact monthly_price=45", rec),
        ("One moment please.\n@hold offer", rec.model_copy(update={"usage": None})),
        ("@bogus", rec),
    ]
    rows = [pss.row("m", v, raw, r, []) for raw, r in answers]
    dead = rec.model_copy(update={"error": "HTTP 500", "response_sha": None})
    rows.append(pss.row("m", v, "", dead, [dead]))
    s = pss.summary(rows, ["m"])["m"]
    cp = s["cp"]
    assert (cp["n"], cp["errors"], cp["failed_attempts"]) == (4, 1, 1)
    assert cp["parse_issue_rate_all"] == 1 / 4
    assert cp["parse_issue_rate_answered"] == 1 / 3
    assert cp["directive_rate"]["slow:fact"] == cp["directive_rate"]["hold"] == 1 / 3
    assert cp["directive_rate"]["wait"] == 0
    assert cp["spoken_words_mean"] == 3 and cp["spoken_words_p90"] == 6
    assert cp["unsupported_number_share"] == 1 / 3
    assert cp["directive_agreement"] == 1 / 3  # the reference relays one fact
    quiet = dataclasses.replace(v, raw="Sure, one moment.")  # no directive in it
    more = pss.summary([*rows, pss.row("m", quiet, "Okay.", rec, [])], ["m"])["m"]
    assert more["cp"]["directive_agreement"] == 2 / 4
    assert more["cp"]["directive_agreement_acting_reference"] == 1 / 3
    assert more["cp"]["acting_reference_n"] == 3
    assert s["model_refs"] == [rec.model_ref.model_dump(mode="json")]
    assert s["served_echoes"] == [rec.served_model_echo] == [QWEN.model_id]
    assert rows[0]["unsupported_numbers"] == ["45"]
    assert rows[0]["sentences"] == 1 and rows[2]["issues"] == [
        "unknown_directive",
        "empty_turn",
    ]
    usage = rec.usage
    assert usage is not None and cp["usage_unknown"] == 1
    assert cp["prompt_tokens"] == 2 * usage.prompt_tokens
    user = s["user"]  # no calls: nothing is invented, no usage is summed as 0
    assert user["n"] == 0 and user["parse_issue_rate_all"] is None
    assert user["prompt_tokens"] is None and user["spoken_words_p90"] is None


def test_numbers_rule() -> None:
    text = "Pay $1,200.50 now, or 75.00 a month for 12 months."
    assert pss.numbers(text) == ["1200.5", "75", "12"]


def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no call, no client, no tokenizer in --plan")

    for name in ("make_client", "load_tokenizer"):
        monkeypatch.setattr(pss, name, refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(httpx.Client, "send", refuse)


MODELS = [
    "--model",
    "vllm:Qwen3.5-9B",
    "--model",
    "relay:claude-sonnet-5",
    "--model",
    "teamrouter:gemini-3.8-flash@none",
]


def test_plan_makes_no_call(
    evidence: tuple[Path, Sent],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_network(monkeypatch)
    for name in ("PL_VLLM_API_KEY", "PL_RELAY_API_KEY", "PL_TEAMROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    root = str(evidence[0])
    assert pss.main(["--plan", "--evidence", root, "--max-views", "2", *MODELS]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["views"] == 2 and plan["funnel"]["dropped_over_cap"] > 0
    assert set(plan["calls"].values()) == {2} and len(plan["est_prompt_tokens"]) == 3


def test_a_dead_endpoint_aborts_and_its_record_is_kept(
    evidence: tuple[Path, Sent], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    set_env(monkeypatch, "relay")

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    def dead(
        ref: ModelRef, *, live: bool, clock: Clock, on_record: RecordSink, **_: Any
    ) -> LLMClient:
        transport = httpx.MockTransport(refused)
        return make_client(
            ref, live=live, clock=clock, on_record=on_record, transport=transport
        )

    monkeypatch.setattr(pss, "make_client", dead)
    out = tmp_path / "probe.json"
    args = ["--evidence", str(evidence[0]), "--max-views", "3", "--out", str(out)]
    with pytest.raises(LLMUnavailable):
        pss.main([*args, "--model", "relay:claude-sonnet-5"])
    report = json.loads(out.read_text())
    assert report["aborted"].startswith("claude-sonnet-5 unavailable")
    (failed,) = [r for r in report["rows"] if r["model"] != pss.REFERENCE]
    assert (
        failed["error"].startswith("ConnectError")
        and len(failed["failed_attempts"]) == 1
    )
    errors = [
        report["summary"]["relay:claude-sonnet-5"][ln]["errors"] for ln in pss.LANES
    ]
    assert sorted(errors) == [0, 1]
    assert "sk-test" not in out.read_text() and "relay.test" not in out.read_text()


def test_a_sealed_test_path_is_refused(tmp_path: Path) -> None:
    sealed = tmp_path / "evidence" / "test"
    sealed.mkdir(parents=True)
    with pytest.raises(SystemExit, match="sealed test dir"):
        pss.main(["--plan", "--evidence", str(sealed), "--max-views", "1", *MODELS])


def test_arm_order_is_shuffled_but_deterministic(evidence: tuple[Path, Sent]) -> None:
    v, labels = views(evidence[0])[0], ["a", "b", "c"]
    many = [dataclasses.replace(v, turn=f"t{i}") for i in range(20)]
    orders = [tuple(pss.arm_order(x, labels)) for x in many]
    assert len(set(orders)) > 1 and len({o[0] for o in orders}) == 3
    assert orders == [tuple(pss.arm_order(x, labels)) for x in many]


@pytest.mark.parametrize("broken", [None, "user", "cp"])
def test_p3_checks_each_lane_before_any_vllm_call_and_a_mismatch_aborts(
    evidence: tuple[Path, Sent], monkeypatch: pytest.MonkeyPatch, broken: str | None
) -> None:
    """As the kernel: one view per lane; the served template wrong for one lane's
    prompt alone (the second, cp, included) aborts before any completion."""
    set_env(monkeypatch, "vllm")
    found, sent, report, tok = (
        views(evidence[0]),
        Sent(),
        dict[str, Any](),
        FakeTokenizer(),
    )
    first = {ln: next(v for v in found if v.lane == ln) for ln in pss.LANES}
    bad = [
        render_prompt(v.view, v.profile, tok) for ln, v in first.items() if ln == broken
    ]
    seams = {"vllm": recording(sent, "vllm", ["Okay."], bad)}
    run = pss.probe(found, {"vllm:Qwen3.5-9B": QWEN}, tok, report, seams)
    if broken:
        with pytest.raises(RuntimeError, match=f"P3 failed for vllm.*'{broken}'"):
            asyncio.run(run)
        assert "vllm" not in sent and report["aborted"].startswith("P3 failed")
    else:
        asyncio.run(run)
        assert len(sent["vllm"]) == len(found) and "aborted" not in report
    checks = report["p3"]["vllm:Qwen3.5-9B"]
    assert {ln: c["turn"] for ln, c in checks.items()} == {
        ln: v.turn for ln, v in first.items()
    }
    assert {ln: c["passed"] for ln, c in checks.items()} == {
        ln: ln != broken for ln in pss.LANES
    }
    assert len(sent["tokenize"]) == 4  # per lane: the messages and the prompt


@pytest.mark.parametrize("cap", ["0", "-3"])
def test_max_views_is_at_least_one(
    evidence: tuple[Path, Sent], capsys: pytest.CaptureFixture[str], cap: str
) -> None:
    args = ["--plan", "--evidence", str(evidence[0]), "--max-views", cap, *MODELS]
    with pytest.raises(SystemExit) as exit_:
        pss.main(args)
    assert exit_.value.code == 2 and "must be at least 1" in capsys.readouterr().err


def test_max_tokens_override_changes_only_max_tokens(
    evidence: tuple[Path, Sent],
) -> None:
    v, tok = next(v for v in views(evidence[0]) if v.lane == "cp"), FakeTokenizer()
    for ref in (QWEN, SONNET):
        default = pss.build_request(v, ref, tok)
        assert default == pss.build_request(v, ref, tok, None)
        assert default.max_tokens == v.sampling.max_tokens == 160
        over = pss.build_request(v, ref, tok, 2048)
        assert over.max_tokens == 2048
        assert over.model_dump() | {"max_tokens": 160} == default.model_dump()


def test_the_override_is_sent_and_shown_in_the_report(
    evidence: tuple[Path, Sent], monkeypatch: pytest.MonkeyPatch
) -> None:
    found, sent = views(evidence[0]), Sent()
    set_env(monkeypatch, "relay")
    seams = {"relay": recording(sent, "relay", ["Okay."])}
    models = {"relay:claude-sonnet-5": SONNET}
    report = asyncio.run(pss.probe(found, models, None, {}, seams, 2048))
    assert report["max_tokens_override"] == 2048
    assert {json.loads(b)["max_tokens"] for b in sent["relay"]} == {2048}
    mine = [r for r in report["rows"] if r["model"] != pss.REFERENCE]
    assert len(mine) == len(found)
    over = [json.loads(b)["max_tokens"] for b in sent["relay"]]
    assert [r["max_tokens_sent"] for r in mine] == over == [2048] * len(found)
    refs = [r for r in report["rows"] if r["model"] == pss.REFERENCE]
    assert {r["max_tokens_sent"] for r in refs} == {160}
    # The record's sampling_sent (contract SamplingKey) does not carry max_tokens:
    # the report-level override and the wire body above are what show it.
    assert all("max_tokens" not in r["record"]["sampling_sent"] for r in mine)
    sent.clear()
    plain = asyncio.run(pss.probe(found, models, None, {}, seams))
    assert plain["max_tokens_override"] is None
    assert {json.loads(b)["max_tokens"] for b in sent["relay"]} == {160}
    rows = [r for r in plain["rows"] if r["model"] != pss.REFERENCE]
    wire = [json.loads(b)["max_tokens"] for b in sent["relay"]]
    assert [r["max_tokens_sent"] for r in rows] == wire  # in call order


def test_plan_shows_the_override(
    evidence: tuple[Path, Sent],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_network(monkeypatch)
    args = ["--plan", "--evidence", str(evidence[0]), "--max-views", "2", *MODELS]
    assert pss.main(args) == 0
    assert json.loads(capsys.readouterr().out)["max_tokens_override"] is None
    assert pss.main([*args, "--max-tokens", "2048"]) == 0
    assert json.loads(capsys.readouterr().out)["max_tokens_override"] == 2048


@pytest.mark.parametrize("n", ["0", "-1"])
def test_max_tokens_is_at_least_one(
    evidence: tuple[Path, Sent], capsys: pytest.CaptureFixture[str], n: str
) -> None:
    args = ["--plan", "--evidence", str(evidence[0]), "--max-views", "1", *MODELS]
    with pytest.raises(SystemExit) as exit_:
        pss.main([*args, "--max-tokens", n])
    assert exit_.value.code == 2 and "must be at least 1" in capsys.readouterr().err


# --- S1-MOD-10: a revised profile, re-tested -----------------------------------------


def restamped(b: Bundle, run_id: str, **manifest: Any) -> Bundle:
    """``older`` with other manifest fields (task_ref, fingerprints)."""
    old = older(b, run_id)
    return Bundle(old.manifest.model_copy(update=manifest), old.events, old.prompts)


def seedless(b: Bundle, run_id: str) -> Bundle:
    """``older`` whose Fast calls recorded no sampling (as before ADR-0019)."""
    old = older(b, run_id)
    events = tuple(
        e.model_copy(update={"payload": e.payload | {"sampling_sent": None}})
        if e.type == "llm.call"
        else e
        for e in old.events
    )
    return Bundle(old.manifest, events, old.prompts)


NEW = {"cp": "pl_cp_v4", "user": "pl_user_v2"}  # the candidates (ADR-0026)


def test_a_profile_override_renders_its_lane_and_rows_record_it(
    evidence: tuple[Path, Sent], monkeypatch: pytest.MonkeyPatch
) -> None:
    found = views(evidence[0])
    assert {v.profile for v in found}.isdisjoint(NEW.values())
    over = [dataclasses.replace(v, render_as=NEW[v.lane]) for v in found]
    set_env(monkeypatch, "relay")
    sent = Sent()
    seams = {"relay": recording(sent, "relay", ["Okay."])}
    report = asyncio.run(
        pss.probe(over, {"relay:claude-sonnet-5": SONNET}, None, {}, seams)
    )
    bodies = [json.loads(b)["messages"] for b in sent["relay"]]
    for v, body in zip(over, bodies, strict=True):  # one arm: calls in view order
        want = render_messages(v.view, NEW[v.lane])
        assert body == [m.model_dump(include={"role", "content"}) for m in want]
        assert body[0]["content"] == fp.PROFILES[NEW[v.lane]].system
        assert body != [
            m.model_dump(include={"role", "content"})
            for m in render_messages(v.view, v.profile)
        ]
    for r in report["rows"]:
        recorded = next(v.profile for v in found if v.turn == r["turn"])
        mine = r["model"] != pss.REFERENCE
        assert r["profile_rendered"] == (NEW[r["lane"]] if mine else recorded)
        assert r["seed_source"] == "recorded"


def test_profile_overrides_are_checked(
    evidence: tuple[Path, Sent],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_network(monkeypatch)
    args = ["--plan", "--evidence", str(evidence[0]), "--max-views", "2", *MODELS]
    refused = {
        "cp=pl_user_v1": "no cp-lane profile",
        "cp=pl_cp_v9": "no cp-lane profile",
        "slow=pl_cp_v3": "once per lane",
    }
    for spec, why in refused.items():
        with pytest.raises(SystemExit, match=why):
            pss.main([*args, "--profile", spec])
    with pytest.raises(SystemExit, match="once per lane"):
        pss.main([*args, "--profile", "cp=pl_cp_v3", "--profile", "cp=pl_cp_v1"])
    assert pss.main([*args, "--profile", "cp=pl_cp_v1"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["profile_override"] == {"cp": "pl_cp_v1"}
    both = ["--profile", "cp=pl_cp_v4", "--profile", "user=pl_user_v2"]
    assert pss.main([*args, *both]) == 0
    assert json.loads(capsys.readouterr().out)["profile_override"] == NEW
    assert pss.main(args) == 0
    assert json.loads(capsys.readouterr().out)["profile_override"] is None


def test_any_fingerprint_needs_an_override_for_every_lane_present(
    evidence: tuple[Path, Sent], monkeypatch: pytest.MonkeyPatch
) -> None:
    no_network(monkeypatch)
    args = ["--plan", "--evidence", str(evidence[0]), "--max-views", "99", *MODELS]
    for more in ([], ["--profile", "cp=pl_cp_v3"]):
        with pytest.raises(SystemExit, match="need a --profile for each lane"):
            pss.main([*args, "--any-fingerprint", *more])
    both = ["--profile", "cp=pl_cp_v3", "--profile", "user=pl_user_v1"]
    assert pss.main([*args, "--any-fingerprint", *both]) == 0


def test_stale_fingerprints_are_taken_only_on_request(
    evidence: tuple[Path, Sent],
) -> None:
    (new,) = pt.load_bundles(evidence[0])
    fps = pt.current_fingerprints()
    stale = restamped(new, "run-stale", fingerprints=fps | {"pl_cp_v3": "0" * 64})
    found, funnel = pss.collect([stale, new], fps, 999)
    assert {v.run_id for v in found} == {new.manifest.run_id}
    assert funnel["bundle_stale_fingerprint"] == 1
    assert "bundle_stale_fingerprint_taken" not in funnel  # a default funnel as before
    found, funnel = pss.collect([stale, new], fps, 999, any_fingerprint=True)
    assert {v.run_id for v in found} == {new.manifest.run_id, "run-stale"}
    assert funnel["bundle_stale_fingerprint_taken"] == 1


def test_family_filters(
    evidence: tuple[Path, Sent],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    (new,) = pt.load_bundles(evidence[0])
    fps, fam = pt.current_fingerprints(), new.manifest.task_ref
    other = restamped(new, "run-other", task_ref="other-family@1")
    both = [other, new]
    found, funnel = pss.collect(both, fps, 999, include=["other-family"])
    assert {v.run_id for v in found} == {"run-other"}
    assert funnel["bundle_family_filtered"] == 1
    found, _ = pss.collect(both, fps, 999, exclude=["other-family"])
    assert {v.run_id for v in found} == {new.manifest.run_id}
    found, _ = pss.collect(both, fps, 999, include=[fam], exclude=["other"])
    assert {v.run_id for v in found} == {new.manifest.run_id}
    assert pss.family_ok("x@1", [], []) and not pss.family_ok("x@1", ["y"], [])
    # The report (and the plan) lists the families taken.
    root = tmp_path / "evidence"
    for b in both:
        shutil.copytree(evidence[0] / new.manifest.run_id, root / b.manifest.run_id)
    manifest = root / "run-other" / "manifest.json"
    doc = json.loads(manifest.read_text())
    manifest.write_text(json.dumps(doc | {"task_ref": "other-family@1"}))
    no_network(monkeypatch)
    args = ["--plan", "--evidence", str(root), "--max-views", "999", *MODELS]
    assert pss.main([*args, "--family-exclude", fam]) == 0
    assert json.loads(capsys.readouterr().out)["families"] == {
        "other-family@1": len(found)
    }


def test_seed_missing_seeds_a_seedless_turn_and_rows_say_so(
    evidence: tuple[Path, Sent], monkeypatch: pytest.MonkeyPatch
) -> None:
    (new,) = pt.load_bundles(evidence[0])
    fps, old = pt.current_fingerprints(), seedless(new, "run-seedless")
    found, funnel = pss.collect([old, new], fps, 999)
    assert {v.run_id for v in found} == {new.manifest.run_id}
    assert funnel["seed_not_recorded"] == len(found)
    found, funnel = pss.collect([old, new], fps, 999, seed_missing=7)
    mine = [v for v in found if v.run_id == "run-seedless"]
    assert funnel["seed_defaulted"] == len(mine) > 0
    assert {(v.seed, v.seed_source) for v in mine} == {(7, "default")}
    assert {v.seed_source for v in found if v not in mine} == {"recorded"}
    set_env(monkeypatch, "relay")
    sent = Sent()
    seams = {"relay": recording(sent, "relay", ["Okay."])}
    report = asyncio.run(
        pss.probe(mine, {"relay:claude-sonnet-5": SONNET}, None, {}, seams)
    )
    assert {json.loads(b)["seed"] for b in sent["relay"]} == {7}
    assert {r["seed_source"] for r in report["rows"]} == {"default"}


def views_file(found: list[pss.View], path: Path) -> Path:
    """A --views-file of ``found`` (as profile_check build-c writes one)."""
    doc = {
        "views": [
            {
                "run_id": v.run_id,
                "turn": f"{v.turn}~x",
                "lane": v.lane,
                "profile": v.profile,
                "view": v.view.model_dump(mode="json"),
                "sampling": v.sampling.model_dump(mode="json"),
                "seed": v.seed,
                "seed_source": v.seed_source,
                "source_call": v.reference.model_dump(mode="json"),
            }
            for v in found
        ]
    }
    path.write_text(json.dumps(doc), "utf-8")
    return path


def test_a_views_file_is_probed_without_reference_rows(
    evidence: tuple[Path, Sent], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    found = views(evidence[0])
    path = views_file(found, tmp_path / "c.json")
    read = pss.read_views(path)
    assert [v.view for v in read] == [v.view for v in found]
    assert all(v.counterfactual and v.raw == "" for v in read)
    set_env(monkeypatch, "relay")
    sent = Sent()
    seams = {"relay": recording(sent, "relay", ["Okay."])}
    models = {"relay:claude-sonnet-5": SONNET}
    report = asyncio.run(pss.probe(read, models, None, {}, seams))
    assert [r["model"] for r in report["rows"]] == ["relay:claude-sonnet-5"] * len(read)
    assert all(
        "agrees" not in r and "reference_directives" not in r for r in report["rows"]
    )
    assert report["summary"][pss.REFERENCE]["cp"]["n"] == 0
    cp = report["summary"]["relay:claude-sonnet-5"]["cp"]
    assert cp["n"] > 0 and cp["directive_agreement"] is None
    assert [json.loads(b)["seed"] for b in sent["relay"]] == [v.seed for v in read]
    out = tmp_path / "probe.json"

    def served(
        ref: ModelRef, *, live: bool, clock: Clock, on_record: RecordSink, **_: Any
    ) -> LLMClient:
        relay = seams["relay"]
        return make_client(
            ref, live=live, clock=clock, on_record=on_record, transport=relay
        )

    monkeypatch.setattr(pss, "make_client", served)
    args = ["--views-file", str(path), "--max-views", "99", "--out", str(out)]
    assert pss.main([*args, "--model", "relay:claude-sonnet-5"]) == 0
    doc = json.loads(out.read_text())
    assert doc["views_file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert not [r for r in doc["rows"] if r["model"] == pss.REFERENCE]


def test_a_views_file_takes_no_bundle_selection(
    evidence: tuple[Path, Sent], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    no_network(monkeypatch)
    path = views_file(views(evidence[0]), tmp_path / "c.json")
    args = ["--plan", "--views-file", str(path), "--max-views", "9", *MODELS]
    for more in (["--seed-missing", "1"], ["--family-exclude", "x"]):
        with pytest.raises(SystemExit, match="take no bundle selection"):
            pss.main([*args, *more])
    with pytest.raises(SystemExit):  # one source: bundles or a views file
        pss.main([*args, "--evidence", str(evidence[0])])


def test_a_views_manifest_is_taken_exactly(
    evidence: tuple[Path, Sent],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--views-manifest``: these views, in this order, stale or seedless alike."""
    (new,) = pt.load_bundles(evidence[0])
    found = views(evidence[0])
    picked = [found[i] for i in (3, 0, 2)]  # any subset, any order
    sel: dict[str, Any] = {"include": [], "exclude": [], "seed_missing": 9}
    rows = [{"run_id": v.run_id, "turn": v.turn} for v in picked]
    doc: dict[str, Any] = {"selection": sel, "views": rows}
    assert [v.turn for v in pss.manifest_views([new], doc)] == [v.turn for v in picked]
    lost = doc | {"views": [*rows, {"run_id": "gone", "turn": "t"}]}
    with pytest.raises(SystemExit, match="1 manifest views not found"):
        pss.manifest_views([new], lost)
    path = tmp_path / "b.json"
    path.write_text(json.dumps(doc), "utf-8")
    no_network(monkeypatch)
    args = ["--plan", "--evidence", str(evidence[0]), "--views-manifest", str(path)]
    args += ["--max-views", "99", *MODELS]
    with pytest.raises(SystemExit, match="need a --profile for each lane"):
        pss.main(args)
    with pytest.raises(SystemExit, match="take no bundle selection"):
        pss.main([*args, "--seed-missing", "1", "--profile", "cp=pl_cp_v4"])
    assert (
        pss.main([*args, "--profile", "cp=pl_cp_v4", "--profile", "user=pl_user_v2"])
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    assert plan["views"] == 3 and plan["funnel"]["selected"] == 3
    assert (
        plan["views_manifest_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    )
