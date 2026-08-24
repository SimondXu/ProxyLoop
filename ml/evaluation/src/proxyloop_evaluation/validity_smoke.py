"""Bounded Phase 03A1-V prompt/input parity experiment.

This module never mutates the frozen r2/r3/r4 artifacts. It prepares six
derived in-memory fixtures whose latest public Provider event exposes the same
allowlisted state supplied to the scripted oracle, and it makes the existing
dynamic output semantics explicit for the diagnostic prompts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Final

from proxyloop_contracts import (
    CaseContextSnapshot,
    ConstraintClassification,
    FastModelView,
    SlowWorkRequest,
)

from .fresh_fixtures import (
    FreshPhase03A1ModelFixture,
    build_fresh_safe_observation,
)
from .openai_frontier import (
    FrontierCallStatus,
    FrontierResponseValidationError,
    OpenAIFrontierAdapter,
    PromptBundle,
    _bundle,
    _parsed_output,
    _raw_message_content,
    _structured_output_text,
    _validate_slow_binding,
    build_slow_prompt,
)
from .qwen_mlx import QwenMLXAdapter, QwenPrompt
from .slow_output import SlowModelOutput, compile_slow_output

SMOKE_CAPABILITIES: Final[tuple[str, ...]] = (
    "accept_offer",
    "decline",
    "request_clarification",
    "request_replan",
    "escalate",
    "refuse_disclosure",
)

_PUBLIC_STATE_MARKER = "\nPUBLIC_PROVIDER_STATE_JSON:"


def select_validity_smoke_fixtures(
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> tuple[FreshPhase03A1ModelFixture, ...]:
    """Select one stable r2 fixture for each bounded capability."""

    selected: list[FreshPhase03A1ModelFixture] = []
    for capability in SMOKE_CAPABILITIES:
        reference = f"simulator.{capability}"
        match = next(
            (
                fixture
                for fixture in sorted(fixtures, key=lambda item: item.episode_id)
                if fixture.reference_capability_id == reference
            ),
            None,
        )
        if match is None:
            raise ValueError(f"missing validity-smoke fixture for {capability}")
        selected.append(match)
    return tuple(selected)


def with_public_provider_state(
    fixture: FreshPhase03A1ModelFixture,
) -> FreshPhase03A1ModelFixture:
    """Derive a prompt-only snapshot with the oracle's public state, not labels."""

    observation = build_fresh_safe_observation(
        fixture.scenario, fixture.scenario.provider_turn
    )
    public_state = {
        "approval_current": observation.approval_current,
        "confirmation_evidence_available": (
            observation.confirmation_evidence_available
        ),
        "needs_clarification": observation.needs_clarification,
        "requested_disclosures": list(observation.requested_disclosures),
        "transfer_available": observation.transfer_available,
    }
    events = fixture.snapshot.visible_events
    if not events:
        raise ValueError("validity-smoke fixture requires a visible Provider event")
    latest = events[-1]
    content = latest.content.split(_PUBLIC_STATE_MARKER, maxsplit=1)[0]
    prepared_event = latest.model_copy(
        update={
            "content": content
            + _PUBLIC_STATE_MARKER
            + json.dumps(
                public_state,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        }
    )
    prepared_snapshot = CaseContextSnapshot.model_validate(
        fixture.snapshot.model_copy(
            update={"visible_events": (*events[:-1], prepared_event)}
        ).model_dump(mode="python")
    )
    return replace(fixture, snapshot=prepared_snapshot)


def build_validity_slow_prompt(request: SlowWorkRequest) -> PromptBundle:
    """Build the r4 prompt plus explicit semantics for the isolated smoke."""

    baseline = build_slow_prompt(request)
    soft_count = sum(
        constraint.classification is ConstraintClassification.SOFT
        for constraint in request.view.constraints
    )
    allowed = tuple(request.view.delegated_authority.allowed_disclosures)
    if soft_count == 0:
        preference_rule = "there are zero SOFT constraints, return []"
    else:
        preference_rule = f"valid positions are 0 through {soft_count - 1}"
    allowed_text = ", ".join(allowed) if allowed else "none"
    baseline_system = str(baseline.messages[0]["content"])
    system = (
        baseline_system + " ranked_preference_positions indexes only the filtered SOFT "
        "constraints, never HARD constraints; "
        + preference_rule
        + ". For allowed_disclosures and approval_required_disclosures, copy "
        "exact identifier tokens from delegated_authority.allowed_disclosures; "
        f"the only allowed tokens for this request are [{allowed_text}]. Do not "
        "write descriptions or values in those fields. Interpret the public "
        "Provider state with this precedence: needs_clarification -> "
        "request_clarification; a requested disclosure outside the allowed set "
        "-> refuse_disclosure; approval_current=false -> request_replan; "
        "transfer_available=true -> escalate; "
        "confirmation_evidence_available=false -> request_replan; otherwise "
        "accept a compliant visible offer or decline a noncompliant offer."
    )
    messages: tuple[dict[str, object], ...] = (
        {"role": "system", "content": system},
        *baseline.messages[1:],
    )
    return _bundle(
        messages,
        baseline.output_schema,
        baseline.output_model,
    )


class ValiditySmokeFrontierAdapter(OpenAIFrontierAdapter):
    """Terra adapter that changes only the diagnostic Slow prompt."""

    def build_slow_prompt(self, request: SlowWorkRequest) -> PromptBundle:
        return build_validity_slow_prompt(request)

    def reason(self, request: SlowWorkRequest):  # type: ignore[no-untyped-def]
        if not isinstance(request, SlowWorkRequest):
            raise TypeError("Slow adapter accepts only SlowWorkRequest")
        self._last_structured_output = None
        bundle = self.build_slow_prompt(request)
        response, record = self._invoke(bundle)
        raw = _raw_message_content(response)
        if raw is not None:
            self._last_structured_output = raw[:16384]
        try:
            parsed = _parsed_output(response, SlowModelOutput)
            self._last_structured_output = _structured_output_text(parsed)
        except Exception as exc:
            self._capture_error(exc)
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error=str(exc),
            )
            raise FrontierResponseValidationError(
                f"frontier Slow response failed output-schema validation: {exc}",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                validation_stage="schema",
            ) from exc
        try:
            result = compile_slow_output(request, parsed)
        except Exception as exc:
            self._capture_error(exc)
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error=str(exc),
            )
            raise FrontierResponseValidationError(
                f"frontier Slow response failed semantic validation: {exc}",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                validation_stage="semantic",
            ) from exc
        try:
            _validate_slow_binding(request, result)
        except Exception as exc:
            self._capture_error(exc)
            self._finish(
                record,
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                error=str(exc),
            )
            raise FrontierResponseValidationError(
                f"frontier Slow response failed canonical binding: {exc}",
                status=FrontierCallStatus.FAILED_INVALID_RESPONSE,
                validation_stage="canonical",
            ) from exc
        self._finish(record, status=FrontierCallStatus.SUCCEEDED)
        return result


class ValiditySmokeQwenAdapter(QwenMLXAdapter):
    """Qwen adapter with one explicit non-completion rule for the smoke."""

    def build_prompt(self, view: FastModelView) -> QwenPrompt:
        baseline = super().build_prompt(view)
        system = (
            baseline.system + " Set completion_claim.status to not_done and "
            "completion_claim.evidence_message_ids to [] unless the typed view "
            "contains verifier-issued completion Evidence and a current "
            "CompletionDecision. This validity smoke contains neither."
        )
        fingerprint_payload = json.dumps(
            {"system": system, "user": baseline.user},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()
        return QwenPrompt(
            system=system,
            user=baseline.user,
            fingerprint=fingerprint,
        )


__all__ = [
    "SMOKE_CAPABILITIES",
    "ValiditySmokeFrontierAdapter",
    "ValiditySmokeQwenAdapter",
    "build_validity_slow_prompt",
    "select_validity_smoke_fixtures",
    "with_public_provider_state",
]
