"""Shared model-facing Fast output and deterministic canonical compiler."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from proxyloop_contracts import (
    DialogueAct,
    FastModelView,
    FastTurnDecision,
)
from proxyloop_contracts.contracts import CompletionClaim, FactUpdate, ReasonerRequest
from pydantic import BaseModel, ConfigDict, Field


class FastModelOutput(BaseModel):
    """Semantic fields a Fast model may propose without infrastructure IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    dialogue_act: DialogueAct
    fact_updates: tuple[FactUpdate, ...] = Field(max_length=16)
    reasoner_request: ReasonerRequest
    completion_claim: CompletionClaim
    response_text: str = Field(min_length=1, max_length=4000)
    action_intent: None


def compile_fast_output(
    view: FastModelView,
    output: FastModelOutput,
) -> FastTurnDecision:
    """Bind one strict semantic proposal to trusted current view metadata."""

    strategy = view.strategy
    if strategy is None:
        raise ValueError("Fast output requires a current Strategy Packet")
    created_at = (
        view.recent_events[-1].occurred_at
        if view.recent_events
        else strategy.created_at
    )
    canonical = json.dumps(
        output.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    decision_id = _stable_uuid4(
        f"fast:{view.case_id}:{view.pins.event_cursor}:{canonical}"
    )
    return FastTurnDecision(
        contract_type="fast_turn_decision",
        schema_version="1.0",
        decision_id=decision_id,
        case_id=view.case_id,
        case_revision=view.pins.case_revision,
        strategy_id=strategy.strategy_id,
        strategy_revision=strategy.revision,
        created_at=created_at,
        dialogue_act=output.dialogue_act,
        fact_updates=output.fact_updates,
        reasoner_request=output.reasoner_request,
        completion_claim=output.completion_claim,
        response_text=output.response_text,
        action_intent=None,
    )


def _stable_uuid4(value: str) -> UUID:
    raw = bytearray(hashlib.sha256(value.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


__all__ = ["FastModelOutput", "compile_fast_output"]
