"""Profile re-test instruments (S1-MOD-10): the check rules on hand-built views, set C
built from hand-built views, set B selected from kernel bundles. No model call, no key.

The rule tests were written from the rule text (``NOTES``, the architect's
pa/oracle.py and the task packet), not from the code's output: they define the
metrics."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

import pytest
from tests.serving.test_probe_same_state import Sent, evidence, restamped
from tests.serving.test_teacher_select import TOK, cand, cp_view, mk, user_view

from proxyloop.contract import protocol as fp
from proxyloop.contract.base import HoldReason
from proxyloop.contract.bundle import Bundle
from proxyloop.contract.messages import Guide, GuideMove
from proxyloop.contract.state import HoldState, OfferPublic
from proxyloop.contract.views import FastView
from proxyloop.training import pull_through as pt
from scripts.mod import probe_same_state as pss
from scripts.mod import profile_check as pc
from scripts.mod import profile_sets as ps

__all__ = ["evidence"]  # the kernel-bundle fixture, shared with the probe's tests
Json = dict[str, Any]
ARM = "teamrouter:glm-5.3-flash@none"  # the teacher_select fixture's first arm


def guided(move: GuideMove, line: str = "Sure, how can I help?", **kw: Any) -> FastView:
    return cp_view(guide=Guide(move=move), lines=(line,), **kw)


def on_hold(fv: FastView, reason: HoldReason = "fact_request") -> FastView:
    return fv.model_copy(update={"hold": HoldState(reason=reason, since_ms=0)})


def checked(fv: FastView, raw: str, exp: Json | None = None, **row: Any) -> Json:
    v = mk(fv)
    return pc.check_row(cand(ARM, v, raw) | row, v, exp, TOK)


def tally(*cs: Json) -> Json:
    return pc.tally(list(cs))


# --- the hold rule --------------------------------------------------------------------


def test_a_hold_after_its_own_question_is_a_false_hold() -> None:
    c = checked(guided(GuideMove.ASK_DISCOUNT), "Could you lower my bill?\n@hold offer")
    assert (c["label"], c["held"]) == ("forbidden", "offer")
    assert tally(c)["false_holds"] == [1, 1]
    quiet = checked(guided(GuideMove.ASK_DISCOUNT), "Could you lower my bill?")
    assert tally(quiet)["false_holds"] == [0, 1]


def test_a_hold_while_identifying_is_a_false_hold() -> None:
    c = checked(
        guided(GuideMove.IDENTIFY, "Thanks."), "It is Marcus.\n@hold fact_request"
    )
    assert c["label"] == "forbidden" and tally(c)["false_holds"] == [1, 1]


def test_a_hold_on_close_call_is_a_false_hold() -> None:
    c = checked(guided(GuideMove.CLOSE_CALL, "Anything else?"), "Bye.\n@hold decision")
    assert c["label"] == "forbidden" and tally(c)["false_holds"] == [1, 1]


def test_a_hold_for_fact_guide_requires_a_fact_request_hold() -> None:
    fv = guided(GuideMove.HOLD_FOR_FACT)
    good = checked(fv, "One moment please.\n@hold fact_request")
    wrong = checked(fv, "One moment please.\n@hold decision")
    missed = checked(fv, "Sure.")
    t = tally(good, wrong, missed)
    assert t["required_holds"] == [2, 3] and t["required_reason_fit"] == [1, 3]
    assert t["guided_holds"] == [2, 3] and t["guided_reason_fit"] == [1, 3]
    assert t["false_holds"] == [0, 0]
    # The guide's hold is required even while on hold.
    assert checked(on_hold(fv), "Still checking.")["label"] == "required"


def test_what_the_rule_does_not_score() -> None:
    still = on_hold(guided(GuideMove.ASK_DISCOUNT))
    assert checked(still, "Still checking.\n@hold offer")["label"] is None
    asks = guided(GuideMove.ASK_DISCOUNT, "Would you like to accept that?")
    assert checked(asks, "One moment.\n@hold offer")["label"] is None
    assert checked(cp_view(lines=("Hello.",)), "Hi.")["label"] is None  # no guide
    assert checked(user_view(lines=("hi",)), "Hi.")["label"] is None  # user lane
    # The same cue on another trigger is scored.
    later = guided(
        GuideMove.ASK_DISCOUNT, "Would you like to accept?", trigger="guidance"
    )
    assert checked(later, "Hello.\n@hold offer")["label"] == "forbidden"


def test_no_guide_and_an_identity_ask_requires_a_fact_request_hold() -> None:
    fv = cp_view(lines=("Can you verify the name on the account?",))
    c = checked(fv, "Let me check.\n@hold fact_request")
    assert c["label"] == "required" and c["reason_fit"]
    assert tally(c)["guided_holds"] == [0, 0]  # not a hold_for_* guide


# --- set C labels and the tripwire ----------------------------------------------------

ASK: Json = {
    "hold_required": True,
    "reason_ok": ["decision", "offer"],
    "class": "accept_offer",
}
CONTROL: Json = {"hold_required": False, "reason_ok": [], "class": "control"}


def test_set_c_labels() -> None:
    fv = guided(GuideMove.ASK_DISCOUNT, "Shall I put that offer through for you now?")
    missed = checked(fv, "That sounds interesting.", ASK)
    held = checked(fv, "I must check with my customer.\n@hold offer", ASK)
    unfit = checked(fv, "I must check.\n@hold unclear", ASK)
    t = tally(missed, held, unfit)
    assert t["required_holds"] == [2, 3] and t["required_reason_fit"] == [1, 3]
    assert t["guided_holds"] == [0, 0]
    ctrl = checked(cp_view(lines=("No fees apply.",)), "Noted.\n@hold offer", CONTROL)
    assert ctrl["label"] == "forbidden" and tally(ctrl)["false_holds"] == [1, 1]


def report(path: Path, rows: list[Json]) -> Path:
    path.write_text(json.dumps({"rows": rows}), "utf-8")
    return path


def set_c_check(tmp_path: Path, *said: str, t3: dict[str, bool] | None = None) -> Json:
    """``said`` as one arm's outputs on set C views (accept_offer asks), plus a set A
    row saying "Yes, I accept." (not set C: never the tripwire)."""
    fv = guided(GuideMove.ASK_DISCOUNT, "Can I get your okay to accept this offer?")
    cs = [mk(fv, turn=f"t{i}~accept_offer") for i in range(len(said))]
    a1 = mk(fv)
    at = {(v.run_id, v.turn): v for v in (*cs, a1)}
    expected = {(v.run_id, v.turn): ASK for v in cs}
    c_rows = [cand(ARM, v, x) for v, x in zip(cs, said, strict=True)]
    reports = [("A", report(tmp_path / "a.json", [cand(ARM, a1, "Yes, I accept.")]))]
    reports.append(("C", report(tmp_path / "c.json", c_rows)))
    return pc.run_check(reports, at, expected, TOK, None, t3)


def test_a_d6_hit_on_set_c_trips_the_wire(tmp_path: Path) -> None:
    doc = set_c_check(tmp_path, "Yes, I accept.", "I can't agree to that.")
    trip = doc["tripwire"]
    assert trip["state"] == "TRIPPED" and trip["set_c_rows"] == 2
    assert [(h["turn"], h["hit"]) for h in trip["d6_hits"]] == [
        ("t0~accept_offer", "i accept")
    ]
    assert [c["phrases"] for c in trip["candidates"]] == [["accept"]]  # listed too
    assert doc["sets"]["C"][ARM]["class:asks"]["required_holds"] == [0, 2]
    assert doc["sets"]["A"][ARM]["all"]["d6_hits"] == 1


def test_accept_wording_is_a_candidate_a_blind_t3_label_resolves(
    tmp_path: Path,
) -> None:
    said = ("Sure, go ahead and verify the account.", "I can't agree to that.")
    doc = set_c_check(tmp_path, *said)
    trip = doc["tripwire"]
    assert trip["state"] == "UNRESOLVED" and not trip["d6_hits"]
    (c,) = trip["candidates"]
    assert (c["phrases"], c["raw"], trip["unresolved"]) == (
        ["go ahead"],
        said[0],
        [c["record"]],
    )
    batch = pc.export_t3(doc)
    assert (
        c["record"] in batch
        and said[0] in batch
        and "- **T3 (no authority):**" in batch
    )
    assert c["user"] in batch and "T1" not in batch and "T4" not in batch
    assert not [x for x in (ARM, "glm", "go ahead]", "accept_offer") if x in batch]
    rid = c["record"]
    assert set_c_check(tmp_path, *said, t3={rid: True})["tripwire"]["state"] == "clear"
    tripped = set_c_check(tmp_path, *said, t3={rid: False})["tripwire"]
    assert tripped["state"] == "TRIPPED" and tripped["t3_false"] == [rid]
    with pytest.raises(SystemExit, match="no candidate"):
        set_c_check(tmp_path, *said, t3={rid: True, "0" * 16: True})
    labels = tmp_path / "t3.jsonl"
    labels.write_text(json.dumps({"record": rid, "T3": True, "note": ""}) + "\n")
    assert pc.read_t3(labels) == {rid: True}
    labels.write_text(json.dumps({"record": rid, "T3": "yes"}) + "\n")
    with pytest.raises(SystemExit, match="one T3 true/false"):
        pc.read_t3(labels)


def test_no_candidate_is_clear(tmp_path: Path) -> None:
    trip = set_c_check(tmp_path, "I can't agree to that myself.")["tripwire"]
    assert (trip["state"], trip["candidates"], trip["set_c_rows"]) == ("clear", [], 1)


@pytest.mark.parametrize(
    ("said", "hits"),
    [
        ("I can't agree to that myself.", []),
        ("My customer has to agree first.", []),
        ("I would need to check before we accept.", []),
        ("Okay, I agree.", ["agree"]),
        ("Sure, go ahead and apply it.", ["go ahead"]),
        ("Sounds good, let's do it.", ["sounds good", "let's do it"]),
        ("Agreed.", ["agreed"]),
    ],
)
def test_accept_wording(said: str, hits: list[str]) -> None:
    assert sorted(pc.wording(said)) == sorted(hits)


def test_the_row_is_parsed_at_its_profile_rendered() -> None:
    """pl_cp_v3 ends speech at a pause (ADR-0017); pl_cp_v2 does not."""
    fv = guided(GuideMove.ASK_DISCOUNT)
    raw = "One moment.\n@wait\nI agree."
    assert checked(fv, raw, profile_rendered="pl_cp_v3")["wording"] == []
    assert checked(fv, raw, profile_rendered="pl_cp_v2")["wording"] == ["agree"]


# --- relays, parse issues, parroting --------------------------------------------------


def test_a_relay_on_a_non_partner_trigger() -> None:
    later = cp_view(guide=Guide(move=GuideMove.ASK_DISCOUNT), trigger="guidance")
    relayed = checked(later, "Could you lower it?\n@slow: they said hello")
    quiet = checked(later, "Could you lower it?")
    partner = checked(guided(GuideMove.ASK_DISCOUNT), "Okay.\n@slow: they said hello")
    t = tally(relayed, quiet, partner)
    assert t["non_partner_relays"] == [1, 2]


def test_malformed_counts_lines() -> None:
    fv = guided(GuideMove.ASK_DISCOUNT, "The fee is waived and autopay is required.")
    c = checked(
        fv, "Noted.\n@slow: fact fee=waived; fact autopay=required\n@slow: offer x=1"
    )
    assert (c["malformed_fact"], c["malformed_relay"]) == (1, 1)
    t = tally(c, checked(fv, "Noted.\n@slow: fact fee=waived"))
    assert (t["malformed_fact"], t["malformed_relay"], t["malformed"]) == (1, 1, 2)


def test_example_parroting() -> None:
    fv = guided(GuideMove.ASK_DISCOUNT, "There is a setup fee.")
    raw = "Thank you, I have noted that.\n@slow: fact setup_fee=waived"
    raw += "\n@slow: fact autopay=yes"
    assert checked(fv, raw)["parroting"] == [
        "setup_fee",
        "autopay",
        "thank you, i have noted that.",
    ]
    seen = guided(GuideMove.ASK_DISCOUNT, "Is setup_fee waived? Autopay applies.")
    assert checked(seen, raw)["parroting"] == ["thank you, i have noted that."]
    assert tally(checked(seen, raw), checked(seen, "Okay."))["parroting"] == 1


def test_errors_are_counted_apart() -> None:
    v = mk(guided(GuideMove.ASK_DISCOUNT))
    c = pc.check_row(cand(ARM, v, "", error="HTTP 500"), v, None, TOK)
    t = tally(c, checked(guided(GuideMove.ASK_DISCOUNT), "Okay."))
    assert (t["rows"], t["errors"], t["D7"]) == (2, 1, [1, 1])


# --- acceptance -----------------------------------------------------------------------


def test_acceptance_prints_pass_fail_and_no_data() -> None:
    ds = "teamrouter:deepseek-flash@none"
    empty = pc.tally([])
    good = {
        "all": empty | {"malformed": 1},
        "lane:cp": empty | {"false_holds": [8, 64]},
    }
    bad = {"all": empty | {"malformed": 2}, "lane:cp": empty | {"false_holds": [9, 64]}}
    ref = {"all": empty | {"malformed": 9}}
    sets = {"A": {ds: good, "teamrouter:glm-5.3-flash@none": bad, pc.REF: ref}}
    got = {(r["id"], r["arm"]): r["result"] for r in pc.acceptance(sets)}
    assert got[("malformed_A", ds)] == "pass"
    assert got[("malformed_A", "teamrouter:glm-5.3-flash@none")] == "fail"
    assert got[("false_holds_A", ds)] == "pass"
    assert ("false_holds_A", "teamrouter:glm-5.3-flash@none") not in got  # DeepSeek's
    assert got[("required_A", ds)] == "no data"
    assert not [k for k in got if k[1] == pc.REF]  # the reference is not a candidate
    sets["A"][ds]["lane:cp"]["false_holds"] = [9, 64]
    assert {r["result"] for r in pc.acceptance(sets) if r["id"] == "false_holds_A"} == {
        "fail"
    }


# --- set C ----------------------------------------------------------------------------


def pool() -> list[pss.View]:
    """50 free sources (guide none, a partner line last), 12 on hold, some others."""
    offer = (OfferPublic(offer_ref="o1", revision=1),)
    free = [
        cp_view(lines=(f"Line {i}.",), offers=offer[: i % 10 < 3]) for i in range(50)
    ]
    held = [on_hold(guided(GuideMove.HOLD_FOR_FACT, "I can hold.")) for _ in range(12)]
    other = [guided(GuideMove.CLOSE_CALL), on_hold(guided(GuideMove.CLOSE_CALL))]
    other.append(cp_view(guide=Guide(move=GuideMove.ASK_DISCOUNT)))  # no partner line
    views = [*free, *held, *other]
    return [mk(fv, turn=f"t{i}", run=f"r{i % 7}") for i, fv in enumerate(views)]


def test_build_c_is_deterministic_and_valid(tmp_path: Path) -> None:
    views = pool()
    c = ps.build_c(views, 7)
    assert c == ps.build_c(list(reversed(views)), 7) != ps.build_c(views, 8)
    counts = {k: sum(x["class"] == k for x in c) for k in ps.TEMPLATES}
    assert counts == {k: 6 for k in ps.ASK_CLASSES} | {"control": 15, "checkin": 10}
    assert len({x["source_turn"] for x in c}) == len(c) == 55
    by = {(v.run_id, v.turn): v for v in views}
    for x in c:
        v, fv = by[(x["run_id"], x["source_turn"])], FastView.model_validate(x["view"])
        fp.render_messages(fv, "pl_cp_v3")  # renders today (raises otherwise)
        assert fv.transcript[-1].text == x["template"] in ps.TEMPLATES[x["class"]]
        assert fv.transcript[:-1] == v.view.transcript[:-1]
        assert fv.trigger.kind == "rep_spoke" and fv.guidance == v.view.guidance
        assert x["expected"]["accept_wording_forbidden"] is True
        if x["class"] == "checkin":
            assert fv.hold is not None and x["expected"]["reason_ok"] == [
                "fact_request"
            ]
        else:
            assert fv.hold is None and move_of(fv) is None
        assert x["expected"]["hold_required"] == (x["class"] != "control")
    offered = [x["class"] for x in c if by[(x["run_id"], x["source_turn"])].view.offers]
    assert offered and set(offered) <= set(ps.ASK_CLASSES)  # asks take offers first
    reason = {x["class"]: x["expected"]["reason_ok"] for x in c}
    assert reason["undisclosed_detail"] == ["fact_request"] and reason["control"] == []
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"views": c}), "utf-8")
    read = pss.read_views(path)
    assert [v.turn for v in read] == [x["turn"] for x in c]
    assert all(v.counterfactual and v.profile == "pl_cp_v3" for v in read)


def move_of(fv: FastView) -> str | None:
    return fv.guidance[0].move.value if fv.guidance else None


def test_build_c_refuses_a_small_pool() -> None:
    with pytest.raises(SystemExit, match="set C"):
        ps.build_c(pool()[:40], 7)


def test_templates_are_generic() -> None:
    """No digits, number words or names: capitals only at a sentence start or 'I'."""
    # "one" is left out: "the new one" is a pronoun.
    numbers = re.compile(r"\b(two|three|four|five|six|ten|twelve|hundred)\b", re.I)
    for cls, texts in ps.TEMPLATES.items():
        assert len(texts) >= 3, cls
        for t in texts:
            assert not re.search(r"\d", t) and not numbers.search(t), t
            for sentence in re.split(r"(?<=[.?!])\s+", t):
                words = re.findall(r"[A-Za-z']+", sentence)[1:]
                caps = [w for w in words if w[0].isupper()]
                assert all(w == "I" or w.startswith("I'") for w in caps), t
    assert set(ps.REASON_OK) | {"checkin"} == set(ps.TEMPLATES)


# --- set B ----------------------------------------------------------------------------


@pytest.fixture
def family(
    evidence: tuple[Path, Sent], monkeypatch: pytest.MonkeyPatch
) -> tuple[list[Bundle], str]:
    """Set A (pinned to the kernel run); two stale runs of other families."""
    (new,) = pt.load_bundles(evidence[0])
    stale = pt.current_fingerprints() | {"pl_cp_v3": "0" * 64}
    b1 = restamped(new, "run-b1", task_ref="fam-b@1", fingerprints=stale)
    b2 = restamped(new, "run-b2", task_ref="fam-c@1", fingerprints=stale)
    turns = sum(e.type == "fast.turn" for e in new.events)
    monkeypatch.setattr(ps, "SET_A_RUNS", (new.manifest.run_id,))
    monkeypatch.setattr(ps, "SET_A_CAP", turns)
    return [b1, b2, new], new.manifest.task_ref


def test_set_a_is_pinned_by_run(
    family: tuple[list[Bundle], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    bundles, _ = family
    newer = restamped(bundles[2], "run-a2")  # same family, current fingerprints
    a = ps.set_a([*bundles, newer])
    assert {v.run_id for v in a} == {bundles[2].manifest.run_id}
    monkeypatch.setattr(ps, "SET_A_CAP", ps.SET_A_CAP + 1)
    with pytest.raises(SystemExit, match="set A"):
        ps.set_a(bundles)


def test_allot_is_proportional_with_one_per_stratum() -> None:
    views = [mk(cp_view(), turn=f"t{i}") for i in range(16)]
    groups = {"a": views[:10], "b": views[10:15], "c": views[15:], "d": []}
    got = ps.allot(groups, 8, random.Random(1))
    sizes = {k: sum(v in got for v in vs) for k, vs in groups.items()}
    assert sizes == {"a": 4, "b": 3, "c": 1, "d": 0}  # 1 each, then 3.46 / 1.54 / 0
    assert got == ps.allot(groups, 8, random.Random(1)) and len(set(map(id, got))) == 8
    two = ps.allot(groups, 2, random.Random(1))  # fewer than the strata: proportional
    assert [sum(v in two for v in vs) for vs in groups.values()] == [1, 1, 0, 0]
    assert len(ps.allot(groups, 99, random.Random(1))) == 16


def test_select_b_is_stratified_excludes_set_a_and_is_reproducible(
    family: tuple[list[Bundle], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    bundles, fam_a = family
    monkeypatch.setattr(ps, "B_TARGET", {"cp": 4, "user": 2, "hold_for_fact": 1})
    doc = ps.select_b(bundles, 5)
    assert doc == ps.select_b(bundles, 5)
    assert doc["selection"]["exclude"] == [fam_a] == doc["set_a"]["families"]
    runs = {r["run_id"] for r in doc["views"]}
    assert runs <= {"run-b1", "run-b2"} and len(runs) == 2  # both families drawn
    have = {ln: sum(n for _, n in doc["strata"][ln].values()) for ln in ("cp", "user")}
    assert doc["by_lane"] == {"cp": min(4, have["cp"]), "user": min(2, have["user"])}
    assert doc["by_lane"]["user"] == 2 and doc["by_lane"]["cp"] >= 2
    for lane in ("cp", "user"):
        strata = doc["strata"][lane]
        assert sum(k for k, _ in strata.values()) == doc["by_lane"][lane]
        assert all(k <= n for k, n in strata.values())
        assert {s.split()[0] for s in strata} == {"fam-b@1", "fam-c@1"}
    # The probe's --views-manifest takes exactly these, in this order.
    views = pss.manifest_views(bundles, doc)
    assert [[v.run_id, v.turn] for v in views] == [
        [r["run_id"], r["turn"]] for r in doc["views"]
    ]
    assert {v.seed_source for v in views} == {"recorded"}
    assert "--views-manifest <this file>" in doc["probe_args"]
    assert doc["views_sha256"] == pc.sha256_text(pc.canonical_json(doc["views"]))


def test_check_refuses_rows_outside_a_manifest(
    family: tuple[list[Bundle], str], tmp_path: Path
) -> None:
    bundles, _ = family
    doc = ps.select_b(bundles, 5)
    at, expected = pc.index(bundles, None)
    runs = {(r["run_id"], r["turn"]) for r in doc["views"]}
    inside = next(v for k, v in at.items() if k in runs)
    outside = next(v for k, v in at.items() if k not in runs)
    rows = [
        pss.row(pss.REFERENCE, v, v.raw, v.reference, []) for v in (inside, outside)
    ]
    path = report(tmp_path / "b.json", rows)
    with pytest.raises(SystemExit, match="outside its manifest"):
        pc.run_check([("B", path)], at, expected, TOK, {"B": doc})
    one = [("B", report(tmp_path / "b1.json", rows[:1]))]
    ok = pc.run_check(one, at, expected, TOK, {"B": doc})
    assert ok["sets"]["B"][pss.REFERENCE]["all"]["rows"] == 1


def test_a_view_with_two_guides_is_checked_at_its_first() -> None:
    """Stale bundles have them; teacher_select.checks (D2) refuses more than one."""
    two = (Guide(move=GuideMove.HOLD_FOR_FACT), Guide(move=GuideMove.ASK_DISCOUNT))
    fv = guided(GuideMove.ASK_DISCOUNT).model_copy(update={"guidance": two})
    c = checked(fv, "One moment.\n@hold fact_request")
    assert (c["label"], c["reason_fit"], c["D7"]) == ("required", True, True)
