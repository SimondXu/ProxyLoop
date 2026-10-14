"""A SimUser that only chats (``sim_chat``, S1-SYS-127): a person in the web
UI decides its cards. Its own approval button never posts (rule 10: the UI or
the sim approver, here the UI), its ``after_card`` trigger still runs, and the
person's decision reaches its chat (ADR-0028: one principal, one answer)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from tests.concurrency.harness import Sim
from tests.concurrency.test_cases import arun

from proxyloop.contract.events import ApprovalPost
from proxyloop.contract.state import ApprovalCard, Mandate
from proxyloop.env.user.simuser import SimUser
from proxyloop.kernel.channels import SimUserChannel


class ChatOnly:
    """The parts of ``SimUser`` its channel calls; silent in the chat."""

    def __init__(self) -> None:
        self.approver = object()  # a button the channel must hide
        self.decided: list[tuple[ApprovalCard | Mandate, ApprovalPost]] = []
        self.triggers: list[str] = []

    def on_decided(self, subject: ApprovalCard | Mandate, post: ApprovalPost) -> None:
        self.decided.append((subject, post))

    async def on_agent_message(self, text: str | None, cause: str) -> None:
        return None

    async def on_trigger(self, kind: str, cause: str) -> None:
        self.triggers.append(kind)
        return None


def test_a_chat_only_sim_user_leaves_its_card_to_the_ui(tmp_path: Path) -> None:
    async def case() -> None:
        user = ChatOnly()
        sim = Sim(tmp_path, user=SimUserChannel(cast(SimUser, user), approves=False))
        await sim.start()
        await sim.offer()
        card = sim.card("o1")
        await sim.vt.run_for(3_000)
        assert not sim.of("approval.post"), "nobody approves for the user"
        assert user.triggers == ["after_card"]
        sim.post(card)  # the person, through the UI endpoint
        await sim.vt.run_for(100)
        (decided,) = sim.of("approval.decided")
        assert decided.payload["decision"] == "granted"
        ((subject, post),) = user.decided
        assert subject == card and post.decision == "granted"
        await sim.stop()

    arun(case())
