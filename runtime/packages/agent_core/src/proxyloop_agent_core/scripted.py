"""Deterministic typed adapters used to validate the Phase 03A1 harness."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Final
from uuid import UUID

from proxyloop_contracts import (
    ConstraintClassification,
    DialogueAct,
    EventActor,
    EvidenceType,
    FastModelView,
    FastTurnDecision,
    SlowWorkRequest,
    SlowWorkResult,
    StrategyPacket,
    strategy_basis_binding,
)
from proxyloop_contracts.contracts import (
    CompletionClaim,
    EvidenceRequirement,
    ReasonerRequest,
)

from .interfaces import BOUNDED_FAST_STATUS_TEXT, FastAdapterResult, ModelIdentity


def _scripted_identity(model: str) -> ModelIdentity:
    """Deterministic, promptless, and zero-token (no usage is reported)."""

    return ModelIdentity(
        provider="scripted",
        model=model,
        model_version="deterministic-v1",
        adapter_version="scripted-v1",
        prompt_version="no-prompt",
    )


class ScriptedFastAdapter:
    """Return one safe typed dialogue decision under a current strategy."""

    model_identity = _scripted_identity("scripted_fast")

    def decide(self, view: FastModelView) -> FastAdapterResult:
        strategy = view.strategy
        if strategy is None:
            raise ValueError("scripted Fast requires a current Strategy Packet")
        created_at = (
            view.recent_events[-1].occurred_at
            if view.recent_events
            else strategy.created_at
        )
        decision = FastTurnDecision(
            contract_type="fast_turn_decision",
            schema_version="1.0",
            decision_id=_stable_uuid4(f"fast:{view.case_id}:{view.pins.event_cursor}"),
            case_id=view.case_id,
            case_revision=view.pins.case_revision,
            strategy_id=strategy.strategy_id,
            strategy_revision=strategy.revision,
            created_at=created_at,
            dialogue_act=DialogueAct.CLARIFY,
            fact_updates=(),
            reasoner_request=ReasonerRequest(needed=False, reason_code="none"),
            completion_claim=CompletionClaim(
                status="not_done", evidence_message_ids=()
            ),
            response_text=BOUNDED_FAST_STATUS_TEXT,
            action_intent=None,
        )
        return FastAdapterResult(pins=view.pins, decision=decision)


SCRIPTED_DIALOGUE_LINES: Final[tuple[str, ...]] = (
    "Thanks. I'm reviewing the fictional offer against your constraints now.",
    "Noted. I'll keep your required features and forbidden changes in view.",
    "Understood. Nothing changes without your explicit approval of exact terms.",
    "Got it. I'll keep checking the fictional offer against what you asked for.",
)
SCRIPTED_PENDING_SLOW_LINE: Final = "I'm refreshing the plan before proposing anything."


class ScriptedDialogueFastAdapter:
    """Select one fixed dialogue line per turn; nothing is interpolated.

    No snapshot text or number is spliced into a line, so every line passes
    the disclosure gate by construction. A turn not triggered by the Consumer
    gets ``BOUNDED_FAST_STATUS_TEXT``, the channel path's constant. The output
    is a pure function of the view, so a retried command gets the same line.
    """

    model_identity = ModelIdentity(
        provider="scripted",
        model="scripted_dialogue_fast",
        model_version="dialogue-v1",
        adapter_version="scripted-v1",
        prompt_version="no-prompt",
    )

    def decide(self, view: FastModelView) -> FastAdapterResult:
        strategy = view.strategy
        if strategy is None:
            raise ValueError("scripted Fast requires a current Strategy Packet")
        latest = view.recent_events[-1] if view.recent_events else None
        if latest is None or latest.actor is not EventActor.CONSUMER:
            text = BOUNDED_FAST_STATUS_TEXT
        elif view.pending_slow_work:
            text = SCRIPTED_PENDING_SLOW_LINE
        else:
            consumer_turns = sum(
                event.actor is EventActor.CONSUMER for event in view.recent_events
            )
            text = SCRIPTED_DIALOGUE_LINES[
                min(consumer_turns, len(SCRIPTED_DIALOGUE_LINES)) - 1
            ]
        decision = FastTurnDecision(
            contract_type="fast_turn_decision",
            schema_version="1.0",
            decision_id=_stable_uuid4(
                f"scripted-dialogue-fast:{view.case_id}:{view.pins.event_cursor}"
            ),
            case_id=view.case_id,
            case_revision=view.pins.case_revision,
            strategy_id=strategy.strategy_id,
            strategy_revision=strategy.revision,
            created_at=latest.occurred_at
            if latest is not None
            else strategy.created_at,
            dialogue_act=DialogueAct.CLARIFY,
            fact_updates=(),
            reasoner_request=ReasonerRequest(needed=False, reason_code="none"),
            completion_claim=CompletionClaim(
                status="not_done", evidence_message_ids=()
            ),
            response_text=text,
            action_intent=None,
        )
        return FastAdapterResult(pins=view.pins, decision=decision)


class ScriptedSlowAdapter:
    """Produce a deterministic reference strategy, never authorization."""

    model_identity = _scripted_identity("scripted_slow")

    def reason(self, request: SlowWorkRequest) -> SlowWorkResult:
        view = request.view
        strategy_id = _stable_uuid4(
            f"strategy:{request.case_id}:{request.pins.planning_basis_fingerprint}"
        )
        prior = view.strategy
        strategy = StrategyPacket(
            contract_type="strategy_packet",
            **strategy_basis_binding(request.planning_basis),
            # A refresh of the same strategy must be distinguishable by revision.
            revision=(
                prior.revision + 1
                if prior is not None and prior.strategy_id == strategy_id
                else 1
            ),
            strategy_id=strategy_id,
            case_id=request.case_id,
            case_revision=request.pins.case_revision,
            fact_ledger_revision=request.pins.fact_ledger_revision,
            created_at=request.created_at,
            expires_at=request.created_at + timedelta(minutes=30),
            primary_objective=view.goal.desired_outcome,
            current_subgoal="Handle the latest fictional Provider turn safely.",
            hard_constraint_ids=tuple(
                constraint.constraint_id
                for constraint in view.constraints
                if constraint.classification is ConstraintClassification.HARD
            ),
            ranked_preference_ids=tuple(
                constraint.constraint_id
                for constraint in sorted(
                    (
                        item
                        for item in view.constraints
                        if item.classification is ConstraintClassification.SOFT
                    ),
                    key=lambda item: item.priority or 0,
                )
            ),
            allowed_disclosures=tuple(
                sorted(view.delegated_authority.allowed_disclosures)
            ),
            approval_required_disclosures=(),
            concession_ladder=("Preserve every hard Consumer constraint.",),
            fallback_outcomes=("Return control to the Consumer safely.",),
            required_completion_evidence=(
                EvidenceRequirement(
                    evidence_type=EvidenceType.CONFIRMATION,
                    description="A fictional Provider confirmation is required.",
                ),
            ),
            escalation_conditions=("A material offer or authority input changes.",),
            replan_conditions=("The planning basis is no longer current.",),
        )
        return SlowWorkResult(
            contract_type="slow_work_result",
            schema_version="1.0",
            revision=1,
            result_id=_stable_uuid4(f"slow-result:{request.request_id}"),
            request_id=request.request_id,
            case_id=request.case_id,
            pins=request.pins,
            planning_basis=request.planning_basis,
            strategy_proposal=strategy,
            capability_proposals=(),
            action_proposals=(),
            created_at=request.created_at,
        )


def _stable_uuid4(value: str) -> UUID:
    raw = bytearray(hashlib.sha256(value.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


__all__ = [
    "SCRIPTED_DIALOGUE_LINES",
    "SCRIPTED_PENDING_SLOW_LINE",
    "ScriptedDialogueFastAdapter",
    "ScriptedFastAdapter",
    "ScriptedSlowAdapter",
]
