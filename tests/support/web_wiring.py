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
- ``authority``: as ``ok``, with what the authority strip and the card's
  read-back progress show (S1-SYS-31), in the kernel's order (#173 N-3):
  Guard's ``status.changed`` INTAKE → IN_CALL, the offer as first stated
  (``o1`` r1) with a partial ``readback.updated`` (the price ``heard``), then
  the read-back revision (r2) confirmed and its card, AWAITING_APPROVAL, the
  user's "actually, stop", the kernel's fence on it, a ``speak.revoked`` and
  an ``action.denied``. No slot goes back from confirmed after the card. Each
  through the real Bus, from its fixed emitter.

``WiringStarter`` implements ``proxyloop.serve.cases.Starter`` (S1-SYS-31):
stub options for the three lanes (labelled "stub", with contract endpoints,
as serve requires), ``TASKS``, and a new ``WiringCase`` per start. The task
picks a failure: ``REFUSING`` maps a task to the ``StartRefused`` reason it
gets, ``wire-dead-kernel`` raises (serve: 503), and ``broken_options`` makes
``model_options`` break serve's promise (two defaults on a lane: serve 500).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from tests.guard.build import offer
from tests.support.api_cases import ApiCase

from proxyloop.contract.events import ApprovalPost
from proxyloop.contract.state import Blackboard
from proxyloop.guard.authorize import Denial, decide
from proxyloop.serve.cases import LaneKey, ModelOption, StartRefused

Mode = Literal["ok", "stale", "refuse", "raise", "authority"]
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
STOP = "actually, stop"
OPTIONS = tuple(
    ModelOption(
        id=f"stub:{lane}:{n}",
        lane=lane,
        label=f"stub {lane} {n}",
        endpoint="vllm" if lane != "slow" else "teamrouter",
        model_id=f"{lane}-stub-{n}",
        default=n == 2,  # not the first: the page must preselect the default
    )
    for lane in ("fast_user", "fast_cp", "slow")
    for n in (1, 2)
)
REFUSING: dict[str, str] = {"wire-unknown-model": "unknown_model", "wire-busy": "busy"}
DEAD = "wire-dead-kernel"
TASKS = ("wire-start", "wire-start-human", *REFUSING, DEAD)


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
        if mode == "authority":
            self._partial()
        run.card(revision=2 if mode == "authority" else 1)
        self.requested = run.bus.events[-1].event_id  # its approval.requested
        if mode == "authority":
            self._authority()

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

    def _partial(self) -> None:
        """Before the card: the call, and the offer as first stated (r1) with
        only its price heard; the card's read-back revision (r2) comes next."""
        run = self._run
        run.emit("status.changed", {"previous": "INTAKE", "status": "IN_CALL"})
        stated = offer("o1")
        kept = stated.model_dump(
            mode="json", include={"offer_ref", "revision", "slots"}
        )
        run.emit("offer.recorded", kept | {"terms_hash": None})
        statuses = {s.field: "unknown" for s in stated.slots} | {
            "monthly_price": "heard"
        }
        partial = {"offer_ref": "o1", "revision": 1, "slot_statuses": statuses}
        run.emit("readback.updated", partial | {"terms_hash": None})

    def _authority(self) -> None:
        run = self._run
        waiting = {"previous": "IN_CALL", "status": "AWAITING_APPROVAL"}
        run.emit("status.changed", waiting)
        stop = run.emit("user.msg", {"text": STOP}, "kernel", causes=())
        fence = {"op": "raised", "fence_id": "fence-1", "utt_id": stop.event_id}
        run.emit("authority.fence", fence, "kernel")
        run.emit("speak.revoked", {"lane": "cp", "reason": "fence"}, "kernel")
        denied = {"intent": "accept_offer", "reason": "fence_raised"}
        run.emit("action.denied", denied, "kernel")

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


class WiringStarter:
    """Implements ``proxyloop.serve.cases.Starter`` over ``root``: each start
    seeds a new ``WiringCase`` (mode ``ok``) named ``started-<n>``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.cases: list[WiringCase] = []
        self.calls: list[tuple[str, dict[LaneKey, str], str]] = []
        self.broken_options = False

    def model_options(self) -> Sequence[ModelOption]:
        if self.broken_options:  # two defaults on a lane, bypassing validation
            return (
                *OPTIONS,
                OPTIONS[0].model_copy(update={"id": "stub:again", "default": True}),
            )
        return OPTIONS

    def task_options(self) -> Sequence[str]:
        return TASKS

    async def start_case(
        self,
        task_ref: str,
        models: Mapping[LaneKey, str],
        rep: Literal["sim", "human"] = "sim",
    ) -> WiringCase:
        self.calls.append((task_ref, dict(models), rep))
        if task_ref == DEAD:
            raise RuntimeError("the kernel is gone")
        if task_ref in REFUSING:
            raise StartRefused(REFUSING[task_ref])
        if task_ref not in TASKS:
            raise StartRefused("unknown_task")
        lanes = {o.id: o.lane for o in OPTIONS}
        if any(lanes.get(option) != lane for lane, option in models.items()):
            raise StartRefused(
                "unknown_model" if set(models.values()) - set(lanes) else "wrong_lane"
            )
        case = WiringCase(self.root, f"started-{len(self.cases) + 1}")
        self.cases.append(case)
        return case
