"""The triage fixture bundle: one run that trips every detector once, with the
seq of each event in a comment. Every event is at ``t_ms = seq * 100``
(``bundles.Log``). Content fields hold ``PRIV`` markers for the privacy test."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from tests.contract.samples import GEMINI, QWEN
from tests.obs.bundles import Log, manifest, write

from proxyloop.contract.bundle import PROMPTS, PromptRecord
from proxyloop.contract.llm import LLMCallRecord, LLMRole, ModelRef

P = dict[str, object]
WINDOW_S = 1.0  # the relay window used with this bundle: 1,000 ms
# cp-g1: a line, the pause, then three sentences on two lines.
CP_G1 = "Please hold.\n@hold fact_request\nStray one. Stray two.\nAgain."
CP_G2 = "@hold fact_request"  # capped at length with no speech
# user-g1: a sentence, a relay line (a directive, not a pause), one more.
USER_G1 = "Noted.\n@slow: note PRIV-relay-note\nThanks."
_ACTOR = {"fast_user": "fast.user", "fast_cp": "fast.cp", "slow": "slow"}


def call(log: Log, role: LLMRole, ref: ModelRef, call_id: str, **kw: object) -> str:
    fields: P = {
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
    return log.add("llm.call", _ACTOR[role], "agent", record, (log.start,))


def turn(log: Log, lane: str, gen_id: str, call_id: str, cause: str) -> str:
    payload: P = {"lane": lane, "gen_id": gen_id, "call_id": call_id, "items": []}
    payload |= {"ttft_ms": 1, "ttfs_ms": 1}
    return log.add("fast.turn", f"fast.{lane}", "agent", payload, (cause,))


def said(log: Log, text: str, revealed: dict[str, str] | None = None) -> str:
    """A user.msg; with ``revealed`` it is caused by a user.sim."""
    causes: tuple[str, ...] = ()
    if revealed is not None:
        sim: P = {"text": text, "revealed": revealed, "delay_s": 1.0}
        causes = (log.add("user.sim", "world.simuser", "world", sim, (log.start,)),)
    return log.add("user.msg", "kernel", "agent", {"text": text}, causes)


def sentence(log: Log, lane: str, gen: str, n: int, text: str, cause: str) -> str:
    payload: P = {"lane": lane, "gen_id": gen, "utt_id": f"{gen}-u{n}", "text": text}
    return log.add("fast.sentence", f"fast.{lane}", "agent", payload, (cause,))


def heard(log: Log, lane: str, utt_id: str, text: str, cut: bool, cause: str) -> str:
    payload: P = {"lane": lane, "utt_id": utt_id, "text_generated": text}
    payload |= {"text_heard": text, "interrupted": cut}
    return log.add("utt.delivered", "kernel", "agent", payload, (cause,))


def s2f(log: Log, msg_id: str, lane: str, kind: str, cause: str, **kw: object) -> str:
    payload: P = {"msg_id": msg_id, "lane": lane, "type": kind} | kw
    return log.add("s2f.msg", "guard", "agent", payload, (cause,))


def policy(log: Log, to: str, kind: str) -> str:
    intent: P = {"kind": kind, "offer_ref": None, "say": ["PRIV-say"], "ask": []}
    payload: P = {"from": "IDENTIFY", "to": to, "intent": intent, "rung": None}
    return log.add("rep.policy", "world.policy", "world", payload)


def bundle(root: Path, split: str = "train") -> Path:
    log = Log("rT", split)  # 0 session.started, t=0
    step: P = {"basis_seq": 0, "wake_reasons": []}
    log.add("slow.step.started", "slow", "agent", step)  # 1
    said(log, "PRIV-msg-unrelayed", {"account.last4": "PRIV-5190"})  # 2 sim, 3 msg
    u1 = call(log, "fast_user", QWEN, "u1")  # 4
    tu = turn(log, "user", "user-g1", "u1", u1)  # 5
    s6 = sentence(log, "user", "user-g1", 0, "PRIV I've passed that along.", tu)
    heard(log, "user", "user-g1-u0", "PRIV-heard I've passed that along.", False, s6)
    relayed = said(log, "PRIV-msg-relayed")  # 8 (t=800)
    f2s: P = {"msg_id": "rT:9", "lane": "user", "gen_id": "user-g1"}
    f2s |= {"utt_ref": relayed, "type": "USER_UPDATE", "text": "PRIV-f2s-text"}
    f2s |= {"facts": [["account.last4", "PRIV-5190"]]}
    log.add("f2s.msg", "fast.user", "agent", f2s, (tu,))  # 9 (t=900)
    said(log, "PRIV-msg-negated")  # 10 (t=1000)
    heard(log, "user", "user-g1-u1", "I haven't passed that along yet.", False, s6)
    c1 = call(log, "fast_cp", QWEN, "c1", finish_reason="length")  # 12
    t13 = turn(log, "cp", "cp-g1", "c1", c1)  # 13
    guide: P = {"move": "identify", "slots": []}
    g1 = s2f(log, "s2f-1", "cp", "GUIDE", t13, guide=guide)  # 14 (t=1400)
    voiced: P = {"msg_id": "s2f-1", "gen_id": "cp-g1"}
    log.add("s2f.voiced", "fast.cp", "agent", voiced, (g1,))  # 15
    s16 = sentence(log, "cp", "cp-g1", 0, "Please hold.", t13)  # 16
    sentence(log, "cp", "cp-g1", 1, "Again and", t13)  # 17: never delivered
    heard(log, "cp", "cp-g1-u0", "Please hold.", True, s16)  # 18 (t=1800)
    policy(log, "IDENTIFY", "ok_hold")  # 19
    policy(log, "IDENTIFY", "ok_hold")  # 20
    policy(log, "IDENTIFY", "ask_identity")  # 21
    policy(log, "DISCOVER", "ok_hold")  # 22
    stale: P = {"move": "hold_for_fact", "slots": []}
    s2f(log, "s2f-2", "cp", "GUIDE", t13, guide=stale)  # 23: never voiced
    c2 = call(log, "fast_cp", QWEN, "c2", finish_reason="length")  # 24
    turn(log, "cp", "cp-g2", "c2", c2)  # 25
    error = "EndpointError: HTTP 400: PRIV-error-text"
    call(log, "slow", GEMINI, "s1", finish_reason=None, error=error)  # 26
    call(log, "slow", GEMINI, "s2", finish_reason=None, error="cancelled")  # 27
    turn(log, "cp", "cp-g3", "c-none", c2)  # 28: no llm.call c-none
    denied: P = {"violations": ["PRIV-violation"]}
    log.add("declass.denied", "guard", "agent", denied, (log.start,))  # 29
    log.add("slow.step.started", "slow", "agent", step)  # 30 (t=3000)
    tool: P = {"name": "act", "args": {"note": "PRIV-args"}, "ok": True}
    tool["result_text"] = "PRIV-result"
    t31 = log.add("slow.tool", "slow", "agent", tool, (log.start,))  # 31
    evil: P = {"name": "PRIV-tool", "args": {}, "ok": False, "result_text": "PRIV-r2"}
    log.add("slow.tool", "slow", "agent", evil, (t31,))  # 32
    no: P = {"intent": "guide_fast", "reason": "guide_slot_not_public"}
    log.add("action.denied", "slow", "agent", no, (t31,))  # 33
    s2f(log, "s2f-3", "user", "ASK_USER", t31, text="PRIV-ask")  # 34
    said(log, "PRIV-msg-late")  # 35 (t=3500)
    end: P = {"reason": "abandoned", "counts": {"hold_repeat": 3}}
    log.add("session.ended", "kernel", "ops", end)  # 36 (t=3600)
    path = write(root / "rT", log, manifest("rT", split=split))
    prompts(path, {"resp-c1": CP_G1, "resp-c2": CP_G2, "resp-u1": USER_G1})
    return path


def prompts(path: Path, responses: dict[str, str]) -> None:
    text = "".join(
        PromptRecord(sha=s, kind="response", content=c).model_dump_json() + "\n"
        for s, c in responses.items()
    )
    (path / PROMPTS).write_text(text, "utf-8")


def bare(root: Path, run_id: str, sha: str, hours: int = 0) -> Path:
    """A run with only session.started on ``sha``, ``hours`` after WALL."""
    log = Log(run_id)
    start = log.events[0]
    payload = start.payload | {"git_sha": sha}
    wall = start.wall + timedelta(hours=hours)
    log.events[0] = start.model_copy(update={"payload": payload, "wall": wall})
    return write(root / run_id, log, manifest(run_id))
