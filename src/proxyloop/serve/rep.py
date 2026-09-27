"""The human rep's stream, ``/ws/rep/{case_id}`` (I4, AGENTS rule 8).

The rep's browser is the counterparty's side of the call, so it gets what
``FastView[cp]``'s public scope allows and nothing else (ARCHITECTURE §5,
views): the cp-lane speech as heard and the cp channel's state. Each frame is
rebuilt from ``REP_FIELDS`` as ``{"seq", "t_ms", "type", "payload"}``, never
the stored line: no ``text_generated``, summary, relay, offer, approval,
mandate, model or world event ever leaves. A field that is missing or of
another type drops the frame. ``seq`` is the stream's own (0, 1, 2, ... over
the allowed frames), so the count of hidden events never shows; ``from_seq``
skips that many allowed frames (the log is re-filtered from its start). It
tails ``events.jsonl`` like /ws/live (same close codes), plus 4403: the rep's
signed cookie pair is required (the Origin is checked by ``serve.api``), and a
user cookie never opens it.

Threat model: on this single-machine 127.0.0.1 server the user/rep split
guards only against cross-site requests and bugs in the web code, not against
a hostile local rep. ``GET /live`` needs no authentication, and ``/ws/live``
and ``/api/replay`` need no cookie, so no claim may say the rep is isolated.
Real rep isolation (a separate host, or authentication) comes later.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Annotated

from fastapi import FastAPI, Query, WebSocket

from proxyloop.contract.events import Event
from proxyloop.serve.bundles import redact
from proxyloop.serve.cases import Cases, open_case
from proxyloop.serve.csrf import Csrf
from proxyloop.serve.stream import follow

_CHANNEL = ("opened", "closed", "hold", "strike", "barge_in")
# The allow-list: FastView[cp]'s public scope, as the rep heard it. Only
# events whose payload lane is "cp"; utt.final only from the partner (the rep).
# Frames are renumbered: the original seq, which counts hidden events, never leaves.
REP_FIELDS: Mapping[str, Mapping[str, type]] = MappingProxyType(
    {
        "utt.final": {"lane": str, "speaker": str, "utt_id": str, "text": str},
        "utt.delivered": {
            "lane": str,
            "utt_id": str,
            "text_heard": str,  # never text_generated: only what was heard
            "interrupted": bool,
        },
    }
    | {f"chan.{kind}": {"lane": str} for kind in _CHANNEL}
)


class RepFrames:
    """One stream's frames: allowed events numbered 0, 1, 2, ...; the first
    ``skip`` of them are not sent."""

    def __init__(self, skip: int) -> None:
        self.skip, self.seq = skip, 0

    def __call__(self, event: Event, line: bytes) -> str | None:
        fields, p = REP_FIELDS.get(event.type), event.payload
        if fields is None or p.get("lane") != "cp":
            return None
        if event.type == "utt.final" and p.get("speaker") != "partner":
            return None
        kept = {name: p.get(name) for name in fields}
        if any(type(kept[name]) is not kind for name, kind in fields.items()):
            return None
        seq, self.seq = self.seq, self.seq + 1
        if seq < self.skip:
            return None
        frame = {"seq": seq, "t_ms": event.t_ms, "type": event.type}
        return redact(json.dumps(frame | {"payload": kept}).encode()).decode()


def add_rep_route(
    app: FastAPI, roots: Sequence[Path], cases: Cases | None, csrf: Csrf
) -> None:
    @app.websocket("/ws/rep/{case_id}")
    async def rep(
        ws: WebSocket, case_id: str, from_seq: Annotated[int, Query(ge=0)] = 0
    ) -> None:
        await ws.accept()  # first, so that the client sees the close code
        if cases is None:
            await ws.close(4404, "unknown case")
        elif not csrf.signed("rep", case_id, ws.cookies):
            await ws.close(4403, "not the rep of this case")
        elif (found := await open_case(roots, cases, case_id)) is None:
            await ws.close(4404, "unknown case")
        else:
            case, path = found
            await follow(ws, path, case.run_id, 0, RepFrames(from_seq))
