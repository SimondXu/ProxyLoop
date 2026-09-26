"""The provenance chain of every delivered line (ARCHITECTURE §4.3).

``llm.call(response_sha) -> fast.turn(items) -> fast.sentence -> utt.delivered``,
or ``speak.verbatim -> speak.released -> utt.delivered`` for Guard lines.
Items, sentences and delivered text must follow from the re-parsed response
bytes; a turn is bound to one successful call of its lane's Fast role and to
its request's model and prompt; lane, gen_id and utt_id agree along the
chain; each sentence or released line is delivered at most once.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import TypeAdapter, ValidationError

from proxyloop.contract.bundle import PromptRecord
from proxyloop.contract.events import Event
from proxyloop.contract.llm import AdapterKind, LLMCallRecord
from proxyloop.contract.protocol import Speech, TurnItem, parse_turn

_ITEMS: TypeAdapter[list[TurnItem]] = TypeAdapter(list[TurnItem])
Chain = tuple[object, str | None, str | None]  # (generated text, source id, why not)


def _cited(e: Event, type_: str, by_id: Mapping[str, Event]) -> list[Event]:
    return [by_id[c] for c in e.cause_ids if c in by_id and by_id[c].type == type_]


def _call(turn: Event, by_id: Mapping[str, Event]) -> LLMCallRecord | None:
    """The one cited ``llm.call`` whose ``call_id`` the turn names."""

    calls = [
        LLMCallRecord.model_validate(c.payload) for c in _cited(turn, "llm.call", by_id)
    ]
    calls = [c for c in calls if c.call_id == turn.payload["call_id"]]
    return calls[0] if len(calls) == 1 else None


def _turn(
    e: Event, by_id: Mapping[str, Event], prompts: Mapping[str, PromptRecord]
) -> str | None:
    """Why the turn does not follow from its request and call, if so."""

    call, requests = _call(e, by_id), _cited(e, "fast.request", by_id)
    if call is None or len(requests) != 1:
        return "it must cite its one fast.request and its one llm.call"
    request, lane = requests[0].payload, e.payload["lane"]
    if lane not in ("user", "cp"):
        return f"lane {lane!r}"
    if call.error is not None:
        return f"call {call.call_id} failed ({call.error}); no line may come from it"
    if call.role != f"fast_{lane}":
        return f"call {call.call_id} is a {call.role} call, not fast_{lane}"
    if (request["lane"], request["gen_id"]) != (lane, e.payload["gen_id"]):
        return "its lane or gen_id is not its fast.request's"
    model = call.model_ref.model_dump(mode="json")
    if (request["model_ref"], request["prompt_sha"]) != (model, call.prompt_sha):
        return "its fast.request names another model or prompt than its call"
    response = prompts.get(call.response_sha or "")
    if response is None:
        return f"the response of call {call.call_id} is not in prompts.jsonl"
    parsed = parse_turn(response.content, lane)
    if e.payload["items"] != [item.model_dump(mode="json") for item in parsed]:
        return "its items are not the parse of the recorded response"
    return None


def _sentence(
    e: Event, sentence: Event, by_id: Mapping[str, Event], real: bool
) -> Chain:
    turns = _cited(sentence, "fast.turn", by_id)
    if not turns:
        return None, None, "its fast.sentence cites no fast.turn"
    s, t, p = sentence.payload, turns[0].payload, e.payload
    along = (s["utt_id"], s["lane"], s["lane"], s["gen_id"])
    if along != (p["utt_id"], p["lane"], t["lane"], t["gen_id"]):
        return None, None, "utt_id, lane or gen_id differ along the chain"
    try:
        items = _ITEMS.validate_python(t["items"])
    except ValidationError:
        return None, None, "its turn's items are malformed"
    if s["text"] not in [i.text for i in items if isinstance(i, Speech)]:
        return None, None, "its fast.sentence is not a sentence of the turn"
    call = _call(turns[0], by_id)
    if real and (call is None or call.adapter_kind is not AdapterKind.REAL_HTTP):
        return None, None, "its turn's own call is not real_http"
    return s["text"], sentence.event_id, None


def _generated(e: Event, by_id: Mapping[str, Event], real: bool) -> Chain:
    """The text the chain generated for ``e``, its source, or why it has none."""

    for sentence in _cited(e, "fast.sentence", by_id):
        return _sentence(e, sentence, by_id, real)
    for released in _cited(e, "speak.released", by_id):
        for verbatim in _cited(released, "speak.verbatim", by_id):
            if verbatim.payload["lane"] != e.payload["lane"]:
                return None, None, "its speak.verbatim is for the other lane"
            return verbatim.payload["text"], released.event_id, None
    return None, None, "no chain to a fast.sentence or a released speak.verbatim"


def _delivered(
    e: Event, by_id: Mapping[str, Event], real: bool, used: set[str]
) -> str | None:
    generated, source, reason = _generated(e, by_id, real)
    heard, said = e.payload["text_heard"], e.payload["text_generated"]
    if reason is not None or source is None:
        return reason
    if source in used:
        return f"{source} is already delivered"
    used.add(source)
    if said != generated:
        return "text_generated differs from the chain's text"
    cut = e.payload["interrupted"] and isinstance(heard, str)
    if heard != said and not (cut and str(said).startswith(str(heard))):
        return "text_heard is neither the generated text nor, interrupted, a prefix"
    return None


def chain_failures(
    events: Sequence[Event], prompts: Mapping[str, PromptRecord], real_only: bool
) -> list[str]:
    """``real_only``: a Fast line's own call must be ``real_http`` (claims)."""

    by_id = {e.event_id: e for e in events}
    used: set[str] = set()
    failures: list[str] = []
    for e in events:
        reason = None
        if e.type == "fast.turn":
            reason = _turn(e, by_id, prompts)
        elif e.type == "utt.delivered":
            reason = _delivered(e, by_id, real_only, used)
        if reason is not None:
            failures.append(f"{e.type} {e.event_id}: {reason}")
    return failures
