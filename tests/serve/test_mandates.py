"""The mandate route (S1-SYS-41): ``POST /api/cases/{case}/mandates/{id}``
carries the approval route's checks and flow for subject "mandate": the
user's CSRF pair and an allowed Origin, a known case, single use per (case,
mandate id) apart from approval ids, and ``guard.decide`` as the pre-check on
a real Blackboard. The decision reaches ``mandate.decided`` through the fake
harness and through the real kernel's ``WebCase``."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.concurrency.harness import VirtualTime
from tests.kernel.test_web import ENDPOINTS, REF, kernel, starter, stop
from tests.serve.client import OMIT, ORIGIN, client, get, headers, login, post
from tests.serve.test_cases import BAD_CSRF, Live
from tests.serve.test_start import OPTIONS, TASKS, operator
from tests.support.api_cases import ApiCase, FakeStarter

from proxyloop.contract.events import Event
from proxyloop.contract.llm import ToolCall
from proxyloop.contract.state import Mandate
from proxyloop.kernel.session import Kernel
from proxyloop.kernel.web import WebCase
from proxyloop.serve.api import create_app

CASE = "case-1"
USER = ("pl_session", "pl_csrf")


@pytest.fixture
def live(tmp_path: Path) -> Iterator[Live]:
    """The case routes plus the start routes, so the operator's pair exists."""
    root = tmp_path / "runs"
    root.mkdir()
    case = ApiCase(root, CASE).start()
    cases = {CASE: case}
    starter = FakeStarter(root, OPTIONS, TASKS)
    app = create_app([root], [ORIGIN], cases=cases.get, start=starter)
    yield Live(TestClient(app, base_url="http://127.0.0.1"), case, cases, root)
    for each in {case, *cases.values(), *starter.cases}:
        each.close()


def body(m: Mandate, **change: object) -> dict[str, object]:
    base: dict[str, object] = {
        "decision": "granted",
        "mandate_hash": m.mandate_hash,
        "authority_epoch": m.epoch,
    }
    return base | change


def decide(
    live: Live, m: Mandate, hdrs: dict[str, str], **change: object
) -> httpx.Response:
    url = f"/api/cases/{CASE}/mandates/{m.mandate_id}"
    return post(live.http, url, body(m, **change), hdrs)


def user(live: Live) -> dict[str, str]:
    return headers(login(live.http, "user", CASE))


def of(events: tuple[Event, ...], type_: str) -> list[Event]:
    return [e for e in events if e.type == type_]


@pytest.mark.parametrize("decision", ["granted", "denied"])
def test_a_mandate_post_reaches_mandate_decided(live: Live, decision: str) -> None:
    m = live.case.propose()
    got = decide(live, m, user(live), decision=decision)
    assert (got.status_code, got.json()) == (200, {"status": "posted"})
    (sent,) = live.case.posts
    assert (sent.subject, sent.subject_id, sent.decision) == (
        "mandate",
        m.mandate_id,
        decision,
    )
    assert (sent.subject_hash, sent.authority_epoch) == (m.mandate_hash, 0)
    events = live.case.bus.events
    (posted,) = of(events, "approval.post")
    (decided,) = of(events, "mandate.decided")
    (bump,) = of(events, "authority.epoch")
    assert posted.actor == "ui" and decided.actor == "kernel"
    assert decided.payload == {
        "mandate_id": m.mandate_id,
        "mandate_hash": m.mandate_hash,
        "decision": decision,
        "by": "ui",
    }
    assert decided.cause_ids == (posted.event_id,)
    assert bump.cause_ids == (decided.event_id,)
    now = live.case.blackboard().private.mandate
    assert now is not None and (now.status, now.decided_by) == (decision, "ui")


def _as_user(cookies: dict[str, str]) -> dict[str, str]:
    """The operator's values under the user's cookie names."""
    return dict(zip(USER, cookies.values(), strict=True))


OPERATOR: dict[str, Callable[[Live], dict[str, str]]] = {
    "the operator's cookies": lambda live: headers(operator(live.http)),
    "the operator's values": lambda live: headers(_as_user(operator(live.http))),
}
MANDATE_CSRF = BAD_CSRF | OPERATOR  # the approval route's cases, plus these


@pytest.mark.parametrize("make", MANDATE_CSRF.values(), ids=MANDATE_CSRF.keys())
def test_a_bad_csrf_token_is_403_and_calls_nothing(
    live: Live, make: Callable[[Live], dict[str, str]]
) -> None:
    m = live.case.propose()
    before = len(live.case.bus.events)
    got = decide(live, m, make(live))
    assert (got.status_code, got.json()) == (403, {"error": "csrf"})
    assert live.case.posts == [] and len(live.case.bus.events) == before


@pytest.mark.parametrize("origin", [OMIT, "http://evil.example", "null"])
def test_a_mandate_post_needs_an_allowed_origin(live: Live, origin: str) -> None:
    m = live.case.propose()
    got = decide(live, m, headers(login(live.http, "user", CASE), origin=origin))
    assert (got.status_code, got.json()) == (403, {"error": "origin"})
    assert "access-control-allow-origin" not in got.headers
    assert live.case.posts == []


Then = Callable[[ApiCase], object]
F64 = "f" * 64
STALE: dict[str, tuple[Then, dict[str, object], str]] = {
    "wrong hash": (lambda c: None, {"mandate_hash": F64}, "subject_hash_mismatch"),
    "wrong epoch": (lambda c: None, {"authority_epoch": 1}, "stale_epoch"),
    "epoch bumped": (lambda c: c.bump_epoch(), {}, "stale_epoch"),
}  # fmt: skip


@pytest.mark.parametrize(("then", "change", "reason"), STALE.values(), ids=STALE.keys())
def test_a_stale_mandate_post_is_409_and_calls_nothing(
    live: Live, then: Then, change: dict[str, object], reason: str
) -> None:
    m = live.case.propose()
    then(live.case)
    before = len(live.case.bus.events)
    got = decide(live, m, user(live), **change)
    assert (got.status_code, got.json()) == (409, {"error": "stale", "reason": reason})
    assert live.case.posts == [] and len(live.case.bus.events) == before


def test_no_proposal_is_stale(live: Live) -> None:
    hdrs, url = user(live), f"/api/cases/{CASE}/mandates/mandate-1"
    sent = {"decision": "granted", "mandate_hash": F64, "authority_epoch": 0}
    got = post(live.http, url, sent, hdrs)  # nothing proposed yet
    assert got.json() == {"error": "stale", "reason": "no_proposal"}
    m = live.case.propose()
    other = m.model_copy(update={"mandate_id": "mandate-9"})
    assert decide(live, other, hdrs).json() == {
        "error": "stale",
        "reason": "no_proposal",
    }
    assert live.case.posts == []


def test_a_denial_does_not_use_up_the_mandate(live: Live) -> None:
    m, hdrs = live.case.propose(), user(live)
    assert decide(live, m, hdrs, mandate_hash=F64).status_code == 409
    assert decide(live, m, hdrs).status_code == 200
    assert len(live.case.posts) == 1


def test_a_replayed_mandate_post_is_409_from_the_slot(live: Live) -> None:
    m, hdrs = live.case.propose(), user(live)
    assert decide(live, m, hdrs).status_code == 200
    again = decide(live, m, hdrs, decision="denied")
    assert (again.status_code, again.json()) == (409, {"error": "already_decided"})
    assert len(live.case.posts) == 1 and live.case.posted() == 1


def test_concurrent_mandate_posts_make_exactly_one_post(live: Live) -> None:
    m, hdrs = live.case.propose(), user(live)
    url = f"/api/cases/{CASE}/mandates/{m.mandate_id}"

    async def race() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=live.http.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as http:
            sent = [http.post(url, json=body(m), headers=hdrs) for _ in range(8)]
            return list(await asyncio.gather(*sent))

    got = asyncio.run(race())
    assert sorted(r.status_code for r in got) == [200] + [409] * 7
    refused = [r.json() for r in got if r.status_code == 409]
    assert refused == [{"error": "already_decided"}] * 7  # the slot's: no reason
    assert len(live.case.posts) == 1 and live.case.posted() == 1


def test_a_mandate_id_equal_to_an_approval_id_has_its_own_slot(live: Live) -> None:
    card, hdrs = live.case.card(), user(live)
    m = live.case.propose(card.approval_id)
    approval = {"decision": "granted", "terms_hash": card.terms_hash}
    approval |= {"authority_epoch": card.authority_epoch}
    url = f"/api/cases/{CASE}/approvals/{card.approval_id}"
    assert post(live.http, url, approval, hdrs).status_code == 200
    got = decide(live, m, hdrs)
    assert (got.status_code, got.json()) == (200, {"status": "posted"})
    assert [p.subject for p in live.case.posts] == ["approval", "mandate"]


def test_a_decided_mandate_is_refused_by_guard_on_a_fresh_app(live: Live) -> None:
    m = live.case.propose()
    assert decide(live, m, user(live)).status_code == 200
    fresh = client(live.root, cases=live.cases.get)  # an empty single-use set
    url = f"/api/cases/{CASE}/mandates/{m.mandate_id}"
    got = post(fresh, url, body(m), headers(login(fresh, "user", CASE)))
    assert got.status_code == 409
    assert got.json() == {"error": "already_decided", "reason": "already_decided"}
    assert len(live.case.posts) == 1  # post_approval not called again


def test_a_failed_handover_is_503_stays_503_and_logs_the_type(
    live: Live, caplog: pytest.LogCaptureFixture
) -> None:
    m, hdrs = live.case.propose(), user(live)
    live.case.unavailable = True
    with caplog.at_level(logging.ERROR, logger="proxyloop.serve.cases"):
        for _ in range(2):  # the retry too: unavailable, not already_decided
            got = decide(live, m, hdrs)
            assert (got.status_code, got.json()) == (503, {"error": "unavailable"})
    live.case.unavailable = False  # fail closed even once the case is back
    assert decide(live, m, hdrs).status_code == 503
    assert live.case.posts == [] and live.case.posted() == 0
    (logged,) = [r for r in caplog.records if r.name == "proxyloop.serve.cases"]
    assert logged.exc_info is None and logged.getMessage().endswith(": RuntimeError")


BAD_BODY: dict[str, dict[str, object]] = {
    "extra field": {"approved": True},
    "terms_hash": {"terms_hash": "f" * 64},
    "short hash": {"mandate_hash": "abc"},
    "upper hash": {"mandate_hash": "A" * 64},
    "negative epoch": {"authority_epoch": -1},
    "string epoch": {"authority_epoch": "0"},
    "not a decision": {"decision": "yes"},
}


@pytest.mark.parametrize("change", BAD_BODY.values(), ids=BAD_BODY.keys())
def test_a_malformed_mandate_body_is_422_and_calls_nothing(
    live: Live, change: dict[str, object]
) -> None:
    m = live.case.propose()
    got = decide(live, m, user(live), **change)
    assert (got.status_code, got.json()) == (422, {"error": "invalid body"})
    assert live.case.posts == []


def test_a_pruned_or_held_out_case_is_404(live: Live) -> None:
    m, hdrs = live.case.propose(), user(live)
    live.cases["case-2"] = ApiCase(live.root, "case-2").start()
    theirs = headers(login(live.http, "user", "case-2"))
    held = ApiCase(live.root, "case-4").start(split="test")  # held out
    held.propose()
    live.cases["case-2"] = held  # the lookup now finds a held-out run
    url = f"/api/cases/case-2/mandates/{m.mandate_id}"
    assert post(live.http, url, body(m), theirs).status_code == 404
    assert get(live.http, "/live/case-2", follow=False).status_code == 404
    del live.cases[CASE]  # pruned after login
    assert decide(live, m, hdrs).status_code == 404
    assert live.case.posts == held.posts == []


# The real kernel's WebCase decides the UI mandate (tests only, I8).


def _propose(k: Kernel) -> Mandate:
    """Slow proposes a mandate through the session's own tools."""
    assert k.slow is not None
    envelope = {"max_monthly_price_minor": 7000}
    calls = [{"tool": "propose_mandate", "envelope": envelope}]
    args = json.dumps({"private_summary": "digest", "calls": calls})
    call = ToolCall(call_id="t", name="act", arguments=args)
    k.slow.tools.act(call, [k.authority.root])
    m = k.bus.bb.private.mandate
    assert m is not None and m.status == "proposed"
    return m


def test_the_real_kernel_decides_a_ui_mandate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for endpoint in ENDPOINTS:  # values only a test uses; never a real endpoint
        prefix = f"PL_{endpoint.upper()}_"
        monkeypatch.setenv(prefix + "BASE_URL", "https://endpoint.invalid")
        monkeypatch.setenv(prefix + "API_KEY", "test-only")
    vt, found = VirtualTime(), dict[str, WebCase]()
    app = create_app([tmp_path / "runs"], [ORIGIN], cases=found.get)
    with TestClient(app, base_url="http://127.0.0.1") as http:
        portal = cast(Any, http).portal
        case: WebCase = portal.call(starter(tmp_path, vt).start_case, REF, {}, "human")
        found[case.run_id] = case
        portal.call(vt.run_for, 5_000)
        m: Mandate = portal.call(_propose, kernel(case))
        url = f"/api/cases/{case.run_id}/mandates/{m.mandate_id}"
        hdrs = headers(login(http, "user", case.run_id))
        got = post(http, url, body(m), hdrs)
        assert (got.status_code, got.json()) == (200, {"status": "posted"})
        portal.call(vt.run_for, 100)  # the kernel's queue decides it
        again = post(http, url, body(m), hdrs)
        assert (again.status_code, again.json()) == (409, {"error": "already_decided"})
        events: tuple[Event, ...] = portal.call(stop, case)
    (posted,) = of(events, "approval.post")
    (decided,) = of(events, "mandate.decided")
    bumps = [
        e for e in of(events, "authority.epoch") if e.cause_ids == (decided.event_id,)
    ]
    assert (posted.actor, posted.payload["subject"]) == ("ui", "mandate")
    assert (decided.payload["by"], decided.payload["decision"]) == ("ui", "granted")
    assert decided.cause_ids == (posted.event_id,) and len(bumps) == 1
    assert not [e for e in events if e.payload.get("intent") == "approval.post"]
