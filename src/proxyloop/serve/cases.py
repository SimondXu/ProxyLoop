"""Live case routes (ARCHITECTURE §9.6, C15; S1: case_id = run_id).

``GET /live/{case}`` and ``GET /rep/{case}`` issue the role's cookies
(``serve.csrf``) and redirect to the web page. Every POST needs an allowed
Origin (``serve.api``), the role's signed CSRF pair echoed in the header, and a
known case; else 403 ``{"error": "origin" | "csrf"}`` or 404:

- ``POST /api/cases/{case}/approvals/{approval_id}`` (user): single use per
  (case, approval id), then ``guard.decide`` as a pre-check on the kernel's
  current blackboard. A Denial is 409 ``already_decided`` or ``stale`` (with
  the reason) and calls nothing: no event. Success hands the post to the
  kernel once (``Case.post_approval``, which emits ``approval.post``); the
  kernel re-runs ``guard.decide`` and emits ``approval.decided`` itself. The
  endpoint never decides, mints or emits a decision (I6).
- ``POST /api/cases/{case}/messages`` (user) and ``/rep`` (the human rep):
  text into the case's user-lane and cp-lane ingress.

A Denial does not use up the single-use slot: only a post handed to the kernel
does. ``guard.decide`` is a pure function of the board, so a later POST is
judged afresh, and a malformed or early POST cannot burn a valid card. Mandate
posts have no route here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Annotated, Protocol

from fastapi import FastAPI, Request
from fastapi import Path as Param
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from proxyloop.contract.bundle import EVENTS
from proxyloop.contract.events import ApprovalPost, Decision
from proxyloop.contract.state import Blackboard
from proxyloop.guard.authorize import Denial, decide
from proxyloop.serve.bundles import RUN_ID, find_run
from proxyloop.serve.csrf import HEADER, Csrf, Role

TEXT_MAX = 4_000  # characters in one chat message or rep line
PAGES: dict[Role, str] = {"user": "live", "rep": "rep"}
Id = Annotated[str, Param(pattern=RUN_ID)]


class Case(Protocol):
    """A running session, as the kernel's starter hands it to serve (L-CORE,
    S1-SYS-05). serve never imports the kernel; this is the seam.

    Guarantee the starter gives: a case becomes visible (``cases`` returns it)
    only after its run's ``session.started`` (seq 0) is written ("start returns
    only after seq 0 exists"). serve still treats a case whose run has no seq 0
    yet as unknown (404 / 4404). Every method is called on serve's event loop
    and must return without blocking."""

    run_id: str

    def blackboard(self) -> Blackboard:
        """The kernel's current fold (a snapshot)."""
        ...

    def post_approval(self, post: ApprovalPost) -> None:
        """Queue ``post`` for the kernel, which emits ``approval.post`` (actor
        ``ui``), re-runs ``guard.decide`` and emits ``approval.decided``."""
        ...

    def user_message(self, text: str) -> None:
        """The user lane's ingress: the kernel emits ``user.msg``."""
        ...

    def rep_utterance(self, text: str) -> None:
        """The human rep's line: the kernel emits ``utt.final`` (lane cp,
        speaker partner)."""
        ...


Cases = Callable[[str], Case | None]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ApprovalBody(_Body):
    decision: Decision
    terms_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_epoch: int = Field(ge=0)


class TextBody(_Body):
    text: str = Field(min_length=1, max_length=TEXT_MAX)


class Refused(Exception):
    """A refusal with a JSON body ``{"error": ..., "reason"?: ...}``."""

    def __init__(self, status: int, error: str, reason: str | None = None) -> None:
        super().__init__(error)
        self.status = status
        self.body = {"error": error} | ({"reason": reason} if reason else {})


async def _refused(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, Refused)
    return JSONResponse(exc.body, exc.status)


def _events(roots: Sequence[Path], run_id: str) -> Path | None:
    run = find_run(roots, run_id)  # servable: seq 0 written, not held out
    return run.file(EVENTS) if run is not None else None


async def open_case(
    roots: Sequence[Path], cases: Cases | None, case_id: str
) -> tuple[Case, Path] | None:
    """The case and its run's ``events.jsonl``, or None: unknown."""
    case = cases(case_id) if cases is not None else None
    if case is None:
        return None
    path = await asyncio.to_thread(_events, roots, case.run_id)
    return None if path is None else (case, path)


def add_case_routes(
    app: FastAPI, roots: Sequence[Path], cases: Cases | None, csrf: Csrf
) -> None:
    posted: set[tuple[str, str]] = set()  # (case_id, approval_id) handed over
    app.add_exception_handler(Refused, _refused)

    async def known(case_id: str) -> Case:
        if (found := await open_case(roots, cases, case_id)) is None:
            raise Refused(404, "unknown case")
        return found[0]

    async def allowed(request: Request, role: Role, case_id: str) -> Case:
        if cases is None:  # a replay-only server
            raise Refused(404, "unknown case")
        header = request.headers.get(HEADER)
        if not csrf.posted(role, case_id, request.cookies, header):
            raise Refused(403, "csrf")
        return await known(case_id)

    async def parse[M: _Body](request: Request, model: type[M]) -> M:
        try:
            return model.model_validate_json(await request.body())
        except ValidationError as err:
            raise Refused(422, "invalid body") from err

    async def page(role: Role, case_id: str) -> Response:
        await known(case_id)
        response = RedirectResponse(f"/?{PAGES[role]}={case_id}", status_code=303)
        csrf.issue(response, role, case_id)
        return response

    @app.get("/live/{case_id}")
    async def live_page(case_id: Id) -> Response:
        return await page("user", case_id)

    @app.get("/rep/{case_id}")
    async def rep_page(case_id: Id) -> Response:
        return await page("rep", case_id)

    @app.post("/api/cases/{case_id}/approvals/{approval_id}")
    async def approve(request: Request, case_id: Id, approval_id: Id) -> Response:
        case = await allowed(request, "user", case_id)
        body = await parse(request, ApprovalBody)
        # No await from here on: concurrent POSTs cannot interleave.
        key = (case_id, approval_id)
        if key in posted:  # handed over; the board may not show it yet
            raise Refused(409, "already_decided")
        post = ApprovalPost(
            subject="approval",
            subject_id=approval_id,
            decision=body.decision,
            subject_hash=body.terms_hash,
            authority_epoch=body.authority_epoch,
        )
        got = decide(case.blackboard(), post, "ui")
        if isinstance(got, Denial):
            error = "already_decided" if got.reason == "already_decided" else "stale"
            raise Refused(409, error, got.reason)
        posted.add(key)
        case.post_approval(post)
        return JSONResponse({"status": "posted"})

    @app.post("/api/cases/{case_id}/messages")
    async def message(request: Request, case_id: Id) -> Response:
        case = await allowed(request, "user", case_id)
        case.user_message((await parse(request, TextBody)).text)
        return JSONResponse({"status": "sent"})

    @app.post("/api/cases/{case_id}/rep")
    async def rep_line(request: Request, case_id: Id) -> Response:
        case = await allowed(request, "rep", case_id)
        case.rep_utterance((await parse(request, TextBody)).text)
        return JSONResponse({"status": "sent"})
