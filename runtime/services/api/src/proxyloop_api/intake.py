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
from dataclasses import dataclass
from typing import Final, Literal

from proxyloop_contracts import Money
from pydantic import BaseModel, ConfigDict, Field

INTAKE_PARSER_VERSION: Final = "intake-parser-v1"
INTAKE_TEXT_MAX_LENGTH = 2000
# The fictional offer's monthly price; the same rule as ``CreateCaseRequest``.
FIXED_OFFER_MINOR = 7200
# $999,999.99: the largest amount the parser, `CreateCaseRequest`, and the
# Web accept.
MAX_AMOUNT_MINOR = 99_999_999
# NFKC can expand a character up to 18-fold; text longer than this after
# normalization is not read (every field ``missing``), which bounds the work.
NORMALIZED_TEXT_MAX_LENGTH = 4000

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


# Rule set ``intake-parser-v1`` (amended before merge after review, I-1..I-3,
# M-3): any uncertainty is a clarification, never a guessed value.
_SENTENCE_BREAK = re.compile(r"[;!?\n]|\.(?=\s|$)")
_CLAUSE_BREAK = re.compile(r",(?=\s|$)|\b(?:and|but)\b")
_QUESTION_START = re.compile(
    r"^\s*(?:(?:can|could|should|would|will|shall|may|might|do|does|did|is|are|am)"
    r"\s+(?:i|we|you|it|they|my|the|there|this|that)|what|how|why|when|where|which)\b"
)
_FOREIGN_CURRENCY = re.compile(r"[€£¥]|[a-z]\$|\b(?:eur|euros?|gbp|cad|aud|jpy)\b")
# Digits are ASCII only: ``\d`` would read other scripts' digits as numbers.
_MONEY = re.compile(
    r"\$\s?(?P<dollar>[-\u2013\u2014+]?[0-9.,]+)"
    r"|\$\s?(?P<junk>[^\s0-9]\S*)"
    r"|(?<![\w.,$])(?P<plain>[0-9][0-9.,]*)\s?(?:usd|dollars?|bucks)\b"
)
_STRICT_AMOUNT = re.compile(r"^(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?$")
_RANGE_AFTER = re.compile(r"^\s*[-\u2013\u2014]\s*\$?[0-9]")
# The end-anchored patterns run only on a bounded, right-stripped tail of the
# text before an amount, and none has two adjacent optional whitespace runs
# (review I-A: those backtracked quadratically on long whitespace).
_TAIL_CHARS = 48
# More amounts than this in one request are not read one by one: both amounts
# are ambiguous, which also bounds the per-amount work.
_MAX_MENTIONS = 8
_TO_AMOUNT_AFTER = re.compile(r"^\s*to\s*(?:\$\s?)?[0-9]")
_TO_AMOUNT_BEFORE = re.compile(r"[0-9](?:\s*(?:usd|dollars?|bucks))?\s+to$")
_FROM_BEFORE = re.compile(r"\bfrom$")
_FROM_TO_BEFORE = re.compile(
    r"\bfrom\s+(?:\$\s?)?[0-9][0-9.,]*(?:\s*(?:usd|dollars?|bucks))?\s+to$"
)
# A request to lower the bill: a question holding one still reads its amounts
# ("Can you lower my phone bill from $92 to $75?"). ``get`` counts only with a
# lowering word ("get my bill down"); a comparative ("lower than $92") is not a
# request.
_LOWERING = re.compile(
    r"\b(?:lower(?!\s+than\b)|reduce|bring\s+down|cut"
    r"|get\b[^.?!]{0,40}?\b(?:down|lower|cheaper|under|below|reduced)\b(?!\s+than\b))"
)
# A price history verb: the amounts after it are not a current bill or a goal
# we can tell apart ("went up to $92", "went from $80 to $92").
_HISTORY = re.compile(
    r"\b(?:went|gone|goes\s+up|go\s+up|moved|changed|jump(?:ed|s)?|rais(?:e|ed|es)"
    r"|rose|risen|increas(?:e|ed|es)|climb(?:ed|s)?|hike[ds]?)\b"
)
_CHANGE_AFTER = re.compile(r"^\s*(?:off|less|cheaper|lower|savings|in\s+savings)\b")
_CHANGE_BEFORE = re.compile(
    r"\b(?:save|saving|savings|cut|by|off|between|at\s+least|(?<!no )more\s+than)\b"
)
_AFTER_CURRENT = re.compile(
    r"^\s*(?:(?:phone|mobile|cell)\s+)?(?:bill|plan|now|currently|today)\b"
)
_AFTER_TARGET = re.compile(
    r"^\s*(?:or\s+(?:less|lower|below|under|cheaper)|max(?:imum)?|tops|target|goal"
    r"|at\s+most)\b"
)
# Role cues before an amount (fourth amendment M-2, root decision). A target
# cue beats a weak current cue ("I only want to pay $75"); a target cue that
# meets a strong current cue leaves the amount without a role. Under these
# rules strong and weak target cues act the same, so they share one list.
_BEFORE_TARGET = re.compile(
    r"\b(?:(?<!comes )to|under|below|target|goal|at\s+most|no\s+more\s+than"
    r"|less\s+than|lower\s+than|cheaper\s+than|max|maximum|reach|want|aim|budget"
    r"|(?:i'd|i\s+would|would|we'd)\s+like|like\s+it\s+(?:to\s+be|at)|hoping"
    r"|hope\s+for|happy\s+with|happy\s+at)\b"
)
# "happy at" is also a strong current cue: "I'm happy at $92" may describe the
# bill as it is.
_STRONG_CURRENT = re.compile(
    r"\b(?:currently|right\s+now|now\s+paying|i\s+pay|i'm\s+paying|i\s+am\s+paying"
    r"|(?:it|bill)\s+(?:is|costs|comes\s+to)|happy\s+at)\b"
)
_BEFORE_CURRENT = re.compile(
    r"\b(?:currently|current|now|pay|paying|paid|is|are|was|cost|costs|costing"
    r"|charge|charged|charges|spend|spending|from|bill|at)\b"
)

_NEGATION = (
    r"no|not|nope|nah|never|cannot|\w+n't|dont|isnt|doesnt|cant|wont|didnt|arent"
    r"|wasnt|shouldnt|wouldnt|without|drop|remove|cancel|lose|disable|off|stop"
    r"|rid|end|forget"
)
_HEDGE = r"unless|if|optional|maybe|perhaps|probably|rather|ideally|whatever"
_CHANGE_WORDS = (
    r"chang\w*|modif\w*|switch\w*|pay\s*off|payoff|refinanc\w*|restructur\w*"
)
_HOTSPOT_TERM = re.compile(r"\b(?:mobile\s+)?hot\s?spot\b|\btethering\b")
_HOTSPOT_KEEP = re.compile(
    r"\b(?:must\s+have|must\s+keep|keep|needs|need|required|requires|require"
    r"|retain|preserve|stays|stay)\b"
)
_HOTSPOT_RESIDUAL = re.compile(rf"\b(?:{_NEGATION}|{_HEDGE})\b")
_FINANCING_TERM = re.compile(
    r"\b(?:(?:device|phone)\s+)?financ(?:e|ing)\b"
    r"|\b(?:device|phone)\s+(?:payment|installment)s?\b|\binstallment\s+plan\b"
)
_FINANCING_KEEP = re.compile(
    r"\b(?:don't\s+change|do\s+not\s+change|never\s+change|not\s+change"
    r"|no\s+changes|no\s+change|without\s+changing|don't\s+touch|do\s+not\s+touch"
    r"|unchanged|untouched|keep|leave|same|as\s+is|alone)\b"
)
_FINANCING_RESIDUAL = re.compile(rf"\b(?:{_NEGATION}|{_HEDGE}|{_CHANGE_WORDS})\b")
# A clause that names no feature but negates or changes something casts doubt
# on the feature named last ("Keep the hotspot? Nope", "... I'd drop it").
_ORPHAN_DOUBT = re.compile(rf"\b(?:{_NEGATION}|{_CHANGE_WORDS})\b")
# ... and on every named feature when its sentence says so ("Actually no.",
# "Actually, forget it, I want to change both.").
_ALL_DOUBT = re.compile(r"\b(?:both|all|everything|actually)\b")
# A retraction casts doubt on every named feature ("Wait, no.", "No.",
# "Never mind.", "Scratch that.").
_RETRACTION = re.compile(
    r"^\s*no\s*$|\bwait\s*,?\s*no\b|\bnever\s*mind\b|\bscratch\s+that\b"
)

_ORDER: tuple[IntakeField, ...] = (
    "current_monthly_total",
    "target_monthly_total",
    "mobile_hotspot_required",
    "device_financing_change_forbidden",
)
_Role = Literal["current", "target"]
_Feature = Literal["hotspot", "financing"]
_Verdict = Literal["keep", "ambiguous", "missing"]
_FEATURES: dict[_Feature, tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]] = {
    "hotspot": (_HOTSPOT_TERM, _HOTSPOT_KEEP, _HOTSPOT_RESIDUAL),
    "financing": (_FINANCING_TERM, _FINANCING_KEEP, _FINANCING_RESIDUAL),
}


@dataclass(frozen=True, slots=True)
class _Clause:
    text: str
    question: bool
    # Read once per sentence: it doubts every named feature, and whether it
    # is a retraction (a retraction needs no negation word in the clause).
    doubts_all: bool
    retraction: bool


def propose_intake(text: str) -> IntakeProposal:
    """Read ``text`` into a typed proposal; pure and deterministic."""

    normalized = unicodedata.normalize("NFKC", text).replace("\u2019", "'").lower()
    if len(normalized) > NORMALIZED_TEXT_MAX_LENGTH:
        return IntakeProposal(
            proposal=IntakeFacts(
                current_monthly_total=None,
                target_monthly_total=None,
                mobile_hotspot_required=None,
                device_financing_change_forbidden=None,
            ),
            clarifications=tuple(
                IntakeClarification(field=field, reason="missing") for field in _ORDER
            ),
        )
    clauses = _clauses(normalized)
    reasons: dict[IntakeField, ClarificationReason] = {}

    current: Money | None = None
    target: Money | None = None
    if _FOREIGN_CURRENCY.search(normalized):
        reasons["current_monthly_total"] = "unsupported_currency"
        reasons["target_monthly_total"] = "unsupported_currency"
    else:
        current, target = _amounts(clauses, reasons)

    verdicts = _features(clauses)
    if verdicts["hotspot"] != "keep":
        reasons["mobile_hotspot_required"] = verdicts["hotspot"]
    if verdicts["financing"] != "keep":
        reasons["device_financing_change_forbidden"] = verdicts["financing"]

    facts = IntakeFacts(
        current_monthly_total=current,
        target_monthly_total=target,
        mobile_hotspot_required=True if verdicts["hotspot"] == "keep" else None,
        device_financing_change_forbidden=(
            True if verdicts["financing"] == "keep" else None
        ),
    )
    return IntakeProposal(
        proposal=facts,
        clarifications=tuple(
            IntakeClarification(field=field, reason=reasons[field])
            for field in _ORDER
            if field in reasons
        ),
    )


def _split(text: str, pattern: re.Pattern[str]) -> list[tuple[str, str]]:
    """Return ``(part, delimiter)`` pairs; the last delimiter is empty."""

    parts: list[tuple[str, str]] = []
    start = 0
    for match in pattern.finditer(text):
        parts.append((text[start : match.start()], match.group()))
        start = match.end()
    parts.append((text[start:], ""))
    return parts


def _clauses(text: str) -> list[_Clause]:
    clauses: list[_Clause] = []
    for sentence, end in _split(text, _SENTENCE_BREAK):
        question = end == "?" or bool(_QUESTION_START.match(sentence))
        retraction = _RETRACTION.search(sentence) is not None
        doubts_all = retraction or _ALL_DOUBT.search(sentence) is not None
        clauses.extend(
            _Clause(part, question, doubts_all, retraction)
            for part, _ in _split(sentence, _CLAUSE_BREAK)
            if part.strip()
        )
    return clauses


def _amounts(
    clauses: list[_Clause], reasons: dict[IntakeField, ClarificationReason]
) -> tuple[Money | None, Money | None]:
    values: dict[_Role, set[int]] = {"current": set(), "target": set()}
    invalid: set[_Role] = set()
    unassigned = False
    mentions = [(clause, list(_MONEY.finditer(clause.text))) for clause in clauses]
    if sum(len(matches) for _, matches in mentions) > _MAX_MENTIONS:
        reasons["current_monthly_total"] = "ambiguous"
        reasons["target_monthly_total"] = "ambiguous"
        return None, None
    for clause, matches in mentions:
        text = clause.text
        # A question has no sure amounts unless it asks to lower the bill.
        unsure = clause.question and not _LOWERING.search(text)
        previous_end = 0
        for match in matches:
            before = text[: match.start()]
            after = text[match.end() :]
            role = (
                None
                if unsure
                else _role(text[previous_end : match.start()], before, after)
            )
            previous_end = match.end()
            amount = _amount_minor(match, before, after)
            if role is None:
                unassigned = True
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
        if unassigned or len(values[role]) > 1:
            # An amount with no role could be either fact.
            reasons[field] = "ambiguous"
        elif role in invalid:
            reasons[field] = "invalid_amount"
        elif values[role]:
            resolved[role] = Money(amount_minor=values[role].pop(), currency="USD")
        else:
            reasons[field] = "missing"

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
    """The amount's role, or ``None`` when it has none or it is unsure."""

    tail = _tail(before)
    if _HISTORY.search(tail):
        return None  # "went up to $92", "jumped from $85 to $110"
    if _FROM_BEFORE.search(tail) and _TO_AMOUNT_AFTER.match(after):
        return "current"  # "from $92 to $75"
    if _FROM_TO_BEFORE.search(tail):
        return "target"
    if _TO_AMOUNT_AFTER.match(after) or _TO_AMOUNT_BEFORE.search(tail):
        return None  # a range: "$70 to $80"
    if _CHANGE_AFTER.match(after):
        return None  # a change amount: "$20 off", "$10 less"
    if _AFTER_CURRENT.match(after):
        return "current"
    if _AFTER_TARGET.match(after):
        return "target"
    # The words since the previous amount decide; with no cue there, the
    # clause before the amount does ("target $75 or maybe $78"). Both see
    # only the bounded tail. A change cue nearer than any role cue ("save
    # $20", "by $10") has no role. A target cue beats a weak current cue
    # ("I only want to pay $75"); a target cue with a strong current cue has
    # no role ("hoping … my bill is $92").
    for words in (_tail(segment), tail):
        change = _last_match(_CHANGE_BEFORE, words)
        target = _last_match(_BEFORE_TARGET, words)
        strong_current = _last_match(_STRONG_CURRENT, words)
        current = max(strong_current, _last_match(_BEFORE_CURRENT, words))
        if change > max(target, current):
            return None
        if target >= 0:
            return None if strong_current >= 0 else "target"
        if current >= 0:
            return "current"
    return None


def _tail(text: str) -> str:
    """The right-stripped last ``_TAIL_CHARS`` characters, whole words only."""

    stripped = text.rstrip()
    if len(stripped) <= _TAIL_CHARS:
        return stripped
    tail = stripped[-_TAIL_CHARS:]
    if stripped[-_TAIL_CHARS - 1].isalnum() or stripped[-_TAIL_CHARS - 1] in "_'":
        return re.sub(r"^[\w']+", "", tail)
    return tail


def _last_match(pattern: re.Pattern[str], text: str) -> int:
    return max((match.start() for match in pattern.finditer(text)), default=-1)


def _amount_minor(match: re.Match[str], before: str, after: str) -> int | None:
    raw = match.group("dollar") or match.group("plain")
    if (
        raw is None
        or before.rstrip().endswith(("-", "\u2013", "\u2014"))
        or _RANGE_AFTER.match(after)
        or (match.group("dollar") is not None and after[:1].isalnum())
    ):
        return None
    if raw.endswith((".", ",")):
        raw = raw[:-1]
    if not _STRICT_AMOUNT.match(raw):
        return None
    whole, _, fraction = raw.replace(",", "").partition(".")
    amount = int(whole) * 100 + int(fraction.ljust(2, "0"))
    return amount if amount <= MAX_AMOUNT_MINOR else None


def _features(clauses: list[_Clause]) -> dict[_Feature, _Verdict]:
    verdicts: dict[_Feature, _Verdict] = {"hotspot": "missing", "financing": "missing"}
    last_named: _Feature | None = None
    for clause in clauses:
        named: list[tuple[int, _Feature]] = []
        for feature, (term, keep, residual) in _FEATURES.items():
            found = term.search(clause.text)
            if found is None:
                continue
            named.append((found.start(), feature))
            doubtful = (
                clause.question
                or not keep.search(clause.text)
                or residual.search(keep.sub(" ", clause.text)) is not None
            )
            if doubtful:
                verdicts[feature] = "ambiguous"
            elif verdicts[feature] == "missing":
                verdicts[feature] = "keep"
        if named:
            last_named = max(named)[1]
        elif last_named is not None and (
            clause.retraction or _ORPHAN_DOUBT.search(clause.text)
        ):
            if clause.doubts_all:
                for feature, verdict in verdicts.items():
                    if verdict != "missing":
                        verdicts[feature] = "ambiguous"
            else:
                verdicts[last_named] = "ambiguous"
    return verdicts


__all__ = [
    "FIXED_OFFER_MINOR",
    "INTAKE_PARSER_VERSION",
    "INTAKE_TEXT_MAX_LENGTH",
    "MAX_AMOUNT_MINOR",
    "NORMALIZED_TEXT_MAX_LENGTH",
    "IntakeClarification",
    "IntakeFacts",
    "IntakeProposal",
    "IntakeProposalRequest",
    "propose_intake",
]
