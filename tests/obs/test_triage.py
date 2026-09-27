"""The triage report over a fixture bundle: counters equal hand counts, the
default output carries no content, and sealed or test-split bundles are refused.

Every event of ``_bundle`` is at ``t_ms = seq * 100`` (``bundles.Log``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from tests.contract.samples import GEMINI, QWEN
from tests.obs.bundles import Log, manifest, write

from proxyloop.contract.bundle import PROMPTS, PromptRecord
from proxyloop.contract.llm import LLMCallRecord, LLMRole, ModelRef
from proxyloop.obs import triage

P = dict[str, object]
WINDOW_S = 1.0  # the relay window: 1,000 ms
# cp-g1: one speech line, the directive, then three sentences on two lines.
CP_G1 = "Please hold.\n@hold fact_request\nStray one. Stray two.\nAgain."
# user-g1: a sentence, a relay line, then one more sentence.
USER_G1 = "Noted.\n@slow: note PRIV-relay-note\nThanks."


def _call(log: Log, role: LLMRole, ref: ModelRef, call_id: str, **kw: object) -> str:
    fields: dict[str, object] = {
        "call_id": call_id,
        "role": role,
        "model_ref": ref,
        "adapter_kind": ref.kind,
        "requested_model": ref.model_id,
        "served_model_echo": ref.model_id,
        "request_id": None,
        "prompt_sha": "p",
        "response_sha": f"resp-{call_id}",
        "usage": None,
        "t_start": 0,
        "t_first_token": None,
        "t_end": 1,
        "finish_reason": "stop",
        "attempt": 0,
    } | kw
    record = LLMCallRecord.model_validate(fields).model_dump(mode="json")
    actor = {"fast_user": "fast.user", "fast_cp": "fast.cp", "slow": "slow"}[role]
    return log.add("llm.call", actor, "agent", record, (log.start,))


def _turn(log: Log, lane: str, gen_id: str, call_id: str, cause: str) -> str:
    payload: P = {"lane": lane, "gen_id": gen_id, "call_id": call_id, "items": []}
    return log.add(
        "fast.turn",
        f"fast.{lane}",
        "agent",
        payload | {"ttft_ms": 1, "ttfs_ms": 1},
        (cause,),
    )


def _said(log: Log, revealed: dict[str, str] | None, text: str) -> str:
    """A user.msg; with ``revealed`` it is caused by a user.sim."""
    causes: tuple[str, ...] = ()
    if revealed is not None:
        sim: P = {"text": text, "revealed": revealed, "delay_s": 1.0}
        causes = (log.add("user.sim", "world.simuser", "world", sim, (log.start,)),)
    return log.add("user.msg", "kernel", "agent", {"text": text}, causes)


def _bundle(root: Path, split: str = "train") -> Path:
    log = Log("rT", split)  # 0 session.started, t=0
    log.add("slow.step.started", "slow", "agent", {"basis_seq": 0, "wake_reasons": []})
    facts = {"account.last4": "PRIV-5190"}
    unrelayed = _said(log, facts, "PRIV-msg-unrelayed")  # 2 sim, 3 msg (t=300)
    _said(log, {}, "PRIV-msg-nofacts")  # 4 sim, 5 msg: no facts
    _said(log, None, "PRIV-msg-human")  # 6 msg: no user.sim
    relayed = _said(log, facts, "PRIV-msg-relayed")  # 7 sim, 8 msg (t=800)
    u1 = _call(log, "fast_user", QWEN, "u1")  # 9
    turn = _turn(log, "user", "user-g1", "u1", u1)  # 10
    f2s: P = {"msg_id": "rT:11", "lane": "user", "gen_id": "user-g1"}
    f2s |= {"utt_ref": relayed, "type": "USER_UPDATE", "text": "PRIV-f2s-text"}
    f2s |= {"facts": [["account.last4", "PRIV-5190"]]}
    log.add("f2s.msg", "fast.user", "agent", f2s, (turn,))  # 11 (t=1100)
    c1 = _call(log, "fast_cp", QWEN, "c1", finish_reason="length")  # 12
    _turn(log, "cp", "cp-g1", "c1", c1)  # 13
    _call(log, "slow", GEMINI, "s1", finish_reason=None, error="HTTP 500")  # 14
    _turn(log, "cp", "cp-g2", "c-none", c1)  # 15: no llm.call c-none
    log.add("slow.step.started", "slow", "agent", {"basis_seq": 15, "wake_reasons": []})
    tool: P = {"name": "act", "args": {"note": "PRIV-args"}, "ok": True}
    tool["result_text"] = "PRIV-result"
    step = log.add("slow.tool", "slow", "agent", tool, (log.start,))  # 17
    evil: P = {"name": "PRIV-tool", "args": {}, "ok": False, "result_text": "PRIV-r2"}
    log.add("slow.tool", "slow", "agent", evil, (step,))  # 18
    s2f: P = {"msg_id": "s2f-1", "lane": "user", "type": "ASK_USER", "text": "PRIV-ask"}
    log.add("s2f.msg", "guard", "agent", s2f, (step,))  # 19
    intent: P = {"kind": "greet", "offer_ref": None, "say": ["PRIV-say"], "ask": []}
    policy: P = {"from": "GREET", "to": "IDENTIFY", "intent": intent, "rung": None}
    log.add("rep.policy", "world.policy", "world", policy)  # 20
    denied: P = {"intent": "guide_fast", "reason": "guide_slot_not_public"}
    log.add("action.denied", "slow", "agent", denied, (step,))  # 21
    status: P = {"previous": "INTAKE", "status": "IN_CALL"}
    log.add("status.changed", "guard", "agent", status, (step,))  # 22
    fence: P = {"op": "raised", "fence_id": "fence-1", "utt_id": unrelayed}
    log.add("authority.fence", "kernel", "agent", fence, (unrelayed,))  # 23
    log.add("slow.step.started", "slow", "agent", {"basis_seq": 23, "wake_reasons": []})
    late = _said(log, facts, "PRIV-msg-late")  # 25 sim, 26 msg (t=2600)
    end: P = {"reason": "abandoned", "counts": {"hold_repeat": 3, "relay_rejected": 1}}
    log.add("session.ended", "kernel", "ops", end)  # 27 (t=2700)
    assert late.endswith(":26")
    path = write(root / "rT", log, manifest("rT", split=split))
    records = [("resp-c1", CP_G1), ("resp-u1", USER_G1)]
    text = "\n".join(
        PromptRecord(sha=s, kind="response", content=c).model_dump_json()
        for s, c in records
    )
    (path / PROMPTS).write_text(text + "\n", "utf-8")
    return path


def test_counters_equal_hand_counts(tmp_path: Path) -> None:
    report = triage.triage(_bundle(tmp_path), relay_window_s=WINDOW_S)
    c = report["counters"]
    assert isinstance(c, dict)
    assert c["slow_steps"] == 3  # seqs 1, 16, 24
    # gaps: 0→100 = 100, 100→1600 = 1500, 1600→2400 = 800
    assert c["slow_step_max_gap_ms"] == 1500
    assert c["llm_errors"] == {"slow": 1}  # s1
    assert c["finish_length"] == {"fast_cp": 1}  # c1
    assert c["finish_reason_null"] == {"slow": 1}  # s1; unknown, not "stop"
    # cp-g1: "Stray one." + "Stray two." + "Again." = 3 after @hold;
    # user-g1: "Thanks." = 1 after the @slow line; 3 + 1 = 4
    assert c["speech_after_directive"] == {
        "total": 4,
        "gens": {"cp-g1": 3, "user-g1": 1},
        "unknown": ["cp-g2"],  # no llm.call
    }
    assert c["hold_repeats"] == 3  # session.ended counts
    # rT:3 (t=300): facts, no f2s, and the log runs past 300 + 1000;
    # rT:8 is relayed at t=1100 <= 800 + 1000; rT:5 revealed nothing
    # rT:6 has no user.sim; rT:26 (t=2600) ends the log before 2600 + 1000
    assert c["user_facts_unrelayed"] == {
        "flagged": ["rT:3"],
        "unknown": ["rT:6", "rT:26"],
    }
    assert report["header"] == {
        "run_id": "rT",
        "git_sha": "g",
        "task_ref": "cp-direct-discount@1",
        "split": "train",
        "mode": None,  # session.started names no models
        "models": {},
        "ended": "abandoned",
        "duration_ms": 2700,
    }


def test_the_default_timeline_has_codes_only(tmp_path: Path) -> None:
    rows = cast(list[P], triage.triage(_bundle(tmp_path))["timeline"])
    by_seq = {r["seq"]: r for r in rows}
    assert by_seq[17] == {
        "seq": 17,
        "t_ms": 1700,
        "type": "slow.tool",
        "name": "act",
        "ok": True,
        "result_len": 11,
    }
    assert by_seq[18]["name"] == "unknown"  # not one of Slow's tools
    assert by_seq[20] == {
        "seq": 20,
        "t_ms": 2000,
        "type": "rep.policy",
        "from": "GREET",
        "to": "IDENTIFY",
        "intent": "greet",
    }
    assert by_seq[21]["reason"] == "guide_slot_not_public"
    assert by_seq[11]["msg_type"] == "USER_UPDATE"
    assert by_seq[11]["n_facts"] == 1


def test_default_output_has_no_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _bundle(tmp_path)
    for args in ([], ["--json"]):
        assert triage.main([str(run), *args]) == 0
        out = capsys.readouterr().out
        assert "PRIV" not in out
    json.loads(out)  # the last one was --json
    assert triage.main([str(run), "--content", "--json"]) == 0
    content = capsys.readouterr().out
    for marker in ("PRIV-result", "PRIV-ask", "PRIV-f2s-text", "PRIV-msg-human"):
        assert marker in content


def test_json_is_deterministic_and_tagged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _bundle(tmp_path)
    outs: list[str] = []
    for _ in range(2):
        assert triage.main([str(run), "--json"]) == 0
        outs.append(capsys.readouterr().out)
    assert outs[0] == outs[1]
    assert json.loads(outs[0])["schema"] == "pl.triage/1"


def test_refuses_sealed_and_test_split(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    test_split = _bundle(tmp_path / "runs", split="test")
    sealed = _bundle(tmp_path / "evidence" / "s4" / "test")
    for run in (test_split, sealed):
        assert triage.main([str(run)]) == 2
        assert "refused" in capsys.readouterr().err
