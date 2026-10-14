"""The user-message path's per-key formats (I4, S1-SYS-15): the span of the
user's own message that ``record_fact`` may publish under a shareable key, or
None. Only a key in ``FORMATS`` can go public from the user, and only in its
format; every other key stays private (safety over coverage). Moved from
``slow.tools`` (S1-SYS-113), which still runs the leak checks on the span."""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal

from proxyloop.contract import state as st

_LAST4 = re.compile(r"[0-9]{4}")  # ASCII only: no NFKC, no separators
_WORD = r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*"  # O'Brien, Lee-Smith
_NAME = re.compile(rf"{_WORD}(?: {_WORD}){{0,3}}")  # 1-4 words, single spaces
_YEARS = re.compile(r"[0-9]{1,2}")
# User decision 2026-10-12: tenure is not confidential; how the user phrases it
# does not matter. The number is still bound to the user's own message (I4).
_TENURE = (  # not an age or a time ago: "36 years old", "of age", "6 years ago"
    r"(?<![\w.]){0}\s+(?:years?|yrs?)\b(?![\s-]+(?:old|of\s+age|ago)\b)"
)
_ONES: dict[str, int] = {w: n for n, w in enumerate((
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
))}  # fmt: skip
_TENS: dict[str, int] = {w: 10 * n for n, w in enumerate(
    ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"), 2
)}  # fmt: skip
_SPELLED = re.compile(  # 0-99 in words: "eight", "twenty-one", "twenty one"
    rf"\b(?:({'|'.join(_TENS)})(?:[\s-]+({'|'.join(list(_ONES)[1:10])}))?"
    rf"|({'|'.join(sorted(_ONES, key=len, reverse=True))}))\b",
    re.IGNORECASE,
)
_BEFORE = (  # a token start; an opener only where it starts a token (no $"4821")
    r"(?:^|(?<=[\s:])|(?<=(?<![^\s:])[(\"\u201c]))"
)
_AFTER = r"(?=[)\"\u201d]?[.,;:!?]?(?:\s|$))"  # a closer, a mark; a space or the end
_EDGE = r"(?<![\w'\u2019-])", r"(?![\w'\u2019-])"  # a name's word bounds
MAX_NAME_CHARS = 60
NUMBER_WORDS = frozenset(
    """zero one two three four five six seven eight nine ten eleven twelve
    thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty
    forty fifty sixty seventy eighty ninety hundred thousand million billion
    dozen half""".split()  # noqa: SIM905
)


def _digits4(value: str, message: str, *_: object) -> str | None:
    """Exactly four ASCII digits, a standalone token of the message: after the
    start, whitespace or ``:``, or an opener ``( " “`` that itself follows one
    of them; then at most one closer ``) " ”``, at most one of
    ``. , ; : ! ?`` and whitespace or the end (S1-SYS-26: "(ending in 4821),")."""
    if not _LAST4.fullmatch(value):
        return None
    return value if re.search(_BEFORE + value + _AFTER, message) else None


def _name(value: str, message: str, *_: object) -> str | None:
    """1-4 ASCII words (``O'Brien``, ``Lee-Smith``), no number word, found
    case-insensitively with word bounds; the user's own spelling is published."""
    if not _NAME.fullmatch(value) or len(value) > MAX_NAME_CHARS:
        return None
    if any(_number_word(w) for w in words(value).split()):
        return None
    found = re.search(_EDGE[0] + re.escape(value) + _EDGE[1], message, re.IGNORECASE)
    return found.group() if found and _NAME.fullmatch(found.group()) else None


def _years(value: str, message: str, *_: object) -> str | None:
    """1-2 ASCII digits the user's message says as ``<n> years`` (or ``yrs``),
    in digits or words ("eight years", "twenty-one years"), in any phrasing
    (user decision 2026-10-12): not an age or a time ago (``<n> years old``,
    ``of age``, ``ago``)."""
    if not _YEARS.fullmatch(value):
        return None
    digits = _SPELLED.sub(_as_digits, message)
    said = re.search(_TENURE.format(re.escape(value)), digits, re.IGNORECASE)
    return value if said else None


def _as_digits(m: re.Match[str]) -> str:  # "twenty-one" -> "21"
    tens, unit, ones = (g.lower() if g else "" for g in m.groups())
    return str(_ONES[ones] if ones else _TENS[tens] + _ONES.get(unit, 0))


def _number_word(word: str) -> bool:  # "sixty", "sixties", "sixes", "hundreds"
    stems = {word, word.removesuffix("s"), word.removesuffix("es")}
    stems |= {word[:-3] + "y"} if word.endswith("ies") else set()
    return bool(stems & NUMBER_WORDS)


def words(text: str) -> str:  # "O'Brien" -> "o brien"
    return " ".join(re.findall(r"[a-z]+", text.casefold()))


# User decision 2026-10-13 (S1-SYS-113, ADR-0033): a competitor quote the user
# states is no fabrication (I11 forbids fabricated ones). Its price goes public
# only said as a price, never as the user's own price or limit; its name only
# as the user wrote it, never the company's or another fact's value.
_PRICE_VALUE = re.compile(r"(?:0|[1-9][0-9]{0,3})(?:\.[0-9]{2})?")  # 58, 57.99
_AMOUNT = re.compile(  # a number token, maybe after "$": not "$1,058", "5.8", "#58"
    r"(?<![\w.,/#@+\u2212-])(\$\s?)?(\d{1,4}(?:\.\d\d)?)(?![\w%-]|[.,/]\d)"
)
_MONEY_AFTER = re.compile(
    r"\s*(?:dollars?|bucks?|usd|(?:a|per|each|every)\s+month|/\s*mo(?:nth)?"
    r"|monthly)\b",
    re.IGNORECASE,
)
_PRICED = frozenset(  # the word right before a price: "a plan for 58"
    """for at charges charge charging offering offers offered quoted quote costs
    cost is only just of""".split()  # noqa: SIM905
)
_NOT_PRICE = frozenset(  # the unit right after a number that is no price
    """month months year years yr yrs day days week weeks hour hours hr hrs
    minute minutes min mins second seconds gb gig gigs mb tb mbps gbps percent
    line lines device devices phone phones people times old""".split()  # noqa: SIM905
)
_OWN = re.compile(  # the user's own price or a limit, in the amount's clause
    r"\b(?:(?:i|we)(?:'m| am|'re| are)? (?:pay|paying)|my (?:bill|plan|budget|max)"
    r"|currently|max(?:imum)?|up to|at most|more than|less than|no more|under"
    r"|below|budget|limit|afford|willing|(?:would|could|can|i'd) pay)\b",
    re.IGNORECASE,
)
_CLAUSE = re.compile(r"[.;!?](?=\s|$)|,(?!\d)|\bbut\b", re.IGNORECASE)


def _price(value: str, message: str, *_: object) -> str | None:
    """``value`` (``58``, ``57.99``) said as a price in the message, in digits
    or words ("$58", "58 dollars", "fifty-eight bucks", "a plan for 58"): a
    "$", a money word after it or a price word before it, no unit of anything
    else after it, and no own price or limit in its clause ("I pay 85", "more
    than 65")."""
    if not _PRICE_VALUE.fullmatch(value):
        return None
    text = _SPELLED.sub(_as_digits, message)
    cuts = [0, *(m.end() for m in _CLAUSE.finditer(text)), len(text)]
    for m in _AMOUNT.finditer(text):
        after = text[m.end() :]
        unit = re.match(r"\s*([a-z]+)", after, re.IGNORECASE)
        before = re.findall(r"[a-z]+", text[: m.start()].lower())[-1:]
        if Decimal(m.group(2)) != Decimal(value) or (
            unit and unit.group(1).lower() in _NOT_PRICE
        ):
            continue
        money = m.group(1) or _MONEY_AFTER.match(after) or set(before) & _PRICED
        start = max(c for c in cuts if c <= m.start())
        end = min(c for c in cuts if c >= m.end())
        if money and not _OWN.search(text[start:end]):
            return value
    return None


def _rival(value: str, message: str, bb: st.Blackboard, company: str) -> str | None:
    """A competitor's name: ``_name``'s span, capitalised as the user wrote
    it, of two letters or more, sharing no word with the company or with
    another recorded fact's value (the holder's name is no competitor)."""
    span = _name(value, message)
    if span is None or not span[0].isupper() or sum(c.isalpha() for c in span) < 2:
        return None
    facts = (*bb.public.facts.values(), *bb.private.case_facts.values())
    theirs = [company, *(f.value for f in facts if f.key != "competitor.name")]
    mine = set(words(span).split())
    return None if any(mine & set(words(t).split()) for t in theirs) else span


Match = Callable[[str, str, st.Blackboard, str], str | None]  # + the company
FORMATS: dict[str, Match] = {  # the one per-key format table (S1-SYS-15)
    "account.last4": _digits4,
    "account.holder_name": _name,
    "tenure_years": _years,
    "competitor.price_usd": _price,  # user decision 2026-10-13 (S1-SYS-113)
    "competitor.name": _rival,
}
