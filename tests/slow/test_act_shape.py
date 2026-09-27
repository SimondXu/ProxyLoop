"""Agent harness v2-A (S1-SYS-45): Slow's offer slots are {field, value,
utt_ref} (role and unit follow from the field, by Guard's tables), and a
malformed act gets one short steering refusal. Bad output is refused and
counted, never repaired (rule 12). The fixtures are the live runs' own texts
(84f731, ed5063, f828f1, aeab91, e6ada1); the asserts are refusal classes."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from tests.slow.test_authority import Host

from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.llm import ToolCall
from proxyloop.contract.views import view_slow
from proxyloop.guard.readback import readback_status
from proxyloop.slow.prompt import status_bar
from proxyloop.slow.tools import SlowTools

# run 84f731: the offer (cp-10) and the rep's read-back after ask_readback (cp-12)
OFFER_84 = (
    "The plan is 75.00 per month on a 12 month term, plus a 20.00 activation fee."
)
READBACK_84 = (
    "The plan is 75.00 per month for a term of 12 months, with an activation fee "
    "of 20.00."
)
# run 84f731, seq 435: recorded then with term_months role "expiry" (never
# confirmable: the read-back left it unknown for the rest of the run)
ACT_435 = [
    {"field": "monthly_price", "role": "recurring", "unit": "usd_minor",
     "utt_ref": "cp-10", "value": "7500"},
    {"field": "term_months", "role": "expiry", "unit": "months",
     "utt_ref": "cp-10", "value": "12"},
    {"field": "fee:activation", "role": "one_time", "unit": "usd_minor",
     "utt_ref": "cp-10", "value": "2000"},
]  # fmt: skip
# run ed5063: the offer line (cp-28) and the act at seq 721 (expires "false")
OFFER_ED = (
    "The rate is 78.00 per month for a 24 month term, with no fees, no other "
    "changes, and no expiry."
)
ACT_721 = [
    {"field": "monthly_price", "role": "recurring", "unit": "usd_minor",
     "utt_ref": "cp-28", "value": "7800"},
    {"field": "term_months", "role": "recurring", "unit": "months",
     "utt_ref": "cp-28", "value": "24"},
    {"field": "fees_none", "role": "one_time", "unit": "bool",
     "utt_ref": "cp-28", "value": "true"},
    {"field": "changes_none", "role": "change", "unit": "bool",
     "utt_ref": "cp-28", "value": "true"},
    {"field": "expires", "role": "expiry", "unit": "bool",
     "utt_ref": "cp-28", "value": "false"},
]  # fmt: skip
# run f828f1, slow:21 (events seq 567-568): the whole act, flattened
FLAT_F828 = (
    '{"calls":[{"field":"monthly_price","role":"recurring","unit":"usd_minor",'
    '"utt_ref":"cp-13","value":"7500"},{"field":"term","role":"change",'
    '"unit":"months","utt_ref":"cp-13","value":"12"}],"offer_ref":"off_1",'
    '"private_summary":"Recording offer off_1 ($75/mo, 12 mo) and asking for '
    'readback.","slots":["offer:off_1"],"tool":"record_offer"}'
)
# run e6ada1: the offer (cp-8), the rep's read-backs (cp-13, cp-15)
OFFER_E6 = "I can offer a monthly price of 78.00 with a term of 24 months."
READBACK_E6 = (
    "The monthly price is 78.00 for a term of 24 months. There are no fees, no "
    "other changes, and no expiry."
)
AGAIN_E6 = (
    "The rate is 78.00 per month for 24 months. There are no fees, no other "
    "changes, and no expiry."
)
STEER = "role and unit follow from field"
NOT_RECORDED = "required slots not recorded"


def _bare(slots: list[dict[str, str]]) -> list[dict[str, str]]:
    """The V1 slot shape: {field, value, utt_ref}."""
    return [{k: s[k] for k in ("field", "value", "utt_ref")} for s in slots]


def _record(ref: str, slots: list[dict[str, str]]) -> dict[str, Any]:
    return {"tool": "record_offer", "offer_ref": ref, "offer_slots": slots}


def _ask(ref: str) -> dict[str, Any]:
    return {"tool": "guide_fast", "move": "ask_readback", "slots": [f"offer:{ref}"]}


def _raw(h: Host, arguments: str) -> str:
    call = ToolCall(call_id="c", name="act", arguments=arguments)
    return h.tools.act(call, [h.root.event_id], basis=h.bb.seq)


def _bar(h: Host) -> str:
    return status_bar(view_slow(h.bb, SlowViewMode.RELAY_ONLY, "b"), frozenset(), 0)


def test_f4_the_84f731_act_is_refused_and_bare_slots_confirm(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    h.rep("cp-10", OFFER_84)
    (refused,) = h.act(_record("offer_1", ACT_435))
    assert refused.startswith("record_offer: record_offer refused"), refused
    assert STEER in refused and not h.of("offer.recorded")
    recorded, asked = h.act(_record("offer_1", _bare(ACT_435)), _ask("offer_1"))
    assert recorded == "record_offer: recorded offer_1 r1", recorded
    assert asked.endswith("read-back asked for offer_1 r1"), asked
    slots = {s.field: s for s in h.bb.public.offers["offer_1"].slots}
    assert (slots["term_months"].role, slots["term_months"].unit) == (
        "recurring",
        "months",
    )  # derived from Guard's ROLE_OF and the ledger's UNITS
    h.rep("cp-12", READBACK_84)
    h.tools.readback()
    statuses = {s.field: s.status for s in h.bb.public.offers["offer_1"].slots}
    assert statuses["term_months"] == "confirmed", statuses
    h.bus.close()


def test_f4_ed5063_expires_false_is_refused(tmp_path: Path) -> None:
    h = Host(tmp_path)
    h.call()
    h.rep("cp-28", OFFER_ED)
    (as_sent,) = h.act(_record("offer-1", ACT_721))
    assert "refused" in as_sent and STEER in as_sent
    (bare,) = h.act(_record("offer-1", _bare(ACT_721)))
    assert "refused" in bare and "expires" in bare and "ISO" in bare, bare
    assert not h.of("offer.recorded")
    h.bus.close()


def test_f5_a_flattened_act_gets_one_steering_refusal(tmp_path: Path) -> None:
    h = Host(tmp_path)
    before = len(h.of("slow.tool"))
    out = _raw(h, FLAT_F828)
    (tool,) = h.of("slow.tool")[before:]  # one refusal, the whole act
    assert tool.payload["name"] == "act" and not tool.payload["ok"]
    assert "unknown tool" not in out and "'None'" not in out
    for key in ("offer_ref", "slots", "tool"):  # named, with the item shape
        assert key in out, out
    assert '"tool"' in out and "calls" in out
    assert not h.of("summary.updated")  # never reinterpreted: nothing ran
    h.bus.close()


def test_f5_a_calls_item_without_a_tool_says_so(tmp_path: Path) -> None:
    h = Host(tmp_path)
    item = json.loads(FLAT_F828)["calls"][0]
    calls = [{"x": 1}, item, "wait"]
    out = _raw(h, json.dumps({"private_summary": "d", "calls": calls}))
    head, first, second, third = out.splitlines()
    assert head.startswith("act: ") and "unknown tool" not in out
    assert "calls[0] has no tool" in first and "x" in first
    assert "calls[1] has no tool" in second and "utt_ref" in second
    assert "calls[2] is not an object" in third
    oks = [e.payload["ok"] for e in h.of("slow.tool")]
    assert oks == [True, False, False, False]  # counted, one refusal each
    h.bus.close()


def test_aeab91_an_invalid_argument_is_one_short_line(tmp_path: Path) -> None:
    """aeab91 (seq 159): guide_fast(move="stall") came back as a raw pydantic
    dump; now ``<tool>: invalid arguments: <field>: <short reason>``."""
    h = Host(tmp_path)
    (out,) = h.act({"move": "stall", "tool": "guide_fast"})
    assert out.startswith("guide_fast: invalid arguments: move: "), out
    assert "\n" not in out and "pydantic" not in out and "validation error" not in out
    (missing,) = h.act({"tool": "ask_user"})
    assert missing.startswith("ask_user: invalid arguments: text"), missing
    h.bus.close()


def test_e6ada1_the_bar_names_required_slots_not_recorded(tmp_path: Path) -> None:
    """e6ada1: only price and term were recorded, the read-back stated the
    rest, the terms never hashed and the approval path was unreachable. The
    bar names Guard's ``missing_required`` until they are recorded; nothing
    is recorded for Slow."""
    h = Host(tmp_path)
    h.call()
    h.rep("cp-8", OFFER_E6)
    two = [
        {"field": "monthly_price", "value": "7800", "utt_ref": "cp-8"},
        {"field": "term_months", "value": "24", "utt_ref": "cp-8"},
    ]
    recorded, _ = h.act(_record("offer-1", two), _ask("offer-1"))
    assert recorded == "record_offer: recorded offer-1 r1", recorded
    h.rep("cp-13", READBACK_E6)
    h.tools.readback()
    bar = _bar(h)
    assert NOT_RECORDED in bar, bar
    for field in ("expires", "fees_none", "changes_none"):
        assert field in bar.split(NOT_RECORDED)[1], bar
    assert h.bb.public.offers["offer-1"].terms_hash is None
    rest = [
        {"field": "fees_none", "value": "true", "utt_ref": "cp-13"},
        {"field": "changes_none", "value": "true", "utt_ref": "cp-13"},
        {"field": "expires", "value": "none", "utt_ref": "cp-13"},
    ]
    all_five = [{**s, "utt_ref": "cp-13"} for s in two] + rest
    recorded, _ = h.act(_record("offer-1", all_five), _ask("offer-1"))
    assert recorded == "record_offer: recorded offer-1 r2", recorded
    h.tools.readback()
    assert NOT_RECORDED not in _bar(h)
    assert h.bb.public.offers["offer-1"].terms_hash  # Guard hashes the terms
    h.rep("cp-15", AGAIN_E6)
    h.tools.readback()
    assert readback_status(h.bb.public.offers["offer-1"]) == "confirmed"
    h.bus.close()


def test_act_needs_the_steps_basis() -> None:
    """#183 review N-c: no fail-open ``basis=None``; SlowLoop passes its view."""
    basis = inspect.signature(SlowTools.act).parameters["basis"]
    assert basis.default is inspect.Parameter.empty
