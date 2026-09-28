"""Every detector against hand counts on the fixture bundle (``triage_bundle``:
event ``seq`` at ``t_ms = seq * 100``), and ``None`` where a bundle cannot tell."""

from __future__ import annotations

from pathlib import Path

from tests.contract.samples import QWEN
from tests.obs.bundles import Log, manifest, write
from tests.obs.triage_bundle import WINDOW_S, bundle, call, prompts, said, turn

from proxyloop.obs import detectors, runs, triage


def _values(run: Path, content: bool = False) -> dict[str, object]:
    return detectors.run_all(triage.read(run, runs.Seal(), WINDOW_S, content)[1])


def test_every_detector_equals_the_hand_count(tmp_path: Path) -> None:
    assert _values(bundle(tmp_path)) == {
        "declass_denied": 1,  # seq 29
        "end_reason": "abandoned",
        "fast_turns": 4,  # seqs 5, 13, 25, 28
        "finish_length": {"fast_cp": 2},  # c1, c2
        "finish_reason_null": {"slow": 2},  # s1 (error), s2 (cancelled)
        # s1's type and HTTP code; its text never leaves the bundle
        "first_llm_error": {
            "role": "slow", "seq": 26, "type": "EndpointError", "http": 400,
        },
        "llm_calls": 5,  # seqs 4, 12, 24, 26, 27
        "llm_cancelled": {"slow": 1},  # s2
        "llm_errors": {"slow": 1},  # s1; a cancellation is not an error
        # cp-g2 (seq 25) is capped and "@hold fact_request" holds no speech;
        # cp-g1 is capped too but speaks
        # turn 28 has no llm.call, so its cap is unknown, not "not capped"
        "empty_length": {"count": 1, "turns": [25], "unknown": [28]},
        "hold_repeats": 3,  # session.ended counts
        # rep.policy 19 ok_hold, 20 ok_hold, 21 ask_identity, 22 ok_hold: 2
        "max_consecutive_ok_hold": 2,
        # s2f-1 (t=1400) voiced by cp-g1, whose first delivery is seq 18
        # (t=1800): 1800 - 1400 = 400; s2f-2 (t=2300) is never voiced and
        # the log runs past 2300 + 1000; s2f-4 (t=3600) is pending when the
        # log ends at 3800 < 3600 + 1000 (the relay window)
        "guide_to_heard_ms": {
            "count": 1, "p50": 400, "p90": 400, "unheard": 1, "unknown": 1,
            "ms": [400],
        },
        # user.msg 3 (t=300) and 10 (t=1000): no f2s cites them by 300 + 1000
        # and 1000 + 1000, and the log runs to 3800; 8 is cited at t=900; 37
        # (t=3700) outlives the log (3700 + 1000 > 3800). Only 3 has a user.sim.
        "relay_gap": {
            "count": 2,
            "flagged": [3, 10],
            "unknown": [37],
            "sim_revealed": [3],
            "handoff_claims": None,  # text: only with content
        },
        "slow_max_step_gap_ms": 2900,  # 0→100 = 100, 100→3000 = 2900
        "slow_last_step_to_end_ms": 800,  # step 30 (t=3000) to the end, 3800
        "slow_steps": 2,  # seqs 1, 30
        # no fast.request names a profile here, so every turn's grammar is
        # unknown (test_speech_after_pause_follows_the_profile has them):
        # no turn could be read, so the count is None, not a clean 0
        "speech_after_pause": {
            "count": None, "items": 0, "issues": 0, "turns": [],
            "unknown": [5, 13, 25, 28],
        },
        # after @hold in cp-g1 (turn 13): "Stray one." + "Stray two." +
        # "Again." = 3; plus user-g1 (turn 5): "Thanks." after the @slow
        # line: 3 + 1 = 4; turn 28 has no llm.call
        "speech_after_directive": {
            "count": 4, "turns": [[5, 1], [13, 3]], "unknown": [28],
        },
        # IDENTIFY→DISCOVER at 22; after it, s2f-2 (seq 23) guides
        # hold_for_fact and s2f-4 (seq 36) identify
        "stale_identity_guides": {"count": 2, "seqs": [23, 36]},
        # 16 delivered interrupted; 17 and 35 never delivered; 17 is capped
        # cp-g1's last line with no closing mark: distinct {16, 17, 35} = 3;
        # 35 is cp-g3's last line and cp-g3 has no llm.call: cap unknown
        "unterminated_voiced": {
            "count": 3, "undelivered": [17, 35], "interrupted": [16], "cut": [17],
            "unknown": [35],
        },
        # the H5 detectors (test_grading has their own bundle): rep.policy
        # 19-22 and no chan.strike; slow.tool 32 is no tool of Slow's; every
        # other signal is absent here, so None
        "identity.strikes": {
            "count": 0, "strikes": [], "abandoned": None, "kind_from": "causes",
            "h5_pass": True,
        },
        "slow.unknown_tool": {"count": 1, "seqs": [32], "from": "name"},
        "slow.lever_refusals": {"count": 0, "seqs": [], "by": {}},
        **dict.fromkeys((
            "identity.cp_opened_ready", "identity.ask_user_per_key", "end.status",
            "approval.path", "slow.invalid_args", "slow.act_shape",
            "slow.finish_before_offer",
            "offer.required_unconfirmed_after_readback",
            "slow.readback_asks_max_per_revision", "close.reply_to_finish_steps",
            "end.unclosed_after_reply", "user.told_terms",
        )),
    }  # fmt: skip


def test_handoff_claims_read_text_only_with_content(tmp_path: Path) -> None:
    gap = _values(bundle(tmp_path), content=True)["relay_gap"]
    # msg 3: FastU's heard line 7 claims it; msg 10: line 11 says "haven't
    # passed that along", a negated claim, so no match
    assert isinstance(gap, dict)
    assert gap["handoff_claims"] == [
        {"seq": 3, "reply_seq": 7, "phrase": "passed that along"}
    ]


def test_unknowns_are_none_not_zero(tmp_path: Path) -> None:
    log = Log("rU")  # session.started only: no end, no rep, no step, no call
    values = _values(write(tmp_path / "rU", log, manifest("rU")))
    for name in (
        "end_reason", "hold_repeats", "slow_max_step_gap_ms",
        "stale_identity_guides", "max_consecutive_ok_hold",
    ):  # fmt: skip
        assert values[name] is None, name
    assert values["guide_to_heard_ms"] == {
        "count": 0, "p50": None, "p90": None, "unheard": 0, "unknown": 0,
        "ms": [],
    }  # fmt: skip
    assert values["first_llm_error"] == {}  # known: no call failed


def test_scalar() -> None:
    assert detectors.scalar(None) is None
    assert detectors.scalar({"count": None}) is None
    assert detectors.scalar({"fast_cp": 2, "slow": 1}) == 3
    assert detectors.scalar({"count": 4, "turns": []}) == 4
    assert detectors.scalar([1, 2]) == 2


def test_handoff_claims_skip_forward_and_other_sentences(tmp_path: Path) -> None:
    log = Log("rF")
    said(log, "PRIV-a")  # 1 (t=100): never relayed
    for n, text in enumerate(
        ("I look forward to helping.", "I can't stay long. I've passed that along.")
    ):
        payload: dict[str, object] = {"lane": "user", "utt_id": f"u{n}"}
        payload["text_generated"] = text
        payload |= {"text_heard": text, "interrupted": False}
        log.add("utt.delivered", "kernel", "agent", payload, (log.start,))  # 2, 3
    log.add("session.ended", "kernel", "ops", {"reason": "done"})  # 4 (t=400)
    run = write(tmp_path / "rF", log, manifest("rF"))
    x = triage.read(run, runs.Seal(), 0.3, True)[1]
    gap = detectors.as_dict(detectors.run_all(x)["relay_gap"])
    # "forward to" is no claim; "can't" is in the sentence before the claim
    assert gap["handoff_claims"] == [
        {"seq": 1, "reply_seq": 3, "phrase": "passed that along"}
    ]


def test_end_reason_is_a_code_or_withheld(tmp_path: Path) -> None:
    log = Log("rR")
    log.add("session.ended", "kernel", "ops", {"reason": "PRIV text reason"})
    assert _values(write(tmp_path / "rR", log, manifest("rR")))["end_reason"] == "?"


def test_events_are_parsed_once(tmp_path: Path) -> None:
    run, x = triage.read(bundle(tmp_path), runs.Seal())
    assert x.events is run.log  # the tuple runs.load parsed, not a second parse


def test_eval_never_imports_obs() -> None:
    src = Path(__file__).parents[2] / "src" / "proxyloop" / "eval"
    for path in src.rglob("*.py"):
        assert "proxyloop.obs" not in path.read_text("utf-8"), path


def test_hold_repeats_missing_key_is_zero_missing_counts_none(tmp_path: Path) -> None:
    ends: list[tuple[str, dict[str, object]]] = [("rC", {"counts": {}}), ("rN", {})]
    for run_id, end in ends:
        log = Log(run_id)
        log.add("session.ended", "kernel", "ops", {"reason": "done"} | end)
        values = _values(write(tmp_path / run_id, log, manifest(run_id)))
        assert values["hold_repeats"] == (0 if end else None), run_id


def test_speech_after_pause_follows_the_profile(tmp_path: Path) -> None:
    """The same raw response per turn: v2 counts the Speech items after the
    pause, v3 (pause_ends_speech) its one speech_after_pause issue per line;
    an unknown profile or no fast.request is unknown."""
    log = Log("rP")
    for n, profile in enumerate(("pl_cp_v2", "pl_cp_v3", "pl_cp_v9", None)):
        gen = f"cp-g{n}"
        if profile is not None:
            request: dict[str, object] = {"lane": "cp", "gen_id": gen}
            request |= {"trigger": "t", "view_sha": "v", "prompt_sha": "p"}
            request |= {"profile": profile, "model_ref": {}, "basis_seq": 0}
            log.add("fast.request", "kernel", "agent", request)
        turn(log, "cp", gen, f"c{n}", call(log, "fast_cp", QWEN, f"c{n}"))
    run = write(tmp_path / "rP", log, manifest("rP"))
    raw = "Please hold.\n@hold fact_request\nStray one. Stray two."
    prompts(run, {f"resp-c{n}": raw for n in range(4)})
    x = triage.read(run, runs.Seal())[1]
    assert detectors.DETECTORS["speech_after_pause"](x) == {
        "count": 3, "items": 2, "issues": 1,
        "turns": [[3, 2], [6, 1]],  # v2's turn (seq 3), v3's (seq 6)
        "unknown": [9, 11],  # pl_cp_v9 is no profile; the last has no request
    }  # fmt: skip
