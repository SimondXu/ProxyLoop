"""Negation scope for the read-back "none" slots (fees_none, changes_none,
expires=none): one deterministic rule over closed word classes, per sentence.

A role word is negated when it sits in a list opened by an ``OPENERS`` word
("no fees, changes, or expiry") or by "not" + an ``EXISTS`` verb ("doesn't
have an expiration date"; "does not expire" negates the verb itself). An item
is up to ``MAX_MODIFIERS`` modifiers and a head; items join by ``JOINERS``. A
``BREAKS`` word, an exception, a temporal word, an amount or date, a word that
is no modifier (``SUBJECTS``, ``PREPOSITIONS``), or a joiner followed by a
``SUBJECTS`` word ("and your plan ...") ends the list. A sentence denies the
role only if some role word is negated and no role word's statement is void:
an exception after it, a temporal word within ``TEMPORAL_WINDOW`` tokens after
an expiry word, a price word within ``PRICE_WINDOW`` tokens of a change word,
or a question. Fail closed: nothing else confirms "none". The word classes are
frozen; they are not phrase lists to grow.
"""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Literal, NamedTuple

Role = Literal["fees", "changes", "expires"]
State = Literal["negated", "void", "plain"]

# the words that name each role; for changes the noun (and "nothing changes")
ROLE_WORDS: dict[Role, frozenset[str]] = {
    "fees": frozenset({"fee", "fees", "charge", "charges", "cost", "costs"}),
    "changes": frozenset({"change", "changes"}),
    "expires": frozenset({"expiry", "expiration", "deadline", "expire", "expires"}),
}
# open a negated list right after them
OPENERS = frozenset({"no", "without", "none", "nothing"})
# after "not", deny that the thing exists or applies
EXISTS = frozenset({"be", "is", "are", "was", "have", "has", "include", "includes",
                    "come", "comes", "apply", "applies", "carry",
                    "carries"})  # fmt: skip
# after "not", deny the event they name; they open no list ("won't change any fees")
SELF = frozenset({"expire", "expires", "change", "changes"})
# may sit between "not" + verb and the list
ARTICLES = frozenset({"a", "an", "any"})
# join list items
JOINERS = frozenset({",", "or", "and", "nor"})
# a contrast, a condition or a sentence mark: the list ends
BREAKS = frozenset({"but", "plus", "however", "although", "though", "while", "yet",
                    "if", ";", ":", "!", "?"})  # fmt: skip
# an exception: after a negated word, its statement is void
EXCEPTIONS = frozenset({"except", "unless", "besides", "beyond"})
EXCEPTION_PAIRS = frozenset({("apart", "from"), ("aside", "from"), ("other", "than")})
# a time bound: the list ends; after an expiry word, its statement is void
TEMPORAL = frozenset({"after", "when", "once", "until", "till", "before", "beyond",
                      "through"})  # fmt: skip
# near a change word, the change is to the price: its statement is void
PRICE = frozenset({"price", "rate", "bill", "cost", "payment"})
# a determiner or pronoun: no modifier; after a joiner it starts a new clause
SUBJECTS = frozenset({"the", "a", "an", "this", "that", "these", "those", "your",
                      "my", "our", "their", "his", "her", "its", "i", "you", "we",
                      "they", "it", "he", "she", "there"})  # fmt: skip
# a preposition: no modifier, so it ends the item
PREPOSITIONS = frozenset({"to", "of", "for", "on", "in", "at", "by", "from", "with",
                          "about", "into", "over", "under"})  # fmt: skip
# a month name before a number is a date
MONTHS = frozenset({"jan", "january", "feb", "february", "mar", "march", "apr",
                    "april", "may", "jun", "june", "jul", "july", "aug", "august",
                    "sep", "sept", "september", "oct", "october", "nov", "november",
                    "dec", "december"})  # fmt: skip
MAX_MODIFIERS = 3  # words before an item's head
TEMPORAL_WINDOW = 4  # tokens after an expiry word
PRICE_WINDOW = 3  # tokens either side of a change word

_TOKEN = re.compile(r"\$?\d[\d,.:]*\d|\$?\d|[a-z]+(?:['-][a-z]+)*|[,;:?!]")
_AMOUNT = re.compile(r"\$?\d.*|dollars?|cents?")  # a number, a money word


class Hit(NamedTuple):
    """A role word: its span in the sentence and how the sentence states it."""

    start: int
    end: int
    state: State


class _Tok(NamedTuple):
    text: str
    start: int
    end: int


def _tokens(sentence: str) -> list[_Tok]:
    """Lower-cased tokens; "n't" is "not" ("won't" is "will not")."""
    out: list[_Tok] = []
    for m in _TOKEN.finditer(sentence.lower().replace("\u2019", "'")):
        w, a, b = m.group(), m.start(), m.end()
        if w == "cannot" or w.endswith("n't"):
            stem = {"won't": "will", "can't": "can", "cannot": "can"}.get(w, w[:-3])
            out += [_Tok(stem, a, b), _Tok("not", a, b)]
        else:
            out.append(_Tok(w, a, b))
    return out


def _amount(w: str) -> bool:
    return _AMOUNT.fullmatch(w) is not None


def _stops(toks: list[_Tok], k: int) -> bool:
    """Token ``k`` ends a list: a break, an exception, a time, an amount or date."""
    w = toks[k].text
    nxt = toks[k + 1].text if k + 1 < len(toks) else ""
    return (
        w in BREAKS or w in EXCEPTIONS or w in TEMPORAL or (w, nxt) in EXCEPTION_PAIRS
        or _amount(w) or (w in MONTHS and _amount(nxt))
    )  # fmt: skip


def _list(toks: list[_Tok], k: int, words: frozenset[str]) -> set[int]:
    """The role words in the negated list that starts at token ``k``."""
    found, n = set[int](), len(toks)
    while True:
        size = 0
        while k < n and size <= MAX_MODIFIERS:
            w = toks[k].text
            if w in JOINERS | OPENERS | SUBJECTS | PREPOSITIONS or _stops(toks, k):
                break
            found |= {k} if w in words else set()
            size, k = size + 1, k + 1
        if size == 0 or k >= n or toks[k].text not in JOINERS:
            return found
        while k < n and toks[k].text in JOINERS:
            k += 1
        if k < n and toks[k].text in SUBJECTS:  # "and your plan ...": a new clause
            return found


def _void(toks: list[_Tok], k: int, role: Role) -> bool:
    """The statement about role word ``k`` is void (see the module docstring)."""
    after = [t.text for t in toks[k + 1 :]]
    if set(after) & EXCEPTIONS or set(pairwise(after)) & EXCEPTION_PAIRS:
        return True
    if role == "expires":
        return bool(set(after[:TEMPORAL_WINDOW]) & TEMPORAL)
    near = {t.text for t in toks[max(0, k - PRICE_WINDOW) : k + 1 + PRICE_WINDOW]}
    return role == "changes" and bool(near & PRICE)


def scan(sentence: str, role: Role) -> list[Hit]:
    """Every role word in ``sentence``, with how the sentence states it."""
    toks, words = _tokens(sentence), ROLE_WORDS[role]
    negated = set[int]()
    for i, t in enumerate(toks):
        verb = toks[i + 1].text if t.text == "not" and i + 1 < len(toks) else ""
        if t.text in OPENERS:
            negated |= _list(toks, i + 1, words)
        elif role == "expires" and verb in SELF & words:  # "does not expire"
            negated.add(i + 1)  # (changes: "won't change" names no change noun)
        elif verb in EXISTS:
            j = i + 2 + int(i + 2 < len(toks) and toks[i + 2].text in ARTICLES)
            negated |= _list(toks, j, words)
    question = sentence.rstrip().endswith("?")
    return [
        Hit(t.start, t.end, "plain" if k not in negated
            else "void" if question or _void(toks, k, role) else "negated")
        for k, t in enumerate(toks) if t.text in words
    ]  # fmt: skip


def denied(sentence: str, role: Role) -> bool:
    """The sentence states that no ``role`` exists: some role word is negated
    and none is void."""
    states = {h.state for h in scan(sentence, role)}
    return "negated" in states and "void" not in states
