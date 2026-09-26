"""Lexical cues over one line a Fast has heard (FSM talker, decision points).

Pure text functions: no world data, no model, no state beyond the line.
"""

from __future__ import annotations

import re

from proxyloop.contract.base import FACT_KEY

MONEY = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d{1,2})?|\b\d[\d,]*(?:\.\d{1,2})?\s+dollars\b", re.I
)
PROTECTED = re.compile(
    r"\b(?:pin|passcode|password|security (?:code|question)|social security|ssn"
    r"|date of birth|card number|verification code)\b",
    re.I,
)
IDENTITY = re.compile(
    r"\b(?:verify|name on the account|account holder|last (?:four|4)"
    r"|account number)\b",
    re.I,
)
ACCEPT = re.compile(
    r"\b(?:accept|go ahead|proceed|process|put (?:it|that|this) through"
    r"|sign (?:you|them|her|him) up|lock (?:it|that|this) in"
    r"|set (?:it|that|this) up|take (?:it|the offer|this)|do we have a deal|agree"
    r"|would you like|want me to|shall i)\b",
    re.I,
)
PRESSURE = re.compile(
    r"\b(?:right now|today only|need an answer|limited time|last chance)\b", re.I
)
OFFER = re.compile(r"\b(?:offer|discount|deal|promotion|i can do|we can do)\b", re.I)
STOP = re.compile(
    r"\b(?:stop|cancel (?:it|that|this)|don'?t (?:do|accept|agree|go ahead)"
    r"|never ?mind|hold off|changed? my mind|forget it|call it off"
    r"|wait,? no|don'?t want (?:that|it|this))\b",
    re.I,
)
CORRECTION = re.compile(
    r"\b(?:actually|sorry|i meant|correction|that'?s wrong)\b", re.I
)
_MY = re.compile(
    r"\bmy ([a-z][a-z ]{1,28}?) (?:is|are|was)\s+([^.;!?,]+?)(?=\s+and\s|[.;!?,]|$)",
    re.I,
)
_NAME = re.compile(r"\b(?i:i am|i'm|this is) ([A-Z][a-z]+(?: [A-Z][a-z]+)+)")
_EXPIRES = re.compile(
    r"\bexpir\w*\s+(?:on\s+)?([A-Z][a-z]+ \d{1,2}(?:, \d{4})?|\d{4}-\d{2}-\d{2})"
)
_MONTHS = re.compile(r"\b(\d{1,3})[\s-]*months?\b", re.I)
_YEARS = re.compile(r"\b(\d{1,2})[\s-]*years?\b", re.I)
_NUMBER = re.compile(r"(?<![\w$])\d(?:[\d,.-]*\d)?(?!\w)")
_MONTHLY = re.compile(r"\s*(?:a|per|/|each)\s*(?:month|mo)\b|\s*monthly", re.I)
_FEE = re.compile(r"\s*(?:([a-z]+)\s+)?fee\b", re.I)
_CREDIT = re.compile(r"\s*(?:[a-z]+\s+)?credit\b", re.I)
_OFF = re.compile(r"\s*(?:off|discount)\b", re.I)
_LIMIT = re.compile(
    r"(?:more than|at most|up to|under|below|maximum|max|limit(?: is)?)\s*$", re.I
)
_KEY = re.compile(rf"^{FACT_KEY}$")


def offer(text: str) -> bool:
    """Offer words, or an amount together with a term ("$65 for 12 months").
    An amount alone ("your current bill is $120") is not an offer."""

    term = _MONTHS.search(text) or _YEARS.search(text)
    return bool(OFFER.search(text) or (MONEY.search(text) and term))


def _key(words: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", words.lower()).strip("_")
    return key if _KEY.match(key) else f"fact_{key}"


def _money_key(text: str, start: int, end: int) -> str:
    after, before = text[end : end + 30], text[max(0, start - 30) : start]
    if _MONTHLY.match(after):
        key = "monthly_price"
    elif fee := _FEE.match(after):
        kind = (fee.group(1) or "").lower()
        key = f"fee.{kind}" if kind and kind not in ("a", "one", "the") else "fee"
    elif "fee" in before[-15:].lower():
        key = "fee"
    elif _CREDIT.match(after):
        key = "credit"
    elif _OFF.match(after):
        key = "discount"
    else:
        key = "amount"
    return f"max_{key}" if _LIMIT.search(before) else key


def facts(text: str) -> tuple[tuple[str, str], ...]:
    """Every key and number this line states, as ``(key, value)`` relay pairs.

    ``my X is Y`` and a full name come first; then amounts (keyed by their
    context), months, years, and any other number as ``number``.
    """

    found: list[tuple[int, str, str]] = []
    taken: list[tuple[int, int]] = []

    def add(start: int, end: int, key: str, value: str) -> None:
        if any(a < end and start < b for a, b in taken):
            return
        value = re.sub(r"\s+", " ", value.replace(";", ",").replace("@", "")).strip()
        value = value.rstrip(",")
        if value:
            taken.append((start, end))
            found.append((start, key, value))

    for m in _MY.finditer(text):
        add(m.start(), m.end(), _key(m.group(1)), m.group(2))
    for m in _NAME.finditer(text):
        add(m.start(1), m.end(1), "name", m.group(1))
    for m in _EXPIRES.finditer(text):
        add(m.start(1), m.end(1), "expires", m.group(1))
    for m in MONEY.finditer(text):
        add(m.start(), m.end(), _money_key(text, m.start(), m.end()), m.group())
    for m in _MONTHS.finditer(text):
        add(m.start(), m.end(), "term_months", m.group(1))
    for m in _YEARS.finditer(text):
        add(m.start(), m.end(), "years", m.group(1))
    for m in _NUMBER.finditer(text):
        add(m.start(), m.end(), "number", m.group())
    pairs: list[tuple[str, str]] = []
    seen: dict[str, int] = {}
    for _, key, value in sorted(found):
        seen[key] = seen.get(key, 0) + 1
        pairs.append((key if seen[key] == 1 else f"{key}_{seen[key]}", value))
    return tuple(pairs)
