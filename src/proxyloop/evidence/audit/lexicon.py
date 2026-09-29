"""The independent, high-recall lexical detector (EVAL §9 item 4, stratum ii).

No model and no Ear: a text is flagged for an audited class when a pinned
pattern matches it. Recall is the goal, so the patterns are wide and precision
is not measured here. Change a pattern only with a new ``LEXICON_VERSION``: the
frame records the version its strata were drawn under.
"""

from __future__ import annotations

import re

LEXICON_VERSION = "ear-audit-lex/1"

_DIGIT_WORDS = "zero|oh|one|two|three|four|five|six|seven|eight|nine"
_PATTERNS: dict[str, tuple[str, ...]] = {
    # affirmation / acceptance, of an offer or otherwise
    "accept": (
        r"\b(?:yes|yeah|yep|yup|sure|okay|ok|alright|all right|agree[sd]?|accept\w*"
        r"|deal|go ahead|proceed|sounds? (?:good|great|fine)|that works|works for me"
        r"|let'?s do (?:it|that)|i'?ll take (?:it|that|the)|take (?:it|the offer)"
        r"|confirm\w*|lock (?:it|that) in|sign me up|please do|do it|fine|perfect"
        r"|great|good to go|i'?m in|we have a deal)\b",
    ),
    # digit patterns of protected formats: a PIN or last-4 (4+ digits, spoken or
    # written, joined by spaces, dashes or commas), an SSN, a long account or
    # card number
    "provide_fact_protected": (
        r"(?<!\d)\d(?:[ ,-]?\d){3,}(?!\d)",
        rf"\b(?:(?:{_DIGIT_WORDS})(?:[ ,-]+|\b)){{4,}}",
        r"\b\d{3}-\d{2}-\d{4}\b",
    ),
    "completion_claim": (
        r"\b(?:done|complete[d]?|finish(?:ed)?|all set|taken care of|sorted"
        r"|resolved|cancel+ed|switched|updated|booked|scheduled|submitted"
        r"|processed|successful(?:ly)?|(?:i'?ve|i have|we'?ve|it'?s|has|have|been)"
        r" (?:now )?(?:been )?"
        r"(?:done|made|changed|applied|set up|arranged|confirmed))\b",
    ),
    "cancel_intent": (
        r"\b(?:cancel\w*|terminat\w*|discontinu\w*|not renew\w*|close (?:my|the) "
        r"account|end (?:my|the|our) (?:service|plan|subscription|contract)"
        r"|switch(?:ing)? (?:away|to)|leav(?:e|ing)"
        r"|stop (?:my|the) (?:service|plan))\b",
    ),
    "cite_competitor": (
        r"\b(?:competitors?|another (?:company|provider|carrier)"
        r"|other (?:company|companies|provider|providers|carrier|carriers|offers?)"
        r"|cheaper|elsewhere|quoted|price[- ]match\w*|verizon|t-mobile|at&t|att"
        r"|comcast|spectrum|xfinity|offering me)\b",
    ),
    "ask_readback": (
        r"\b(?:read (?:it|that|them|those|all|the \w+) back|repeat\w*|go over"
        r"|recap\w*|confirm (?:the|all|that)|all (?:the |of the )?terms|full terms"
        r"|summari[sz]e\w*|spell (?:it )?out|walk me through)\b",
    ),
}
_COMPILED = {
    cls: tuple(re.compile(p, re.IGNORECASE) for p in ps)
    for cls, ps in _PATTERNS.items()
}
CLASSES = tuple(_PATTERNS)


def flags(text: str) -> tuple[str, ...]:
    """The audited classes ``text`` is flagged for, in ``CLASSES`` order."""

    return tuple(
        cls for cls, ps in _COMPILED.items() if any(p.search(text) for p in ps)
    )
