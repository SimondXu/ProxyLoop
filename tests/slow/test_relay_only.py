"""I5: Slow's context holds relays and its own tool history, never a transcript.

Every user and rep line carries a marker no Fast lane relays; one Fast relay
carries its own marker. Every prompt Slow was sent is searched for them.
"""

from __future__ import annotations

from pathlib import Path

from tests.kernel.test_session import FINISH
from tests.support.sessions import act, ear, only_bundle, reply, run

from proxyloop.contract.llm import LLMCallRecord
from proxyloop.slow import prompt

USER_SAID = "ZEBRA-QUILL"  # in every SimUser message, never relayed
REP_SAID = "OKAPI-MARBLE"  # in every rep line, never relayed
FAST_SAID = "Could you lower the monthly price?"  # FastC's speech, never relayed
RELAYED = "GIRAFFE-RELAY"  # FastU relays it
SCRIPTS = {
    "simuser": [reply(f"Get me a better price. Code {USER_SAID}.")],
    "fast_user": [f"On it.\n@slow: request {RELAYED}"],
    "ear": [ear("other"), ear("ask_discount")],
    "mouth": [f"{REP_SAID} speaking."],
    "fast_cp": [f"{FAST_SAID}\n@slow: fact monthly_price=75.00"],
    "slow": [act("Waiting.", {"tool": "wait", "seconds": 5})],
}


def test_no_utterance_reaches_slow_unless_relayed(tmp_path: Path) -> None:
    run(tmp_path, SCRIPTS, until={"slow": ("] cp_update", FINISH)})
    bundle = only_bundle(tmp_path)
    said = " ".join(
        str(e.payload.get("text") or e.payload.get("text_heard") or "")
        for e in bundle.events
        if e.type in ("user.msg", "utt.final", "fast.sentence")
    )
    assert USER_SAID in said and REP_SAID in said and FAST_SAID in said  # not vacuous
    calls = [
        LLMCallRecord.model_validate(e.payload)
        for e in bundle.events
        if e.type == "llm.call" and e.payload["role"] == "slow"
    ]
    context = [bundle.prompts[c.prompt_sha].content for c in calls]
    assert len(context) >= 2
    assert not [c for c in context if USER_SAID in c or REP_SAID in c or FAST_SAID in c]
    assert any(RELAYED in c for c in context)  # a relay does reach Slow
    assert any("[REP CALL] cp_update monthly_price=75.00" in c for c in context)


EVERY_TOOL = act(
    "Trying every tool.",
    {"tool": "ask_user", "text": "Any limits?"},
    {"tool": "tell_user", "text": "Working on it."},
    {"tool": "guide_fast", "move": "ask_readback", "slots": ["offer:o1"]},
    {"tool": "record_fact", "key": "tenure_years", "value": "6", "utt_ref": "u"},
    {"tool": "record_offer", "offer_ref": "o1", "offer_slots": []},
    {"tool": "share_fact", "key": "tenure_years"},
    {"tool": "propose_mandate", "envelope": {"max_monthly_price_minor": 7000}},
    {"tool": "tighten_mandate", "changes": {"max_monthly_price_minor": 6500}},
    {"tool": "request_approval", "offer_ref": "o1"},
    {"tool": "accept_offer", "offer_ref": "o1"},
    {"tool": "decline_offer", "offer_ref": "o1", "reason": "too high"},
    {"tool": "check_account"},
    {"tool": "revoke", "reason": "the user said stop"},
    {"tool": "finish", "outcome": "no_deal", "summary": "none"},
    {"tool": "wait", "seconds": 5},
    public="Asking about a lower price.",
)


def test_no_utterance_reaches_slow_under_every_tool(tmp_path: Path) -> None:
    """I5 with every S1 tool's result in Slow's context (tool results are
    Guard's text and Slow's own values, never a transcript line)."""
    scripts = {**SCRIPTS, "slow": [EVERY_TOOL]}
    run(tmp_path, scripts, until={"slow": ("] cp_update", FINISH)})
    bundle = only_bundle(tmp_path)
    used = {str(e.payload["name"]) for e in bundle.events if e.type == "slow.tool"}
    assert used >= set(prompt.TOOLS)  # not vacuous: every tool ran
    calls = [
        LLMCallRecord.model_validate(e.payload)
        for e in bundle.events
        if e.type == "llm.call" and e.payload["role"] == "slow"
    ]
    context = [bundle.prompts[c.prompt_sha].content for c in calls]
    assert any("request_approval: denied: " in c for c in context)
    assert not [c for c in context if USER_SAID in c or REP_SAID in c or FAST_SAID in c]
