"""Deterministic disclosure gate for Fast dialogue text shown to a person.

``validate_fast_result`` asks whether a Fast output is current and permitted;
this gate asks whether its validated text may be shown. It is a lexical floor,
not semantic safety: it treats every line as if the Provider could read it and
refuses anything that could state an undisclosed number, a commitment, a
completion, an authority claim, an identifier, or a consequential act.

Text outside plain ASCII letters is refused (``fast_gate_non_ascii_text``):
an invisible format character or a lookalike letter would otherwise split or
disguise a word the phrase rules look for. Non-ASCII punctuation and symbols
(an em dash, a curly quote) are allowed.

Known v1 limits (it does not check): paraphrased commitments, non-English
text, one to nine written as words, feature or plan claims without digits,
and non-numeric disclosure of constraints. Any rule change bumps
``FAST_GATE_VERSION``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from decimal import Decimal
from typing import Final

from proxyloop_contracts import CaseContextSnapshot, DialogueAct, FastTurnDecision

FAST_GATE_VERSION: Final = "fast-gate-v1"
FAST_GATE_ALLOWED_ACTS: Final = frozenset(
    {DialogueAct.CLARIFY, DialogueAct.CHALLENGE, DialogueAct.ESCALATE}
)
FAST_GATE_MAX_TEXT_LENGTH: Final = 600

FastGate = Callable[[FastTurnDecision, CaseContextSnapshot], tuple[str, ...]]

_QUOTES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u02bc": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201f": '"',
        "\u2033": '"',
    }
)
# A leading sign counts only when it does not join two words ("7-5", "x-2").
_DIGIT_TOKEN = re.compile(r"((?<!\w)[-+\u2212])?([$]?\d[\d,]*(?:\.\d+)?)")
# "72 %", "72 percent", and "72pct" all state a rate.
_PERCENT = re.compile(r"%|(?<![a-z])(?:per\s*cent|pct)\b")
_NUMBER_WORD = re.compile(
    r"\b(?:ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen"
    r"|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
    r"|hundred|thousand|million)\b"
)
_DATE = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|october"
    r"|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\.?\s*\d"
    r"|\b\d{4}-\d{2}-\d{2}\b"
)
_IDENTIFIER_OR_LINK = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|http|www\.|@|\w+://"
    # A scheme-less domain: a word, a dot, and two or more letters ("e.g." and
    # "i.e." have one letter after the dot).
    r"|\b[a-z][a-z0-9-]*\.[a-z]{2,}\b"
)
_ADVERB = r"(?:\s+(?:now|just|already))?"
_LOCK_IN = r"lock(?:ed)?\s+(?:(?:it|this|that)\s+)?in"
_COMMITMENT = re.compile(
    r"\b(?:i|we)(?:'ll|'ve|'d|'m|'re)?(?:\s+(?:will|have|am|are))?"
    + _ADVERB
    + r"\s+(?:accept(?:ed)?|agreed?|approved?|sign(?:ed)?|commit(?:ted)?"
    r"|confirm(?:ed)?|switch(?:ed)?|cancell?ed|upgraded?|downgraded?"
    r"|purchased?|pay|paid|order(?:ed)?|" + _LOCK_IN + r")\b"
    r"|\b(?:deal|guarantee[ds]?|promise[ds]?)\b"
)
_COMPLETION = re.compile(
    r"\b(?:is|has\s+been|have\s+been|was|are)"
    + _ADVERB
    + r"\s+(?:completed?|done|finali[sz]ed|applied|changed|switched|cancell?ed"
    r"|activated|processed)\b"
    # A consequential participle states an outcome with or without an
    # auxiliary ("Offer accepted and signed."). "accept" itself is allowed.
    r"|\b(?:accepted|approved|signed|agreed|confirmed|finali[sz]ed)\b"
    r"|\blocked\s+(?:(?:it|this|that)\s+)?in\b"
    r"|\ball\s+set\b|\byou're\s+set\b"
)
_AUTHORITY = re.compile(
    r"\b(?:i\s+am|i'm)\s+(?:(?:the|a|an)\s+)?"
    r"(?:account\s+holder|customer|owner|subscriber)\b"
    r"|\bauthori[sz]ed\s+to\b"
)


def fast_disclosure_violations(
    decision: FastTurnDecision, snapshot: CaseContextSnapshot
) -> tuple[str, ...]:
    """Sorted unique ``fast_gate_*`` codes; ``()`` means the text may be shown.

    Pure: no I/O, clock, or model. ``snapshot`` is the one the Fast view was
    projected from; the allowed disclosures are the same strategy-and-authority
    intersection the Fast view carries.
    """

    text = decision.response_text
    normalised = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    lowered = normalised.lower()
    codes: set[str] = set()
    if _has_hidden_or_lookalike_character(text):
        codes.add("fast_gate_non_ascii_text")
    if _has_undisclosed_number(text, normalised, snapshot):
        codes.add("fast_gate_number_not_allowed")
    if _NUMBER_WORD.search(lowered):
        codes.add("fast_gate_number_word")
    if _DATE.search(lowered):
        codes.add("fast_gate_date")
    if _IDENTIFIER_OR_LINK.search(lowered):
        codes.add("fast_gate_identifier_or_link")
    if _COMMITMENT.search(lowered):
        codes.add("fast_gate_commitment")
    if _COMPLETION.search(lowered) or decision.completion_claim.status == "candidate":
        codes.add("fast_gate_completion")
    if _AUTHORITY.search(lowered):
        codes.add("fast_gate_authority")
    if decision.dialogue_act not in FAST_GATE_ALLOWED_ACTS:
        codes.add("fast_gate_dialogue_act")
    if len(text) > FAST_GATE_MAX_TEXT_LENGTH:
        codes.add("fast_gate_text_too_long")
    return tuple(sorted(codes))


def _has_hidden_or_lookalike_character(text: str) -> bool:
    # Letters (L*), combining marks (M*), and format, control, private-use,
    # surrogate, or unassigned code points (C*) outside ASCII.
    return any(
        not char.isascii() and unicodedata.category(char)[0] in {"L", "M", "C"}
        for char in text
    )


def _allowed_disclosures(snapshot: CaseContextSnapshot) -> frozenset[str]:
    if snapshot.strategy is None:
        return frozenset()
    authority = snapshot.case.delegated_authority.allowed_disclosures
    return frozenset(
        item for item in snapshot.strategy.allowed_disclosures if item in authority
    )


def _allowed_numbers(
    snapshot: CaseContextSnapshot,
) -> tuple[frozenset[int], frozenset[int]]:
    """The money amounts (minor units) and plain integers the text may state."""

    money: set[int] = set()
    integers: set[int] = set()
    for offer in snapshot.offers:
        money.add(abs(offer.monthly_price.amount_minor))
        money.add(abs(offer.total_cost.amount_minor))
        money.update(abs(fee.amount.amount_minor) for fee in offer.fees)
        integers.add(offer.term_months)
    disclosed = _allowed_disclosures(snapshot)
    bill = snapshot.case.bill_snapshot
    if "current_monthly_total" in disclosed and bill is not None:
        money.add(abs(bill.monthly_total.amount_minor))
    target = snapshot.case.goal.target_monthly_total
    if "target_monthly_total" in disclosed and target is not None:
        money.add(abs(target.amount_minor))
    return frozenset(money), frozenset(integers)


def _has_undisclosed_number(
    original: str, normalised: str, snapshot: CaseContextSnapshot
) -> bool:
    # A numeral outside ASCII (full-width, other scripts, fractions) is never
    # allowed, even when normalisation would turn it into an allowed value.
    if any(
        not char.isascii() and unicodedata.numeric(char, None) is not None
        for char in original
    ):
        return True
    if _PERCENT.search(normalised.lower()):
        return True
    money, integers = _allowed_numbers(snapshot)
    for match in _DIGIT_TOKEN.finditer(normalised):
        sign, token = match.group(1), match.group(2).rstrip(",")
        if sign:
            return True
        is_money = token.startswith("$")
        digits = token.lstrip("$").replace(",", "")
        whole, _, fraction = digits.partition(".")
        if len(fraction) > 2:
            return True
        minor = int(Decimal(digits) * 100)
        if minor in money:
            continue
        if not is_money and not fraction and int(whole) in integers:
            continue
        return True
    return False


__all__ = [
    "FAST_GATE_ALLOWED_ACTS",
    "FAST_GATE_MAX_TEXT_LENGTH",
    "FAST_GATE_VERSION",
    "FastGate",
    "fast_disclosure_violations",
]
