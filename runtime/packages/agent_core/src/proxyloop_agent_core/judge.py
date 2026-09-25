"""The Stage 2 Judge seam (PR-14): an advisory review of admitted Slow work.

The Judge reviews a Slow Work Result that the coordinator already admitted.
Its verdict is ``accept`` or ``revise``; there is no ``block``, because
authority stays with deterministic policy (decision 7). A binding ``revise``
lets the coordinator retry a Slow adapter that implements
``FeedbackReasoningSlowAdapter`` once, with the verdict passed in process: it
is never a contract field (decision 20) and never read back from the trace
log. A verdict carries closed codes only, never text.

Nothing in evaluation, metrics, policy, the executor, or storage may import
this module (``tests/contract/test_judge_boundary.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Protocol, runtime_checkable
from uuid import UUID

from proxyloop_contracts import ActionType, SlowWorkRequest, SlowWorkResult

from .interfaces import ModelCallUsage, ModelIdentity

# The trace ``output_schema_version`` of a verdict.
JUDGE_VERDICT_VERSION: Final = "judge-verdict-v1"
# Closed: a new code is a new verdict version (root answer 2).
JUDGE_REVISE_CODES: Final = frozenset({"judge_premature_give_up"})
# A Judge call that yielded no verdict, by cause.
JUDGE_ADAPTER_FAILURE_CODES: Final = frozenset(
    {
        "judge_adapter_timeout",
        "judge_adapter_unavailable",
        "judge_adapter_invalid_output",
    }
)

JudgeVerdictKind = Literal["accept", "revise"]


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """The Judge's advisory verdict on one Slow result; codes only."""

    verdict: JudgeVerdictKind
    request_id: UUID
    result_id: UUID
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.verdict not in ("accept", "revise"):
            raise ValueError("a Judge verdict is accept or revise")
        if self.verdict == "accept" and self.reason_codes:
            raise ValueError("an accept verdict carries no reason code")
        if self.verdict == "revise" and not self.reason_codes:
            raise ValueError("a revise verdict needs a reason code")
        if not set(self.reason_codes) <= JUDGE_REVISE_CODES:
            raise ValueError("Judge reason code is not allow-listed")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("Judge reason codes must be unique")


class JudgeAdapter(Protocol):
    """Replaceable advisory reviewer of an admitted Slow result."""

    def judge(
        self, request: SlowWorkRequest, result: SlowWorkResult
    ) -> JudgeVerdict: ...


class JudgeAdapterFailure(RuntimeError):
    """A Judge call that yielded no verdict, for an allow-listed cause.

    The coordinator records it as a ``FAILED`` Judge trace and keeps the
    first admitted Slow result; any other exception propagates.
    """

    def __init__(self, reason_code: str) -> None:
        if reason_code not in JUDGE_ADAPTER_FAILURE_CODES:
            raise ValueError("Judge failure reason code is not allow-listed")
        super().__init__(reason_code)
        self.reason_code = reason_code

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return (self.reason_code,)


@runtime_checkable
class FeedbackReasoningSlowAdapter(Protocol):
    """Optional: a Slow adapter that can take the Judge's verdict on a retry."""

    def reason_with_feedback(
        self, request: SlowWorkRequest, verdict: JudgeVerdict
    ) -> tuple[SlowWorkResult, ModelCallUsage]: ...


class ScriptedJudgeAdapter:
    """Revise a premature give-up; accept everything else.

    A pure function of the request and result. It revises only when Slow
    proposed nothing although an offer was live and the manifest could act on
    it. That is exactly when ``ScriptedProposingSlowAdapter`` proposes, so on
    the default Slow this Judge always accepts.
    """

    model_identity = ModelIdentity(
        provider="scripted",
        model="scripted_judge",
        model_version="rules-v1",
        adapter_version="scripted-v1",
        prompt_version="no-prompt",
    )

    def judge(self, request: SlowWorkRequest, result: SlowWorkResult) -> JudgeVerdict:
        view = request.view
        live_offer = any(offer.expires_at > request.created_at for offer in view.offers)
        can_accept = any(
            definition.allowed_action_types == (ActionType.ACCEPT_OFFER,)
            for definition in view.capability_manifest.capabilities
        )
        if not result.capability_proposals and live_offer and can_accept:
            return JudgeVerdict(
                "revise",
                request.request_id,
                result.result_id,
                ("judge_premature_give_up",),
            )
        return JudgeVerdict("accept", request.request_id, result.result_id)


__all__ = [
    "JUDGE_ADAPTER_FAILURE_CODES",
    "JUDGE_REVISE_CODES",
    "JUDGE_VERDICT_VERSION",
    "FeedbackReasoningSlowAdapter",
    "JudgeAdapter",
    "JudgeAdapterFailure",
    "JudgeVerdict",
    "JudgeVerdictKind",
    "ScriptedJudgeAdapter",
]
