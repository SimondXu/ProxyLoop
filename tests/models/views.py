"""Views for the models tests: the committed goldens, and small built views."""

from __future__ import annotations

import json
from pathlib import Path

from proxyloop.contract.llm import ChatMessage, TextRequest
from proxyloop.contract.protocol import PROFILES, render_messages
from proxyloop.contract.state import CaseStatus, Line
from proxyloop.contract.views import FastView, Trigger

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "views"
PROFILE = {"user": "pl_user_v1", "cp": "pl_cp_v1"}


def goldens() -> dict[str, tuple[FastView, tuple[ChatMessage, ...]]]:
    out: dict[str, tuple[FastView, tuple[ChatMessage, ...]]] = {}
    for path in sorted(GOLDEN.glob("*.json")):
        doc = json.loads(path.read_text("utf-8"))
        messages = tuple(ChatMessage.model_validate(m) for m in doc["messages"])
        out[path.stem] = (FastView.model_validate(doc["view"]), messages)
    return out


def view(
    lane: str,
    heard: str = "",
    trigger: str | None = None,
    status: CaseStatus = CaseStatus.IN_CALL,
    **update: object,
) -> FastView:
    """A view whose last transcript line is the partner saying ``heard``."""

    kind = trigger or ("user_msg" if lane == "user" else "rep_spoke")
    lines = (Line(utt_id="p1", speaker="partner", text=heard),) if heard else ()
    trig = Trigger.model_validate(
        {
            "kind": kind,
            "wait_s": 10 if kind == "hold_wait" else None,
            "msg_id": "s1" if kind == "slow_msg" else None,
        }
    )
    base: dict[str, object] = {
        "lane": lane,
        "brief": "Help the account holder lower their monthly bill.",
        "public_summary": "",
        "action_log": (),
        "offers": (),
        "status": status,
        "transcript": lines,
        "trigger": trig,
    }
    return FastView.model_validate(base | update)


def request(
    messages: tuple[ChatMessage, ...] | FastView, call_id: str = "fast_cp:0"
) -> TextRequest:
    if isinstance(messages, FastView):
        messages = render_messages(messages, PROFILE[messages.lane])
    lane = next(p.lane for p in PROFILES.values() if p.system == messages[0].content)
    return TextRequest(
        call_id=call_id,
        role="fast_user" if lane == "user" else "fast_cp",
        messages=messages,
        max_tokens=160,
        temperature=0.3,
        top_p=0.9,
        seed=11,
    )
