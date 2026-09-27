"""The case routes (ARCHITECTURE §9.6, C15): per-role cookies, signed double
submit CSRF, a required Origin on every POST, case scope, and the approval
endpoint's single use and ``guard.decide`` pre-check on a real Blackboard."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.serve.client import (
    NAMES,
    OMIT,
    ORIGIN,
    PAGE,
    client,
    get,
    headers,
    login,
    post,
)
from tests.support.api_cases import ApiCase

from proxyloop.contract.state import ApprovalCard

CASE = "case-1"


@dataclass
class Live:
    http: TestClient
    case: ApiCase
    cases: dict[str, ApiCase]
    root: Path


@pytest.fixture
def live(tmp_path: Path) -> Iterator[Live]:
    root = tmp_path / "runs"
    root.mkdir()
    case = ApiCase(root, CASE).start()
    cases = {CASE: case}
    yield Live(client(root, cases=cases.get), case, cases, root)
    for each in {case, *cases.values()}:
        each.close()


def body(card: ApprovalCard, **change: object) -> dict[str, object]:
    base: dict[str, object] = {
        "decision": "granted",
        "terms_hash": card.terms_hash,
        "authority_epoch": card.authority_epoch,
    }
    return base | change


def approve(
    live: Live, card: ApprovalCard, hdrs: dict[str, str], **change: object
) -> httpx.Response:
    url = f"/api/cases/{CASE}/approvals/{card.approval_id}"
    return post(live.http, url, body(card, **change), hdrs)


def test_login_sets_per_role_cookies(live: Live) -> None:
    for role, (session, csrf) in NAMES.items():
        got = get(live.http, f"/{PAGE[role]}/{CASE}", follow=False)
        live.http.cookies.clear()
        sets = {
            c.split("=", 1)[0]: c.lower() for c in got.headers.get_list("set-cookie")
        }
        assert set(sets) == {session, csrf}
        for cookie in sets.values():
            assert "samesite=strict" in cookie and "path=/" in cookie
        assert "httponly" in sets[session] and "httponly" not in sets[csrf]


def test_an_approval_posts_once_and_decides_nothing(live: Live) -> None:
    card = live.case.card()
    got = approve(live, card, headers(login(live.http, "user", CASE)))
    assert got.status_code == 200, got.text
    (sent,) = live.case.posts
    assert (sent.subject, sent.subject_id, sent.decision) == (
        "approval",
        card.approval_id,
        "granted",
    )
    assert (sent.subject_hash, sent.authority_epoch) == (card.terms_hash, 0)
    types = [e.type for e in live.case.bus.events]
    assert types.count("approval.post") == 1 and "approval.decided" not in types


def test_a_denied_decision_is_posted_too(live: Live) -> None:
    card = live.case.card()
    got = approve(
        live, card, headers(login(live.http, "user", CASE)), decision="denied"
    )
    assert got.status_code == 200
    assert [p.decision for p in live.case.posts] == ["denied"]


def _other_case(live: Live) -> dict[str, str]:
    other = ApiCase(live.root, "case-2").start()
    live.cases["case-2"] = other
    return login(live.http, "user", "case-2")


def _swapped(live: Live) -> dict[str, str]:
    """The rep's values under the user's cookie names."""
    rep = login(live.http, "rep", CASE)
    return {"pl_session": rep["pl_rep_session"], "pl_csrf": rep["pl_rep_csrf"]}


def _forged(live: Live) -> dict[str, str]:
    return {"pl_session": "a" * 43, "pl_csrf": "b" * 64}


BAD_CSRF: dict[str, Callable[[Live], dict[str, str]]] = {
    "no token": lambda live: headers(login(live.http, "user", CASE), OMIT),
    "wrong token": lambda live: headers(login(live.http, "user", CASE), "0" * 64),
    "no cookies": lambda live: headers({}, login(live.http, "user", CASE)["pl_csrf"]),
    "no session cookie": lambda live: headers(
        {"pl_csrf": login(live.http, "user", CASE)["pl_csrf"]}
    ),
    "another case": lambda live: headers(_other_case(live)),
    "the rep's cookies": lambda live: headers(login(live.http, "rep", CASE)),
    "the rep's values": lambda live: headers(_swapped(live)),
    "forged pair": lambda live: headers(_forged(live)),
}


@pytest.mark.parametrize("make", BAD_CSRF.values(), ids=BAD_CSRF.keys())
def test_a_bad_csrf_token_is_403_and_calls_nothing(
    live: Live, make: Callable[[Live], dict[str, str]]
) -> None:
    card = live.case.card()
    hdrs = make(live)
    got = approve(live, card, hdrs)
    assert (got.status_code, got.json()) == (403, {"error": "csrf"})
    text = {"text": "hello"}
    got = post(live.http, f"/api/cases/{CASE}/messages", text, hdrs)
    assert (got.status_code, got.json()) == (403, {"error": "csrf"})
    assert live.case.posts == [] and live.case.messages == []
    assert live.case.posted() == 0


@pytest.mark.parametrize("origin", [OMIT, "http://evil.example", "null"])
def test_every_post_needs_an_allowed_origin(live: Live, origin: str) -> None:
    card = live.case.card()
    user = headers(login(live.http, "user", CASE), origin=origin)
    rep = headers(login(live.http, "rep", CASE), origin=origin)
    text = {"text": "hi"}
    for got in (
        approve(live, card, user),
        post(live.http, f"/api/cases/{CASE}/messages", text, user),
        post(live.http, f"/api/cases/{CASE}/rep", text, rep),
    ):
        assert (got.status_code, got.json()) == (403, {"error": "origin"})
        assert "access-control-allow-origin" not in got.headers
    assert live.case.posts == live.case.messages == live.case.utterances == []


def test_a_foreign_host_is_refused(live: Live) -> None:
    card = live.case.card()
    hdrs = headers(login(live.http, "user", CASE)) | {"host": "evil.example"}
    assert approve(live, card, hdrs).status_code == 400
    assert get(live.http, f"/live/{CASE}", {"host": "evil.example"}).status_code == 400
    assert live.case.posts == []


Then = Callable[[ApiCase, ApprovalCard], object]
F64 = "f" * 64
STALE: dict[str, tuple[Then, dict[str, object], str]] = {
    "wrong hash": (lambda c, k: None, {"terms_hash": F64}, "subject_hash_mismatch"),
    "wrong epoch": (lambda c, k: None, {"authority_epoch": 1}, "stale_epoch"),
    "epoch bumped": (lambda c, k: c.bump_epoch(), {}, "stale_epoch"),
    "superseded": (lambda c, k: c.revise(), {}, "card_superseded"),
    "expired": (lambda c, k: c.expire(k), {}, "card_expired"),
}  # fmt: skip


@pytest.mark.parametrize(("then", "change", "reason"), STALE.values(), ids=STALE.keys())
def test_a_stale_post_is_409_and_calls_nothing(
    live: Live,
    then: Then,
    change: dict[str, object],
    reason: str,
) -> None:
    card = live.case.card()
    then(live.case, card)
    before = len(live.case.bus.events)
    got = approve(live, card, headers(login(live.http, "user", CASE)), **change)
    assert (got.status_code, got.json()) == (409, {"error": "stale", "reason": reason})
    assert live.case.posts == [] and len(live.case.bus.events) == before


def test_an_unknown_approval_id_is_stale(live: Live) -> None:
    card = live.case.card().model_copy(update={"approval_id": "apr-nope"})
    got = approve(live, card, headers(login(live.http, "user", CASE)))
    assert got.json() == {"error": "stale", "reason": "no_pending_card"}
    assert live.case.posts == []


def test_a_denial_does_not_use_up_the_card(live: Live) -> None:
    card, hdrs = live.case.card(), headers(login(live.http, "user", CASE))
    assert approve(live, card, hdrs, terms_hash="f" * 64).status_code == 409
    assert approve(live, card, hdrs).status_code == 200
    assert len(live.case.posts) == 1


def test_a_replayed_post_is_409_with_exactly_one_post(live: Live) -> None:
    card, hdrs = live.case.card(), headers(login(live.http, "user", CASE))
    assert approve(live, card, hdrs).status_code == 200
    # The kernel has not decided yet: the card is still pending on the board.
    assert live.case.blackboard().private.pending_approval == card
    again = approve(live, card, hdrs, decision="denied")
    assert (again.status_code, again.json()["error"]) == (409, "already_decided")
    live.case.decided()  # now the board shows the decision too
    third = approve(live, card, hdrs)
    assert (third.status_code, third.json()["error"]) == (409, "already_decided")
    assert len(live.case.posts) == 1 and live.case.posted() == 1


def test_concurrent_posts_make_exactly_one_post(live: Live) -> None:
    card, hdrs = live.case.card(), headers(login(live.http, "user", CASE))
    url = f"/api/cases/{CASE}/approvals/{card.approval_id}"

    async def race() -> list[int]:
        transport = httpx.ASGITransport(app=live.http.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as http:
            sent = [http.post(url, json=body(card), headers=hdrs) for _ in range(8)]
            return sorted(r.status_code for r in await asyncio.gather(*sent))

    assert asyncio.run(race()) == [200] + [409] * 7
    assert len(live.case.posts) == 1 and live.case.posted() == 1


BAD_BODY: dict[str, dict[str, object]] = {
    "extra field": {"approved": True},
    "short hash": {"terms_hash": "abc"},
    "upper hash": {"terms_hash": "A" * 64},
    "negative epoch": {"authority_epoch": -1},
    "not a decision": {"decision": "yes"},
}


@pytest.mark.parametrize("change", BAD_BODY.values(), ids=BAD_BODY.keys())
def test_a_malformed_body_is_422_and_calls_nothing(
    live: Live, change: dict[str, object]
) -> None:
    card = live.case.card()
    assert (
        approve(
            live, card, headers(login(live.http, "user", CASE)), **change
        ).status_code
        == 422
    )
    assert live.case.posts == []


def test_messages_and_rep_lines_go_through_their_own_role(live: Live) -> None:
    user, rep = login(live.http, "user", CASE), login(live.http, "rep", CASE)
    messages, said = f"/api/cases/{CASE}/messages", f"/api/cases/{CASE}/rep"
    assert post(live.http, messages, {"text": "stop"}, headers(user)).status_code == 200
    assert (
        post(live.http, said, {"text": "Hi, Sam here."}, headers(rep)).status_code
        == 200
    )
    for url, hdrs in [(messages, headers(rep)), (said, headers(user))]:
        got = post(live.http, url, {"text": "cross"}, hdrs)
        assert (got.status_code, got.json()) == (403, {"error": "csrf"})
    card = live.case.card()  # a rep can never approve
    got = approve(live, card, headers(rep))
    assert (got.status_code, got.json()) == (403, {"error": "csrf"})
    assert live.case.messages == ["stop"] and live.case.utterances == ["Hi, Sam here."]
    assert live.case.posts == []


@pytest.mark.parametrize("text", ["", "x" * 4001], ids=["empty", "over the cap"])
def test_text_is_bounded(live: Live, text: str) -> None:
    got = post(
        live.http,
        f"/api/cases/{CASE}/messages",
        {"text": text},
        headers(login(live.http, "user", CASE)),
    )
    assert got.status_code == 422
    assert live.case.messages == []


def test_an_unknown_case_is_404(live: Live) -> None:
    for page in ("live", "rep"):
        assert get(live.http, f"/{page}/case-9", follow=False).status_code == 404
    hdrs = headers(login(live.http, "user", CASE))
    card = live.case.card()
    del live.cases[CASE]  # the case went away after login
    assert approve(live, card, hdrs).status_code == 404
    got = post(live.http, f"/api/cases/{CASE}/messages", {"text": "hi"}, hdrs)
    assert got.status_code == 404
    assert live.case.posts == [] and live.case.messages == []


def test_a_replay_only_server_has_no_case_routes(live: Live) -> None:
    http = client(live.root)  # cases=None
    for page in ("live", "rep"):
        assert get(http, f"/{page}/{CASE}", follow=False).status_code == 404
    hdrs = {"origin": ORIGIN, "x-csrf-token": "t", "cookie": "pl_session=s; pl_csrf=t"}
    for url in ("approvals/apr-1", "messages", "rep"):
        assert post(http, f"/api/cases/{CASE}/{url}", {}, hdrs).status_code == 404


def test_a_case_is_unknown_until_its_session_started_exists(live: Live) -> None:
    fresh = ApiCase(live.root, "case-3")  # no seq 0 yet
    live.cases["case-3"] = fresh
    assert get(live.http, "/live/case-3", follow=False).status_code == 404
    fresh.start()
    login(live.http, "user", "case-3")
    held = ApiCase(live.root, "case-4").start(split="test")  # held out: never
    live.cases["case-4"] = held
    assert get(live.http, "/live/case-4", follow=False).status_code == 404
