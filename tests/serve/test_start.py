"""Starting a live case from the browser (S1-SYS-33): ``GET /start`` issues the
operator's cookie pair, ``GET /api/models`` lists what may be started, and
``POST /api/cases`` hands one start to the kernel's ``Starter``, under one lock,
only with an allowed Origin and the operator's signed double-submit token."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.serve.client import OMIT, ORIGIN, client, get, headers, login, post
from tests.support.api_cases import ApiCase, FakeStarter

from proxyloop.serve.api import create_app
from proxyloop.serve.cases import ModelOption

CASE = "case-1"  # a case of the existing lookup: the user's and rep's tokens
OP = ("pl_op_session", "pl_op_csrf")
LOGGER = "proxyloop.serve.start"
TASKS = ("cp-direct-discount", "cp-hidden-fee-readback")
OPTIONS = (
    ModelOption(
        id="vllm:qwen",
        lane="fast_user",
        label="Qwen (vLLM)",
        endpoint="vllm",
        model_id="Qwen/Qwen3.5-9B",
        default=True,
    ),
    ModelOption(
        id="openrouter:luna",
        lane="fast_user",
        label="Luna",
        endpoint="openrouter",
        model_id="openai/gpt-6-luna",
        default=False,
    ),
    ModelOption(
        id="vllm:qwen-cp",
        lane="fast_cp",
        label="Qwen (vLLM)",
        endpoint="vllm",
        model_id="Qwen/Qwen3.5-9B",
        default=True,
    ),
    ModelOption(
        id="teamrouter:flash",
        lane="slow",
        label="Flash",
        endpoint="teamrouter",
        model_id="gemini-3.8-flash",
        default=True,
    ),
)
BODY: dict[str, object] = {"task_ref": TASKS[0], "models": {"slow": "teamrouter:flash"}}


class Env:  # not a dataclass: pyright sees such a TestClient field as Unknown
    def __init__(self, http: TestClient, starter: FakeStarter, other: ApiCase) -> None:
        self.http, self.starter, self.other = http, starter, other


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    root = tmp_path / "runs"
    root.mkdir()
    starter = FakeStarter(root, OPTIONS, TASKS)
    other = ApiCase(root, CASE).start()
    cases = {CASE: other}
    app = create_app([root], [ORIGIN], cases=cases.get, start=starter)
    yield Env(TestClient(app, base_url="http://127.0.0.1"), starter, other)
    for case in [other, *starter.cases]:
        case.close()


def operator(http: TestClient) -> dict[str, str]:
    """GET /start: the operator's two cookies (the client's jar is emptied)."""
    got = get(http, "/start", follow=False)
    assert got.status_code == 303, got.text
    assert got.headers["location"] == "/?start"
    cookies = dict(got.cookies)
    assert set(cookies) == set(OP)
    cast(Any, http).cookies.clear()
    return cookies


def start(env: Env, hdrs: dict[str, str], body: object = BODY) -> httpx.Response:
    return post(env.http, "/api/cases", body, hdrs)


# Auth: Origin and the operator's CSRF pair, before anything else.


def test_start_sets_the_operator_cookies(env: Env) -> None:
    got = get(env.http, "/start", follow=False)
    assert (got.status_code, got.headers["location"]) == (303, "/?start")
    sets = {c.split("=", 1)[0]: c.lower() for c in got.headers.get_list("set-cookie")}
    assert set(sets) == set(OP)
    for cookie in sets.values():
        assert "samesite=strict" in cookie and "path=/" in cookie
    assert "httponly" in sets[OP[0]] and "httponly" not in sets[OP[1]]


def _renamed(cookies: dict[str, str], names: Sequence[str]) -> dict[str, str]:
    """A pair's values under other cookie names, in order (session, csrf)."""
    return dict(zip(names, cookies.values(), strict=True))


def _crossed(env: Env) -> dict[str, str]:
    """One operator session's cookie with another session's token."""
    first, second = operator(env.http), operator(env.http)
    return {OP[0]: first[OP[0]], OP[1]: second[OP[1]]}


BAD_CSRF: dict[str, Callable[[Env], dict[str, str]]] = {
    "no token": lambda env: headers(operator(env.http), OMIT),
    "wrong token": lambda env: headers(operator(env.http), "0" * 64),
    "no cookies": lambda env: headers({}, operator(env.http)[OP[1]]),
    "no session cookie": lambda env: headers({OP[1]: operator(env.http)[OP[1]]}),
    "another session": lambda env: headers(_crossed(env)),
    "forged pair": lambda env: headers({OP[0]: "a" * 43, OP[1]: "b" * 64}),
    "the user's cookies": lambda env: headers(login(env.http, "user", CASE)),
    "the rep's cookies": lambda env: headers(login(env.http, "rep", CASE)),
    "the user's values": lambda env: headers(
        _renamed(login(env.http, "user", CASE), OP)
    ),
    "the rep's values": lambda env: headers(_renamed(login(env.http, "rep", CASE), OP)),
}


@pytest.mark.parametrize("make", BAD_CSRF.values(), ids=BAD_CSRF.keys())
def test_a_bad_operator_token_is_403_and_starts_nothing(
    env: Env, make: Callable[[Env], dict[str, str]]
) -> None:
    got = start(env, make(env))
    assert (got.status_code, got.json()) == (403, {"error": "csrf"})
    assert env.starter.calls == []


@pytest.mark.parametrize("origin", [OMIT, "http://evil.example", "null"])
def test_a_start_needs_an_allowed_origin(env: Env, origin: str) -> None:
    got = start(env, headers(operator(env.http), origin=origin))
    assert (got.status_code, got.json()) == (403, {"error": "origin"})
    assert "access-control-allow-origin" not in got.headers
    assert env.starter.calls == []


def test_the_operator_token_opens_no_user_or_rep_post(env: Env) -> None:
    op = operator(env.http)
    card = env.other.card()
    approval = f"/api/cases/{CASE}/approvals/{card.approval_id}"
    body = {"decision": "granted", "terms_hash": card.terms_hash}
    body |= {"authority_epoch": card.authority_epoch}
    text = {"text": "hi"}
    as_user = _renamed(op, ("pl_session", "pl_csrf"))
    as_rep = _renamed(op, ("pl_rep_session", "pl_rep_csrf"))
    for url, sent, hdrs in [
        (approval, body, headers(op)),
        (approval, body, headers(as_user)),
        (f"/api/cases/{CASE}/messages", text, headers(op)),
        (f"/api/cases/{CASE}/messages", text, headers(as_user)),
        (f"/api/cases/{CASE}/rep", text, headers(op)),
        (f"/api/cases/{CASE}/rep", text, headers(as_rep)),
    ]:
        got = post(env.http, url, sent, hdrs)
        assert (got.status_code, got.json()) == (403, {"error": "csrf"}), url
    assert env.other.posts == env.other.messages == env.other.utterances == []
    assert env.other.posted() == 0


def test_without_a_starter_the_start_routes_are_404(tmp_path: Path) -> None:
    root, web = tmp_path / "runs", tmp_path / "web"
    root.mkdir()
    web.mkdir()
    (web / "index.html").write_text("<html></html>")
    hdrs = {"origin": ORIGIN, "x-csrf-token": "t"}
    hdrs["cookie"] = f"{OP[0]}=s; {OP[1]}=t"
    for http in (client(root), client(root, web_dir=web)):
        assert get(http, "/start", follow=False).status_code == 404
        assert get(http, "/api/models").status_code == 404
        assert post(http, "/api/cases", BODY, hdrs).status_code == 404


# The body, the outcomes and the lock.


BAD_BODY: dict[str, object] = {
    "extra field": BODY | {"approve": True},
    "no models": {"task_ref": TASKS[0]},
    "models not a map": BODY | {"models": ["slow"]},
    "unknown lane": BODY | {"models": {"ear": "vllm:qwen"}},
    "empty model id": BODY | {"models": {"slow": ""}},
    "long model id": BODY | {"models": {"slow": "x" * 129}},
    "space in model id": BODY | {"models": {"slow": "a b"}},
    "empty task_ref": BODY | {"task_ref": ""},
    "upper task_ref": BODY | {"task_ref": "CP-direct-discount"},
    "path task_ref": BODY | {"task_ref": "../cp-direct-discount"},
    "long task_ref": BODY | {"task_ref": "a" * 65},
    "number task_ref": BODY | {"task_ref": 7},
    "unknown rep": BODY | {"rep": "robot"},
}


@pytest.mark.parametrize("body", BAD_BODY.values(), ids=BAD_BODY.keys())
def test_a_malformed_body_is_422_and_starts_nothing(env: Env, body: object) -> None:
    got = start(env, headers(operator(env.http)), body)
    assert (got.status_code, got.json()) == (422, {"error": "invalid body"})
    assert env.starter.calls == []


REASONS = ["unknown_task", "unknown_model", "wrong_lane", "not_live", "unavailable"]


@pytest.mark.parametrize(
    ("reason", "status"), [*((r, 400) for r in REASONS), ("busy", 409)]
)
def test_a_refused_start_answers_its_reason(env: Env, reason: str, status: int) -> None:
    env.starter.refuse = reason
    got = start(env, headers(operator(env.http)))
    assert (got.status_code, got.json()) == (
        status,
        {"error": "start", "reason": reason},
    )
    assert len(env.starter.calls) == 1


def test_the_models_are_forwarded_as_given(env: Env) -> None:
    hdrs = headers(operator(env.http))
    assert start(env, hdrs).status_code == 201
    no_models: dict[str, str] = {}
    human = BODY | {"models": no_models, "rep": "human"}
    assert start(env, hdrs, human).status_code == 201
    assert env.starter.calls == [
        (TASKS[0], {"slow": "teamrouter:flash"}, "sim"),  # no default filled in
        (TASKS[0], {}, "human"),
    ]


def test_an_unknown_refusal_reason_is_503_and_logged_redacted(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    env.starter.refuse = "relay https://relay.example/v1 is down"
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        got = start(env, headers(operator(env.http)))
    assert (got.status_code, got.json()) == (503, {"error": "unavailable"})
    (record,) = [r for r in caplog.records if r.name == LOGGER]
    assert record.levelno == logging.ERROR
    assert "<redacted-url>" in record.getMessage()
    assert "https://" not in caplog.text and "https://" not in got.text


def test_a_run_id_started_twice_is_503_and_keeps_the_first(
    env: Env, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    hdrs = headers(operator(env.http))
    assert start(env, hdrs).json() == {"case_id": "live-1"}
    (first,) = env.starter.cases
    impostor = ApiCase(tmp_path / "elsewhere", "live-1").start()
    env.starter.returns = impostor
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        got = start(env, hdrs)
    impostor.close()
    assert (got.status_code, got.json()) == (503, {"error": "unavailable"})
    assert [r.levelno for r in caplog.records if r.name == LOGGER] == [logging.ERROR]
    user = login(env.http, "user", "live-1")
    got = post(env.http, "/api/cases/live-1/messages", {"text": "hi"}, headers(user))
    assert got.status_code == 200
    assert first.messages == ["hi"] and impostor.messages == []


def test_a_raising_starter_is_503_logged_and_not_retried(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    env.starter.fail = True
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        got = start(env, headers(operator(env.http)))
    assert (got.status_code, got.json()) == (503, {"error": "unavailable"})
    assert len(env.starter.calls) == 1
    (record,) = [r for r in caplog.records if r.name == LOGGER]
    assert record.levelno == logging.ERROR and record.exc_info is not None


def test_concurrent_starts_enter_the_starter_one_at_a_time(env: Env) -> None:
    env.starter.delay_s = 0.05
    hdrs = headers(operator(env.http))

    async def race() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=env.http.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as http:
            sent = [http.post("/api/cases", json=BODY, headers=hdrs) for _ in range(3)]
            return list(await asyncio.gather(*sent))

    got = asyncio.run(race())
    assert [r.status_code for r in got] == [201] * 3
    assert sorted(r.json()["case_id"] for r in got) == ["live-1", "live-2", "live-3"]
    assert env.starter.most == 1 and len(env.starter.calls) == 3


def test_a_started_case_is_live_and_takes_an_approval(env: Env) -> None:
    got = start(env, headers(operator(env.http)))
    assert (got.status_code, got.json()) == (201, {"case_id": "live-1"})
    (case,) = env.starter.cases
    assert env.starter.resolved == [
        {
            "fast_user": "vllm:qwen",
            "fast_cp": "vllm:qwen-cp",
            "slow": "teamrouter:flash",
        }
    ]
    login(env.http, "rep", "live-1")  # GET /rep finds it too
    user = login(env.http, "user", "live-1")  # GET /live/{case_id}
    card = case.card()
    body = {"decision": "granted", "terms_hash": card.terms_hash}
    body |= {"authority_epoch": card.authority_epoch}
    url = f"/api/cases/live-1/approvals/{card.approval_id}"
    approved = post(env.http, url, body, headers(user))
    assert (approved.status_code, approved.json()) == (200, {"status": "posted"})
    assert len(case.posts) == 1 and case.posted() == 1
    assert env.other.posts == []  # the existing lookup's case is untouched


# GET /api/models.


def test_models_lists_the_options_and_tasks(env: Env) -> None:
    got = get(env.http, "/api/models")
    assert got.status_code == 200
    assert got.json() == {
        "options": [option.model_dump(mode="json") for option in OPTIONS],
        "tasks": list(TASKS),
    }


def _with(i: int, **change: object) -> tuple[ModelOption, ...]:
    """OPTIONS with option ``i`` changed, unvalidated (a buggy starter)."""
    changed = OPTIONS[i].model_copy(update=change)
    return (*OPTIONS[:i], changed, *OPTIONS[i + 1 :])


TWIN = OPTIONS[0].model_copy(update={"default": False})  # the same id again
BROKEN: dict[str, tuple[object, object]] = {  # (options, tasks)
    "duplicate id": ((*OPTIONS, TWIN), TASKS),
    "two defaults": (_with(1, default=True), TASKS),
    "no default": (_with(3, default=False), TASKS),
    "no endpoint": (_with(3, endpoint=None), TASKS),
    "baseline endpoint": (_with(3, endpoint="baseline"), TASKS),
    "unknown lane": (_with(3, lane="ear"), TASKS),
    "not an option": ([*OPTIONS, OPTIONS[0].model_dump()], TASKS),
    "an id with a space": (_with(1, id="open router"), TASKS),
    "a task POST would refuse": (OPTIONS, [*TASKS, "Upper-Task"]),
    "tasks a bare string": (OPTIONS, TASKS[0]),
    "a task not a string": (OPTIONS, [TASKS[0], 7]),
}  # fmt: skip


@pytest.mark.parametrize(("options", "tasks"), BROKEN.values(), ids=BROKEN.keys())
def test_a_broken_starter_fails_models_loudly(
    env: Env, caplog: pytest.LogCaptureFixture, options: object, tasks: object
) -> None:
    env.starter.options = cast(Any, options)
    env.starter.tasks = cast(Any, tasks)
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        got = get(env.http, "/api/models")
    assert (got.status_code, got.json()["error"]) == (500, "options")
    assert [r.levelno for r in caplog.records if r.name == LOGGER] == [logging.ERROR]
