"""Validator rules of the contract types (messages, LLM records, config, state)."""

from __future__ import annotations

from typing import Any

import pytest
from tests.contract.samples import GEMINI, QWEN, call_record, session_config

from proxyloop.contract.config import AblationId, WorldModels, config_hash
from proxyloop.contract.llm import (
    AdapterKind,
    ChatMessage,
    ModelRef,
    TextRequest,
    ToolRequest,
    ToolSpec,
    request_content,
)
from proxyloop.contract.messages import FastToSlow, Guide, SlowToFast
from proxyloop.contract.state import ApprovalCard, Mandate, ReadbackBinding


def _f2s(**update: Any) -> dict[str, Any]:
    base = {
        "msg_id": "f1",
        "lane": "user",
        "gen_id": "g1",
        "utt_ref": None,
        "type": "NOTE",
    }
    return base | update


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"type": "REVOKE", "lane": "cp"}, "user-lane relay"),
        ({"type": "HOLD"}, "cp-lane relay"),
        ({"type": "NOTE", "correction": True}, "correction"),
        ({"text": "x" * 241}, "240"),
    ],
)
def test_fast_to_slow_rules(update: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        FastToSlow.model_validate(_f2s(**update))


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"lane": "cp", "type": "ASK_USER", "text": "q"}, "user-lane message"),
        (
            {"lane": "user", "type": "GUIDE", "guide": {"move": "ask_discount"}},
            "cp-lane",
        ),
        ({"lane": "cp", "type": "END", "text": "bye"}, "never receives free text"),
        ({"lane": "user", "type": "TELL_USER"}, "needs text"),
        ({"lane": "cp", "type": "GUIDE"}, "guide is set iff"),
        ({"lane": "user", "type": "APPROVAL_NOTICE"}, "approval_id is set iff"),
    ],
)
def test_slow_to_fast_rules(body: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SlowToFast.model_validate({"msg_id": "s1"} | body)


@pytest.mark.parametrize("slot", ["fact:Bad", "offer:", "free text", "fact:a b"])
def test_guide_slots_are_references_not_text(slot: str) -> None:
    with pytest.raises(ValueError):
        Guide.model_validate({"move": "ask_discount", "slots": [slot]})


def test_model_ref_endpoint_rules() -> None:
    with pytest.raises(ValueError, match="needs an endpoint"):
        ModelRef(kind=AdapterKind.REAL_HTTP, endpoint=None, model_id="m")
    with pytest.raises(ValueError, match="in process"):
        ModelRef(kind=AdapterKind.BASELINE, endpoint="vllm", model_id="fsm")
    with pytest.raises(ValueError):
        ModelRef.model_validate(
            {"kind": "real_http", "endpoint": "openai", "model_id": "m"}
        )
    assert (
        ModelRef(kind=AdapterKind.BASELINE, endpoint=None, model_id="fsm").endpoint
        is None
    )


def test_world_models_pin_reasoning_and_have_no_default() -> None:
    with pytest.raises(ValueError, match=r"world\.ear must pin"):
        WorldModels(ear=QWEN, mouth=GEMINI, simuser=GEMINI)
    with pytest.raises(ValueError, match="world"):
        session_config(world=None)


def test_config_hash_ignores_ablation_order() -> None:
    a = session_config(
        ablations=[AblationId.SUPPRESS_RELAY_CP, AblationId.SUPPRESS_RELAY_USER]
    )
    b = session_config(
        ablations=[AblationId.SUPPRESS_RELAY_USER, AblationId.SUPPRESS_RELAY_CP]
    )
    assert config_hash(a) == config_hash(b) != config_hash(session_config())
    assert len(AblationId) == 6


def test_call_record_consistency() -> None:
    assert call_record().requested_model == "Qwen3.5-9B"
    with pytest.raises(ValueError, match="requested_model"):
        call_record(requested_model="Qwen3.5-4B")
    with pytest.raises(ValueError, match="adapter_kind"):
        call_record(adapter_kind=AdapterKind.TEST_FAKE)
    with pytest.raises(ValueError, match="t_first_token"):
        call_record(t_first_token=50)


def test_requests() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        TextRequest(call_id="k", role="fast_cp", max_tokens=5, temperature=0.0)
    msgs = (ChatMessage(role="user", content="hi"),)
    tool = ToolSpec(name="classify", description="d", parameters={"type": "object"})
    with pytest.raises(ValueError, match="tool_choice"):
        ToolRequest(
            call_id="k",
            role="ear",
            messages=msgs,
            tools=(tool,),
            tool_choice="x",
            max_tokens=5,
        )
    forced = ToolRequest(
        call_id="k",
        role="ear",
        messages=msgs,
        tools=(tool,),
        tool_choice="classify",
        max_tokens=5,
    )
    assert '"tool_choice":"classify"' in request_content(forced)
    prompt = TextRequest(
        call_id="k", role="fast_cp", prompt="P", max_tokens=5, temperature=0.3
    )
    assert request_content(prompt) == "P"


def test_approval_card_binding_must_match_the_card() -> None:
    binding = ReadbackBinding(
        offer_ref="o1",
        revision=2,
        account_ref="a",
        principal_ref="p",
        purpose="x",
        authority_epoch=1,
    )
    with pytest.raises(ValueError, match="binding"):
        ApprovalCard(
            approval_id="a1",
            offer_ref="o1",
            revision=1,
            terms_hash="t",
            readback_text="r",
            authority_epoch=1,
            expires_ms=5,
            binding=binding,
        )


def test_live_mode_refuses_fakes_and_replays_and_baseline_outside_fast() -> None:
    fake = QWEN.model_copy(update={"kind": AdapterKind.TEST_FAKE})
    replay = QWEN.model_copy(update={"kind": AdapterKind.RECORDED_REPLAY})
    fsm = ModelRef(kind=AdapterKind.BASELINE, endpoint=None, model_id="fsm")
    assert session_config(fast_cp=fsm).live  # baseline is a Fast condition
    for update in ({"fast_user": fake}, {"slow": replay}, {"slow": fsm}):
        with pytest.raises(ValueError, match="live mode refuses"):
            session_config(**update)
    assert not session_config(live=False, fast_user=fake).live


def test_teacher_iff_teacher_repair() -> None:
    repair = [AblationId.TEACHER_REPAIR_CP]
    with pytest.raises(ValueError, match="teacher is set iff"):
        session_config(ablations=repair)
    with pytest.raises(ValueError, match="teacher is set iff"):
        session_config(teacher=GEMINI)
    cfg = session_config(ablations=repair, teacher=GEMINI)
    assert config_hash(cfg) != config_hash(
        session_config(ablations=repair, teacher=QWEN)
    )


def test_decided_mandate_names_who_decided() -> None:
    body = {"mandate_id": "m", "mandate_hash": "h", "epoch": 1}
    with pytest.raises(ValueError, match="needs decided_by"):
        Mandate.model_validate(body | {"status": "granted"})
    assert Mandate.model_validate(body | {"status": "granted", "decided_by": "ui"})
