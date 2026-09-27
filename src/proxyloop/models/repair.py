"""Teacher-repair, condition R and ablation A4 (EVAL §4; TRAINING §2.1).

Two parts, split along what each can see:

- ``decision_point(view)``: the kernel-side detector over a ``FastView``. It
  names the decision points of TRAINING §2.1 (a rep offer, an ask to accept or
  decide, any rep question while an offer is open, a protected-fact or identity
  request heard, a pending approval, a user correction or stop).
  ``substitutes(view, ablations)`` applies it only on a lane whose
  ``teacher_repair_*`` ablation is set.
- ``TeacherRepair``: the teacher as a Fast under Fast-role constraints. It
  receives exactly the kernel's ``render_messages(view, profile)`` request (it
  renders nothing, I3). ``max_resamples`` has no default:
  - evaluation (conditions T and R) passes 0: the teacher's output is delivered
    as it streams, and parse issues are counted, exactly as for the student;
  - teacher-in-harness data generation (TRAINING §2.1, S3) passes 2: output
    the student parser rejects is resampled, and each call's count is kept.
  The teacher runs on the wall clock (I7).

The kernel (S1-SYS-02) routes a generation to ``TeacherRepair`` when
``substitutes`` names a decision point, and to the student otherwise.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Collection
from typing import Literal

from proxyloop.contract.base import Lane
from proxyloop.contract.config import AblationId
from proxyloop.contract.llm import (
    LLMCallRecord,
    LLMClient,
    ModelRef,
    TextRequest,
    ToolRequest,
    ToolResponse,
)
from proxyloop.contract.protocol import PROFILES, ParseIssue, parse_turn
from proxyloop.contract.views import FastView
from proxyloop.models import cues

DecisionPoint = Literal["offer", "fact_request", "approval", "correction", "stop"]
_REPAIR: dict[Lane, AblationId] = {
    "user": AblationId.TEACHER_REPAIR_USER,
    "cp": AblationId.TEACHER_REPAIR_CP,
}


def decision_point(view: FastView) -> DecisionPoint | None:
    """The decision point this generation answers, from the view alone."""

    last = view.transcript[-1] if view.transcript else None
    heard = last.text if last is not None and last.speaker == "partner" else ""
    if view.lane == "user":
        if view.pending_approval is not None:
            return "approval"
        if view.trigger.kind != "user_msg":
            return None
        if cues.STOP.search(heard):
            return "stop"
        return "correction" if cues.CORRECTION.search(heard) else None
    if view.trigger.kind != "rep_spoke":
        return None
    if cues.PROTECTED.search(heard) or cues.IDENTITY.search(heard):
        return "fact_request"
    if cues.ACCEPT.search(heard) or cues.PRESSURE.search(heard) or cues.offer(heard):
        return "offer"
    asked = heard.rstrip().endswith("?")
    return "offer" if asked and any(o.status == "open" for o in view.offers) else None


def substitutes(
    view: FastView, ablations: Collection[AblationId]
) -> DecisionPoint | None:
    """Whether the teacher answers this generation (condition R, ablation A4)."""

    return decision_point(view) if _REPAIR[view.lane] in ablations else None


def _lane(request: TextRequest) -> Lane:
    system = request.messages[0].content if request.messages else None
    profile = next((p for p in PROFILES.values() if p.system == system), None)
    if profile is None:
        raise ValueError("the teacher takes the contract's render_messages only")
    return profile.lane


class TeacherRepair:
    """``LLMClient`` over the teacher's client; its ref is the teacher's.

    With ``max_resamples > 0`` the output is held until it parses (a resample
    must never follow spoken text), then delivered whole with the record of the
    attempt it came from. Every attempt's record reaches the teacher client's
    own sink. After ``max_resamples`` the last output is delivered as it is,
    and its parse issues are counted downstream, never repaired.
    """

    def __init__(self, teacher: LLMClient, max_resamples: int) -> None:
        if max_resamples < 0:
            raise ValueError("max_resamples must be 0 (evaluation) or more")
        self._teacher, self.max_resamples = teacher, max_resamples
        self.resamples: dict[str, int] = {}  # call_id -> resamples it used

    @property
    def ref(self) -> ModelRef:
        return self._teacher.ref

    async def stream_text(
        self, request: TextRequest
    ) -> AsyncIterator[str | LLMCallRecord]:
        lane, text, record = _lane(request), "", None
        if self.max_resamples == 0:  # evaluation: streamed, never resampled
            self.resamples[request.call_id] = 0
            async for item in self._teacher.stream_text(request):
                yield item
            return
        for n in range(self.max_resamples + 1):
            seed = None if request.seed is None else request.seed + n
            attempt = request.model_copy(update={"seed": seed})
            text, record = "", None
            async for item in self._teacher.stream_text(attempt):
                if isinstance(item, LLMCallRecord):
                    record = item
                else:
                    text += item
            if record is None:
                raise RuntimeError("the teacher's stream ended without its record")
            self.resamples[request.call_id] = n
            parsed = parse_turn(text, lane)
            if not any(isinstance(i, ParseIssue) for i in parsed):
                break
        assert record is not None
        if text:
            yield text
        yield record

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        raise TypeError("the teacher as a Fast serves text only")
