"""Phase 03C Stage 1b verifier filters F1-F5 for raw teacher samples.

Each filter takes one raw teacher completion (or the strict output parsed from
it) and returns a reason code ``"<filter>:<detail>"`` or ``None``.
``apply_filters`` runs them in contract order and stops at the first failure.
The filters are deterministic and call no model; F3 replays the decision's
dialogue act through the frozen ``MultiTurnProviderEnvironment`` verifier.
The F5 second-family adapter is injected as a callable so no Gemini client or
price is asserted here.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from proxyloop_contracts import FastModelView
from proxyloop_provider_simulator.multi_turn import MultiTurnProviderEnvironment
from proxyloop_provider_simulator.scenarios import BenchmarkScenario
from pydantic import ValidationError

from proxyloop_evaluation.fast_output import FastModelOutput, compile_fast_output
from proxyloop_evaluation.phase03b_experiment import (
    detect_disallowed_disclosure,
    detect_false_completion,
    detect_pii,
    detect_unsupported_response_facts,
)
from proxyloop_evaluation.phase03b_readiness import (
    TARGET_DIALOGUE_ACTS,
    proposed_fast_target,
)
from proxyloop_evaluation.phase03c_experiment import analyze_raw_output
from proxyloop_evaluation.phase03c_prompt_set import (
    PromptSetRow,
    render_prompt_view,
    resolve_row,
)
from proxyloop_evaluation.phase03c_scenarios import FastPosition

STRICT_JSON_SCHEMA: Final = "strict_json_schema"
TARGET_AGREEMENT: Final = "target_agreement"
VERIFIER_REPLAY: Final = "verifier_replay"
DETECTORS: Final = "detectors"
SECOND_FAMILY_AGREEMENT: Final = "second_family_agreement"
FILTER_ORDER: Final = (
    STRICT_JSON_SCHEMA,
    TARGET_AGREEMENT,
    VERIFIER_REPLAY,
    DETECTORS,
    SECOND_FAMILY_AGREEMENT,
)
_REPLAY_IDEMPOTENCY_KEY: Final = "teacher-replay:1"
_WHITESPACE: Final = re.compile(r"\s+")

AgreementFilter = Callable[[FastModelView], bool]

# Inverse of the oracle-derived target table: (dialogue_act, needed) names
# exactly one oracle action, which is what the environment verifier accepts.
_ACT_TO_ORACLE_ACTION: Final[dict[tuple[str, bool], str]] = {
    (act, needed): action for action, (act, needed, _) in TARGET_DIALOGUE_ACTS.items()
}
if len(_ACT_TO_ORACLE_ACTION) != len(TARGET_DIALOGUE_ACTS):
    raise RuntimeError("TARGET_DIALOGUE_ACTS is not invertible")


@dataclass(frozen=True, slots=True)
class CandidateContext:
    """Everything the filters need about one prompt: never any teacher text."""

    row: PromptSetRow
    scenario: BenchmarkScenario
    position: FastPosition
    view: FastModelView


def build_candidate_context(row: PromptSetRow) -> CandidateContext:
    scenario, position = resolve_row(row)
    return CandidateContext(
        row=row,
        scenario=scenario,
        position=position,
        view=render_prompt_view(scenario, position),
    )


@dataclass(frozen=True, slots=True)
class FilterResult:
    """First failing reason (or none), the strict output, and the F5 flag."""

    reason: str | None
    output: FastModelOutput | None
    second_family_act_agrees: bool | None

    @property
    def filter_name(self) -> str | None:
        return self.reason.split(":", 1)[0] if self.reason is not None else None

    @property
    def accepted(self) -> bool:
        return self.reason is None


def filter_strict_json_schema(content: str) -> str | None:
    """F1: strict JSON (no fence, duplicate key, or thinking leak) and schema."""

    signals = analyze_raw_output(content)
    if signals.thinking_leak:
        return f"{STRICT_JSON_SCHEMA}:thinking_leak"
    if signals.json_parse_mode not in (None, "strict"):
        return f"{STRICT_JSON_SCHEMA}:{signals.json_parse_mode}"
    if signals.duplicate_key:
        return f"{STRICT_JSON_SCHEMA}:duplicate_key"
    if not signals.json_valid_strict:
        return f"{STRICT_JSON_SCHEMA}:invalid_json"
    try:
        FastModelOutput.model_validate_json(content)
    except ValidationError:
        return f"{STRICT_JSON_SCHEMA}:schema"
    return None


def parse_strict_output(content: str) -> FastModelOutput | None:
    """The strict output when F1 passes, else ``None``; no tolerant repair."""

    if filter_strict_json_schema(content) is not None:
        return None
    return FastModelOutput.model_validate_json(content)


def _target(oracle_action: str) -> tuple[str, dict[str, object]]:
    target = proposed_fast_target(oracle_action)
    reasoner = target["reasoner_request"]
    if not isinstance(reasoner, dict):
        raise TypeError("proposed_fast_target reasoner_request must be a mapping")
    return str(target["dialogue_act"]), reasoner


def act_needed_agrees(output: FastModelOutput, oracle_action: str) -> bool:
    """The contract's literal F2: dialogue act and reasoner ``needed`` only."""

    act, reasoner = _target(oracle_action)
    return (
        output.dialogue_act.value == act
        and output.reasoner_request.needed == reasoner["needed"]
    )


def filter_target_agreement(output: FastModelOutput, oracle_action: str) -> str | None:
    """F2: act and the full reasoner request equal the oracle target.

    ``reasoner_request`` equality covers ``needed`` and ``reason_code``, as
    ``evaluate_fast_result_v3`` scores it; no authority or completion claims.
    """

    act, reasoner = _target(oracle_action)
    if output.dialogue_act.value != act:
        return f"{TARGET_AGREEMENT}:dialogue_act"
    if output.reasoner_request.needed != reasoner["needed"]:
        return f"{TARGET_AGREEMENT}:reasoner_needed"
    if output.reasoner_request.reason_code != reasoner["reason_code"]:
        return f"{TARGET_AGREEMENT}:reasoner_reason_code"
    # ``action_intent`` is typed ``None`` on FastModelOutput, so a strict
    # parse (F1) already rejects any action intent; nothing to re-check here.
    if (
        output.completion_claim.status != "not_done"
        or output.completion_claim.evidence_message_ids
    ):
        return f"{TARGET_AGREEMENT}:completion_claim"
    return None


def replay_action(output: FastModelOutput) -> str | None:
    """The oracle action the decision's (act, needed) pair names, if any."""

    return _ACT_TO_ORACLE_ACTION.get(
        (output.dialogue_act.value, output.reasoner_request.needed)
    )


def filter_verifier_replay(
    context: CandidateContext, output: FastModelOutput
) -> str | None:
    """F3: compile the decision and replay its act through the verifier.

    ``runner_v2.execute_model_proposal_r2`` executes Slow capability proposals
    and has no Fast entry point, and the frozen multi-turn environment is
    terminal after its first input, so a position-2 replay cannot submit the
    consumer message and then a capability attempt.  Both positions therefore
    replay on a fresh environment: the follow-up turn carries the opening
    turn's offers, so the verifier verdict is the same at either position.
    """

    decision = compile_fast_output(context.view, output)
    action = replay_action(output)
    if action is None:
        return f"{VERIFIER_REPLAY}:unmapped_act"
    environment = MultiTurnProviderEnvironment(context.scenario)
    environment.start()
    transition = environment.submit_capability_attempt(
        {
            "capability_id": f"simulator.{action}",
            "idempotency_key": _REPLAY_IDEMPOTENCY_KEY,
            "offer_id": context.position.oracle_offer_id,
        }
    )
    verification = transition.verification
    if verification.false_completion or decision.completion_claim.status != "not_done":
        return f"{VERIFIER_REPLAY}:false_completion"
    if not verification.valid_outcome:
        return f"{VERIFIER_REPLAY}:invalid_outcome"
    return None


def filter_detectors(context: CandidateContext, output: FastModelOutput) -> str | None:
    """F4: PII, disclosure, false completion, numeric grounding, fact updates.

    Any non-empty ``fact_updates`` is rejected: the oracle target has none and
    ``evaluate_fast_result_v3`` counts any as unsupported, so training data
    must not be more permissive than evaluation.
    """

    text = output.response_text
    observation = context.position.observation
    if detect_pii(text):
        return f"{DETECTORS}:pii"
    if detect_disallowed_disclosure(text, observation):
        return f"{DETECTORS}:disclosure"
    if detect_false_completion(text):
        return f"{DETECTORS}:false_completion"
    if detect_unsupported_response_facts(text, observation):
        return f"{DETECTORS}:unsupported_facts"
    if output.fact_updates:
        return f"{DETECTORS}:fact_updates_present"
    return None


def filter_second_family_agreement(
    view: FastModelView, second_family: AgreementFilter | None
) -> tuple[str | None, bool | None]:
    """F5: optional; skipped with a ``None`` flag when no adapter is given."""

    if second_family is None:
        return None, None
    agrees = bool(second_family(view))
    return (None if agrees else f"{SECOND_FAMILY_AGREEMENT}:disagrees"), agrees


def apply_filters(
    context: CandidateContext,
    content: str,
    *,
    second_family: AgreementFilter | None = None,
) -> FilterResult:
    """Run F1-F5 in order; the first failure wins."""

    reason = filter_strict_json_schema(content)
    if reason is not None:
        return FilterResult(reason, None, None)
    output = FastModelOutput.model_validate_json(content)
    reason = (
        filter_target_agreement(output, context.row.oracle_action)
        or filter_verifier_replay(context, output)
        or filter_detectors(context, output)
    )
    if reason is not None:
        return FilterResult(reason, output, None)
    reason, agrees = filter_second_family_agreement(context.view, second_family)
    return FilterResult(reason, output, agrees)


def content_hash(content: str) -> str:
    """Exact hash of the raw completion bytes."""

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def lexical_fingerprint(response_text: str) -> str:
    """Hash of the response text casefolded with whitespace collapsed."""

    normalised = _WHITESPACE.sub(" ", response_text.casefold()).strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


__all__ = [
    "DETECTORS",
    "FILTER_ORDER",
    "SECOND_FAMILY_AGREEMENT",
    "STRICT_JSON_SCHEMA",
    "TARGET_AGREEMENT",
    "VERIFIER_REPLAY",
    "AgreementFilter",
    "CandidateContext",
    "FilterResult",
    "act_needed_agrees",
    "apply_filters",
    "build_candidate_context",
    "content_hash",
    "filter_detectors",
    "filter_second_family_agreement",
    "filter_strict_json_schema",
    "filter_target_agreement",
    "filter_verifier_replay",
    "lexical_fingerprint",
    "parse_strict_output",
    "replay_action",
]
