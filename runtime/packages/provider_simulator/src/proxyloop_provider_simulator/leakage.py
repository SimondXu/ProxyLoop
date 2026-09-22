"""Value-level scan for private scenario tokens in model-facing payloads.

Key-name guards (``FORBIDDEN_OBSERVATION_KEYS``, ``_forbidden_keys``,
``_assert_safe_keys``) stop at ``str`` values, so a family or scenario id
carried inside an ``offer_id`` or inside JSON encoded in an event ``content``
string passed them (audit D1-1, D3-1, D3-2).  This module scans every string
value, including JSON encoded inside strings, against the tokens that would
tell a model which family, configuration, or scenario it is looking at.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from proxyloop_contracts.offer_policy import SUPPORTED_APPLIED_CHANGES

from .scenarios import BenchmarkScenario, ScenarioAction

# Vocabulary a model legitimately sees or emits: the shared public
# ``applied_changes`` tokens (``plan_change`` is also a hazard name) and the
# consumer decision vocabulary (``expected_action`` values are the same words
# as ``learning_content.decision.action`` / ``OracleAction``).
PUBLIC_VOCABULARY: frozenset[str] = frozenset(SUPPORTED_APPLIED_CHANGES) | frozenset(
    action.value for action in ScenarioAction
)


@dataclass(frozen=True, slots=True)
class PrivateTokens:
    """Private tokens with the two matching rules the scan applies.

    ``identifiers`` (family, configuration, and scenario ids) are synthetic
    strings that never occur in legitimate public content, so any casefolded
    substring occurrence is a leak.  ``labels`` (hazard names, expected
    outcomes, private reason codes) are short domain words that also occur
    in natural language (``clarification``, ``declined``); they are a leak
    only when carried as a discrete string value, for example
    ``{"hazard": "fee_total_cost_trap"}`` inside an event ``content`` string.
    """

    identifiers: frozenset[str]
    labels: frozenset[str]


def private_tokens(scenarios: Iterable[BenchmarkScenario]) -> PrivateTokens:
    """Every token of ``scenarios`` that must not reach a model."""

    identifiers: set[str] = set()
    labels: set[str] = set()
    for scenario in scenarios:
        identifiers.update(
            (scenario.family_id, scenario.configuration_id, scenario.scenario_id)
        )
        labels.add(scenario.hazard)
        labels.add(scenario.expected_action.value)
        labels.add(scenario.expected_outcome.value)
        labels.update(scenario.private_reason_codes)
    return PrivateTokens(
        identifiers=frozenset(token.casefold() for token in identifiers),
        labels=frozenset(
            token.casefold() for token in labels if token not in PUBLIC_VOCABULARY
        ),
    )


def leaked_private_values(payload: object, tokens: PrivateTokens) -> tuple[str, ...]:
    """The private tokens found in any string value of ``payload``, sorted.

    Walks mappings, sequences, and every ``str``; a string whose tail from
    its first ``{`` or ``[`` parses as a JSON object or array is walked again
    so JSON-in-string content (including marker-prefixed event content) is
    covered.  Matching is casefolded.
    """

    found: set[str] = set()
    for value in _string_values(payload):
        folded = value.casefold()
        found.update(token for token in tokens.identifiers if token in folded)
        if folded.strip() in tokens.labels:
            found.add(folded.strip())
    return tuple(sorted(found))


def _string_values(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        parsed = _parse_json(value)
        if parsed is not None:
            yield from _string_values(parsed)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _string_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _string_values(child)


def _parse_json(value: str) -> object | None:
    starts = [index for index in (value.find("{"), value.find("[")) if index >= 0]
    if not starts:
        return None
    try:
        parsed = json.loads(value[min(starts) :])
    except ValueError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


__all__ = [
    "PUBLIC_VOCABULARY",
    "PrivateTokens",
    "leaked_private_values",
    "private_tokens",
]
