"""Stateless intake: free text to an inert, typed proposal (PR-12).

``propose_intake`` reads the Consumer's own words into the four
``CreateCaseRequest`` fields plus closed-code clarifications. It is pure and
deterministic: no Case, no Runtime, no model, no I/O. The proposal is not a
Consumer Goal; only the typed facts the Consumer confirms create a Case.

The text is never logged, echoed, or stored: the result holds only Money,
booleans, and closed codes. The rules are a lexical floor (English, closed
vocabulary); a miss becomes a clarification, never a guessed value. Any rule
change bumps ``INTAKE_PARSER_VERSION``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final, Literal

from proxyloop_contracts import Money
from pydantic import BaseModel, ConfigDict, Field

INTAKE_PARSER_VERSION: Final = "intake-parser-v1"
INTAKE_TEXT_MAX_LENGTH = 2000
# The fictional offer's monthly price; the same rule as ``CreateCaseRequest``.
FIXED_OFFER_MINOR = 7200
_MAX_AMOUNT_MINOR = 99_999_999

IntakeField = Literal[
    "current_monthly_total",
    "target_monthly_total",
    "mobile_hotspot_required",
    "device_financing_change_forbidden",
]
ClarificationReason = Literal[
    "missing",
    "ambiguous",
    "invalid_amount",
    "unsupported_currency",
    "below_fixed_offer",
    "target_not_below_current",
]


class IntakeProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=INTAKE_TEXT_MAX_LENGTH)


class IntakeFacts(BaseModel):
    """The four ``CreateCaseRequest`` keys; ``None`` means not read."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    current_monthly_total: Money | None
    target_monthly_total: Money | None
    mobile_hotspot_required: Literal[True] | None
    device_financing_change_forbidden: Literal[True] | None


class IntakeClarification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: IntakeField
    reason: ClarificationReason


class IntakeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parser: Literal["intake-parser-v1"] = INTAKE_PARSER_VERSION
    proposal: IntakeFacts
    clarifications: tuple[IntakeClarification, ...]


_CLAUSE_BREAK = re.compile(r"[;!?\n]|[.,](?=\s|$)|\b(?:and|but)\b")
_FOREIGN_CURRENCY = re.compile(r"[€£¥]|[a-z]\$|\b(?:eur|euros?|gbp|cad|aud|jpy)\b")
_MONEY = re.compile(
    r"\$\s?(?P<dollar>[-\u2013\u2014+]?[\d.,]+)"
    r"|(?<![\w.,$])(?P<plain>\d[\d.,]*)\s?(?:usd|dollars?|bucks)\b"
)
_STRICT_AMOUNT = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$")
_RANGE_AFTER = re.compile(r"^\s*[-\u2013\u2014]\s*\$?\d")
_AFTER_CURRENT = re.compile(r"^\s*(?:bill|plan|now|currently|today)\b")
_AFTER_TARGET = re.compile(
    r"^\s*(?:or\s+(?:less|lower|below|under|cheaper)|max(?:imum)?|tops|target|goal"
    r"|at\s+most)\b"
)
_BEFORE_TARGET = re.compile(
    r"\b(?:to|under|below|target|goal|at\s+most|no\s+more\s+than|less\s+than"
    r"|lower\s+than|cheaper\s+than|max|maximum|reach|want|aim|budget)\b"
)
_BEFORE_CURRENT = re.compile(
    r"\b(?:currently|current|now|pay|paying|paid|is|are|was|cost|costs|costing"
    r"|charge|charged|charges|spend|spending|from|bill|at)\b"
)

_HOTSPOT_TERM = re.compile(r"\b(?:mobile\s+)?hot\s?spot\b|\btethering\b")
_HOTSPOT_KEEP = re.compile(
    r"\b(?:must\s+have|must\s+keep|keep|needs|need|required|requires|require"
    r"|retain|preserve|stays|stay)\b"
)
_NEGATION = (
    r"no|not|don't|dont|do\s+not|never|without|drop|remove|cancel|lose|disable"
    r"|off|stop|rid"
)
_HOTSPOT_RESIDUAL = re.compile(rf"\b(?:{_NEGATION})\b")
_FINANCING_TERM = re.compile(
    r"\b(?:(?:device|phone)\s+)?financ(?:e|ing)\b"
    r"|\b(?:device|phone)\s+(?:payment|installment)s?\b|\binstallment\s+plan\b"
)
_FINANCING_KEEP = re.compile(
    r"\b(?:don't\s+change|do\s+not\s+change|never\s+change|not\s+change"
    r"|no\s+changes|no\s+change|without\s+changing|don't\s+touch|do\s+not\s+touch"
    r"|unchanged|untouched|keep|leave|same|as\s+is|alone)\b"
)
_FINANCING_RESIDUAL = re.compile(
    rf"\b(?:{_NEGATION}|chang\w*|modif\w*|switch\w*|pay\s*off|payoff|end"
    r"|refinanc\w*|restructur\w*)\b"
)

_Role = Literal["current", "target"]


def propose_intake(text: str) -> IntakeProposal:
    """Read ``text`` into a typed proposal; pure and deterministic."""

    normalized = unicodedata.normalize("NFKC", text).replace("\u2019", "'").lower()
    clauses = _clauses(normalized)
    reasons: dict[IntakeField, ClarificationReason] = {}

    current: Money | None = None
    target: Money | None = None
    if _FOREIGN_CURRENCY.search(normalized):
        reasons["current_monthly_total"] = "unsupported_currency"
        reasons["target_monthly_total"] = "unsupported_currency"
    else:
        current, target = _amounts(clauses, reasons)

    hotspot = _feature(clauses, _HOTSPOT_TERM, _HOTSPOT_KEEP, _HOTSPOT_RESIDUAL)
    financing = _feature(clauses, _FINANCING_TERM, _FINANCING_KEEP, _FINANCING_RESIDUAL)
    if hotspot != "keep":
        reasons["mobile_hotspot_required"] = hotspot
    if financing != "keep":
        reasons["device_financing_change_forbidden"] = financing

    facts = IntakeFacts(
        current_monthly_total=current,
        target_monthly_total=target,
        mobile_hotspot_required=True if hotspot == "keep" else None,
        device_financing_change_forbidden=True if financing == "keep" else None,
    )
    order: tuple[IntakeField, ...] = (
        "current_monthly_total",
        "target_monthly_total",
        "mobile_hotspot_required",
        "device_financing_change_forbidden",
    )
    return IntakeProposal(
        proposal=facts,
        clarifications=tuple(
            IntakeClarification(field=field, reason=reasons[field])
            for field in order
            if field in reasons
        ),
    )


def _clauses(text: str) -> list[str]:
    clauses: list[str] = []
    start = 0
    for match in _CLAUSE_BREAK.finditer(text):
        clauses.append(text[start : match.start()])
        start = match.end()
    clauses.append(text[start:])
    return [clause for clause in clauses if clause.strip()]


def _amounts(
    clauses: list[str], reasons: dict[IntakeField, ClarificationReason]
) -> tuple[Money | None, Money | None]:
    values: dict[_Role, set[int]] = {"current": set(), "target": set()}
    invalid: set[_Role] = set()
    unresolved = False
    for clause in clauses:
        previous_end = 0
        for match in _MONEY.finditer(clause):
            before = clause[: match.start()]
            after = clause[match.end() :]
            role = _role(clause[previous_end : match.start()], before, after)
            previous_end = match.end()
            amount = _amount_minor(match, before, after)
            if role is None:
                unresolved = True
            elif amount is None:
                invalid.add(role)
            else:
                values[role].add(amount)

    resolved: dict[_Role, Money | None] = {"current": None, "target": None}
    fields: dict[_Role, IntakeField] = {
        "current": "current_monthly_total",
        "target": "target_monthly_total",
    }
    for role, field in fields.items():
        if role in invalid:
            reasons[field] = "invalid_amount"
        elif len(values[role]) > 1:
            reasons[field] = "ambiguous"
        elif values[role]:
            resolved[role] = Money(amount_minor=values[role].pop(), currency="USD")
        else:
            reasons[field] = "ambiguous" if unresolved else "missing"

    current, target = resolved["current"], resolved["target"]
    if current is not None and current.amount_minor <= FIXED_OFFER_MINOR:
        reasons["current_monthly_total"] = "below_fixed_offer"
    if target is not None:
        if target.amount_minor < FIXED_OFFER_MINOR:
            reasons["target_monthly_total"] = "below_fixed_offer"
        elif current is not None and target.amount_minor >= current.amount_minor:
            reasons["target_monthly_total"] = "target_not_below_current"
    return current, target


def _role(segment: str, before: str, after: str) -> _Role | None:
    if _AFTER_CURRENT.match(after):
        return "current"
    if _AFTER_TARGET.match(after):
        return "target"
    # The words since the previous amount decide; with no cue there, the
    # whole clause before the amount does ("target $75 or maybe $78").
    for words in (segment, before):
        if _BEFORE_TARGET.search(words):
            return "target"
        if _BEFORE_CURRENT.search(words):
            return "current"
    return None


def _amount_minor(match: re.Match[str], before: str, after: str) -> int | None:
    raw = match.group("dollar") or match.group("plain")
    if (
        before.rstrip().endswith(("-", "\u2013", "\u2014"))
        or _RANGE_AFTER.match(after)
        or (match.group("dollar") is not None and after[:1].isalpha())
    ):
        return None
    if raw.endswith((".", ",")):
        raw = raw[:-1]
    if not _STRICT_AMOUNT.match(raw):
        return None
    whole, _, fraction = raw.replace(",", "").partition(".")
    amount = int(whole) * 100 + int(fraction.ljust(2, "0"))
    return amount if amount <= _MAX_AMOUNT_MINOR else None


def _feature(
    clauses: list[str],
    term: re.Pattern[str],
    keep: re.Pattern[str],
    residual: re.Pattern[str],
) -> Literal["keep", "ambiguous", "missing"]:
    mentioned = [clause for clause in clauses if term.search(clause)]
    if not mentioned:
        return "missing"
    for clause in mentioned:
        if not keep.search(clause) or residual.search(keep.sub(" ", clause)):
            return "ambiguous"
    return "keep"


__all__ = [
    "FIXED_OFFER_MINOR",
    "INTAKE_PARSER_VERSION",
    "INTAKE_TEXT_MAX_LENGTH",
    "IntakeClarification",
    "IntakeFacts",
    "IntakeProposal",
    "IntakeProposalRequest",
    "propose_intake",
]
