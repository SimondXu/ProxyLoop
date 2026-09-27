"""Live case routes (ARCHITECTURE §9.6, C15; S1: case_id = run_id).

``GET /live/{case}`` and ``GET /rep/{case}`` issue the role's cookies
(``serve.csrf``) and redirect to the web page. Every POST needs an allowed
Origin (``serve.api``), the role's signed CSRF pair echoed in the header, and a
known case; else 403 ``{"error": "origin" | "csrf"}`` or 404:

- ``POST /api/cases/{case}/approvals/{approval_id}`` (user): single use per
  (case, approval id), then ``guard.decide`` as a pre-check on the kernel's
  current blackboard. A Denial is 409 ``already_decided`` or ``stale`` (with
  the reason) and calls nothing: no event. Success hands the post to the
  kernel once (``Case.post_approval``) and returns 200: "posted", not
  "decided" (the kernel decides; see ``Case.post_approval``). If the handover
  raises, 503 ``unavailable``, and that approval id stays 503 (fail closed).
  The endpoint never decides, mints or emits a decision (I6).
- ``POST /api/cases/{case}/messages`` (user) and ``/rep`` (the human rep):
  text into the case's user-lane and cp-lane ingress; if the ingress raises,
  503 ``unavailable``, logged. Text that is empty after ``strip()`` is 422
  ``invalid body`` (the kernel refuses it too); accepted text is forwarded as
  sent, not stripped.

A Denial does not use up the single-use slot: only a post handed to the kernel
does. ``guard.decide`` is a pure function of the board, so a later POST is
judged afresh, and a malformed or early POST cannot burn a valid card. Mandate
posts have no route here.

Threat model: on this single-machine 127.0.0.1 server the user/rep split
guards only against cross-site requests and bugs in the web code, not against
a hostile local rep. ``GET /live`` needs no authentication, and ``/ws/live``
and ``/api/replay`` need no cookie, so no claim may say the rep is isolated.
Real rep isolation (a separate host, or authentication) comes later.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Literal, Protocol

from fastapi import FastAPI, Request
from fastapi import Path as Param
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from proxyloop.contract.bundle import EVENTS
from proxyloop.contract.events import ApprovalPost, Decision
from proxyloop.contract.llm import Endpoint
from proxyloop.contract.state import Blackboard
from proxyloop.guard.authorize import Denial, decide
from proxyloop.serve.bundles import RUN_ID, find_run
from proxyloop.serve.csrf import HEADER, Csrf, Role

TEXT_MAX = 4_000  # characters in one chat message or rep line
PAGES: dict[Role, str] = {"user": "live", "rep": "rep"}
Id = Annotated[str, Param(pattern=RUN_ID)]
_log = logging.getLogger(__name__)


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
        """Only enqueue ``post``; serve's 200 means "posted", not "decided".
        On its own loop the kernel re-runs ``guard.decide(bb, post, "ui")`` on
        the board at that point:

        - success: emit ``approval.post`` (actor ``ui``), then
          ``approval.decided`` (actor ``kernel``) citing that post;
        - Denial: the fold refuses a stale ``approval.post``, so instead emit
          the restrict-only ``action.denied{intent: "approval.post", reason:
          <decide's reason>}`` (actor ``kernel``) citing a legal cause (e.g.
          the refused card's ``approval.requested``), and wake Slow.

        Either way the user's click leaves an event. (Should the contract
        refuse such an ``action.denied``, that is an L-CORE fold change.)
        Raising here makes serve answer 503 ``unavailable``."""
        ...

    def user_message(self, text: str) -> None:
        """The user lane's ingress: the kernel emits ``user.msg``."""
        ...

    def rep_utterance(self, text: str) -> None:
        """The human rep's line: the kernel emits ``utt.final`` (lane cp,
        speaker partner)."""
        ...


Cases = Callable[[str], Case | None]
LaneKey = Literal["fast_user", "fast_cp", "slow"]


class ModelOption(BaseModel):
    """One model a lane may be started with, as the starter offers it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str  # stable option id, e.g. "openrouter:openai/gpt-6-luna"
    lane: LaneKey
    label: str  # dropdown text
    endpoint: Endpoint
    model_id: str
    default: bool  # exactly one default per lane


class StartRefused(Exception):
    """Kernel refuses a start; serve answers 400 {"error": "start", "reason":
    reason}, or 409 when reason == "busy"."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Starter(Protocol):
    """Starts a live case (L-CORE, S1-SYS-05, ``kernel/web.py``): the seam
    serve calls and never imports. S1: one case = one run."""

    def model_options(self) -> Sequence[ModelOption]:
        """Pure, fast, in a stable order."""
        ...

    def task_options(self) -> Sequence[str]:
        """Training families only (AGENTS rule 11), in a stable order."""
        ...

    async def start_case(
        self,
        task_ref: str,
        models: Mapping[LaneKey, str],
        rep: Literal["sim", "human"] = "sim",
    ) -> Case:
        """Start one run. A lane missing from ``models`` gets that lane's
        default. Raises ``StartRefused`` with reason ``unknown_task``,
        ``unknown_model``, ``wrong_lane``, ``not_live``, ``busy`` or
        ``unavailable``. Returns only after the run's ``session.started``
        (seq 0) is written; the Case's ``run_id`` is the case_id, and the run
        lives at ``runs/live/<run_id>/<run_id>``. Model failures after the
        start are the session's, never raised here. serve may cancel this call
        when the client disconnects, and then never registers the case: a
        kernel that completes the start must accept the cancellation cleanly
        or keep the run reachable."""
        ...


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ApprovalBody(_Body):
    decision: Decision
    terms_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_epoch: int = Field(ge=0)


class TextBody(_Body):
    text: str = Field(min_length=1, max_length=TEXT_MAX)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, text: str) -> str:
        if not text.strip():  # as HumanWebChannel.say refuses it: a 422, not 503
            raise ValueError("blank text")
        return text  # as sent


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


def _open(
    roots: Sequence[Path], cases: Cases, case_id: str
) -> tuple[Case, Path] | None:
    if (case := cases(case_id)) is None:
        return None
    path = _events(roots, case.run_id)
    return None if path is None else (case, path)


async def open_case(
    roots: Sequence[Path], cases: Cases | None, case_id: str
) -> tuple[Case, Path] | None:
    """The case and its run's ``events.jsonl``, or None: unknown. ``cases``
    runs in the worker thread with the bundle lookup (the started map's lookup
    reads files, ``serve.start``); the Case's methods are still called only on
    the event loop."""
    if cases is None:
        return None
    return await asyncio.to_thread(_open, roots, cases, case_id)


def add_case_routes(
    app: FastAPI, roots: Sequence[Path], cases: Cases | None, csrf: Csrf
) -> None:
    # (case_id, approval_id) -> handed over, or the handover raised
    slots: dict[tuple[str, str], Literal["posted", "failed"]] = {}
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
        if slots.get(key) == "failed":
            raise Refused(503, "unavailable")
        if key in slots:  # handed over; the board may not show it yet
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
        slots[key] = "posted"
        try:
            case.post_approval(post)
        except Exception as err:  # loud: logged, 503, and the id stays refused
            slots[key] = "failed"
            why = type(err).__name__  # only: no text, traceback or cause (rule 15)
            _log.error("post_approval failed for %s/%s: %s", case_id, approval_id, why)
            raise Refused(503, "unavailable") from err
        return JSONResponse({"status": "posted"})

    def send(ingress: Callable[[str], None], text: str, case_id: str) -> Response:
        try:
            ingress(text)
        except Exception as err:  # loud: logged, 503, no retry
            why = type(err).__name__  # only: no text, traceback or cause (rule 15)
            _log.error("the ingress failed for case %s: %s", case_id, why)
            raise Refused(503, "unavailable") from err
        return JSONResponse({"status": "sent"})

    @app.post("/api/cases/{case_id}/messages")
    async def message(request: Request, case_id: Id) -> Response:
        case = await allowed(request, "user", case_id)
        text = (await parse(request, TextBody)).text
        return send(case.user_message, text, case_id)

    @app.post("/api/cases/{case_id}/rep")
    async def rep_line(request: Request, case_id: Id) -> Response:
        case = await allowed(request, "rep", case_id)
        text = (await parse(request, TextBody)).text
        return send(case.rep_utterance, text, case_id)
