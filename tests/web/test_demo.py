"""The demo harness (S1-SYS-32) on the real kernel, headless: the browser E2E's
scripted cases (``tests.support.web_demo``) run through ``run_session`` on a
sped-up clock, and the bundle passes ``evidence.check`` offline.

What the kernel on main does, asserted as it is:
- readiness, in either order (S1-SYS-21's gate or main's call at the start):
  the call happens and the identity facts are public before the rep's offer;
- approve: the accept is released and heard, the rep confirms and closes the
  call, and the case stays COMMITTED: no FastC turn follows the closing line,
  so no confirmation is relayed and Slow cannot ``check_account``. The run is
  then stopped here (``stopped``), never shown as completed;
- stop: the fence rises on the user's message, FastU's revoke moves the epoch,
  the card goes stale, a post of it is refused by the kernel (``action.denied``
  ``stale_epoch``) and no accept is ever minted; the case stays
  AWAITING_APPROVAL.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from tests.support.manual_clock import ScaledClock
from tests.support.web_demo import FAMILY, LABEL, DemoStarter

from proxyloop.contract.bundle import read_bundle
from proxyloop.contract.events import ApprovalPost, Event
from proxyloop.contract.llm import AdapterKind
from proxyloop.evidence.check import check_path
from proxyloop.guard.authorize import Denial, decide
from proxyloop.kernel.web import WebCase
from proxyloop.serve.cases import StartRefused
from proxyloop.serve.start import broken

SPEED = 10.0  # session seconds per real second
TASK = f"{FAMILY}@1"
TASK_SAID = "Please lower my Crestline Wireless bill."
IDENTITY = "My name is Marcus Bell and my account ends in 5190."
STOP = "actually, stop"


def starter(tmp_path: Path) -> DemoStarter:
    clock = ScaledClock(SPEED)
    return DemoStarter(tmp_path / "runs", clock=clock, sleep=clock.sleep)


def events(case: WebCase, tmp_path: Path) -> list[Event]:
    run = tmp_path / "runs" / "live" / case.run_id / case.run_id / "events.jsonl"
    lines = run.read_text("utf-8").splitlines()
    return [Event.model_validate_json(x) for x in lines if x.strip()]


async def until(
    case: WebCase, tmp_path: Path, done: Callable[[list[Event]], bool]
) -> list[Event]:
    log = events(case, tmp_path)
    for _ in range(600):  # 60 s of real time
        if done(log := events(case, tmp_path)):
            return log
        await asyncio.sleep(0.1)
    raise AssertionError("timed out: " + json.dumps([e.type for e in log][-30:]))


def of(log: list[Event], type_: str, **match: object) -> list[Event]:
    return [
        e
        for e in log
        if e.type == type_ and all(e.payload.get(k) == v for k, v in match.items())
    ]


def body(e: Event) -> dict[str, Any]:
    return cast(dict[str, Any], e.payload)


def has(type_: str, **match: object) -> Callable[[list[Event]], bool]:
    return lambda log: bool(of(log, type_, **match))


async def to_card(s: DemoStarter, tmp_path: Path) -> tuple[WebCase, list[Event]]:
    """Start, state the task, answer the identity ask: up to the card."""
    case = await s.start_case(TASK, {})
    case.user_message(TASK_SAID)
    await until(case, tmp_path, has("s2f.msg", type="ASK_USER"))
    case.user_message(IDENTITY)
    return case, await until(case, tmp_path, has("approval.requested"))


def stop_fence(log: list[Event]) -> Event:
    (stop,) = of(log, "user.msg", text=STOP)
    raised = of(log, "authority.fence", op="raised")
    (fence,) = [e for e in raised if e.cause_ids == (stop.event_id,)]
    return fence


def stop_cleared(log: list[Event]) -> bool:
    if not of(log, "user.msg", text=STOP):
        return False
    fence = stop_fence(log).payload["fence_id"]
    return bool(of(log, "authority.fence", op="cleared", fence_id=fence))


def post(card: dict[str, Any]) -> ApprovalPost:
    return ApprovalPost(
        subject="approval",
        subject_id=card["approval_id"],
        decision="granted",
        subject_hash=card["terms_hash"],
        authority_epoch=card["authority_epoch"],
    )


def test_the_options_are_stub_test_fake_and_serve_takes_them(tmp_path: Path) -> None:
    s = starter(tmp_path)
    options, tasks = s.model_options(), s.task_options()
    assert broken(options, tasks) is None
    assert {o.label for o in options} == {LABEL}
    assert {o.lane for o in options} == {"fast_user", "fast_cp", "slow"}
    assert list(tasks) == [TASK]


@pytest.mark.parametrize(
    ("task_ref", "models", "reason"),
    [
        ("cp-direct-discount@1", {}, "unknown_task"),
        (TASK, {"slow": "stub:nope"}, "unknown_model"),
        (TASK, {"slow": "stub:fast_cp"}, "wrong_lane"),
    ],
)
def test_a_refused_start_names_its_reason(
    tmp_path: Path, task_ref: str, models: dict[str, str], reason: str
) -> None:
    async def case() -> None:
        with pytest.raises(StartRefused, match=reason):
            await starter(tmp_path).start_case(task_ref, cast(Any, models))

    asyncio.run(case())
    assert not (tmp_path / "runs").exists()


def test_approve_on_the_real_kernel_up_to_the_closed_call(tmp_path: Path) -> None:
    async def case() -> list[Event]:
        s = starter(tmp_path)
        case, log = await to_card(s, tmp_path)
        with pytest.raises(StartRefused, match="busy"):
            await s.start_case(TASK, {})
        (card,) = of(log, "approval.requested")
        case.post_approval(post(card.payload))
        await until(case, tmp_path, has("chan.closed", lane="cp"))
        await s.stop()
        return events(case, tmp_path)

    log = asyncio.run(case())
    ids = {e.event_id: e for e in log}
    started = body(log[0])["models"]
    assert {m["ref"]["kind"] for m in started.values()} == {"test_fake"}
    assert set(started) == {"fast_user", "fast_cp", "slow", "ear", "mouth"}
    # readiness, order-agnostic: the call happens, and the identity facts are
    # public (from the user's words) before the rep's first offer
    assert of(log, "chan.opened", lane="cp")
    facts = of(log, "fact.recorded", scope="public", source="shareable")
    assert {f.payload["key"] for f in facts} == {"account.holder_name", "account.last4"}
    offered = [e for e in of(log, "rep.policy") if body(e)["intent"]["kind"] == "offer"]
    assert max(f.seq for f in facts) < offered[0].seq
    # the offer, read back and confirmed, then the card
    assert body(of(log, "rep.policy")[0])["intent"]["kind"] == "greet"
    (card,) = of(log, "approval.requested")
    confirmed = of(log, "readback.updated", revision=card.payload["revision"])
    assert set(body(confirmed[-1])["slot_statuses"].values()) == {"confirmed"}
    # the UI's post, decided by the kernel
    (posted,) = of(log, "approval.post")
    (decided,) = of(log, "approval.decided")
    assert posted.actor == "ui" and decided.actor == "kernel"
    assert (decided.payload["by"], decided.payload["decision"]) == ("ui", "granted")
    assert decided.cause_ids == (posted.event_id,)
    # the accept: minted, released with its capability, heard
    (said,) = of(log, "speak.verbatim", kind="accept")
    (released,) = [e for e in of(log, "speak.released") if said.event_id in e.cause_ids]
    assert released.payload["cap_id"] == said.payload["cap_id"]
    (heard,) = [e for e in of(log, "utt.delivered") if released.event_id in e.cause_ids]
    assert heard.payload["text_heard"] == said.payload["text"]
    assert ids[said.cause_ids[0]].type == "slow.tool"
    # the rep commits and closes the call; the case stays COMMITTED (the wall)
    assert of(log, "rep.commit_heard") and of(log, "ledger.write")
    statuses = [e.payload["status"] for e in of(log, "status.changed")]
    assert statuses[-1] == "COMMITTED" and not of(log, "completion.decided")
    assert log[-1].payload["reason"] == "stopped"
    run = tmp_path / "runs" / "live" / log[0].run_id / log[0].run_id
    assert check_path(run, "offline").failures == ()
    manifest = read_bundle(run).manifest
    assert set(manifest.reality.values()) == {AdapterKind.TEST_FAKE}
    assert not manifest.cfg.live  # never a live run: live mode takes real_http only


def test_stop_fences_and_the_stale_card_is_refused_by_the_kernel(
    tmp_path: Path,
) -> None:
    async def case() -> tuple[list[Event], object]:
        s = starter(tmp_path)
        case, log = await to_card(s, tmp_path)
        (card,) = of(log, "approval.requested")
        case.user_message(STOP)
        await until(case, tmp_path, has("authority.epoch", reason="f2s_revoke"))
        await until(case, tmp_path, stop_cleared)
        got = decide(case.blackboard(), post(card.payload), "ui")  # serve's pre-check
        # the card, approved after the stop: straight to the kernel's queue (serve
        # would answer 409 stale first, the e2e's path); the kernel decides
        case.post_approval(post(card.payload))
        await until(case, tmp_path, has("action.denied", intent="approval.post"))
        await s.stop()
        return events(case, tmp_path), got

    log, got = asyncio.run(case())
    (stop,) = of(log, "user.msg", text=STOP)
    raised = stop_fence(log)
    fence = raised.payload["fence_id"]
    (cleared,) = of(log, "authority.fence", op="cleared", fence_id=fence)
    assert cleared.seq > raised.seq
    (bump,) = of(log, "authority.epoch", reason="f2s_revoke")
    (revoke,) = of(log, "f2s.msg", type="REVOKE")
    assert bump.cause_ids == (revoke.event_id,) and bump.seq > stop.seq
    assert isinstance(got, Denial) and got.reason == "stale_epoch"  # 409 stale
    # the kernel's own outcome for the stale post: refused, citing the card
    (card,) = of(log, "approval.requested")
    (denied,) = of(log, "action.denied", intent="approval.post")
    assert (denied.actor, denied.payload["reason"]) == ("kernel", "stale_epoch")
    assert denied.cause_ids == (card.event_id,) and denied.seq > bump.seq
    assert not of(log, "approval.post") and not of(log, "approval.decided")
    assert not of(log, "action.authorized") and not of(
        log, "speak.verbatim", kind="accept"
    )
    kinds = {e.payload["kind"] for e in of(log, "speak.verbatim")}
    assert kinds == {"disclosure"} and len(of(log, "speak.released")) == 1
    # the stale card replans (S1-SYS-38): the bump moves it to NEEDS_REPLAN,
    # Slow's next step back to IN_CALL; nothing is ever authorized
    (replan,) = of(
        log, "status.changed", previous="AWAITING_APPROVAL", status="NEEDS_REPLAN"
    )
    assert bump.event_id in replan.cause_ids
    resumed = of(log, "status.changed", previous="NEEDS_REPLAN", status="IN_CALL")
    assert resumed and resumed[0].seq > replan.seq
    assert not of(log, "status.changed", status="COMMIT_AUTHORIZED")
