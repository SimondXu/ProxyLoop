"""A ``WorldSink`` over the real ``Bus`` (the only writer) for the env tests;
``llm`` builds scripted clients whose every record goes to ``World.record``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from tests.support.fakes import ScriptedLLM, fake_ref
from tests.support.manual_clock import ManualClock

from proxyloop.contract.base import sha256_text
from proxyloop.contract.events import Event
from proxyloop.core.bus import Bus
from proxyloop.env.world import World


class BusSink:
    def __init__(self, tmp_path: Path) -> None:
        self.clock = ManualClock()
        self.bus = Bus(tmp_path / "events.jsonl", "r1", self.clock)
        self.prompts: dict[str, tuple[str, str]] = {}  # sha -> (kind, content)
        self._root = self.bus.emit("user.msg", "kernel", "agent", {"text": "start"})
        self.world = World(self)

    def llm(
        self, *responses: str, dead: bool = False, hang_s: float = 0
    ) -> ScriptedLLM:
        return ScriptedLLM(
            fake_ref(), responses, dead=dead, on_record=self.world.record, hang_s=hang_s
        )

    def emit(
        self,
        type_: str,
        actor: str,
        payload: Mapping[str, object],
        causes: Sequence[str],
    ) -> str:
        return self.bus.emit(type_, actor, "world", payload, causes).event_id

    def store(self, kind: Literal["messages", "response"], content: str) -> None:
        self.prompts[sha256_text(content)] = (kind, content)

    def heard(self, text: str, lane: str = "cp") -> Event:
        """An agent line as delivered: the cause world reactions cite."""

        payload = {"lane": lane, "utt_id": f"u{self.bus.events[-1].seq + 1}"}
        payload |= {"text_generated": text, "text_heard": text, "interrupted": False}
        return self.bus.emit(
            "utt.delivered", "kernel", "agent", payload, [self._root.event_id]
        )

    def of(self, type_: str) -> list[Event]:
        return [e for e in self.bus.events if e.type == type_]
