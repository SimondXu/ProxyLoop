"""Negation scope for the read-back "none" slots (fees_none, changes_none,
expires=none): one deterministic rule over closed word classes, per sentence.

A statement opens at ``OPENERS``, "not" + an ``EXISTS`` or ``SELF`` verb, or
"everything (else) stays/remains the same"; a role word counts only as an
item's head. It counts only if what follows is clean: the end, a joiner into
the same list's next item (whose tail then decides), account phrases
(``PREPOSITIONS`` ... ``TARGETS``), a joiner and up to ``BRIDGE_MAX`` plain
words into the next statement, or a joiner into a clause naming a role word
(another field's, read per clause; its own field's is plain, so it voids).
Anything else voids it and all after it; so does a ``HEDGES`` word before the
first, a question, an off-form "everything ... same", or a change item
modified by ``KINDS``. The role is denied only if every role word is negated.
Fail closed; the classes are frozen.
"""

from __future__ import annotations

import re
from typing import Literal, NamedTuple

Role = Literal["fees", "changes", "expires"]

# the words that name each role; for changes the noun (and "nothing changes")
ROLE_WORDS: dict[Role, frozenset[str]] = {
    "fees": frozenset({"fee", "fees", "charge", "charges", "cost", "costs"}),
    "changes": frozenset({"change", "changes"}),
    "expires": frozenset({"expiry", "expiration", "deadline", "expire", "expires"}),
}
# open a negated list right after them
OPENERS = frozenset({"no", "without", "none", "nothing"})
# after "not", deny that the thing exists or applies
EXISTS = frozenset({"be", "is", "are", "was", "have", "has", "come", "comes",
                    "apply", "applies", "carry", "carries"})  # fmt: skip
# after "not", deny the event they name ("does not expire"); they open no list
SELF = frozenset({"expire", "expires", "change", "changes"})
# may sit between "not" + verb and the list
ARTICLES = frozenset({"a", "an", "any"})
# join list items; "and" joins only an item that repeats its opener
JOINERS = frozenset({",", ";", "or", "and", "nor"})
# after an expiry word, the item's head ("no expiry date")
EXPIRY_HEADS = frozenset({"date", "period"})
# "everything (else) stays/remains the same": nothing changes
SAME = frozenset({"stays", "remains"})
# another term kind: a change they modify is no "other change" ("no fee changes")
KINDS = frozenset({"fee", "fees", "charge", "charges", "cost", "costs", "price",
                   "rate", "bill", "payment", "contract", "term"})  # fmt: skip
# a determiner or pronoun: no modifier
SUBJECTS = frozenset({"the", "a", "an", "this", "that", "these", "those", "your",
                      "my", "our", "their", "his", "her", "its", "i", "you", "we",
                      "they", "it", "he", "she", "there"})  # fmt: skip
# open a prepositional phrase that may follow a statement
PREPOSITIONS = frozenset({"to", "on", "for", "with", "in", "of", "at"})
# what such a phrase must end on: the account the offer is about
TARGETS = frozenset({"plan", "plans", "account", "service", "services", "offer",
                     "package"})  # fmt: skip
# a negation or hedge: before the first statement it voids the sentence
HEDGES = frozenset({"not", "never", "maybe", "might", "perhaps", "probably",
                    "think", "guess", "believe"})  # fmt: skip
# a time, condition, restriction or time bound: never a clean tail (a contrast
# word fails as no item, joiner or phrase: "no fees, but ...")
QUALIFIERS = frozenset({
    "day", "days", "week", "weeks", "month", "months", "year", "years", "hour",
    "hours", "today", "now", "yet", "soon", "tomorrow",  # a time
    "if", "while", "as", "provided", "assuming", "when", "once",  # a condition
    "unless",
    "only", "just", "exception", "save", "minus", "except", "excluding", "besides",
    "apart", "aside", "than",  # a restriction
    "after", "until", "till", "before", "through", "during", "within", "beyond",
})  # fmt: skip
# a sentence opening with one of them qualifies the one before ("No fees. Except")
CONTINUERS = frozenset({"except", "apart", "aside", "besides", "beyond", "other",
                        "only", "just", "save", "minus", "excluding", "unless",
                        "well"})  # fmt: skip
MAX_MODIFIERS = 3  # words before an item's head
BRIDGE_MAX = 4  # plain words between a joiner and the next statement

_TOKEN = re.compile(r"\$?\d[\d,.:]*\d|\$?\d|[a-z]+(?:['-][a-z]+)*|[,;:?!]")
_AMOUNT = re.compile(r"\$?\d.*|dollars?|cents?")  # a number, a money word


class Hit(NamedTuple):
    """A role word: its span in the sentence and how the sentence states it."""

    start: int
    end: int
    state: Literal["negated", "void", "plain"]


class _Tok(NamedTuple):
    text: str
    start: int
    end: int


def _tokens(sentence: str) -> list[_Tok]:
    """Lower-cased tokens; "n't" is "not" ("won't" is "will not")."""
    out: list[_Tok] = []
    for m in _TOKEN.finditer(sentence.lower().replace("\u2019", "'")):
        w, a, b = m.group(), m.start(), m.end()
        stem = {"won't": "will", "can't": "can", "cannot": "can"}.get(w, w[:-3])
        neg = w == "cannot" or w.endswith("n't")
        out += [_Tok(stem, a, b), _Tok("not", a, b)] if neg else [_Tok(w, a, b)]
    return out


def continues(sentence: str) -> bool:
    """The sentence opens with a ``CONTINUERS`` word."""
    return any(t.text in CONTINUERS for t in _tokens(sentence)[:1])


def _plain(w: str) -> bool:
    """A word that may sit in a tail: no qualifier, hedge, amount or mark."""
    special = QUALIFIERS | HEDGES | JOINERS | OPENERS | {";", ":", "!", "?"}
    return w not in special and _AMOUNT.fullmatch(w) is None


def _modifier(w: str) -> bool:
    return _plain(w) and w not in SUBJECTS | PREPOSITIONS


def _head(toks: list[_Tok], item: list[int], role: Role) -> set[int]:
    """The item's role word, if it heads the item."""
    words = [toks[k].text for k in item]
    if words[-1] in ROLE_WORDS[role]:
        return {item[-1]}
    expiry = role == "expires" and len(words) > 1 and words[-2] in ROLE_WORDS[role]
    return {item[-2]} if expiry and words[-1] in EXPIRY_HEADS else set()


def _phrases(toks: list[_Tok], k: int) -> int:
    """``k`` past the clean prepositional phrases there; -1 for a bad one."""
    while k < len(toks) and toks[k].text in PREPOSITIONS:
        rest = [t.text for t in toks[k + 1 : k + 2 + MAX_MODIFIERS]]
        end = next((n for n, w in enumerate(rest) if w in TARGETS), None)
        if end is None or not all(_modifier(w) or w in SUBJECTS for w in rest[:end]):
            return -1
        k += end + 2
    return k


def _same(toks: list[_Tok], i: int) -> int | None:
    """The last token of "everything (else) stays/remains the same" at ``i``."""
    w = [t.text for t in toks[i : i + 5]]
    j = 2 if w[1:2] == ["else"] else 1
    same = w[:1] == ["everything"] and w[j + 1 : j + 3] == ["the", "same"]
    return i + j + 2 if same and w[j] in SAME else None


def _opens(toks: list[_Tok], i: int) -> bool:
    w, nxt = toks[i].text, toks[i + 1].text if i + 1 < len(toks) else ""
    return w in OPENERS or (w == "not" and nxt in EXISTS | SELF) or (
        _same(toks, i) is not None)  # fmt: skip


def _statement(toks: list[_Tok], i: int, role: Role) -> tuple[dict[int, int], int]:
    """The role words statement ``i`` negates (first: last token) and where its
    list ends (-1: a bad list)."""
    w, n = toks[i].text, len(toks)
    if (last := _same(toks, i)) is not None:
        return ({i: last} if role == "changes" else {}), last + 1
    if w == "not" and toks[i + 1].text in SELF:
        mine = role == "expires" and toks[i + 1].text in ROLE_WORDS[role]
        return ({i + 1: i + 1} if mine else {}), i + 2
    k = i + 1 if w in OPENERS else i + 2
    k += int(w == "not" and k < n and toks[k].text in ARTICLES)
    heads = dict[int, int]()
    while True:
        item = list[int]()
        while k < n and len(item) <= MAX_MODIFIERS and _modifier(toks[k].text):
            item, k = [*item, k], k + 1
        head = _head(toks, item, role) if item else set[int]()
        if not item or (role == "changes" and head and {
                toks[m].text for m in item[:-1]} & KINDS):  # fmt: skip
            return heads, -1
        heads |= {h: h for h in head}
        j = k
        while j < n and toks[j].text in JOINERS - {"and"}:
            j += 1
        if j == k or j >= n or not _modifier(toks[j].text):  # no bare next item
            return heads, k
        k = j


def _next(toks: list[_Tok], k: int) -> tuple[int, bool]:
    """After a list ending at ``k``: the next statement and whether it continues
    the same list; the end if the tail ends or is a clause on another term
    ("..., and the offer expires June 30"); (-1, False) if it is not clean."""
    if k >= 0 and all(t.text == "!" for t in toks[k:]):
        return len(toks), False
    j = k
    while 0 <= j < len(toks) and toks[j].text in JOINERS:
        j += 1
    if k < 0 or j == k or j >= len(toks):
        return -1, False
    if _opens(toks, j):
        return j, True
    for n in range(j, min(j + BRIDGE_MAX + 1, len(toks))):
        if _opens(toks, n):
            return n, False
        if not _plain(toks[n].text):
            break
    terms = {w for ws in ROLE_WORDS.values() for w in ws}  # own field's: plain
    return (len(toks), False) if {t.text for t in toks[j:]} & terms else (-1, False)


def scan(sentence: str, role: Role) -> list[Hit]:
    """Every role word in ``sentence`` (and, for changes, every "everything
    stays the same"), with how the sentence states it."""
    toks = _tokens(sentence)
    good, bad, group = dict[int, int](), dict[int, int](), dict[int, int]()
    i = next((k for k in range(len(toks)) if _opens(toks, k)), len(toks))
    void = sentence.rstrip().endswith("?") or bool({t.text for t in toks[:i]} & HEDGES)
    while i < len(toks):
        heads, k = _statement(toks, i, role)
        group |= heads
        i, same_list = _next(toks, -1 if k < 0 else _phrases(toks, k))
        if i < 0:
            bad |= group
            break
        if not same_list:  # a new statement, on its own
            good, group = good | group, {}
    words = [t.text for t in toks]
    void |= role == "changes" and any(
        w == "everything" and "same" in words[k:] and _same(toks, k) is None
        for k, w in enumerate(words))  # fmt: skip
    hits = {k: k for k, w in enumerate(words) if w in ROLE_WORDS[role]} | good | bad
    return [
        Hit(toks[k].start, toks[last].end, "plain" if k not in good | bad
            else "void" if void or k in bad else "negated")
        for k, last in sorted(hits.items())
    ]  # fmt: skip


def denied(sentence: str, role: Role) -> bool:
    """The sentence states that no ``role`` exists: every role word is negated."""
    return {h.state for h in scan(sentence, role)} == {"negated"}
