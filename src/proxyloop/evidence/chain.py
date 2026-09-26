"""The provenance chain of every delivered line (ARCHITECTURE §4.3).

``llm.call(response_sha) -> fast.turn(items) -> fast.sentence -> utt.delivered``,
or ``speak.verbatim -> speak.released -> utt.delivered`` for Guard lines.
The check re-parses the stored response with the contract parser, so a
turn's items, its sentences and the delivered text must all follow from the
response bytes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import TypeAdapter, ValidationError

from proxyloop.contract.bundle import PromptRecord
from proxyloop.contract.events import Event
from proxyloop.contract.llm import AdapterKind, LLMCallRecord
from proxyloop.contract.protocol import Speech, TurnItem, parse_turn

_ITEMS: TypeAdapter[list[TurnItem]] = TypeAdapter(list[TurnItem])


def _cited(e: Event, type_: str, by_id: Mapping[str, Event]) -> list[Event]:
    return [by_id[c] for c in e.cause_ids if c in by_id and by_id[c].type == type_]


def _calls(e: Event, by_id: Mapping[str, Event]) -> list[LLMCallRecord]:
    return [
        LLMCallRecord.model_validate(c.payload) for c in _cited(e, "llm.call", by_id)
    ]


def _turn(
    e: Event, by_id: Mapping[str, Event], prompts: Mapping[str, PromptRecord]
) -> str | None:
    """Why the turn's items do not follow from its call's response, if so."""

    calls = [c for c in _calls(e, by_id) if c.call_id == e.payload["call_id"]]
    if len(calls) != 1 or not _cited(e, "fast.request", by_id):
        return "it must cite its fast.request and its one llm.call"
    response = prompts.get(calls[0].response_sha or "")
    if response is None:
        return f"the response of call {calls[0].call_id} is not in prompts.jsonl"
    lane = e.payload["lane"]
    if lane not in ("user", "cp"):
        return f"lane {lane!r}"
    parsed = parse_turn(response.content, lane)
    if e.payload["items"] != [item.model_dump(mode="json") for item in parsed]:
        return "its items are not the parse of the recorded response"
    return None


def _generated(
    e: Event, by_id: Mapping[str, Event], real_only: bool
) -> tuple[object, str | None]:
    """The text the chain generated for ``e``, or why it has none."""

    for sentence in _cited(e, "fast.sentence", by_id):
        turns = _cited(sentence, "fast.turn", by_id)
        if not turns or sentence.payload["utt_id"] != e.payload["utt_id"]:
            return None, "its fast.sentence has no fast.turn, or another utt_id"
        try:
            items = _ITEMS.validate_python(turns[0].payload["items"])
        except ValidationError:
            return None, "its turn's items are malformed"
        spoken = [i.text for i in items if isinstance(i, Speech)]
        if sentence.payload["text"] not in spoken:
            return None, "its fast.sentence is not a sentence of the turn"
        kinds = {c.adapter_kind for c in _calls(turns[0], by_id)}
        if real_only and AdapterKind.REAL_HTTP not in kinds:
            return None, "its turn comes from no real_http call"
        return sentence.payload["text"], None
    for released in _cited(e, "speak.released", by_id):
        for verbatim in _cited(released, "speak.verbatim", by_id):
            return verbatim.payload["text"], None
    return None, "no chain to a fast.sentence or a released speak.verbatim"


def _delivered(e: Event, by_id: Mapping[str, Event], real_only: bool) -> str | None:
    generated, reason = _generated(e, by_id, real_only)
    heard, said = e.payload["text_heard"], e.payload["text_generated"]
    if reason is not None:
        return reason
    if said != generated:
        return "text_generated differs from the chain's text"
    cut = e.payload["interrupted"] and isinstance(heard, str)
    if heard != said and not (cut and str(said).startswith(str(heard))):
        return "text_heard is neither the generated text nor, interrupted, a prefix"
    return None


def chain_failures(
    events: Sequence[Event], prompts: Mapping[str, PromptRecord], real_only: bool
) -> list[str]:
    """``real_only``: a Fast chain must reach a ``real_http`` call (claims)."""

    by_id = {e.event_id: e for e in events}
    failures: list[str] = []
    for e in events:
        reason = None
        if e.type == "fast.turn":
            reason = _turn(e, by_id, prompts)
        elif e.type == "utt.delivered":
            reason = _delivered(e, by_id, real_only)
        if reason is not None:
            failures.append(f"{e.type} {e.event_id}: {reason}")
    return failures
