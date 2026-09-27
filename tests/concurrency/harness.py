"""A real ``Kernel`` on virtual time, for the concurrency suite (tests only, I8).

``VirtualTime`` is a ``ManualClock`` whose ``sleep`` parks until ``run_for``
moves time past it, firing timers in due order: every interleaving is
deterministic. The user and the rep are silent channels the test speaks for;
FastU, FastC and Slow's own steps answer from scripts (``RepeatingLLM``). The
test plays Slow's tool calls through the session's real ``SlowTools.act`` (so
Guard decides every rule on ``Kernel.bb``) and the UI through
``Kernel.post_approval``.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path

from tests.support.fakes import RepeatingLLM
from tests.support.manual_clock import ManualClock
from tests.support.sessions import Gated, act, fake_config, patient_task

from proxyloop.contract.config import SessionConfig
from proxyloop.contract.events import ApprovalPost, Approver, Event
from proxyloop.contract.llm import LLMClient, LLMRole, ModelRef, ToolCall
from proxyloop.contract.state import ApprovalCard, Blackboard
from proxyloop.env.tasks.schema import Task
from proxyloop.guard.mandate import proposal
from proxyloop.kernel.channels import Channel, Incoming
from proxyloop.kernel.session import ChannelSpec, Kernel
from proxyloop.llm.http import RecordSink
from proxyloop.slow.tools import SlowTools

NOTED = act("Noted.")  # Slow's own step: a private summary, no tool
SCRIPTS: Mapping[str, Sequence[str]] = {
    "fast_user": ["Okay."],
    "fast_cp": ["Okay."],
    "slow": [NOTED],
}
LONG = " ".join(["word"] * 28)  # ten seconds of speech


def terms(dollars: int) -> str:
    return (
        f"It is ${dollars} a month on a 12-month term, no fees, no other "
        "changes, and the offer does not expire."
    )


def slots(dollars: int, utt: str) -> list[dict[str, str]]:
    rows = [
        ("monthly_price", str(100 * dollars), "usd_minor", "recurring"),
        ("term_months", "12", "months", "recurring"),
        ("fees_none", "true", "bool", "one_time"),
        ("changes_none", "true", "bool", "change"),
        ("expires", "none", "iso", "expiry"),
    ]
    keys = ("field", "value", "unit", "role")
    return [dict(zip(keys, row, strict=True)) | {"utt_ref": utt} for row in rows]


async def settle(turns: int = 40) -> None:
    for _ in range(turns):
        await asyncio.sleep(0)


class VirtualTime(ManualClock):
    def __init__(self) -> None:
        super().__init__()
        self._timers: list[tuple[int, int, asyncio.Future[None]]] = []
        self._n = 0

    async def sleep(self, seconds: float) -> None:
        wake = asyncio.get_running_loop().create_future()
        self._n += 1
        due = self.monotonic_ms() + max(0, round(seconds * 1000))
        heapq.heappush(self._timers, (due, self._n, wake))
        await wake

    async def run_for(self, ms: int) -> None:
        """Move time ``ms`` on, firing each due timer in order."""
        end = self.monotonic_ms() + ms
        await settle()
        while self._timers and self._timers[0][0] <= end:
            due, _, wake = heapq.heappop(self._timers)
            if wake.done():  # cancelled
                continue
            self.advance(max(0, due - self.monotonic_ms()))
            wake.set_result(None)
            await settle(12)  # work still pending when the next is due took that long
        self.advance(max(0, end - self.monotonic_ms()))
        await settle()


class Sim:
    """One session: ``start`` runs it, ``stop`` ends it (``stopped``)."""

    def __init__(
        self,
        root: Path,
        scripts: Mapping[str, Sequence[str]] | None = None,
        task: Task | None = None,
        user: ChannelSpec | None = None,
        gates: Mapping[str, Callable[[], Awaitable[None]]] | None = None,
        cfg: SessionConfig | None = None,
        until: Mapping[str, tuple[str, str]] | None = None,
    ) -> None:
        """``until``: role -> (marker, response), as ``RepeatingLLM``'s."""
        self.vt, self.rep = VirtualTime(), Channel()
        self.user = Channel() if user is None else user
        lines = {**SCRIPTS, **(scripts or {})}
        self.llms: dict[str, RepeatingLLM] = {}  # a test may kill one mid-session

        def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
            said = lines.get(role, ["unused"])
            mark = (until or {}).get(role)
            client = RepeatingLLM(ref, said, self.vt, False, sink, mark)
            self.llms[role] = client
            gate = (gates or {}).get(role)
            return client if gate is None else Gated(client, gate)

        specs: dict[str, ChannelSpec] = {"user": self.user, "cp": self.rep}
        task, cfg = task or patient_task(), cfg or fake_config()
        vt = self.vt
        self.k = Kernel(cfg, task, specs, root, vt, vt.sleep, make, None)
        self._run: asyncio.Task[object] | None = None
        self._rep = 0
        self.rep_turns: list[int] = []  # the next seq when each rep turn was queued
        self.rep_busy: list[list[int]] = []  # [from, to) seqs the rep composed in

    async def start(self) -> None:
        """Run the session past the disclosure (about 4 s of speech)."""
        self._run = asyncio.ensure_future(self.k.run())
        await self.vt.run_for(5_000)

    async def stop(self) -> tuple[Event, ...]:
        assert self._run is not None
        if not self._run.done():
            self._run.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._run
        return self.k.bus.events

    @property
    def bb(self) -> Blackboard:  # the fold as the log has it
        return self.k.bus.bb

    @property
    def events(self) -> tuple[Event, ...]:
        return self.k.bus.events

    def of(self, type_: str, **match: object) -> list[Event]:
        return [
            e
            for e in self.events
            if e.type == type_ and all(e.payload.get(k) == v for k, v in match.items())
        ]

    # The partners and the UI.
    def user_says(self, text: str) -> None:
        assert isinstance(self.user, Channel)
        self.user.incoming.put_nowait(Incoming(((text, None),)))

    def rep_says(self, text: str) -> None:
        self.rep_turns.append(len(self.k.bus.events))
        self.rep.incoming.put_nowait(Incoming(((text, None),)))

    def rep_composes(self) -> None:  # as SimRepChannel while the rep's LLM runs
        assert not self.rep.busy
        self.rep.composing(1)
        self.rep_busy.append([len(self.k.bus.events), -1])

    def rep_done(self, text: str | None = None) -> None:
        """The rep's turn ends: its reply (if any) queued, then it is quiet."""
        if text is not None:
            self.rep_says(text)
        self.rep.composing(-1)
        self.rep_busy[-1][1] = len(self.k.bus.events)

    def post(self, card: ApprovalCard, by: Approver = "ui", **change: object) -> None:
        post = {"subject": "approval", "subject_id": card.approval_id}
        post |= {"decision": "granted", "subject_hash": card.terms_hash}
        post |= {"authority_epoch": card.authority_epoch} | change
        self.k.post_approval(ApprovalPost.model_validate(post), by)

    # Slow's tool calls, through the session's own SlowTools.
    @property
    def tools(self) -> SlowTools:
        assert self.k.slow is not None
        return self.k.slow.tools

    def act(self, *calls: Mapping[str, object]) -> list[str]:
        body = json.dumps({"private_summary": "digest", "calls": list(calls)})
        call = ToolCall(call_id="t", name="act", arguments=body)
        return self.tools.act(call, [self.k.authority.root]).splitlines()[1:]

    async def offer(self, ref: str = "o1", dollars: int = 68) -> None:
        """The rep states an offer, Slow records it and asks for the read-back,
        and the rep reads it back: every slot confirmed (§9.2)."""
        self.rep_says(terms(dollars))
        await self.vt.run_for(3_000)
        utt = [x for x in self.bb.channels["cp"].lines if x.speaker == "partner"]
        record: dict[str, object] = {"tool": "record_offer", "offer_ref": ref}
        record["offer_slots"] = slots(dollars, utt[-1].utt_id)
        ask = {"tool": "guide_fast", "move": "ask_readback", "slots": [f"offer:{ref}"]}
        out = self.act(record, ask)
        assert f"read-back asked for {ref} r" in out[-1], out
        await self.vt.run_for(3_000)
        self.rep_says(terms(dollars))
        await self.vt.run_for(3_000)
        self.tools.readback()
        o = self.bb.public.offers[ref]
        assert {s.status for s in o.slots} == {"confirmed"} and o.terms_hash, o

    def card(self, ref: str = "o1") -> ApprovalCard:
        (text,) = self.act({"tool": "request_approval", "offer_ref": ref})
        assert "sent to the user" in text, text
        card = self.bb.private.pending_approval
        assert card is not None
        return card

    def accept(self, ref: str = "o1") -> str:
        (text,) = self.act({"tool": "accept_offer", "offer_ref": ref})
        return text

    def revoke(self) -> None:
        (text,) = self.act({"tool": "revoke"})
        assert text.startswith("revoke: revoked"), text

    def mandate(self, expires_ms: int) -> None:
        """A proposed mandate (unbounded but for its expiry) the UI grants."""
        kind, m = proposal(self.bb, "mandate-t", expires_ms=expires_ms)
        done: dict[str, object] = {"name": "propose_mandate", "args": {}}
        done |= {"result_text": "", "ok": True}
        tool = self.k.emit("slow.tool", "slow", done, [self.k.authority.root])
        self.k.emit(kind, "guard", m, [tool.event_id])
        post = {"subject": "mandate", "subject_id": m["mandate_id"]}
        post |= {"decision": "granted", "subject_hash": m["mandate_hash"]}
        post |= {"authority_epoch": m["epoch"]}
        self.k.post_approval(ApprovalPost.model_validate(post))


async def granted(sim: Sim, ref: str = "o1", dollars: int = 68) -> ApprovalCard:
    """An offer, its card and the UI's grant, decided by the kernel."""
    await sim.offer(ref, dollars)
    card = sim.card(ref)
    sim.post(card)
    await sim.vt.run_for(100)
    assert sim.bb.private.approvals[card.approval_id].decision == "granted"
    return card
