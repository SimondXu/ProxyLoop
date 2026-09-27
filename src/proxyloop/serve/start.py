"""Starting a live case from the browser (S1-SYS-33; S1: one case = one run).

The kernel's ``Starter`` (``serve.cases``; L-CORE, ``kernel/web.py``) is the
seam: serve never imports the kernel. Without a starter every route here is
404.

- ``GET /start`` sets the operator's cookie pair (``serve.csrf``, role
  ``operator``, bound to no case) and redirects 303 to ``/?start``.
- ``GET /api/models`` is ``{"options": [ModelOption...], "tasks": [task_ref...]}``.
  serve checks the starter's promises and fails loudly (500 ``{"error":
  "options"}``, logged) instead of repairing them.
- ``POST /api/cases`` needs an allowed Origin (``serve.api``: every POST) and
  the operator's signed double-submit token, else 403 before the body is
  read; a malformed body is 422. ``models`` is forwarded as given (defaults
  are the kernel's rule). One lock serialises ``start_case``, so two clicks
  never race inside the kernel ("busy" stays the kernel's answer). 201
  ``{"case_id": run_id}``; ``StartRefused`` is 400 ``{"error": "start",
  "reason"}`` (409 when busy); any other exception 503 ``unavailable``,
  logged and never retried (I8, AGENTS rule 6).

A started case is kept in serve's own map, which ``create_app`` puts in front
of its ``cases`` lookup: ``GET /live``, ``/rep``, the case POSTs and
``/ws/rep`` find it like any other case (and 404 while its run is not
servable). A run_id already in the map is 503 ``unavailable``, logged, and
never replaces the case it names. A refusal reason outside ``REASONS`` is 503
``unavailable`` too, logged with its URLs redacted (AGENTS rule 15).

Threat model: ``GET /start`` needs no authentication, so any local process can
act as operator and start a paid session; the operator pair and the Origin
check guard only against cross-site requests (as for ``serve.cases``).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from typing import Annotated, Literal, cast, get_args

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from proxyloop.contract.llm import Endpoint
from proxyloop.serve.bundles import redact
from proxyloop.serve.cases import (
    Case,
    Cases,
    LaneKey,
    ModelOption,
    Refused,
    Starter,
    StartRefused,
)
from proxyloop.serve.csrf import HEADER, NO_CASE, Csrf

TASK_REF = r"^[a-z0-9][a-z0-9._@-]{0,63}$"  # a family name, e.g. cp-direct-discount
OPTION_ID = r"^[!-~]{1,128}$"  # printable ASCII without spaces: an opaque option id
REASONS = frozenset(
    ("unknown_task", "unknown_model", "wrong_lane", "not_live", "busy", "unavailable")
)  # the frozen StartRefused reasons: only these reach the browser
_log = logging.getLogger(__name__)


class StartBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_ref: str = Field(pattern=TASK_REF)
    models: dict[LaneKey, Annotated[str, Field(pattern=OPTION_ID)]]
    rep: Literal["sim", "human"] = "sim"


def broken(options: Sequence[object], tasks: object) -> str | None:
    """The first promise the starter's lists break, or None."""
    if isinstance(tasks, str) or not isinstance(tasks, Sequence):
        return "tasks are not a list"
    if not all(isinstance(task, str) for task in cast(Sequence[object], tasks)):
        return "a task is not a string"
    if not all(re.fullmatch(TASK_REF, task) for task in cast(Sequence[str], tasks)):
        return "a task would be refused by POST /api/cases (TASK_REF)"
    if not all(isinstance(option, ModelOption) for option in options):
        return "an option is not a ModelOption"
    offered = cast(Sequence[ModelOption], options)
    if not all(re.fullmatch(OPTION_ID, option.id) for option in offered):
        return "an option id would be refused by POST /api/cases (OPTION_ID)"
    if len({option.id for option in offered}) != len(offered):
        return "option ids are not unique"
    for option in offered:  # a buggy starter can skip validation (model_copy)
        if option.lane not in get_args(LaneKey):
            return f"option {option.id!r} has an unknown lane"
        # Only real_http models may be offered live. ModelOption has no adapter
        # kind, so the check is that its endpoint is a contract Endpoint: a
        # baseline (endpoint None) or anything else fails.
        if option.endpoint not in get_args(Endpoint):
            return f"option {option.id!r} has no contract endpoint"
    for lane in {option.lane for option in offered}:
        if sum(o.default for o in offered if o.lane == lane) != 1:
            return f"lane {lane!r} does not have exactly one default"
    return None


def add_start_routes(app: FastAPI, start: Starter | None, csrf: Csrf) -> Cases:
    """Add the routes; return the lookup of the cases started through them."""
    started: dict[str, Case] = {}
    lock = asyncio.Lock()

    def starter() -> Starter:
        if start is None:  # no live starts on this server
            raise Refused(404, "no starter")
        return start

    @app.get("/start")
    async def operator_page() -> Response:
        starter()
        response = RedirectResponse("/?start", status_code=303)
        csrf.issue(response, "operator", NO_CASE)
        return response

    @app.get("/api/models")
    async def models() -> Response:
        kernel = starter()
        options, tasks = kernel.model_options(), kernel.task_options()
        if (why := broken(options, tasks)) is not None:
            _log.error("the starter broke its promise: %s", why)
            raise Refused(500, "options", why)
        listed = [option.model_dump(mode="json") for option in options]
        return JSONResponse({"options": listed, "tasks": list(tasks)})

    @app.post("/api/cases")
    async def start_case(request: Request) -> Response:
        kernel = starter()
        header = request.headers.get(HEADER)
        if not csrf.posted("operator", NO_CASE, request.cookies, header):
            raise Refused(403, "csrf")
        try:
            body = StartBody.model_validate_json(await request.body())
        except ValidationError as err:
            raise Refused(422, "invalid body") from err
        async with lock:
            try:
                case = await kernel.start_case(body.task_ref, body.models, body.rep)
            except StartRefused as refused:
                if refused.reason not in REASONS:
                    why = redact(refused.reason.encode()).decode()
                    _log.error("start refused with an unknown reason: %s", why)
                    raise Refused(503, "unavailable") from None
                status = 409 if refused.reason == "busy" else 400
                raise Refused(status, "start", refused.reason) from refused
            except Exception as err:  # loud: logged, 503, no retry
                _log.exception("start_case failed for task %s", body.task_ref)
                raise Refused(503, "unavailable") from err
            if case.run_id in started:
                _log.error("the starter returned run_id %r twice", case.run_id)
                raise Refused(503, "unavailable")
            started[case.run_id] = case
        return JSONResponse({"case_id": case.run_id}, 201)

    return started.get
