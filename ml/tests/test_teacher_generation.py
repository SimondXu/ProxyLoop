from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from proxyloop_data_pipeline.teacher_pipeline import (
    GENERATION_REPORT_FILENAME,
    GENERATION_REPORT_SCHEMA_VERSION,
    LEDGER_FILENAME,
    load_samples,
    samples_path,
)
from proxyloop_evaluation.openai_frontier import FRONTIER_API_KEY_ENV
from proxyloop_evaluation.phase03c_experiment import PHASE03C_COMPILER_VERSIONS
from proxyloop_evaluation.phase03c_prompt_set import (
    PromptSetRow,
    load_prompt_set_manifest,
    render_prompt,
    write_prompt_set_manifest,
)
from proxyloop_evaluation.phase03c_teacher_filters import (
    CandidateContext,
    build_candidate_context,
)
from test_teacher_pipeline import (
    MODEL,
    TRAIN_FAMILIES,
    _Client,
    _Completions,
    perfect_content,
)

from scripts import run_phase03c_teacher_generation

ROOT = Path(__file__).resolve().parents[2]


def perfect_client(contexts: dict[str, CandidateContext]) -> _Client:
    """The fake relay keyed by user prompt; identical prompts share one target."""

    table: dict[str, list[str]] = {}
    for context in contexts.values():
        user = render_prompt(context.view).user
        content = [perfect_content(context.row)]
        assert table.setdefault(user, content) == content
    return _Client(_Completions(table))


@pytest.fixture(scope="module")
def small_manifest(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # One train seed and one development seed: 40 train + 40 development rows.
    path = tmp_path_factory.mktemp("manifest") / "prompt-set.json"
    write_prompt_set_manifest(path, train_seeds=(1,), dev_seeds=(900,))
    return path


@pytest.fixture(scope="module")
def small_rows(small_manifest: Path) -> tuple[PromptSetRow, ...]:
    return load_prompt_set_manifest(small_manifest)


@pytest.fixture(scope="module")
def train_contexts(
    small_rows: tuple[PromptSetRow, ...],
) -> dict[str, CandidateContext]:
    return {
        row.prompt_id: build_candidate_context(row)
        for row in small_rows
        if row.split == "train"
    }


def test_dry_run_reports_worst_case_for_train_rows_only(
    small_manifest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        run_phase03c_teacher_generation.main(
            ["--dry-run", "--manifest", str(small_manifest), "--k", "2"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "train prompts: 40 (k=2, prompt v6, concurrency 1)" in out
    assert f"{MODEL}: worst-case USD" in out and "for 80 calls" in out
    total = float(out.split("total worst-case USD ")[1].split(" ")[0])
    assert 0 < total < 150.0


def test_generation_run_writes_report_and_check_validates_it(
    small_manifest: Path,
    small_rows: tuple[PromptSetRow, ...],
    train_contexts: dict[str, CandidateContext],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    created: list[dict[str, object]] = []

    def factory(**kwargs: object) -> object:
        created.append(kwargs)
        return perfect_client(train_contexts)

    monkeypatch.setenv(FRONTIER_API_KEY_ENV, "sk-test-only-not-a-real-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=factory))
    out_dir = tmp_path / "teacher-full"
    args = ["--out-dir", str(out_dir), "--manifest", str(small_manifest)]

    assert run_phase03c_teacher_generation.main(["--check", *args]) == 0
    assert "nothing to check" in capsys.readouterr().out

    assert (
        run_phase03c_teacher_generation.main(["--k", "2", "--concurrency", "4", *args])
        == 0
    )
    captured = capsys.readouterr()
    assert len(created) == 1
    assert f"{MODEL}: sampled 40, skipped 0, calls 80" in captured.err
    assert "training_ready: False" in captured.out
    for name in (
        LEDGER_FILENAME,
        GENERATION_REPORT_FILENAME,
        f"{MODEL}-phase-03c-teacher-manifest.json",
        f"{MODEL}-phase-03c-teacher-quarantine.json",
        f"{MODEL}-phase-03c-teacher-quality-report.json",
        f"{MODEL}-samples.jsonl",
        f"{MODEL}-accepted.jsonl",
    ):
        assert (out_dir / name).is_file(), name
    # No development row was sampled: only the fake table's train prompts.
    samples = load_samples(samples_path(out_dir, MODEL))
    assert len(samples) == 80
    sampled_ids = {sample.prompt_id for sample in samples}
    dev_ids = {row.prompt_id for row in small_rows if row.split == "development"}
    assert sampled_ids.isdisjoint(dev_ids) and len(sampled_ids) == 40

    report = json.loads((out_dir / GENERATION_REPORT_FILENAME).read_text())
    assert report["schema_version"] == GENERATION_REPORT_SCHEMA_VERSION
    assert report["model"] == MODEL
    assert report["prompt_version"] == "v6"
    assert report["compiler_version"] == PHASE03C_COMPILER_VERSIONS["v6"]
    assert report["selection"] == {"split": "train", "k": 2, "concurrency": 4}
    assert report["prompt_count"] == 40
    assert report["rates"]["calls"] == 80
    assert report["rates"]["f1_rate"] == 1.0
    assert report["rates"]["f2_act_needed_rate"] == 1.0
    assert report["rates"]["f1_f4_rate"] == 1.0
    # No Go/Stop anywhere in the generation report; completeness is explicit.
    assert "decision" not in report["rates"]
    assert "decision" not in report
    assert report["prompts_sampled"] == 40
    assert report["prompts_complete"] == 40
    assert report["run_complete"] is True
    assert report["budget_stopped"] is False
    assert report["stop_reason"] is None
    assert report["ledger"]["stop_reason"] is None
    # Perfect identical completions: one accepted row per prompt.
    assert report["accepted_count"] == 40
    assert sum(report["accepted_per_family"].values()) == 40
    assert set(report["accepted_per_family"]) == TRAIN_FAMILIES
    assert report["accepted_families_coverage"] == {
        "covered": sorted(TRAIN_FAMILIES),
        "missing": [],
        "train_family_count": len(TRAIN_FAMILIES),
    }
    assert report["quarantine_per_filter"] == {"dedup": 40}
    assert report["training_ready"] is False
    assert report["training_ready_criteria"]["accepted_at_least_target"] is False
    assert report["training_ready_criteria"]["ledger_within_cap"] is True
    assert report["ledger"]["total_calls"] == 80
    assert report["ledger"]["usd_ceiling"] == 140.0

    assert run_phase03c_teacher_generation.main(["--check", *args]) == 0
    assert "recomputed from raw samples" in capsys.readouterr().out

    # A resumed run makes no new calls and rewrites the same report.
    assert run_phase03c_teacher_generation.main(["--k", "2", *args]) == 0
    assert f"{MODEL}: sampled 0, skipped 40, calls 0" in capsys.readouterr().err
    assert json.loads((out_dir / GENERATION_REPORT_FILENAME).read_text()) == {
        **report,
        "selection": {**report["selection"], "concurrency": 1},
    }

    # Tampering with the derived fields fails the check.
    report_path = out_dir / GENERATION_REPORT_FILENAME
    tampered = json.loads(report_path.read_text())
    tampered["training_ready"] = True
    tampered["accepted_count"] = 41
    tampered["run_complete"] = False
    tampered["prompts_complete"] = 39
    report_path.write_text(json.dumps(tampered))
    assert run_phase03c_teacher_generation.main(["--check", *args]) == 1
    out = capsys.readouterr().out
    assert "training_ready_not_derived" in out
    assert "curation_drift:accepted_count" in out
    assert "quality_report_drift:accepted_count" in out
    assert "completeness_drift:run_complete" in out
    assert "completeness_drift:prompts_complete" in out

    # Without raw samples the check still validates the stored report.
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    samples_path(out_dir, MODEL).unlink()
    assert run_phase03c_teacher_generation.main(["--check", *args]) == 0
    assert "raw samples absent" in capsys.readouterr().out


def test_hard_error_stops_the_generation_run_and_reset_rebuilds_the_ledger(
    small_manifest: Path,
    train_contexts: dict[str, CandidateContext],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from test_teacher_pipeline import _HardErrorCompletions

    perfect = perfect_client(train_contexts)
    client = _Client(
        _HardErrorCompletions(perfect.completions.by_user_prompt, successes=3)
    )
    monkeypatch.setenv(FRONTIER_API_KEY_ENV, "sk-test-only-not-a-real-key")
    monkeypatch.setitem(
        sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kwargs: client)
    )
    out_dir = tmp_path / "teacher-full"
    args = ["--out-dir", str(out_dir), "--manifest", str(small_manifest)]
    workers, k = 6, 2

    assert (
        run_phase03c_teacher_generation.main(
            ["--k", str(k), "--concurrency", str(workers), *args]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "stop_reason=hard_error:AuthenticationError" in captured.err
    calls = len(client.completions.calls)
    assert 4 <= calls <= 3 + workers * k
    report = json.loads((out_dir / GENERATION_REPORT_FILENAME).read_text())
    assert report["stop_reason"] == "hard_error:AuthenticationError"
    assert report["budget_stopped"] is False
    assert report["run_complete"] is False
    assert report["prompts_complete"] <= 1
    assert report["prompts_sampled"] < 40
    assert report["rates"]["calls"] == calls
    assert report["ledger"]["stop_reason"] == "hard_error:AuthenticationError"
    assert report["ledger"]["total_calls"] == calls
    assert run_phase03c_teacher_generation.main(["--check", *args]) == 0

    # The failed calls were charged at the worst case; the reset keeps only
    # the three succeeded calls' recorded estimates.
    per_call = 1_500 * 3.0 / 1e6 + 120 * 15.0 / 1e6
    ledger_before = json.loads((out_dir / LEDGER_FILENAME).read_text())
    assert ledger_before["total_estimated_usd"] > 3 * per_call
    assert run_phase03c_teacher_generation.main(["--reset-failed-charges", *args]) == 0
    out = capsys.readouterr().out
    assert f"ledger before: {calls} calls" in out
    assert f"ledger after: {calls} calls, USD {3 * per_call:.4f}" in out
    ledger_after = json.loads((out_dir / LEDGER_FILENAME).read_text())
    assert ledger_after["total_calls"] == calls
    assert ledger_after["total_estimated_usd"] == pytest.approx(3 * per_call)
    assert ledger_after["per_model"][MODEL]["succeeded"] == 3
    assert ledger_after["per_model"][MODEL]["failed"] == calls - 3
    assert ledger_after["stop_reason"] == "hard_error:AuthenticationError"
    assert ledger_after["usd_ceiling"] == 140.0
    assert not (out_dir / (LEDGER_FILENAME + ".tmp")).exists()

    samples_path(out_dir, MODEL).unlink()
    assert run_phase03c_teacher_generation.main(["--reset-failed-charges", *args]) == 1
    assert "nothing to reset" in capsys.readouterr().out


def test_committed_generation_report_is_consistent_or_absent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_phase03c_teacher_generation.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "nothing to check" in out or "consistent" in out
