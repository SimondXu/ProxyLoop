"""A bundle's ``events.jsonl`` as OTel-shaped spans (ADR-0008), offline.

The mapping is pure: events in, ``SpanRecord`` out, with no OTel import (the
OTLP adapter is ``obs.otlp``, loaded only to export). One trace per run, rooted
at ``session.started``; one span per event; the first cause is the parent and
the others are links. Attributes are built from an allow-list (default deny):
the envelope and named non-content keys. ``content`` adds only what I4 makes
public: cp-lane text and ``fast_cp`` prompts. Sealed data (AGENTS rule 11) is
refused before any span is emitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeGuard, cast

from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS, PromptRecord
from proxyloop.contract.events import Event
from proxyloop.contract.llm import LLMCallRecord
from proxyloop.obs.runs import Seal, head, sealed

Value = str | int | float | bool | tuple[str, ...]
Sink = Callable[[Sequence["SpanRecord"]], None]
PHOENIX = "http://127.0.0.1:6006/v1/traces"
_SERVICES = {"fast.user": "user", "fast.cp": "cp", "slow": "slow"} | {
    a: a for a in ("guard", "kernel", "ui", "sim_approver")
}
# Non-content payload keys (ADR-0008); ``name``/``ok`` only on slow.tool, and
# ``move`` is the GUIDE's enum.
_ALLOWED = (
    "lane", "gen_id", "utt_id", "call_id", "trigger", "reason", "basis_seq",
    "ttft_ms", "ttfs_ms", "offer_ref", "revision", "scope", "status", "previous",
)  # fmt: skip
_TOOL = ("name", "ok")
# Authority payloads never leave the bundle, whatever their keys.
_ENVELOPE_ONLY = ("approval.", "mandate.", "declass.denied")
# The cp-lane text I4 makes public: the rep's lines and the agent's heard lines.
_CP_TEXT = {"utt.final": "text", "utt.delivered": "text_heard"}


class Refused(Exception):
    """The bundle is, or may be, sealed held-out data (AGENTS rule 11)."""


@dataclass(frozen=True)
class SpanRecord:
    trace_id: str  # 32 hex digits
    span_id: str  # 16 hex digits
    parent_id: str | None
    links: tuple[str, ...]
    name: str
    start_ns: int
    end_ns: int
    service: str
    attributes: Mapping[str, Value]
    status: Literal["UNSET", "ERROR"] = "UNSET"


def trace_id(run_id: str) -> str:
    return hashlib.sha256(run_id.encode()).hexdigest()[:32]


def span_id(event_id: str) -> str:
    return hashlib.sha256(event_id.encode()).hexdigest()[:16]


def check(run: Path, seal: Seal) -> None:
    """Raise ``Refused`` unless the bundle is unsealed and its split is known
    and not ``test``. Reads only the manifest or the first line."""
    if seal.covers(run) or sealed(run, seal):
        raise Refused(f"{run} is sealed held-out data (AGENTS rule 11)")
    at = head(run)
    if at is None:
        raise Refused(f"{run}: no {MANIFEST} and no session.started, so no split")
    if at["split"] == "test":
        raise Refused(f"{run} has split test (AGENTS rule 11)")


def lines(path: Path, follow: bool, poll_s: float = 0.2) -> Iterator[str]:
    """Complete lines only: a partial last line waits for its newline. When
    following, an idle poll yields ``""``."""
    with path.open("rb") as f:
        rest = b""
        while True:
            chunk = f.read(1 << 16)
            if not chunk:
                if not follow:
                    return
                yield ""
                time.sleep(poll_s)
                continue
            *done, rest = (rest + chunk).split(b"\n")
            yield from (x.decode("utf-8") for x in done if x.strip())


class Prompts:
    """``prompts.jsonl`` by sha, re-read on a miss (the bundle may be growing)."""

    def __init__(self, path: Path) -> None:
        self.path, self._by_sha = path, dict[str, str]()

    def get(self, sha: str) -> str | None:
        if sha not in self._by_sha and self.path.is_file():
            for line in lines(self.path, follow=False):
                record = PromptRecord.model_validate_json(line)
                self._by_sha[record.sha] = record.content
        return self._by_sha.get(sha)


class Mapper:
    """Events → spans, one event at a time, in log order."""

    def __init__(self, prompts: Prompts | None = None) -> None:
        self.prompts = prompts  # None: no content
        self._origin_ns: int | None = None
        self._root: str | None = None

    def span(self, event: Event) -> SpanRecord:
        if self._root is None:
            if event.type != "session.started":
                raise Refused("the first event is not session.started: no split")
            if event.payload.get("split") == "test":
                raise Refused("session.started has split test (AGENTS rule 11)")
            self._origin_ns = _ns(event.wall) - event.t_ms * 1_000_000
            self._root = span_id(event.event_id)
            parent = None
        else:
            parent = span_id(event.cause_ids[0]) if event.cause_ids else self._root
        start = end = self._at(event.t_ms)
        attrs = _envelope(event)
        status: Literal["UNSET", "ERROR"] = "UNSET"
        if event.type == "llm.call":
            record = LLMCallRecord.model_validate(event.payload)
            start, end = self._at(record.t_start), self._at(record.t_end)
            attrs |= self._llm(record)
            service = record.role
            status = "UNSET" if record.error is None else "ERROR"
        else:
            attrs |= self._payload(event)
            service = _service(event.actor)
        return SpanRecord(
            trace_id=trace_id(event.run_id),
            span_id=span_id(event.event_id),
            parent_id=parent,
            links=tuple(span_id(c) for c in event.cause_ids[1:]),
            name=event.type,
            start_ns=start,
            end_ns=end,
            service=service,
            attributes=attrs,
            status=status,
        )

    def _at(self, t_ms: int) -> int:
        """session.started's wall, on the session clock (``t_ms``)."""
        assert self._origin_ns is not None
        return self._origin_ns + t_ms * 1_000_000

    def _payload(self, event: Event) -> dict[str, Value]:
        if event.type.startswith(_ENVELOPE_ONLY):
            return {}
        p = event.payload
        keys = _ALLOWED + (_TOOL if event.type == "slow.tool" else ())
        attrs: dict[str, Value] = {}
        for k in keys:
            if _scalar(v := p.get(k)):
                attrs[f"pl.{k}"] = v
        guide = p.get("guide")
        guide = cast(dict[str, object], guide) if isinstance(guide, dict) else {}
        if _scalar(move := guide.get("move")):
            attrs["pl.move"] = move
        key = _CP_TEXT.get(event.type)
        public = self.prompts is not None and p.get("lane") == "cp"
        if public and key and _scalar(text := p.get(key)):
            attrs[f"pl.{key}"] = text
        return attrs

    def _llm(self, r: LLMCallRecord) -> dict[str, Value]:
        attrs: dict[str, Value] = {
            "pl.call_id": r.call_id,
            "pl.role": r.role,
            "pl.attempt": r.attempt,
            "gen_ai.request.model": r.requested_model,
        }
        if r.served_model_echo is not None:
            attrs["gen_ai.response.model"] = r.served_model_echo
        if r.model_ref.endpoint is not None:
            attrs["pl.endpoint"] = r.model_ref.endpoint
        if r.usage is not None:
            attrs["gen_ai.usage.input_tokens"] = r.usage.prompt_tokens
            attrs["gen_ai.usage.output_tokens"] = r.usage.completion_tokens
            if r.usage.reasoning_tokens is not None:
                attrs["pl.usage.reasoning_tokens"] = r.usage.reasoning_tokens
        prompts = self.prompts if r.role == "fast_cp" else None
        if prompts is not None and (prompt := prompts.get(r.prompt_sha)) is not None:
            attrs["pl.prompt"] = prompt
        return attrs


def export(run: Path, sink: Sink, content: bool = False, follow: bool = False) -> int:
    """Map the bundle at ``run`` and hand its spans to ``sink``: all at once,
    or when following, per poll until ``session.ended``. Returns the count."""
    seal = Seal()
    if seal.covers(run):  # never stat inside sealed data, even to wait
        raise Refused(f"{run} is sealed held-out data (AGENTS rule 11)")
    while follow and not _ready(run):
        time.sleep(0.2)
    check(run, seal)
    mapper = Mapper(Prompts(run / PROMPTS) if content else None)
    batch: list[SpanRecord] = []
    total = 0
    for line in lines(run / EVENTS, follow):
        if line:
            event = Event.model_validate_json(line)
            batch.append(mapper.span(event))
            if not follow or event.type != "session.ended":
                continue
        if batch:  # an idle poll, or session.ended
            sink(batch)
            total, batch = total + len(batch), []
        if line:
            break
    if batch:
        sink(batch)
        total += len(batch)
    return total


def _ready(run: Path) -> bool:
    """A manifest, or a complete first line to read the split from."""
    if (run / MANIFEST).is_file():
        return True
    if not (run / EVENTS).is_file():
        return False
    with (run / EVENTS).open("rb") as f:
        return f.readline().endswith(b"\n")


def _envelope(event: Event) -> dict[str, Value]:
    return {
        "pl.event_id": event.event_id,
        "pl.t_ms": event.t_ms,
        "pl.actor": event.actor,
        "pl.stream": event.stream,
        "pl.cause_ids": event.cause_ids,
        "pl.type": event.type,
    }


def _service(actor: str) -> str:
    if actor.startswith("world."):
        return "world"
    if actor not in _SERVICES:
        raise ValueError(f"actor {actor!r} has no service (ADR-0008)")
    return _SERVICES[actor]


def _scalar(value: object) -> TypeGuard[str | int | float | bool]:
    return isinstance(value, str | int | float | bool)


def _ns(wall: datetime) -> int:
    delta = wall - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 10**9 + delta.microseconds * 1000


def to_json(records: Sequence[SpanRecord]) -> str:
    return json.dumps([asdict(r) for r in records], indent=1, default=dict)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m proxyloop.obs.trace")
    parser.add_argument("run", type=Path, metavar="RUN")
    parser.add_argument("--endpoint", nargs="?", const=PHOENIX, metavar="URL")
    parser.add_argument("--content", action="store_true")
    parser.add_argument("--json", type=Path, metavar="OUT")
    parser.add_argument("--follow", action="store_true")
    args = parser.parse_args(argv)
    endpoint = args.endpoint or (None if args.json else PHOENIX)
    kept: list[SpanRecord] = []
    sinks: list[Sink] = [kept.extend] if args.json else []
    if endpoint is not None:
        from proxyloop.obs import otlp  # the only OTel import, and a lazy one

        exporter = otlp.exporter(endpoint)
        sinks.append(lambda batch: otlp.export(batch, exporter))

    def sink(batch: Sequence[SpanRecord]) -> None:
        for each in sinks:
            each(batch)

    try:
        n = export(args.run, sink, args.content, args.follow)
    except Refused as err:
        print(f"refused: {err}", file=sys.stderr)
        return 2
    if args.json:
        args.json.write_text(to_json(kept), "utf-8")
    print(f"{n} spans" + (f" → {endpoint}" if endpoint else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
