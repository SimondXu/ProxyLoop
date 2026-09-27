"""S0-SYS-07 follow-up item 2, from run ``4ce0ad``: a FastC stream cut mid-delivery
(the rep hangs up) records ``error="cancelled"`` with the delivered text's sha,
and the lane stores that text, so the bundle reads offline. The FastC adapter
is the real one over a transport double; the other roles are scripted."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from tests.contract.samples import SONNET
from tests.kernel.test_session import SCRIPTS
from tests.llm.wire import chat_chunks, set_env, sse
from tests.support.manual_clock import ScaledClock
from tests.support.sessions import clients, fake_config, only_bundle, patient_task

from proxyloop.contract.base import sha256_text
from proxyloop.contract.llm import LLMClient, LLMRole, ModelRef
from proxyloop.evidence.check import check_path
from proxyloop.kernel.channels import Channel, Incoming
from proxyloop.kernel.session import run_session
from proxyloop.llm.factory import make_client
from proxyloop.llm.http import RecordSink

DELIVERED = "Could you"


class Rep(Channel):
    """Says one line, and hangs up once FastC's answer stalls."""

    def __init__(self) -> None:
        super().__init__()
        self.incoming.put_nowait(Incoming((("How can I help?", None),), due_ms=500))

    def hang_up(self) -> None:
        self.incoming.put_nowait(Incoming((), end="hangup"))


class Stalled(httpx.AsyncByteStream):
    """The first delta of FastC's answer, then nothing until the call ends."""

    def __init__(self, rep: Rep) -> None:
        chunks = chat_chunks(SONNET, [DELIVERED, " lower it?"])
        self.first, self.rep = sse(chunks[0], done=False), rep

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.first
        self.rep.hang_up()  # the delta is delivered: the lane asked for more
        await asyncio.Event().wait()


def test_a_stream_cut_mid_delivery_records_and_stores_what_was_delivered(
    tmp_path: Path, monkeypatch: Any
) -> None:
    set_env(monkeypatch, "relay")
    rep, clock = Rep(), ScaledClock(100)
    transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=Stalled(rep)))
    scripted = clients(SCRIPTS, clock, (), {})

    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        if role != "fast_cp":
            return scripted(role, ref, sink)
        now = clock.monotonic_ms
        return make_client(
            ref, live=False, clock=now, on_record=sink, transport=transport
        )

    cfg = fake_config().model_copy(update={"fast_cp": SONNET})
    session = run_session(
        cfg,
        patient_task(),
        {"user": "sim", "cp": rep},
        runs_dir=tmp_path,
        clock=clock,
        sleep=clock.sleep,
        clients=make,
    )
    result = asyncio.run(asyncio.wait_for(session, timeout=30))
    assert result.reason == "abandoned"
    bundle = only_bundle(tmp_path)
    (cut,) = [
        e.payload
        for e in bundle.events
        if e.type == "llm.call" and e.payload["role"] == "fast_cp"
    ]
    assert (cut["error"], cut["response_sha"]) == ("cancelled", sha256_text(DELIVERED))
    assert cut["t_first_token"] is not None
    cp_turns = [
        e for e in bundle.events if e.type == "fast.turn" and e.payload["lane"] == "cp"
    ]
    assert not cp_turns  # the cut call backs no line
    report = check_path(result.path, "offline")
    assert report.ok, report.failures
    assert bundle.prompts[sha256_text(DELIVERED)].content == DELIVERED
