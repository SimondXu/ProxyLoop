"""Condition F through the one execution path: the FSM on both Fast lanes of a
``run_session`` whose other roles are fakes (tests/support)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import TypeAdapter
from tests.support.manual_clock import ScaledClock
from tests.support.sessions import (
    act,
    clients,
    ear,
    fake_config,
    only_bundle,
    patient_task,
    reply,
)

from proxyloop.contract.config import SessionConfig
from proxyloop.contract.llm import (
    AdapterKind,
    LLMCallRecord,
    LLMClient,
    LLMRole,
    ModelRef,
)
from proxyloop.contract.messages import FastToSlow
from proxyloop.contract.protocol import ParseIssue, TurnItem
from proxyloop.evidence.check import check_path
from proxyloop.kernel.session import ClientFactory, RunResult, run_session
from proxyloop.llm.http import RecordSink
from proxyloop.models.fsm import FsmTalker
from proxyloop.models.registry import condition

NAME = "Dana Reyes"
SCRIPTS = {
    "simuser": [reply(f"Please get me a lower price. I am {NAME}.")],
    "ear": [ear("other"), ear("ask_discount")],
    "mouth": ["I can do $75 a month for 12 months."],
    "slow": [
        act(
            "The user wants a lower price.",
            {"tool": "tell_user", "text": "I am calling them now."},
            public="Calling for a lower price.",
        ),
        act("Waiting for the call.", {"tool": "wait", "seconds": 5}),
    ],
}
ITEMS = TypeAdapter(list[TurnItem])
FINISH = act("Done.", {"tool": "finish", "outcome": "info_only", "summary": "ok"})


def test_condition_f_runs_a_session_that_passes_the_offline_check(
    tmp_path: Path,
) -> None:
    cfg = condition("F").apply(fake_config())
    clock = ScaledClock(100)
    others = clients(SCRIPTS, clock, (), {"slow": ("[REP CALL] hold", FINISH)})

    def make(role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        if ref.kind is AdapterKind.BASELINE:
            return FsmTalker(ref, clock.monotonic_ms, sink)
        return others(role, ref, sink)

    result = asyncio.run(asyncio.wait_for(_run(cfg, tmp_path, clock, make), 30))
    assert result.reason == "info_only"
    report = check_path(result.path, "offline")
    assert report.ok, report.failures
    events = only_bundle(tmp_path).events
    turns = [e.payload for e in events if e.type == "fast.turn"]
    assert {t["lane"] for t in turns} == {"user", "cp"}
    items = [i for t in turns for i in ITEMS.validate_python(t["items"])]
    assert items and not [i for i in items if isinstance(i, ParseIssue)]
    relays = [
        FastToSlow.model_validate(e.payload) for e in events if e.type == "f2s.msg"
    ]
    # the user's name is relayed typed; the rep's identity request is held
    assert (("name", NAME),) in [r.facts for r in relays if r.type == "USER_UPDATE"]
    assert "fact_request" in [r.text for r in relays if r.type == "HOLD"]
    calls = [
        LLMCallRecord.model_validate(e.payload) for e in events if e.type == "llm.call"
    ]
    fast = {c.adapter_kind for c in calls if c.role in ("fast_user", "fast_cp")}
    assert fast == {AdapterKind.BASELINE}


async def _run(
    cfg: SessionConfig, tmp_path: Path, clock: ScaledClock, make: ClientFactory
) -> RunResult:
    return await run_session(
        cfg,
        patient_task(),
        None,
        runs_dir=tmp_path,
        clock=clock,
        sleep=clock.sleep,
        clients=make,
    )
