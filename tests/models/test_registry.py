"""The condition registry (EVAL §4.1), and no clock dilation anywhere (I7)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.contract.samples import SONNET, session_config
from tests.support.fakes import ScriptedLLM, fake_ref

from proxyloop.contract.config import AblationId, SessionConfig
from proxyloop.contract.llm import AdapterKind
from proxyloop.evidence.reality import label
from proxyloop.models.registry import condition, conditions, resolve

ROOT = Path(__file__).resolve().parents[2]
REPAIR = (AblationId.TEACHER_REPAIR_CP, AblationId.TEACHER_REPAIR_USER)


def test_the_six_conditions() -> None:
    assert set(conditions()) == {"C2", "C3", "C4", "T", "F", "R"}


@pytest.mark.parametrize("name", ["C2", "C3", "C4", "T", "F", "R"])
def test_every_condition_makes_a_valid_live_config(name: str) -> None:
    cfg = condition(name).apply(session_config())
    assert cfg.live and cfg.slow == SONNET  # only the Fast side changes
    assert (cfg.fast_user.kind is AdapterKind.BASELINE) == (name == "F")


def test_what_each_condition_runs() -> None:
    fast = {name: condition(name).fast_cp.model_id for name in conditions()}
    assert fast == {
        "C2": "Qwen3.5-9B",
        "C3": "Qwen3.5-4B",
        "C4": "claude-haiku-4-5-20251001",
        "T": "claude-sonnet-5",
        "F": "proxyloop-fsm-v1",
        "R": "Qwen3.5-9B",
    }
    for name in conditions():
        c = condition(name)
        assert c.fast_user == c.fast_cp
        assert (c.teacher, c.ablations) == (
            (resolve("claude-sonnet-5"), REPAIR) if name == "R" else (None, ())
        )


def test_t_and_r_run_the_teacher_with_no_resamples() -> None:
    """E2 (#124): in evaluation the teacher gets no retry the student lacks."""

    limits = {name: condition(name).teacher_resamples for name in conditions()}
    assert limits == {"C2": None, "C3": None, "C4": None, "T": 0, "F": None, "R": 0}
    teacher = ScriptedLLM(fake_ref("teacher"), [])
    for name in ("T", "R"):
        assert condition(name).teacher_repair(teacher).max_resamples == 0
    with pytest.raises(ValueError, match="no teacher"):
        condition("C2").teacher_repair(teacher)


def test_the_reality_report_labels_f_as_the_baseline_fsm() -> None:
    assert label(condition("F").fast_cp) == "baseline_fsm"
    assert {label(condition(n).fast_cp) for n in ("C2", "C3", "R")} == {"vllm"}
    assert {label(condition(n).fast_cp) for n in ("C4", "T")} == {"hosted"}


def test_apply_merges_ablations_and_refuses_a_second_teacher() -> None:
    cfg = session_config(ablations=(AblationId.SUPPRESS_RELAY_CP,))
    merged = condition("R").apply(cfg)
    assert set(merged.ablations) == {AblationId.SUPPRESS_RELAY_CP, *REPAIR}
    haiku = resolve("claude-haiku-4-5")
    other = SessionConfig.model_validate(
        session_config().model_dump()
        | {"teacher": haiku, "ablations": (AblationId.TEACHER_REPAIR_CP,)}
    )
    with pytest.raises(ValueError, match="teacher"):
        condition("R").apply(other)


def test_unknown_names_fail_loudly() -> None:
    with pytest.raises(KeyError, match="known"):
        resolve("qwen-latest")
    with pytest.raises(KeyError, match="known"):
        condition("C9")


DILATION = re.compile(
    r"dilat|time[_-]?scale|clock[_-]?(?:scale|factor|speed)|slow[_-]?motion"
    r"|speed[_-]?up|scaled[_-]?clock|scale[_-]?(?:factor|clock|time)",
    re.I,
)
# src/ is held to a wider net: any "scale" word, except the unit table
# ``slow/tools.SCALE`` (minor units and months, not time).
SRC_SCALE = re.compile(r"scale", re.I)
UNIT_SCALE = re.compile(r"\bSCALE\b(?:\s*=\s*\{\"usd_minor\"|\[|\s*and\b|:)|in SCALE\b")
SCANNED = ("src", "serving", "training_jobs", "scripts", "tasks", "mk")
CODE = {".py", ".yaml", ".yml", ".toml", ".json", ".mk", ".sh"}


def test_no_clock_dilation_option_exists() -> None:
    """I7, C8: the teacher runs on the wall clock; no option can slow time."""

    files = [ROOT / "Makefile", ROOT / "pyproject.toml"]
    for top in SCANNED:
        files += [p for p in (ROOT / top).rglob("*") if p.suffix in CODE]
    hits = [
        f"{path.relative_to(ROOT)}:{n}"
        for path in files
        if path.is_file()
        for n, line in enumerate(path.read_text("utf-8").splitlines(), 1)
        if DILATION.search(line)
        or (
            path.is_relative_to(ROOT / "src")
            and SRC_SCALE.search(UNIT_SCALE.sub("", line))
        )
    ]
    assert hits == []
    assert not [f for f in SessionConfig.model_fields if DILATION.search(f)]


@pytest.mark.parametrize(
    "line",
    [
        "teacher_dilated: bool = False",
        "PL_TIME_SCALE = 10",
        "clock = ScaledClock(100)",
        "speedup: float = 1.0",
        "wall_scale = 2",
    ],
)
def test_the_src_net_catches_dilation_words(line: str) -> None:
    assert DILATION.search(line) or SRC_SCALE.search(UNIT_SCALE.sub("", line))
