"""Stub cases for the web↔API wiring test (S1-SYS-18; tests only, I8).

A ``WiringCase`` implements ``proxyloop.serve.cases.Case`` over one run under
a tmp root. It writes through ``ApiCase`` (``tests.support.api_cases``): a real
``Bus`` validates every event against the contract registry and folds it, so
``blackboard()`` is the log's own fold, holding the card that
``guard.request_approval`` minted. The seed is what the user and rep pages
need: session.started (``test_fake`` refs), a cp call with one agent line as
heard, a private summary, a user message and the card.

It stands in for the kernel's ingress (S1-SYS-05) as ``Case`` documents it:
``post_approval`` only enqueues; ``DECIDE_AFTER_S`` later it re-runs
``guard.decide`` on its board and emits ``approval.post`` (ui) then
``approval.decided`` (kernel) citing it, or on a Denial the kernel's
``action.denied{intent: "approval.post"}`` citing the card's
``approval.requested``. ``Mode`` picks the path under test:

- ``ok``: nothing moves the board; the post is decided.
- ``stale``: a revoke (``authority.epoch``) lands just before serve reads the
  board for its pre-check: serve answers 409 stale and nothing is posted.
- ``refuse``: the revoke lands after serve's pre-check, before the re-decide:
  200, then ``action.denied`` with decide's reason.
- ``raise``: the handover raises, as a dead kernel would: serve answers 503.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from tests.support.api_cases import ApiCase

from proxyloop.contract.events import ApprovalPost
from proxyloop.contract.state import Blackboard
from proxyloop.guard.authorize import Denial, decide

Mode = Literal["ok", "stale", "refuse", "raise"]
DECIDE_AFTER_S = 2.0  # long enough for the page to show "sent" first, even loaded
ROLES = ("fast_user", "fast_cp", "slow")
STARTED: dict[str, object] = {
    "cfg_hash": "wiring",
    "task_ref": "wiring@1",
    "instance_hash": "wiring",
    "split": "train",
    "models": {
        role: {
            "ref": {"kind": "test_fake", "endpoint": None, "model_id": f"{role}-fake"}
        }
        for role in ROLES
    },
    "renderer_fp": {},
    "contract_version": "v1",
    "git_sha": "wiring",
    "attest": None,
    "parity": "not_applicable",
}
HEARD = "Hi, this is an AI assistant calling for Dana Reyes about her plan."
PRIVATE = "Private: Dana accepts at most 70 dollars a month."
USER_SAID = "Please get me a lower price."


class WiringCase:
    """Implements ``proxyloop.serve.cases.Case`` for run ``run_id`` under ``root``."""

    def __init__(self, root: Path, run_id: str, mode: Mode = "ok") -> None:
        self.run_id, self.mode = run_id, mode
        self._run = ApiCase(root, run_id)
        self._revoked = False
        self._utts = 0
        run = self._run
        run.emit("session.started", STARTED, "kernel", "ops", causes=())
        run.emit("chan.opened", {"lane": "cp"}, "kernel")
        delivered = {"lane": "cp", "utt_id": "agent-0", "interrupted": False}
        delivered |= {"text_generated": HEARD, "text_heard": HEARD}
        run.emit("utt.delivered", delivered, "kernel")
        run.emit("summary.updated", {"scope": "private", "text": PRIVATE}, "guard")
        run.emit("user.msg", {"text": USER_SAID}, "kernel", causes=())
        run.card()
        self.requested = run.bus.events[-1].event_id  # its approval.requested

    # The Case protocol.
    def blackboard(self) -> Blackboard:
        if self.mode == "stale":
            self._revoke()
        return self._run.bus.bb

    def post_approval(self, post: ApprovalPost) -> None:
        if self.mode == "raise":
            raise RuntimeError("the case's kernel is gone")
        asyncio.get_running_loop().call_later(DECIDE_AFTER_S, self._decide, post)

    def user_message(self, text: str) -> None:
        self._run.emit("user.msg", {"text": text}, "kernel", causes=())

    def rep_utterance(self, text: str) -> None:
        self._utts += 1
        said = {"lane": "cp", "speaker": "partner", "utt_id": f"rep-{self._utts}"}
        self._run.emit("utt.final", said | {"text": text}, "kernel", causes=())

    # The kernel's side.
    def _revoke(self) -> None:
        """One revoke per case: the epoch moves past the card."""
        if not self._revoked:
            self._revoked = True
            self._run.bump_epoch()

    def _decide(self, post: ApprovalPost) -> None:
        if self.mode == "refuse":
            self._revoke()
        got = decide(self._run.bus.bb, post, "ui")
        if isinstance(got, Denial):
            denied = {"intent": "approval.post", "reason": got.reason}
            self._run.emit("action.denied", denied, "kernel", causes=[self.requested])
            return
        sent = self._run.emit(
            "approval.post", post.model_dump(mode="json"), "ui", causes=()
        )
        kind, payload = got
        self._run.emit(kind, payload, "kernel", causes=[sent.event_id])

    def close(self) -> None:
        self._run.close()
