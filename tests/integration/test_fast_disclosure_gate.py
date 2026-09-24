"""The Fast disclosure gate table (G1-G8) and its coordinator hook (C1-C3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from proxyloop_agent_core import (
    BOUNDED_FAST_STATUS_TEXT,
    FAST_GATE_VERSION,
    SCRIPTED_DIALOGUE_LINES,
    SCRIPTED_PENDING_SLOW_LINE,
    CaseCoordinator,
    FastAdapterResult,
    RouteRequest,
    ScriptedFastAdapter,
    fast_disclosure_violations,
)
from proxyloop_case_runtime import SCRIPTED_CASE_ID, ThinAgentRuntime
from proxyloop_contracts import (
    CaseContextSnapshot,
    DialogueAct,
    FastModelView,
    FastTurnDecision,
    ModelResult,
    RoutingOutcome,
)
from proxyloop_contracts.contracts import CompletionClaim

from scripts.run_fast_slow_split_report import run_demo_path, run_dialogue_path

T0 = datetime(2035, 1, 1, tzinfo=UTC)
LATER = T0 + timedelta(minutes=2)


def _created_snapshot() -> CaseContextSnapshot:
    """$92 bill, $75 target, a $72 offer, and a current strategy (fast_now)."""

    runtime = ThinAgentRuntime(clock=lambda: T0)
    return runtime.create_case(occurred_at=T0).snapshot


SNAPSHOT = _created_snapshot()


def _decision(text: str, **update: Any) -> FastTurnDecision:
    view = CaseCoordinator.project_fast_view(SNAPSHOT)
    decision = ScriptedFastAdapter().decide(view).decision
    return decision.model_copy(update={"response_text": text, **update})


def _codes(
    text: str, snapshot: CaseContextSnapshot = SNAPSHOT, **update: Any
) -> tuple[str, ...]:
    return fast_disclosure_violations(_decision(text, **update), snapshot)


def _without_bill_disclosure(snapshot: CaseContextSnapshot) -> CaseContextSnapshot:
    assert snapshot.strategy is not None
    strategy = snapshot.strategy.model_copy(
        update={
            "allowed_disclosures": tuple(
                item
                for item in snapshot.strategy.allowed_disclosures
                if item != "current_monthly_total"
            )
        }
    )
    return snapshot.model_copy(update={"strategy": strategy})


def _with_term(snapshot: CaseContextSnapshot, months: int) -> CaseContextSnapshot:
    offer = snapshot.offers[0].model_copy(update={"term_months": months})
    return snapshot.model_copy(update={"offers": (offer,)})


def test_the_fixture_is_the_runtime_case() -> None:
    offer = SNAPSHOT.offers[0]
    assert offer.monthly_price.amount_minor == 7200
    assert SNAPSHOT.case.bill_snapshot is not None
    assert SNAPSHOT.case.bill_snapshot.monthly_total.amount_minor == 9200
    assert SNAPSHOT.case.goal.target_monthly_total is not None
    assert SNAPSHOT.case.goal.target_monthly_total.amount_minor == 7500
    assert FAST_GATE_VERSION == "fast-gate-v1"


# G1 Numbers.
@pytest.mark.parametrize(
    "text",
    [
        "The offer is $72 a month.",
        "The offer is 72.00 a month.",
        "The offer is 72 a month.",
        "Your bill is $92 today.",
        "The total is $864.00.",
    ],
)
def test_g1_offer_and_disclosed_numbers_pass(text: str) -> None:
    assert _codes(text) == ()


@pytest.mark.parametrize(
    "text",
    ["They offered $61.", "That is 7200 cents.", "A 10% discount.", "$72.001 now."],
)
def test_g1_undisclosed_numbers_are_rejected(text: str) -> None:
    assert _codes(text) == ("fast_gate_number_not_allowed",)


def test_g1_the_bill_is_rejected_once_its_disclosure_is_removed() -> None:
    assert _codes("Your bill is $92 today.", _without_bill_disclosure(SNAPSHOT)) == (
        "fast_gate_number_not_allowed",
    )


@pytest.mark.parametrize("text", ["Your target is $75.", "We aim for 75.00."])
def test_g1_the_target_is_always_rejected(text: str) -> None:
    assert _codes(text) == ("fast_gate_number_not_allowed",)


# G2 Full-width digits and number words.
@pytest.mark.parametrize(
    ("text", "code"),
    [
        (
            "The offer is \N{FULLWIDTH DIGIT SEVEN}\N{FULLWIDTH DIGIT TWO} a month.",
            "fast_gate_number_not_allowed",
        ),
        ("That is seventy-five dollars.", "fast_gate_number_word"),
        ("About twenty dollars less.", "fast_gate_number_word"),
    ],
)
def test_g2_full_width_digits_and_number_words_are_rejected(
    text: str, code: str
) -> None:
    assert _codes(text) == (code,)


# G3 Dates.
def test_g3_a_month_date_is_rejected_even_when_the_digit_is_allowed() -> None:
    snapshot = _with_term(SNAPSHOT, 12)
    assert _codes("The term is 12 months.", snapshot) == ()
    assert _codes("It starts December 12.", snapshot) == ("fast_gate_date",)


def test_g3_an_iso_date_is_rejected() -> None:
    assert "fast_gate_date" in _codes("It starts 2035-01-01.")


# G4 Commitment, completion, authority.
@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("I accepted the offer for you.", "fast_gate_commitment"),
        (
            "We\N{RIGHT SINGLE QUOTATION MARK}ll switch you over.",
            "fast_gate_commitment",
        ),
        ("I will sign it now.", "fast_gate_commitment"),
        ("It's a deal.", "fast_gate_commitment"),
        ("I promise it is cheaper.", "fast_gate_commitment"),
        ("Your plan has been changed.", "fast_gate_completion"),
        ("The switch is now complete.", "fast_gate_completion"),
        ("You're all set.", "fast_gate_completion"),
        ("I am the account holder.", "fast_gate_authority"),
        ("I'm authorized to change the plan.", "fast_gate_authority"),
    ],
)
def test_g4_commitment_completion_and_authority_are_rejected(
    text: str, code: str
) -> None:
    assert _codes(text) == (code,)


def test_g4_negotiating_on_behalf_of_the_consumer_passes() -> None:
    assert _codes("I am negotiating on behalf of the consumer.") == ()


def test_g4_a_candidate_completion_claim_is_rejected() -> None:
    claim = CompletionClaim(status="candidate", evidence_message_ids=())
    assert _codes("Checking.", completion_claim=claim) == ("fast_gate_completion",)


# G5 Dialogue acts.
@pytest.mark.parametrize(
    "act", [DialogueAct.CONFIRM, DialogueAct.CLOSE, DialogueAct.COUNTER]
)
def test_g5_consequential_acts_are_rejected(act: DialogueAct) -> None:
    assert _codes("Checking.", dialogue_act=act) == ("fast_gate_dialogue_act",)


@pytest.mark.parametrize(
    "act", [DialogueAct.CLARIFY, DialogueAct.CHALLENGE, DialogueAct.ESCALATE]
)
def test_g5_dialogue_acts_pass(act: DialogueAct) -> None:
    assert _codes("Checking.", dialogue_act=act) == ()


# G6 Identifiers, links, length.
@pytest.mark.parametrize(
    "text",
    [
        "Reference 1b4e28ba-2fa1-41d2-883f-0016d3cca427.",
        "See https example page.",
        "Visit www.example.test for details.",
        "Write to someone@example.test please.",
    ],
)
def test_g6_identifiers_and_links_are_rejected(text: str) -> None:
    assert "fast_gate_identifier_or_link" in _codes(text)


def test_g6_text_over_600_characters_is_rejected() -> None:
    assert _codes("a" * 600) == ()
    assert _codes("a" * 601) == ("fast_gate_text_too_long",)


# G7 Every scripted line passes on the report scenarios.
@pytest.mark.parametrize("scenario", [run_demo_path, run_dialogue_path])
def test_g7_every_scripted_line_passes(scenario: Any) -> None:
    state = scenario().repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    for text in (
        BOUNDED_FAST_STATUS_TEXT,
        SCRIPTED_PENDING_SLOW_LINE,
        *SCRIPTED_DIALOGUE_LINES,
    ):
        assert fast_disclosure_violations(_decision(text), state.snapshot) == ()


# G8 Determinism.
def test_g8_the_verdict_is_deterministic_and_sorted() -> None:
    text = "Deal: I signed you up at $61 on December 1, see www.x.test."
    first = _codes(text, dialogue_act=DialogueAct.CONFIRM)
    assert first == tuple(sorted(set(first)))
    assert len(first) == 5
    for _ in range(5):
        assert _codes(text, dialogue_act=DialogueAct.CONFIRM) == first


# Coordinator hook.
class _TextFast:
    def __init__(self, text: str, *, stale: bool = False) -> None:
        self._text = text
        self._stale = stale

    def decide(self, view: FastModelView) -> FastAdapterResult:
        result = ScriptedFastAdapter().decide(view)
        pins = (
            result.pins.model_copy(update={"event_cursor": 0})
            if self._stale
            else result.pins
        )
        return FastAdapterResult(
            pins=pins,
            decision=result.decision.model_copy(update={"response_text": self._text}),
        )


class _SpyGate:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self, decision: FastTurnDecision, snapshot: CaseContextSnapshot
    ) -> tuple[str, ...]:
        self.calls += 1
        return fast_disclosure_violations(decision, snapshot)


def _advance(fast: Any, **kwargs: Any) -> Any:
    outcome = CaseCoordinator(snapshot=SNAPSHOT, **kwargs).advance(
        RouteRequest(snapshot=SNAPSHOT, created_at=LATER), fast=fast
    )
    assert outcome.route.outcome is RoutingOutcome.FAST_NOW
    return outcome


def test_c1_a_gate_reject_withholds_the_decision_and_traces_the_codes() -> None:
    outcome = _advance(
        _TextFast("I signed you up at $61."), fast_gate=fast_disclosure_violations
    )
    codes = ("fast_gate_commitment", "fast_gate_number_not_allowed")
    assert outcome.fast_disclosure_rejected is True
    assert outcome.fast_decision is None
    assert outcome.audits[-1].accepted is False
    assert outcome.audits[-1].reason_codes == codes
    (trace,) = outcome.traces
    assert trace.result is ModelResult.REJECTED
    assert trace.reason_codes == codes
    assert "$61" not in trace.model_dump_json()


def test_c2_without_a_gate_numeric_text_is_accepted_as_before() -> None:
    fast = _TextFast("I signed you up at $61.")
    default = _advance(fast)
    explicit = _advance(fast, fast_gate=None)
    assert default == explicit
    assert default.fast_disclosure_rejected is False
    assert default.fast_decision is not None
    assert default.fast_decision.response_text == "I signed you up at $61."
    (trace,) = default.traces
    assert trace.result is ModelResult.SUCCEEDED
    assert trace.reason_codes == ("fast_result_current",)


def test_c3_a_validation_reject_never_reaches_the_gate() -> None:
    gate = _SpyGate()
    outcome = _advance(_TextFast("I signed you up at $61.", stale=True), fast_gate=gate)
    assert gate.calls == 0
    assert outcome.fast_disclosure_rejected is False
    assert outcome.fast_decision is None
    (trace,) = outcome.traces
    assert trace.result is ModelResult.REJECTED
    assert trace.reason_codes is not None
    assert "stale_fast_result" in trace.reason_codes
    assert not [code for code in trace.reason_codes if code.startswith("fast_gate_")]
