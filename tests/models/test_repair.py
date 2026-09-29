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
from proxyloop.kernel import lanes
from proxyloop.models.repair import (
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
    "c08_v2_empty": None,  # call_connected: not rep_spoke
    "c09_v2_hold_for_fact": None,  # guidance: not rep_spoke
    "c10_v3_empty": None,  # call_connected: not rep_spoke
    "c11_v3_hold_for_fact": None,  # guidance: not rep_spoke
    "c12_v4_empty": None,  # call_connected: not rep_spoke
    "c13_v4_hold_for_decision": None,  # guidance: not rep_spoke
    "c14_v4_persisted_moves": "offer",
    "c15_v4_over_budget": None,  # hold_wait
    "u07_v2_empty": None,
    "u08_v2_user_msg": None,
    "u09_v2_over_budget": "approval",
    "u01_empty": None,
    "u02_user_msg": None,
    "u03_ask_user": None,
    "u04_tell_user": None,
    "u05_approval_card": "approval",
    "u06_over_budget": None,
}
CP_OFFER = view("cp", "I can do $65 a month for 12 months.")
OPEN = {"offer_ref": "o1", "revision": 1}
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
        (view("cp", "Should I process that for you?"), "offer"),
        (view("cp", "I can put it through right away."), "offer"),
        (view("cp", "Would you like the new plan?"), "offer"),
        (view("cp", "Do you want me to switch the plan?"), "offer"),
        (view("cp", "Shall I make the change?"), "offer"),
        (view("cp", "We can go ahead with that."), "offer"),
        (view("cp", "Is there anything else?", offers=(OPEN,)), "offer"),
        (view("cp", "Is there anything else?"), None),
        (view("cp", "Your current bill is $120."), None),
        (view("cp", "It's $65 a month for 12 months."), "offer"),
        (view("cp", "Thanks for holding, how can I help?"), None),
        (view("cp", "The PIN, please.", trigger="hold_wait"), None),
        (view("user", "Stop, don't accept anything."), "stop"),
        (view("user", "Wait, no, I don't want that."), "stop"),
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
    responses: list[str], records: list[LLMCallRecord], max_resamples: int = 2
) -> tuple[TeacherRepair, ScriptedLLM]:
    teacher = ScriptedLLM(fake_ref("teacher"), responses, on_record=records.append)
    return TeacherRepair(teacher, max_resamples=max_resamples), teacher


@pytest.mark.parametrize("limit", [0, 2])
def test_conformance_without_resampling(limit: int) -> None:
    records: list[LLMCallRecord] = []
    repair, teacher = _repair([VALID], records, limit)
    record = asyncio.run(assert_text_conformance(repair, request(CP_OFFER)))
    assert repair.ref == teacher.ref and record.model_ref == teacher.ref
    assert (teacher.calls, repair.resamples) == (1, {"fast_cp:0": 0})
    assert records == [record]


def test_evaluation_limit_0_delivers_invalid_output_as_the_student_s() -> None:
    """E2: T and R get no retry C2 does not get; the issue is counted later."""

    records: list[LLMCallRecord] = []
    repair, teacher = _repair([INVALID, VALID], records, max_resamples=0)
    req = request(CP_OFFER)
    items = asyncio.run(_collect(repair, req))
    assert "".join(i for i in items if isinstance(i, str)) == INVALID
    assert (teacher.calls, repair.resamples, len(records)) == (1, {req.call_id: 0}, 1)


def test_the_limit_has_no_default_and_is_not_negative() -> None:
    teacher = ScriptedLLM(fake_ref("teacher"), [])
    with pytest.raises(TypeError):
        TeacherRepair(teacher)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="max_resamples"):
        TeacherRepair(teacher, max_resamples=-1)


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
    assert teacher.calls == 3 == len(records)
    assert repair.resamples == {req.call_id: 2}


def test_the_lane_is_the_rendered_profile_s() -> None:
    """A cp directive is invalid on the user lane: resampled there."""

    records: list[LLMCallRecord] = []
    repair, teacher = _repair(["Hello.\n@hold offer", "Hello."], records)
    asyncio.run(assert_text_conformance(repair, request(view("user", "Hi"))))
    assert teacher.calls == 2


SPEECH_AFTER_PAUSE = "@hold decision\nSure, one moment."


def test_speech_after_a_pause_is_resampled_under_the_live_cp_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The request carries no profile (every cp profile renders the same
    messages), so the grammar is the live lane profile's: pl_cp_v3 (ADR-0017)."""

    assert lanes.PROFILE["cp"] == "pl_cp_v3"
    repair, teacher = _repair([SPEECH_AFTER_PAUSE, VALID], [])
    asyncio.run(assert_text_conformance(repair, request(CP_OFFER)))
    assert (teacher.calls, repair.resamples) == (2, {"fast_cp:0": 1})
    monkeypatch.setitem(lanes.PROFILE, "cp", "pl_cp_v2")  # the frozen grammar
    repair, teacher = _repair([SPEECH_AFTER_PAUSE, VALID], [])
    asyncio.run(assert_text_conformance(repair, request(CP_OFFER)))
    assert (teacher.calls, repair.resamples) == (1, {"fast_cp:0": 0})


def test_a_dead_teacher_aborts_loudly() -> None:
    teacher = ScriptedLLM(fake_ref("teacher"), [], dead=True)
    for limit in (0, 2):
        repair = TeacherRepair(teacher, max_resamples=limit)
        asyncio.run(assert_unavailable(repair, request(CP_OFFER)))


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
