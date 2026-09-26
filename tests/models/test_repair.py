"""Teacher-repair: the decision-point detector and the constrained teacher."""

from __future__ import annotations

import asyncio

import pytest
from tests.contract.llm_conformance import (
    assert_text_conformance,
    assert_unavailable,
)
from tests.models.views import goldens, request, view
from tests.support.fakes import ScriptedLLM, fake_ref

from proxyloop.contract.config import AblationId
from proxyloop.contract.llm import LLMCallRecord, ToolRequest
from proxyloop.contract.views import FastView
from proxyloop.models.repair import (
    MAX_RESAMPLES,
    DecisionPoint,
    TeacherRepair,
    decision_point,
    substitutes,
)

GOLDENS = goldens()
# The cp goldens c02, c05 and c07 answer the rep's offer; u05 shows an approval
# card. Guidance, a hold wait, a session start and Slow messages are not points.
EXPECTED: dict[str, DecisionPoint | None] = {
    "c01_empty": None,
    "c02_rep_offer": "offer",
    "c03_guidance": None,
    "c04_hold_wait": None,
    "c05_readback_confirmed": "offer",
    "c06_over_budget": None,
    "c07_over_budget_actions": "offer",
    "u01_empty": None,
    "u02_user_msg": None,
    "u03_ask_user": None,
    "u04_tell_user": None,
    "u05_approval_card": "approval",
    "u06_over_budget": None,
}
CP_OFFER = view("cp", "I can do $65 a month for 12 months.")
VALID = "Could you read back every term of that offer?\n@hold offer"
INVALID = "Sure, I accept.\n@hold whenever"  # bad_hold_reason


def test_the_goldens_are_all_named() -> None:
    assert set(EXPECTED) == set(GOLDENS)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_detector_on_goldens(name: str) -> None:
    assert decision_point(GOLDENS[name][0]) == EXPECTED[name]


@pytest.mark.parametrize(
    ("v", "point"),
    [
        (view("cp", "Can you give me the PIN on the account?"), "fact_request"),
        (view("cp", "Can you verify the name on the account?"), "fact_request"),
        (view("cp", "Shall I go ahead and sign you up?"), "offer"),
        (view("cp", "This deal is today only."), "offer"),
        (view("cp", "Thanks for holding, how can I help?"), None),
        (view("cp", "The PIN, please.", trigger="hold_wait"), None),
        (view("user", "Stop, don't accept anything."), "stop"),
        (view("user", "Actually, my last name is Reyes-Cole."), "correction"),
        (view("user", "Can you lower my bill?"), None),
    ],
)
def test_detector_units(v: FastView, point: DecisionPoint | None) -> None:
    assert decision_point(v) == point


def test_only_a_repaired_lane_substitutes() -> None:
    cp, user = AblationId.TEACHER_REPAIR_CP, AblationId.TEACHER_REPAIR_USER
    assert substitutes(CP_OFFER, {cp}) == "offer"
    assert substitutes(CP_OFFER, {user}) is None
    assert substitutes(CP_OFFER, ()) is None


def _repair(
    responses: list[str], records: list[LLMCallRecord]
) -> tuple[TeacherRepair, ScriptedLLM]:
    teacher = ScriptedLLM(fake_ref("teacher"), responses, on_record=records.append)
    return TeacherRepair(teacher), teacher


def test_conformance_without_resampling() -> None:
    records: list[LLMCallRecord] = []
    repair, teacher = _repair([VALID], records)
    record = asyncio.run(assert_text_conformance(repair, request(CP_OFFER)))
    assert repair.ref == teacher.ref and record.model_ref == teacher.ref
    assert (teacher.calls, repair.resamples) == (1, {"fast_cp:0": 0})
    assert records == [record]


def test_invalid_output_is_resampled_by_the_student_parser() -> None:
    records: list[LLMCallRecord] = []
    repair, teacher = _repair([INVALID, VALID], records)
    record = asyncio.run(assert_text_conformance(repair, request(CP_OFFER)))
    assert (teacher.calls, repair.resamples) == (2, {"fast_cp:0": 1})
    assert records[-1] == record and len(records) == 2  # every attempt recorded


def test_after_two_resamples_the_last_output_is_delivered_unrepaired() -> None:
    records: list[LLMCallRecord] = []
    repair, teacher = _repair([INVALID] * 3, records)
    req = request(CP_OFFER)
    items = asyncio.run(_collect(repair, req))
    assert items[0] == INVALID  # delivered as it is; its issue is counted later
    assert teacher.calls == MAX_RESAMPLES + 1 == len(records)
    assert repair.resamples == {req.call_id: MAX_RESAMPLES}


def test_the_lane_is_the_rendered_profile_s() -> None:
    """A cp directive is invalid on the user lane: resampled there."""

    records: list[LLMCallRecord] = []
    repair, teacher = _repair(["Hello.\n@hold offer", "Hello."], records)
    asyncio.run(assert_text_conformance(repair, request(view("user", "Hi"))))
    assert teacher.calls == 2


def test_a_dead_teacher_aborts_loudly() -> None:
    teacher = ScriptedLLM(fake_ref("teacher"), [], dead=True)
    asyncio.run(assert_unavailable(TeacherRepair(teacher), request(CP_OFFER)))


def test_the_teacher_takes_only_rendered_messages() -> None:
    repair, _ = _repair([VALID], [])
    prompt = request(CP_OFFER).model_copy(update={"messages": (), "prompt": "P"})
    with pytest.raises(ValueError, match="render_messages"):
        asyncio.run(_collect(repair, prompt))
    tool = ToolRequest.model_validate(
        {
            "call_id": "t",
            "role": "teacher",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"name": "x", "description": "", "parameters": {}}],
            "max_tokens": 8,
        }
    )
    with pytest.raises(TypeError):
        asyncio.run(repair.chat_tools(tool))


async def _collect(repair: TeacherRepair, req: object) -> list[object]:
    return [item async for item in repair.stream_text(req)]  # type: ignore[arg-type]
