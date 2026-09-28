"""Success-path progress (``obs.progress``, S1-SYS-86): the generic milestone
ladder per run from fixed-emitter events, table-driven over one synthetic
success path with one step left out at a time; the optional and by-outcome
milestones; the per-family summary diagnose prints. A diagnostic, never a
claim or a metric."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.obs.bundles import manifest, write
from tests.obs.path_bundle import Run, success

from proxyloop.obs import diagnose, progress


def _run(r: Run) -> Any:
    return progress.run(r.inputs())


def _status(out: Any) -> dict[str, str]:
    return {k: v["status"] for k, v in out["milestones"].items()}


def test_the_ladder_is_ordered_and_generic() -> None:
    assert progress.MILESTONES == (
        "identified", "discount_asked", "offer_recorded", "slow_lever_sent",
        "world_lever_heard", "later_rung", "readback_confirmed", "approval_requested",
        "approval_decided", "accept_released", "commit_heard", "verified",
    )  # fmt: skip
    assert frozenset({"approval_requested", "approval_decided"}) == progress.OPTIONAL
    assert (
        frozenset({"slow_lever_sent", "world_lever_heard", "later_rung"})
        == progress.BY_OUTCOME
    )


def test_a_full_path_reaches_every_milestone() -> None:
    out = _run(success())
    assert set(_status(out).values()) == {"reached"}
    assert out["furthest"] == "verified" and out["first_missing"] is None
    assert out["committed_rung"] == 1
    assert out["label"] == progress.LABEL
    assert out["end_status"] == "VERIFIED_COMPLETE" and out["tier"] == "B"


# (the step left out, the milestone that goes missing and is the first missing);
# "identified" is any rep.policy past identity, so an offer implies it: its
# missing case is the identity hang-up below.
CASES = [
    ("ask_discount", "discount_asked"),
    ("record", "offer_recorded"),
    ("lever_guide", "slow_lever_sent"),
    ("lever_ear", "world_lever_heard"),
    ("readback", "readback_confirmed"),
    ("decide", "approval_decided"),
    ("release", "accept_released"),
    ("commit", "commit_heard"),
    ("verified", "verified"),
]


@pytest.mark.parametrize(("skip", "missing"), CASES)
def test_one_step_left_out_is_the_first_missing(skip: str, missing: str) -> None:
    out = _run(success(frozenset({skip})))
    status = _status(out)
    assert status[missing] == "missing"
    assert out["first_missing"] == missing
    before = progress.MILESTONES[: progress.MILESTONES.index(missing)]
    assert all(status[m] in ("reached", "not_needed", "n/a") for m in before)


@pytest.mark.parametrize(
    ("verdict", "outcome", "status"),
    [("ok", "completed", "reached"), ("fail", "completed", "missing"),
     ("ok", "no_deal", "missing")],
)  # fmt: skip
def test_verified_is_the_deal_verifier_ok(
    verdict: str, outcome: str, status: str
) -> None:
    r = success(frozenset({"verified"}))
    r.verified(verdict, outcome)
    assert _status(_run(r))["verified"] == status


def test_the_seq_cited_is_the_first_trigger() -> None:
    r = success()
    out = _run(r)
    ms = out["milestones"]
    first_record = next(e.seq for e in r.log.events if e.type == "offer.recorded")
    assert ms["offer_recorded"]["seq"] == first_record
    commit = next(e.seq for e in r.log.events if e.type == "rep.commit_heard")
    assert ms["commit_heard"]["seq"] == commit


def test_approval_milestones_apply_only_with_a_card() -> None:
    out = _run(success(frozenset({"request"})))  # a mandate-style accept: no card
    status = _status(out)
    assert status["approval_requested"] == status["approval_decided"] == "n/a"
    assert out["first_missing"] is None and out["furthest"] == "verified"


def test_a_first_rung_close_needs_no_lever() -> None:
    """P-OBS clarification: an inside offer at rung 1 of the ladder accepted
    (or sent for approval) makes the lever and later-rung milestones "not
    needed", never the first missing."""
    out = _run(success(rung=0))
    status = _status(out)
    assert out["committed_rung"] == 0
    assert {status[m] for m in progress.BY_OUTCOME} == {"not_needed"}
    assert out["first_missing"] is None and out["furthest"] == "verified"


def test_a_first_rung_offer_only_sent_for_approval_needs_no_lever() -> None:
    r = Run()
    r.identify()
    r.guide("ask_discount")
    r.record(r.offer("ask_discount", 0, "save-1"))
    r.request()  # sent for approval, never decided
    r.end("timeout")
    out = _run(r)
    status = _status(out)
    assert {status[m] for m in progress.BY_OUTCOME} == {"not_needed"}
    assert out["first_missing"] == "readback_confirmed"


def test_no_committed_offer_needs_the_levers() -> None:
    """The rep offered rung 0, the agent levered, the rep had nothing better:
    nothing committed, so the later rung is missing, not "not needed"."""
    r = Run()
    r.identify()
    r.guide("ask_discount")
    r.record(r.offer("ask_discount", 0, "save-1"))
    r.guide("mention_tenure")
    r.policy("OFFER", "OFFER", "no_better", None, 0,
             r.ear("tenure", r.spoken("lever-x")))  # fmt: skip
    r.end("timeout")
    out = _run(r)
    status = _status(out)
    assert out["committed_rung"] is None
    assert status["slow_lever_sent"] == status["world_lever_heard"] == "reached"
    assert status["later_rung"] == "missing"
    assert (
        out["first_missing"] == "later_rung" and out["furthest"] == "world_lever_heard"
    )


def test_identified_is_the_move_past_identity() -> None:
    r = Run()
    r.identify()  # IDENTIFY -> DISCOVER, then the rep hangs up on silence
    r.end("abandoned")
    out = _run(r)
    assert _status(out)["identified"] == "reached"
    assert out["first_missing"] == "discount_asked"


def test_a_lever_before_the_first_offer_is_not_a_lever_sent() -> None:
    r = Run()
    r.identify()
    r.guide("ask_discount")  # the lever that makes the first offer
    r.record(r.offer("ask_discount", 0, "save-1"))
    r.end("timeout")
    status = _status(_run(r))
    assert status["slow_lever_sent"] == status["world_lever_heard"] == "missing"


def test_a_lagged_ear_label_is_not_a_lever_heard_after_the_offer() -> None:
    """rev-270 (run bdfcc0): the agent's line is delivered before the rep's
    first offer, the Ear labels it a lever after that offer; the anchor is the
    line's delivery, so it is not a lever heard after the first offer."""
    r = Run()
    r.identify()
    said = r.spoken("cp-g8-u1")  # before the offer
    r.record(r.offer("ask_discount", 0, "save-1"))
    r.ear("ask_discount", said)  # the Ear's label lands a turn later
    r.end("timeout")
    assert _status(_run(r))["world_lever_heard"] == "missing"
    r2 = Run()
    r2.identify()
    r2.record(r2.offer("ask_discount", 0, "save-1"))
    r2.ear("tenure", r2.spoken("cp-g9-u1"))  # said and labelled after the offer
    r2.end("timeout")
    assert _status(_run(r2))["world_lever_heard"] == "reached"


def _two_rungs(r: Run) -> tuple[str, str]:
    """The rep's rung-0 and rung-1 offer lines (world save-1, save-2)."""
    r.identify()
    first = r.offer("ask_discount", 0, "save-1")
    second = r.say(r.policy("OFFER", "FINAL", "final_offer", "save-2", 1,
                            r.ear("tenure", r.spoken("lever-2"))))  # fmt: skip
    return first, second


def test_the_committed_rung_is_the_highest_of_two_revisions() -> None:
    r = Run()
    first, second = _two_rungs(r)
    r.record(first, "offer-1", 1, "th1")
    r.request("offer-1", 1, "th1")  # rung 0, sent for approval
    r.record(second, "offer-1", 2, "th2")
    r.verbatim(r.authorize(r.start, "th2"))  # rung 1, accepted
    r.end("done")
    assert _run(r)["committed_rung"] == 1


def test_one_revision_citing_both_rungs_is_the_higher() -> None:
    r = Run()
    first, second = _two_rungs(r)
    r.record(first, "offer-1", 1, "th", second)
    r.request()
    r.end("done")
    out = _run(r)
    assert out["committed_rung"] == 1
    assert _status(out)["later_rung"] == "reached"


def test_one_unknown_slot_makes_the_committed_rung_unknown() -> None:
    r = Run()
    first, _ = _two_rungs(r)
    r.record(first, "offer-1", 1, "th", "cp-99")  # the second slot: no rep line
    r.request()
    r.end("done")
    assert _run(r)["committed_rung"] is None


def test_an_unknown_committed_rung_keeps_the_levers_needed() -> None:
    """The committed record cites no rep line obs can follow to a rung."""
    r = Run()
    r.identify()
    r.guide("ask_discount")
    r.offer("ask_discount", 0, "save-1")
    r.record("cp-99")  # no such rep line
    r.request()
    r.end("timeout")
    out = _run(r)
    assert out["committed_rung"] is None
    assert _status(out)["slow_lever_sent"] == "missing"


def test_a_denied_card_is_decided_and_the_accept_missing() -> None:
    r = Run()
    r.identify()
    r.guide("ask_discount")
    utt = r.offer("ask_discount", 0, "save-1")
    r.record(utt)
    r.guide("ask_readback", "offer:offer-1.monthly_price")
    r.confirmed()
    r.decide(r.request(), "denied")
    r.end("done")
    out = _run(r)
    status = _status(out)
    assert status["approval_decided"] == "reached"
    assert out["first_missing"] == "accept_released"


def test_identity_strikes_travel_with_the_run() -> None:
    r = Run()
    r.policy("GREET", "IDENTIFY", "ask_identity", cause=r.start)
    r.log.add("chan.strike", "kernel", "agent", {"lane": "cp", "kind": "identity"})
    r.policy("IDENTIFY", "ENDED", "hang_up", reason="identity", cause=r.start)
    r.end("abandoned")
    out = _run(r)
    assert out["identity_strikes"] == 2  # the strike plus the hang-up
    assert out["first_missing"] == "identified" and out["furthest"] is None


def test_summary_counts_runs_per_family_and_labels_itself() -> None:
    full, part, first = success(), success(frozenset({"commit"})), success(rung=0)
    rows = [
        {"run_id": "r1", "detectors": {"tier": {"family": "fam-a"}},
         "progress": _run(full)},
        {"run_id": "r2", "detectors": {"tier": {"family": "fam-a"}},
         "progress": _run(part)},
        {"run_id": "r3", "detectors": {"tier": {"family": "fam-b"}},
         "progress": _run(first)},
    ]  # fmt: skip
    s = progress.summary(rows)
    assert s["label"] == progress.LABEL
    fams: Any = s["families"]
    a, b = fams["fam-a"], fams["fam-b"]
    assert a["runs"] == 2 and a["reached"]["commit_heard"] == 1
    assert a["reached"]["accept_released"] == 2
    assert a["first_missing"] == {"commit_heard": 1}
    assert b["not_needed"] == {
        "later_rung": 1,
        "world_lever_heard": 1,
        "slow_lever_sent": 1,
    }
    text = progress.block(s, "slow_fp:abcdef0123456789")
    lines = text.splitlines()
    assert lines[0] == f"== progress slow_fp abcdef012345 ({progress.LABEL})"
    assert lines[1] == f"  legend: {progress.LEGEND}"
    assert any(x.startswith("  fam-a runs=2 ") for x in lines)
    assert "first_missing commit_heard=1" in text


def test_diagnose_adds_the_blocks_and_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    r = success()
    write(tmp_path / "rP", r.log, manifest("rP"))
    assert diagnose.main(["--root", str(tmp_path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert sorted(doc) == ["progress", "runs", "tiers", "watch", "world"]
    row = doc["runs"][0]
    assert row["progress"]["furthest"] == "verified"
    assert row["watch"]["label"] == progress.LABEL
    fam = doc["progress"]["git_sha:g"]["families"]["fam-a"]
    assert fam["runs"] == 1 and fam["reached"]["verified"] == 1
    assert diagnose.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"== progress git_sha g ({progress.LABEL})" in out
    assert f"== watch git_sha g ({progress.LABEL})" in out


REAL = Path(__file__).parents[2] / "evidence" / "s0" / "20260927T011839Z-a73470"


def test_a_real_bundle_smoke() -> None:
    """A committed S0 bundle (real models; it predates S1-SYS-62..85): the rep
    struck identity out and hung up, so nothing past identity is reached."""
    rows, skipped = diagnose.rows([REAL.parent])
    row: Any = next(x for x in rows if x["run_id"] == REAL.name)
    assert skipped == []
    p, w = row["progress"], row["watch"]
    assert p["first_missing"] == "identified" and p["furthest"] is None
    assert p["tier"] == "F" and p["tier_reason"] == "abandoned"
    items = w["items"]
    assert items["identity_strikes"]["count"] == p["identity_strikes"] == 3
    strikes = items["identity_strikes"]
    assert strikes["hang_up"] == 148 and strikes["hang_up_reason"] is None  # no key yet
    assert all(v["count"] == 0 for k, v in items.items() if k != "identity_strikes")
