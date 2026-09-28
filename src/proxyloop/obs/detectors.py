"""Triage detectors over one bundle: pure functions of (events, manifest, prompts).

ADVISORY ONLY: triage signals, never a metric, a claim or a merge gate (and
never imported by ``proxyloop.eval``).

``DETECTORS`` maps a name to ``fn(Inputs) -> value``: a number, a per-role
count, a dict with a ``count`` and the seqs behind it, or ``None`` when the
bundle cannot tell. An unknown is never 0. By default values carry ids,
codes and numbers only; the text-reading detectors (the hand-off claim in
``relay_gap``, the closing reply in ``grading``) run only with ``content`` and
are ``None`` otherwise, and only with ``content`` does ``end_world_error`` add
the kernel-authored world_error message. ``grading`` adds the H5 detectors, and
``ladder`` the offer-ladder ones, to this one registry.

A detector that reads rep.ear labels must pair each with the line it cites
(its ``utt_id``), never with the nearest line in time: the Ear lags FastC by
about a turn (L-CORE's 21988c diagnosis).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cached_property
from itertools import pairwise
from typing import cast

from proxyloop.contract import protocol as fp
from proxyloop.contract.bundle import Manifest
from proxyloop.contract.events import Event
from proxyloop.contract.llm import LLMCallRecord
from proxyloop.obs.trace import identifier

BANNER = "advisory triage signals: not metrics, not claims, not a merge gate"
Value = object
_PAUSES = (fp.Hold, fp.Wait)
_DIRECTIVES = (fp.Relay, fp.Hold, fp.Wait, fp.EndCall)
_STALE = frozenset({"identify", "hold_for_fact", "deflect_fact_request"})
# Hand-offs FastU may claim to the user; a negation earlier in the same
# sentence ("I haven't passed that along") voids the match. A bare "forward"
# is no claim ("I look forward to it").
_HANDOFF = re.compile(
    r"\bpass(?:ed|ing)? (?:it |that |this |those |these |them )?(?:along|on)\b"
    r"|\brelay(?:ed|ing)?\b|\bforward(?:ed|ing)\b"
    r"|\blet (?:them|the rep|the representative) know\b"
    r"|\bcheck(?:ing)? with (?:them|the rep|the representative)\b"
    r"|\b(?:i've|i have) (?:shared|sent|told them)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"n't\b|\b(?:not|never|cannot|unable)\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?\u2026][\"'\u201d\u2019)\]]*\s*$")
_SENTENCE = re.compile(r"[.!?\u2026]\s")  # a sentence break inside a line
_ERROR_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}")
_HTTP = re.compile(r"\bHTTP (\d{3})\b")


@dataclass(frozen=True)
class Turn:
    seq: int
    gen_id: str
    lane: str
    record: LLMCallRecord | None  # the turn's llm.call, final attempt
    # the raw response in the BASE grammar on purpose (the raw output); a
    # detector that needs the live parse re-parses with ``profile``
    items: tuple[fp.TurnItem, ...] | None  # None: missing
    text: str | None  # the raw response; None: missing
    profile: str | None  # its fast.request's profile; None: no fast.request


class Inputs:
    """One bundle as the detectors see it; derived views are computed once."""

    def __init__(
        self,
        events: Sequence[Event],
        manifest: Manifest | None,
        prompt: Callable[[str], str | None],
        relay_window_ms: int = 10_000,
        content: bool = False,
    ) -> None:
        self.events, self.manifest, self.prompt = tuple(events), manifest, prompt
        self.relay_window_ms, self.content = relay_window_ms, content

    @cached_property
    def by_id(self) -> dict[str, Event]:
        return {e.event_id: e for e in self.events}

    def of(self, *types: str) -> list[Event]:
        return [e for e in self.events if e.type in types]

    @cached_property
    def calls(self) -> list[tuple[int, LLMCallRecord]]:
        calls = self.of("llm.call")
        return [(e.seq, LLMCallRecord.model_validate(e.payload)) for e in calls]

    @cached_property
    def turns(self) -> list[Turn]:
        last = {r.call_id: r for _, r in self.calls}
        profile = {
            str(e.payload["gen_id"]): str(e.payload["profile"])
            for e in self.of("fast.request")
        }
        out: list[Turn] = []
        for e in self.of("fast.turn"):
            p = e.payload
            record = last.get(str(p["call_id"]))
            sha = record.response_sha if record else None
            text = self.prompt(sha) if sha else None
            lane = "cp" if p["lane"] == "cp" else "user"
            items = None if text is None else fp.parse_turn(text, lane)  # base grammar
            gen = str(p["gen_id"])
            out.append(Turn(e.seq, gen, lane, record, items, text, profile.get(gen)))
        return out


Detector = Callable[[Inputs], Value]
DETECTORS: dict[str, Detector] = {}


def detector(name: str) -> Callable[[Detector], Detector]:
    def register(fn: Detector) -> Detector:
        DETECTORS[name] = fn
        return fn

    return register


def run_all(x: Inputs) -> dict[str, Value]:
    return {name: fn(x) for name, fn in sorted(DETECTORS.items())}


def scalar(value: Value) -> int | float | None:
    """One number per detector for the cross-run table (None: unknown)."""
    if value is None or isinstance(value, int | float):
        return value
    if isinstance(value, list):
        return len(cast(list[object], value))
    if isinstance(value, dict):
        d = cast(dict[str, object], value)
        if "count" in d:
            return scalar(d["count"])
        if all(isinstance(v, int) for v in d.values()):
            return sum(cast(dict[str, int], d).values())
    return None


def safe(value: object) -> object:
    """An identifier, number or bool as is; any other value is withheld."""
    return value if value is None or identifier(value) else "?"


def as_dict(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _per_role(keep: Callable[[LLMCallRecord], bool]) -> Detector:
    return lambda x: dict(Counter(r.role for _, r in x.calls if keep(r)))


DETECTORS["llm_calls"] = lambda x: len(x.calls)
DETECTORS["fast_turns"] = lambda x: len(x.turns)
DETECTORS["slow_steps"] = lambda x: len(x.of("slow.step.started"))
DETECTORS["declass_denied"] = lambda x: len(x.of("declass.denied"))
DETECTORS["llm_errors"] = _per_role(lambda r: r.error not in (None, "cancelled"))
DETECTORS["llm_cancelled"] = _per_role(lambda r: r.error == "cancelled")
DETECTORS["finish_length"] = _per_role(lambda r: r.finish_reason == "length")
DETECTORS["finish_reason_null"] = _per_role(lambda r: r.finish_reason is None)


@detector("end_reason")
def _end(x: Inputs) -> Value:
    ends = x.of("session.ended")
    return safe(ends[-1].payload.get("reason")) if ends else None


@detector("end_world_error")
def _world_error(x: Inputs) -> Value:
    """session.ended ``world_error`` (S1-SYS-43): ``world_error_type``, and
    its kernel-authored ``world_error_message`` only with ``content``. ``{}``:
    the session ended for another reason (known: none). None: no end, or a
    ``world_error`` end without the key (a bundle from before it)."""
    ends = x.of("session.ended")
    if not ends:
        return None
    end = ends[-1].payload
    if not (err := as_dict(end.get("world_error"))):
        return None if end.get("reason") == "world_error" else {}
    out: dict[str, object] = {"world_error_type": safe(err.get("type"))}
    if x.content:
        out["world_error_message"] = err.get("message")
    return out


@detector("first_llm_error")
def _first_error(x: Inputs) -> Value:
    """The first failed call (not a cancellation): role, seq, the error's type
    and HTTP code, never its text; ``{}``: no call failed."""
    for seq, r in x.calls:
        if r.error not in (None, "cancelled"):
            kind, code = _ERROR_TYPE.match(r.error), _HTTP.search(r.error)
            return {
                "role": r.role,
                "seq": seq,
                "type": kind.group() if kind else "?",
                "http": int(code.group(1)) if code else None,
            }
    return {}


@detector("slow_max_step_gap_ms")
def _slow_gap(x: Inputs) -> Value:
    """From session.started to the first step, then step to step; None: no step."""
    ts = [e.t_ms for e in x.of("session.started", "slow.step.started")]
    return max((b - a for a, b in pairwise(ts)), default=None)


@detector("slow_last_step_to_end_ms")
def _slow_tail(x: Inputs) -> Value:
    """From the last slow.step.started to the log's last event; None: no step."""
    steps = x.of("slow.step.started")
    return x.events[-1].t_ms - steps[-1].t_ms if steps else None


def _after(items: Sequence[fp.TurnItem], marks: tuple[type, ...]) -> int:
    """Speech items after the first ``marks`` item."""
    n, seen = 0, False
    for item in items:
        seen = seen or isinstance(item, marks)
        n += seen and isinstance(item, fp.Speech)
    return n


@detector("speech_after_directive")
def _speech_after(x: Inputs) -> Value:
    """Speech items after the first directive in each Fast turn's raw
    response, parsed by the contract parser's base grammar; ``turns`` lists
    [seq, items]; ``count`` None: no turn could be read."""
    turns: list[list[int]] = []
    unknown: list[int] = []
    for t in x.turns:
        if t.items is None:
            unknown.append(t.seq)
        elif n := _after(t.items, _DIRECTIVES):
            turns.append([t.seq, n])
    count = _known(sum(n for _, n in turns), unknown, x)
    return {"count": count, "turns": turns, "unknown": unknown}


def _known(count: int, unknown: list[int], x: Inputs) -> int | None:
    """None when there were turns and none could be read: no clean 0."""
    return None if unknown and len(unknown) == len(x.turns) else count


@detector("speech_after_pause")
def _speech_after_pause(x: Inputs) -> Value:
    """Speech after a Hold/Wait in each Fast turn's raw response, in the
    grammar of its fast.request ``profile`` (the contract parser): ``items``,
    Speech items after the pause on a profile without ``pause_ends_speech``;
    ``issues``, ParseIssue(speech_after_pause) on one with it (pl_cp_v3, one
    per line, ADR-0017); ``count``, both (None: no turn could be read);
    ``turns`` lists [seq, n];
    ``unknown``: no response, or a missing or unknown profile."""
    turns: list[list[int]] = []
    unknown: list[int] = []
    items = issues = 0
    for t in x.turns:
        spec = fp.PROFILES.get(t.profile or "")
        if t.items is None or t.text is None or spec is None or spec.lane != t.lane:
            unknown.append(t.seq)
            continue
        if spec.pause_ends_speech:
            parsed = fp.parse_turn(t.text, spec.lane, t.profile)
            n = sum(
                isinstance(i, fp.ParseIssue) and i.reason == "speech_after_pause"
                for i in parsed
            )
            issues += n
        else:
            n = _after(t.items, _PAUSES)
            items += n
        if n:
            turns.append([t.seq, n])
    return {"count": _known(items + issues, unknown, x), "items": items,
            "issues": issues,
            "turns": turns, "unknown": unknown}  # fmt: skip


@detector("empty_length")
def _empty_length(x: Inputs) -> Value:
    """Fast turns cut at the length cap whose response, parsed in its
    fast.request ``profile``'s grammar, holds no speech item (on pl_cp_v3 a
    line after a Hold/Wait is no speech, ADR-0017); ``unknown``: no llm.call
    record, no response, or a missing or unknown profile (as in
    ``speech_after_pause``); ``count`` None: every capped turn is unknown."""
    turns: list[int] = []
    unknown: list[int] = []
    capped = [
        t for t in x.turns if t.record is None or t.record.finish_reason == "length"
    ]
    for t in capped:
        spec = fp.PROFILES.get(t.profile or "")
        if t.record is None or t.text is None or spec is None or spec.lane != t.lane:
            unknown.append(t.seq)
        elif not any(
            isinstance(i, fp.Speech)
            for i in fp.parse_turn(t.text, spec.lane, t.profile)
        ):
            turns.append(t.seq)
    count = None if unknown and len(unknown) == len(capped) else len(turns)
    return {"count": count, "turns": turns, "unknown": unknown}


@detector("unterminated_voiced")
def _unterminated(x: Inputs) -> Value:
    """Voiced lines (fast.sentence) never delivered, delivered interrupted, or
    ``cut``: the last line of a length-capped turn, with no closing mark.
    ``unknown``: last lines whose turn has no llm.call record (cap unknown)."""
    delivered = {str(e.payload["utt_id"]): e for e in x.of("utt.delivered")}
    capped = {t.gen_id: t.record.finish_reason == "length" for t in x.turns if t.record}
    out: dict[str, list[int]] = {"undelivered": [], "interrupted": [], "cut": []}
    unknown: list[int] = []
    last: dict[str, Event] = {}
    for s in x.of("fast.sentence"):
        d = delivered.get(str(s.payload["utt_id"]))
        if d is None:
            out["undelivered"].append(s.seq)
        elif d.payload.get("interrupted") is True:
            out["interrupted"].append(s.seq)
        last[str(s.payload.get("gen_id"))] = s
    for gen, s in last.items():
        if gen not in capped:
            unknown.append(s.seq)
        elif capped[gen] and not _SENTENCE_END.search(str(s.payload.get("text", ""))):
            out["cut"].append(s.seq)
    out["cut"].sort()
    count = len({s for seqs in out.values() for s in seqs})
    return {"count": count} | out | {"unknown": sorted(unknown)}


@detector("relay_gap")
def _relay_gap(x: Inputs) -> Value:
    """(a) ``flagged``: user.msg with no user-lane f2s.msg citing it (utt_ref)
    within the window, from ids and timing; ``unknown`` when the log ends first.
    ``sim_revealed``: the flagged ones whose user.sim cause revealed facts
    (world data). (b) ``handoff_claims``: flagged messages whose heard FastU
    reply in the window claims a hand-off; only with ``content``, else None."""
    by_id = x.by_id
    end = x.events[-1].t_ms if x.events else 0
    relayed: dict[str, list[int]] = {}
    for f in x.of("f2s.msg"):
        if f.payload.get("lane") == "user":
            relayed.setdefault(str(f.payload.get("utt_ref")), []).append(f.t_ms)
    flagged, unknown = list[Event](), list[int]()
    for msg in x.of("user.msg"):
        close = msg.t_ms + x.relay_window_ms
        if any(t <= close for t in relayed.get(msg.event_id, [])):
            continue
        if end < close:
            unknown.append(msg.seq)
        else:
            flagged.append(msg)
    revealed = [
        m.seq
        for m in flagged
        if any(by_id[c].type == "user.sim" and as_dict(by_id[c].payload.get("revealed"))
               for c in m.cause_ids)
    ]  # fmt: skip
    return {
        "count": len(flagged),
        "flagged": [m.seq for m in flagged],
        "unknown": unknown,
        "sim_revealed": revealed,
        "handoff_claims": _claims(x, flagged) if x.content else None,
    }


def _claims(x: Inputs, flagged: Sequence[Event]) -> list[dict[str, object]]:
    heard = [e for e in x.of("utt.delivered") if e.payload.get("lane") == "user"]
    hits: list[dict[str, object]] = []
    for msg in flagged:
        for d in heard:
            if not msg.t_ms <= d.t_ms <= msg.t_ms + x.relay_window_ms:
                continue
            text = str(d.payload.get("text_heard", "")).replace("\u2019", "'")
            m = _HANDOFF.search(text)
            before = _SENTENCE.split(text[: m.start()])[-1] if m else ""
            if m and not _NEGATION.search(before):  # in this sentence only
                hits.append({"seq": msg.seq, "reply_seq": d.seq, "phrase": m.group()})
                break
    return hits


@detector("stale_identity_guides")
def _stale(x: Inputs) -> Value:
    """cp GUIDEs with an identity move after the rep's IDENTIFY→DISCOVER; None:
    the bundle has no rep.policy (no world rep to read)."""
    policy = x.of("rep.policy")
    if not policy:
        return None
    moved = [
        e.seq
        for e in policy
        if (e.payload["from"], e.payload["to"]) == ("IDENTIFY", "DISCOVER")
    ]
    if not moved:
        return {"count": 0, "seqs": []}
    seqs = [
        e.seq
        for e in x.of("s2f.msg")
        if e.seq > moved[0] and as_dict(e.payload.get("guide")).get("move") in _STALE
    ]
    return {"count": len(seqs), "seqs": seqs}


@detector("max_consecutive_ok_hold")
def _ok_hold(x: Inputs) -> Value:
    """The longest run of consecutive rep.policy events whose intent is
    ``ok_hold`` (the rep agreeing to wait again); None: no rep.policy."""
    policy = x.of("rep.policy")
    if not policy:
        return None
    best = run = 0
    for e in policy:
        run = run + 1 if as_dict(e.payload["intent"]).get("kind") == "ok_hold" else 0
        best = max(best, run)
    return best


@detector("guide_to_heard_ms")
def _guide_to_heard(x: Inputs) -> Value:
    """From each GUIDE s2f.msg to the first utt.delivered of a generation that
    voiced it (s2f.voiced msg_id → gen_id; fast.sentence utt_id → gen_id). A
    voicing generation that was cancelled (``fast.cancelled``; S1-SYS-59's
    ``verbatim`` comes after its s2f.voiced) is replaced by its re-run
    (``_reruns``), followed through further cancellations; ``cancelled``:
    guides with such a generation. On bundles before #230, or when the GUIDE
    is no longer its lane's newest, the re-run voices no s2f.voiced for it (the
    fold dropped it from ``s2f_pending``): its view shows only the newest GUIDE
    (``guidance_cp``), so a guide another GUIDE on its lane followed before the
    re-run's fast.request is ``superseded``, never credited with the re-run's
    lines. After #230 a re-run that acts voices the lane's newest GUIDE again
    (a second s2f.voiced): both voicings lead to the re-run, counted once.
    ``unheard``: guides never voiced or delivered; ``unknown``: those the log
    ends on within the relay window (as in ``relay_gap``), or whose cancelled
    generation has no re-run."""
    gens: dict[str, list[str]] = {}
    for v in x.of("s2f.voiced"):
        gens.setdefault(str(v.payload["msg_id"]), []).append(str(v.payload["gen_id"]))
    gen_of = {
        str(s.payload["utt_id"]): str(s.payload["gen_id"])
        for s in x.of("fast.sentence")
    }
    first: dict[str, int] = {}
    for d in x.of("utt.delivered"):
        gen = gen_of.get(str(d.payload["utt_id"]))
        if gen is not None:
            first.setdefault(gen, d.t_ms)
    reruns = _reruns(x)
    asked = {str(r.payload["gen_id"]): r.seq for r in x.of("fast.request")}
    guides = [g for g in x.of("s2f.msg") if g.payload.get("type") == "GUIDE"]
    ms: list[int] = []
    unheard = unknown = cancelled = superseded = 0
    end = x.events[-1].t_ms if x.events else 0
    for g in guides:
        voicing = gens.get(str(g.payload["msg_id"]), [])
        cancelled += any(n in reruns for n in voicing)
        speakers = [(n, _follow(n, reruns)) for n in voicing]
        lane = g.payload.get("lane")
        newer = [
            h.seq for h in guides if h.seq > g.seq and h.payload.get("lane") == lane
        ]
        replaced = [  # a re-run whose view held a newer GUIDE instead
            n
            for n, run in speakers
            if run not in (None, n) and any(s < asked[str(run)] for s in newer)
        ]
        heard = [
            first[run]
            for n, run in speakers
            if run is not None and run in first and n not in replaced
        ]
        if heard:
            ms.append(min(heard) - g.t_ms)
        elif any(run is None for _, run in speakers):
            unknown += 1
        elif replaced:
            superseded += 1
        elif end < g.t_ms + x.relay_window_ms:
            unknown += 1
        else:
            unheard += 1
    ms.sort()
    return {
        "count": len(ms),
        "p50": _rank(ms, 0.5),
        "p90": _rank(ms, 0.9),
        "unheard": unheard,
        "unknown": unknown,
        "cancelled": cancelled,
        "superseded": superseded,
        "ms": ms,
    }


def _reruns(x: Inputs) -> dict[str, str | None]:
    """Each cancelled generation's re-run: the kernel re-queues a cancelled
    generation's trigger first (lanes.py ``_again``), so its re-run is the
    first later fast.request on the same ``lane`` with the same ``trigger``
    kind whose ``basis_seq`` is at or after the fast.cancelled (its board holds
    the cancellation). Causes are not compared: a newer trigger of the same
    kind absorbs the re-queued one. None: the cancelled generation has no
    fast.request, or no request matches."""
    asked = x.of("fast.request")
    by_gen = {str(r.payload["gen_id"]): r for r in asked}
    out: dict[str, str | None] = {}
    for c in x.of("fast.cancelled"):
        gen, run = str(c.payload["gen_id"]), None
        if (own := by_gen.get(gen)) is not None:
            same = [own.payload.get(k) for k in ("lane", "trigger")]
            run = next(
                (
                    str(r.payload["gen_id"])
                    for r in asked
                    if [r.payload.get(k) for k in ("lane", "trigger")] == same
                    and _at_or_after(r.payload.get("basis_seq"), c.seq)
                ),
                None,
            )
        out[gen] = run
    return out


def _at_or_after(basis: object, seq: int) -> bool:
    return isinstance(basis, int) and not isinstance(basis, bool) and basis >= seq


def _follow(gen: str, reruns: dict[str, str | None]) -> str | None:
    """The generation that finally ran for ``gen``; None: a re-run is missing,
    or the chain loops (only a malformed ``basis_seq`` can make one)."""
    seen = {gen}
    while gen in reruns:
        if (nxt := reruns[gen]) is None or nxt in seen:
            return None
        seen.add(gen := nxt)
    return gen


def _rank(xs: Sequence[int], q: float) -> int | None:
    """Nearest-rank percentile; None for no data."""
    return xs[max(math.ceil(q * len(xs)) - 1, 0)] if xs else None


@detector("hold_repeats")
def _holds(x: Inputs) -> Value:
    """The kernel's own count (session.ended ``counts.hold_repeat``); None: no
    end record, or no ``counts``. ``counts`` is a Counter (kernel/lanes.py,
    ``k.counts["hold_repeat"] += 1``), which omits zeros: a missing key is 0."""
    ends = x.of("session.ended")
    if not ends or not isinstance(ends[-1].payload.get("counts"), dict):
        return None
    return as_dict(ends[-1].payload["counts"]).get("hold_repeat", 0)


from proxyloop.obs import grading as grading  # noqa: E402  (registers H5)
from proxyloop.obs import ladder as ladder  # noqa: E402  (registers the ladder)
from proxyloop.obs import tiers as tiers  # noqa: E402  (registers the tier)
