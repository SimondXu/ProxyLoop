"""Slow reads the conversations (ADR-0016, S1-SYS-34) on a real, idle kernel
(the test is its only writer): the relay_only regression pin, the heard-only
fold -> view_slow -> request chain, the counterfactuals, the context shape and
the bounded 18-step context."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from tests.support.fakes import RepeatingLLM
from tests.support.manual_clock import ManualClock
from tests.support.sessions import act, fake, fake_config
from tests.support.sessions import patient_task as task

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.llm import LLMClient, LLMRole, ModelRef
from proxyloop.contract.messages import FastToSlow
from proxyloop.kernel.session import ChannelSpec, Kernel
from proxyloop.llm.http import RecordSink
from proxyloop.slow import prompt
from proxyloop.slow.loop import SlowLoop

SNAPSHOT = Path(__file__).parent / "snapshots" / "relay_only_requests.json"
NOTED = act("Noted.", public="Asking for a lower price.")
ASK = act("Asking.", {"tool": "ask_user", "text": "Any price limit?"})
SILENT = json.dumps({"text": "Thinking.", "tool_calls": []})


class Board:
    """A kernel that never runs (manual clock), and one Slow loop on it."""

    def __init__(
        self, tmp_path: Path, mode: SlowViewMode, script: list[str] | None = None
    ) -> None:
        self.clock, sinks = ManualClock(), dict[str, RecordSink]()

        def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
            sinks[role] = sink
            return RepeatingLLM(ref, ["unused"], self.clock, on_record=sink)

        cfg = fake_config().model_copy(update={"slow_view": mode})
        specs: dict[str, ChannelSpec] = {"user": "sim", "cp": "sim"}
        t = task()
        self.k = Kernel(cfg, t, specs, tmp_path, self.clock, asyncio.sleep, make, None)
        client = RepeatingLLM(
            fake("slow"), script or [NOTED], self.clock, on_record=sinks["slow"]
        )
        keys = frozenset(t.disclosure.shareable)
        self.slow = SlowLoop(self.k, client, t.slow_brief, keys)

    def emit(self, type_: str, payload: dict[str, Any], *causes: str) -> str:
        self.clock.advance(1_000)
        return self.k.emit(type_, "kernel", payload, list(causes)).event_id

    def user(self, text: str) -> str:
        return self.emit("user.msg", {"text": text})

    def rep(self, utt_id: str, text: str) -> str:
        said = {"lane": "cp", "speaker": "partner", "utt_id": utt_id, "text": text}
        return self.emit("utt.final", said)

    def heard(
        self, lane: str, utt_id: str, generated: str, heard: str, cause: str
    ) -> str:
        """FastC's sentence as generated, then what the listener heard."""
        sentence = {"lane": lane, "gen_id": "g", "utt_id": utt_id, "text": generated}
        said = self.emit("fast.sentence", sentence, cause)
        delivered = {"lane": lane, "utt_id": utt_id, "text_generated": generated}
        delivered |= {"text_heard": heard, "interrupted": heard != generated}
        return self.emit("utt.delivered", delivered, said)

    def relay(self, cause: str, **fields: Any) -> str:
        msg = FastToSlow(msg_id=self.k.next_event_id(), gen_id="g", **fields)
        return self.emit("f2s.msg", msg.model_dump(mode="json"), cause)

    def step(self, reason: str = "relay") -> None:
        asyncio.run(self.slow.step([reason]))

    def requests(self) -> list[list[dict[str, Any]]]:  # Slow's messages, in order
        calls = [e for e in self.k.bus.events if e.type == "llm.call"]
        shas = [str(e.payload["prompt_sha"]) for e in calls]
        return [json.loads(self.k.prompts[s].content)["messages"] for s in shas]

    def plain(self) -> str:
        """Every request, the run id normalised and the system prompt named."""
        out = []
        for messages in self.requests():
            system = messages[0]
            assert (system["role"], system["content"]) == ("system", prompt.SYSTEM)
            out.append([system | {"content": "<SYSTEM>"}, *messages[1:]])
        text = json.dumps(out, indent=1, ensure_ascii=True) + "\n"
        return text.replace(self.k.run_id, "RUN")


def conversation(b: Board, steps: int) -> None:
    """Both lanes talk every step; each lane's Fast relays a note."""
    for n in range(steps):
        said = b.user(f"user line {n} ZEBRA-QUILL")
        b.relay(said, lane="user", utt_ref=said, type="USER_UPDATE", text=f"<u{n}>")
        b.heard("user", f"chat-{n}", f"chat {n} and UNHEARD-CHAT", f"chat {n}", said)
        rep = b.rep(f"cp-{n}", f"rep line {n} OKAPI-MARBLE")
        b.heard("cp", f"phone-{n}", f"phone {n} and UNHEARD-PHONE", f"phone {n}", rep)
        b.relay(rep, lane="cp", utt_ref=f"cp-{n}", type="CP_UPDATE", text=f"<c{n}>")
        b.step()


RELAY_SCRIPT = [NOTED, SILENT, ASK, NOTED, SILENT, NOTED, ASK, SILENT, NOTED]


def test_relay_only_requests_equal_the_pre_transcript_ones(tmp_path: Path) -> None:
    """The regression pin (A5): under ``relay_only`` Slow's requests are byte
    for byte what they were before S1-SYS-34 (snapshot taken on that code;
    past the window, so the ``[EARLIER]`` head is pinned too)."""
    b = Board(tmp_path, SlowViewMode.RELAY_ONLY, RELAY_SCRIPT)
    conversation(b, len(RELAY_SCRIPT))
    got = b.plain()
    assert "ZEBRA" not in got and "OKAPI" not in got and "[CONVERSATIONS" not in got
    assert got == SNAPSHOT.read_text("utf-8")
    b.k.bus.close()
