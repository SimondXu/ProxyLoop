"""Strict/tolerant extraction of one JSON object from raw Fast model output.

Kept separate from ``fast_output.py`` on purpose: that module's bytes are bound
by the Phase 03A1 r4 execution contract (``hosted_rerun._R4_EXECUTION_PATHS``),
so Phase 03C adds parsing next to it instead of inside it.
"""

from __future__ import annotations

import json
import re
from typing import Literal

JSONParseMode = Literal["strict", "fenced", "prefixed_fenced"]

# One optional leading ``json`` word, one optional markdown fence with an
# optional ``json`` language tag, a body that contains no fence, and one
# closing fence.  Anything else is left untouched and reported as ``strict``.
_FENCED_JSON_PATTERN = re.compile(
    r"\A\s*(?P<prefix>json\s*)?```(?:json)?[ \t]*\r?\n?"
    r"(?P<body>(?:(?!```).)*?)"
    r"\r?\n?[ \t]*```\s*\Z",
    re.DOTALL | re.IGNORECASE,
)


class DuplicateJSONKeyError(ValueError):
    """Raised when a Fast output repeats any JSON object member."""


def extract_fast_json(raw: str) -> tuple[str, JSONParseMode]:
    """Strip at most one markdown fence from a raw Fast output.

    ``strict`` returns ``raw`` unchanged.  ``fenced`` and ``prefixed_fenced``
    return the fence body verbatim; the body itself is never edited, so
    schema and duplicate-key failures inside the fence stay visible.
    """

    if not isinstance(raw, str):
        raise TypeError("Fast output must be text")
    match = _FENCED_JSON_PATTERN.match(raw)
    if match is None:
        return raw, "strict"
    body = match.group("body")
    if match.group("prefix"):
        return body, "prefixed_fenced"
    return body, "fenced"


def _reject_duplicate_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for key, value in pairs:
        if key in parsed:
            raise DuplicateJSONKeyError(f"duplicate_json_key:{key}")
        parsed[key] = value
    return parsed


def parse_fast_json(text: str) -> object:
    """Parse JSON text while rejecting duplicate object members."""

    return json.loads(text, object_pairs_hook=_reject_duplicate_json_object)


def duplicate_json_keys(text: str) -> tuple[str, ...]:
    """Names of repeated members in first-seen order; ``text`` must be JSON."""

    seen: list[str] = []

    def collect(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result and key not in seen:
                seen.append(key)
            result[key] = value
        return result

    json.loads(text, object_pairs_hook=collect)
    return tuple(seen)


__all__ = [
    "DuplicateJSONKeyError",
    "JSONParseMode",
    "duplicate_json_keys",
    "extract_fast_json",
    "parse_fast_json",
]
