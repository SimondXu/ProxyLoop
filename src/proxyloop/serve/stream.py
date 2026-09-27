"""Following ``events.jsonl`` over a WebSocket (ARCHITECTURE §14): one tail for
/ws/live and /ws/rep, which differ only in what one event becomes (``Frame``).

Lines are sent in dense seq order from ``from_seq`` (an original seq), polling
the file for new bytes; reading and validation run in a worker thread, one
bounded chunk at a time. A gap, a bad line, another run's event, or a file
truncated, replaced or removed under the tail closes 1011, a held-out run 4404
(at seq 0), and ``session.ended`` 1000.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from proxyloop.contract.events import Event
from proxyloop.serve.bundles import held_out, redact

POLL_S = 0.05  # how often a stream looks for new bytes
CHUNK = 256 * 1024  # the most a stream reads and validates per step
Close = tuple[int, str]  # a WebSocket close code and reason
Frame = Callable[[Event, bytes], str | None]  # the text to send, or None: skip


def raw(event: Event, line: bytes) -> str:
    """/ws/live: the stored line itself, redacted."""
    return redact(line).decode("utf-8")


@dataclass
class Reader:
    """``events.jsonl`` read, split and validated in bounded steps."""

    file: BinaryIO
    run_id: str
    from_seq: int
    frame: Frame = raw
    seq: int = 0
    pending: bytes = b""  # a trailing partial line waits for its newline

    def step(self) -> tuple[list[str], Close | None, bool]:
        """One chunk: the frames to send, a close, and whether it was empty."""
        chunk = self.file.read(CHUNK)
        *lines, self.pending = (self.pending + chunk).split(b"\n")
        frames: list[str] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                event = Event.model_validate_json(line)
            except ValidationError:
                return frames, (1011, f"invalid line after seq {self.seq - 1}"), False
            if event.run_id != self.run_id or event.seq != self.seq:
                why = f"seq {event.seq} of {event.run_id}, {self.seq} expected"
                return frames, (1011, why), False
            if held_out(event):  # seq 0: nothing of a test-split run is sent
                return frames, (4404, "unknown run"), False
            self.seq += 1
            if event.seq >= self.from_seq and (text := self.frame(event, line)):
                frames.append(text)
            if event.type == "session.ended":
                return frames, (1000, "session ended"), False
        if not chunk and self.moved():  # else it would wait forever
            return frames, (1011, "events.jsonl was truncated or replaced"), False
        return frames, None, not chunk

    def moved(self) -> bool:
        """The open file shrank below what was read, or its path is gone or
        now names another file. (A truncation that has already regrown past
        the read position is not seen.)"""
        opened = os.fstat(self.file.fileno())
        try:
            now = os.stat(self.file.name)
        except FileNotFoundError:
            return True
        same = (now.st_ino, now.st_dev) == (opened.st_ino, opened.st_dev)
        return opened.st_size < self.file.tell() or not same


async def _tail(ws: WebSocket, reader: Reader) -> Close | None:
    """Send frames as the file grows. None: the client left."""
    while True:
        frames, close, empty = await asyncio.to_thread(reader.step)
        for frame in frames:
            try:
                await ws.send_text(frame)
            except WebSocketDisconnect:
                return None
        if close is not None:
            return close
        await asyncio.sleep(POLL_S if empty else 0)


async def _gone(ws: WebSocket) -> None:
    """Return when the client disconnects; frames it sends are ignored."""
    while (await ws.receive())["type"] != "websocket.disconnect":
        pass


async def follow(
    ws: WebSocket, path: Path, run_id: str, from_seq: int, frame: Frame = raw
) -> None:
    """Stream an accepted socket until the run ends, fails or the client leaves."""
    with path.open("rb") as f:
        tail = asyncio.create_task(_tail(ws, Reader(f, run_id, from_seq, frame)))
        gone = asyncio.create_task(_gone(ws))
        try:
            done, _ = await asyncio.wait(
                (tail, gone), return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (tail, gone):
                task.cancel()
            await asyncio.wait((tail, gone))
            if not gone.cancelled():
                gone.exception()  # retrieved: a failed receive means the client left
    if tail.cancelled():
        return
    close = tail.result()  # re-raises a real error
    if close is not None and gone not in done:
        await ws.close(*close)
