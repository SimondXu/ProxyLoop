"""Frame (strata, seeded draws, inclusion probabilities), lexicon, blinded export."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import pytest
from tests.evidence.audit.bundles import Line, Script, write_bundle

from proxyloop.evidence.audit import export, frame, items, lexicon
from proxyloop.evidence.audit.__main__ import main

_ACTS = ["accept", "cancel_intent", "ask_readback", "smalltalk", "cite_competitor"]
_TEXTS = [
    "Yes, I accept that offer.",
    "I want to cancel my plan.",
    "Could you read it back to me?",
    "Nice weather today.",
    "Another company quoted me less.",
    "My pin is 4 8 2 1",
    "Okay.",
]


def _script(n: int) -> Script:
    lines: list[Line] = []
    for i in range(n):
        text = _TEXTS[i % len(_TEXTS)]
        act = _ACTS[i % len(_ACTS)] if i % 3 else None  # some lines the Ear missed
        facts = (("account.pin", "4821"),) if "pin" in text and i % 2 else ()
        if facts:
            act = "provide_fact"
        lines.append(Line("cp", text, act, facts))
        lines.append(
            Line("user", "All done, it is cancelled." if i % 2 else "Working on it.")
        )
    return Script(lines=lines, offer=True)


@pytest.fixture
def bundles(tmp_path: Path) -> list[Path]:
    a = write_bundle(tmp_path / "a", "run-a", _script(40), "Qwen3.5-9B")
    b = write_bundle(tmp_path / "b", "run-b", _script(30), "Qwen3.5-9B-lora")
    return [a, b]


def test_the_lexicon_flags_wide_and_only_by_lane() -> None:
    assert "accept" in lexicon.flags("Sure, sounds good.")
    assert "provide_fact_protected" in lexicon.flags("it is four eight two one")
    assert "provide_fact_protected" in lexicon.flags("code 48-21")
    assert "completion_claim" in lexicon.flags("I've cancelled it, all set.")
    assert lexicon.flags("What plan are you on?") == ()
    assert lexicon.flags("The room is 12") == ()
    assert lexicon.flags("Nice weather today.") == ()


def test_candidates_carry_the_ear_label_context_and_speaker(
    bundles: list[Path],
) -> None:
    cands = items.load(bundles, seed=1)
    assert len(cands) == 140
    by_text = {c.utt_id: c for c in cands if c.run_id == "run-a"}
    first = by_text["cp-0"]
    assert (first.lane, first.ear_act, first.ear_class) == ("cp", None, None)
    assert first.previous_rep == "Which plan is it?"
    assert first.offers[0]["slots"][0] == {
        "field": "monthly", "value": "5000", "unit": "usd_minor", "role": "recurring",
    }  # fmt: skip
    assert all(c.ear_act is None for c in cands if c.lane == "user")
    assert {c.speaker_model for c in cands} == {
        "real_http:Qwen3.5-9B",
        "real_http:Qwen3.5-9B-lora",
    }
    protected = [c for c in cands if c.ear_class == "provide_fact_protected"]
    assert protected and all(c.ear_act == "provide_fact" for c in protected)
    user_flags = {f for c in cands if c.lane == "user" for f in c.flags}
    assert user_flags == {"completion_claim"}


def test_a_line_without_a_fast_sentence_is_not_a_fast_model_line(
    tmp_path: Path,
) -> None:
    script = Script(lines=[Line("cp", "Yes, deal.", "accept", verbatim=True)])
    run = write_bundle(tmp_path / "v", "run-v", script)
    assert [c.speaker_model for c in items.load([run], 1)] == ["verbatim"]


def test_the_draw_is_deterministic_in_the_seed(bundles: list[Path]) -> None:
    def picked(seed: int) -> list[str]:
        cands = items.load(bundles, seed)
        sizes = {"positive": 3, "flagged": 3, "random": 10}
        return sorted(i["item_id"] for i in frame.build(cands, seed, sizes).sampled())

    assert picked(5) == picked(5)
    assert picked(5) != picked(6)


def test_inclusion_probabilities_follow_the_design(bundles: list[Path]) -> None:
    sizes = {"positive": 4, "flagged": 5, "random": 12}
    built = frame.build(items.load(bundles, 3), 3, sizes)
    per_stratum: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "N": 0})
    for cell in built.cells:
        assert cell.pi == cell.n / cell.N and 0 < cell.pi <= 1
        kind = cell.stratum.split("/")[0]
        assert cell.n <= sizes[kind]
        per_stratum[cell.stratum]["n"] += cell.n
        per_stratum[cell.stratum]["N"] += cell.N
    for stratum, tot in per_stratum.items():  # a stratum holds min(size, N) draws
        assert tot["n"] == min(sizes[stratum.split("/")[0]], tot["N"]), stratum
    random_cells = [c for c in built.cells if c.stratum == "random/all"]
    assert {c.model for c in random_cells} == {  # the random stratum splits by model
        "real_http:Qwen3.5-9B", "real_http:Qwen3.5-9B-lora",
    }  # fmt: skip
    assert sum(c.n for c in random_cells) == 12
    # the stored pi of the items of each cell sum to that cell's n
    sums: dict[str, float] = defaultdict(float)
    for row in built.items:
        for key, pi in row["cells"].items():
            sums[key] += pi
    for cell in built.cells:
        assert sums[cell.key] == pytest.approx(cell.n)
    for row in built.items:  # the item's own pi combines its cells
        miss = 1.0
        for pi in row["cells"].values():
            miss *= 1 - pi
        assert row["pi"] == pytest.approx(1 - miss)
        assert 0 < row["pi"] <= 1


def test_positive_and_flagged_strata_have_the_right_members(
    bundles: list[Path],
) -> None:
    cands = items.load(bundles, 1)
    for c in cands:
        strata = frame.strata_of(c)
        assert "random/all" in strata
        assert (f"positive/{c.ear_class}" in strata) == (c.ear_class is not None)
        for f in c.flags:
            assert (f"flagged/{f}" in strata) == (f != c.ear_class)
    assert frame.allocate({"a": 100, "b": 100}, 60) == {"a": 30, "b": 30}
    assert frame.allocate({"a": 5, "b": 100}, 60) == {"a": 5, "b": 55}
    assert frame.allocate({"a": 3, "b": 4}, 60) == {"a": 3, "b": 4}
    assert sum(frame.allocate({"a": 9, "b": 9, "c": 9}, 10).values()) == 10


def test_the_export_is_blind(bundles: list[Path], tmp_path: Path) -> None:
    cands = items.load(bundles, 9)
    built = frame.build(cands, 9, {"positive": 4, "flagged": 4, "random": 10})
    doc = json.loads(json.dumps({"items": built.items}))
    rows = export.export(doc, seed=1)
    assert len(rows) == len(built.sampled()) > 0
    assert all(tuple(r) == export.BLIND_FIELDS for r in rows)
    secret = {"run-a", "run-b", "base", "cp", "user", "verbatim", "scripted"}
    for c in cands:
        secret |= {
            c.bundle,
            c.speaker_model,
            c.condition,
            c.utt_id,
            f"{c.run_id}-secret",
        }
        secret |= {a for a in (c.ear_act, c.ear_class, *c.flags) if a}
    for row in rows:
        values = [row["item_id"], row["utterance"], row["previous_rep"]]
        values += [str(v) for o in row["offers"] for v in _leaves(o)]
        assert not secret & {v for v in values if isinstance(v, str)}
        assert "source_utt" not in json.dumps(row["offers"])
    blob = "\n".join(json.dumps(r) for r in rows)
    for token in ("run-a", "run-b", "Qwen3.5", "positive/", "flagged/", "ear_"):
        assert token not in blob
    ids = [r["item_id"] for r in rows]
    assert ids != sorted(ids)  # shuffled
    assert ids == [r["item_id"] for r in export.export(doc, seed=1)]
    assert ids != [r["item_id"] for r in export.export(doc, seed=2)]


def _leaves(x: Any) -> list[Any]:
    if isinstance(x, dict):
        return [
            v for child in cast("dict[str, Any]", x).values() for v in _leaves(child)
        ]
    if isinstance(x, list):
        return [v for child in cast("list[Any]", x) for v in _leaves(child)]
    return [x]


def test_the_cli_frames_and_exports(
    bundles: list[Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f, out = tmp_path / "frame.json", tmp_path / "items.jsonl"
    argv = ["frame", *map(str, bundles), "--seed", "4", "--out", str(f)]
    assert main([*argv, "--positive", "3", "--flagged", "3", "--random", "9"]) == 0
    assert main(["export", str(f), "--seed", "4", "--out", str(out)]) == 0
    rows = [json.loads(line) for line in out.read_text("utf-8").splitlines()]
    doc = frame.load(f)
    assert {r["item_id"] for r in rows} == {
        i["item_id"] for i in doc["items"] if i["sampled"]
    }
    assert doc["lexicon"] == lexicon.LEXICON_VERSION
    capsys.readouterr()
