from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def document(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_hosted_rerun_is_closed_and_training_stays_inactive() -> None:
    agents = document("AGENTS.md")
    plans = document("PLANS.md")
    contract = document("harness/build/phase-03a1-hosted-rerun.md")

    assert "Phase 03A1-R hosted baseline reliability rerun completed" in agents
    assert "No implementation phase is active" in agents
    assert "| 03A1-R |" in plans and "Complete; corrected full matrix" in plans
    assert "| 03B |" in plans and "Not started" in plans
    assert "**Status**: Complete with the corrected full hosted matrix" in contract
    assert "`phase_completion_ready=true`" in contract
    assert "No SFT, QLoRA, DPO, RL" in contract


def test_hosted_rerun_has_a_separate_module_command_artifact_and_make_gate() -> None:
    required = (
        "ml/evaluation/src/proxyloop_evaluation/hosted_rerun.py",
        "scripts/run_phase_03a1_hosted_rerun.py",
    )
    missing = [path for path in required if not (ROOT / path).is_file()]

    assert not missing, f"missing Phase 03A1-R surface: {missing}"
    makefile = document("Makefile")
    assert "hosted-rerun-source-check:" in makefile
    assert "hosted-rerun-check:" in makefile
    assert "scripts.run_phase_03a1_hosted_rerun --check-sources" in makefile
    assert "scripts.run_phase_03a1_hosted_rerun --check" in makefile
    test_target = next(
        line for line in makefile.splitlines() if line.startswith("test:")
    )
    assert "hosted-rerun-check" in test_target


def test_r4_artifact_path_cannot_alias_immutable_r2_or_r3() -> None:
    source = document("ml/evaluation/src/proxyloop_evaluation/hosted_rerun.py")

    assert "phase-03a1-r4-hosted-rerun-report.json" in source
    assert "R2_REPORT_PATH" in source
    assert "R3_REPORT_PATH" in source
    assert "write_report_v2" not in source
    assert "write_report_v3" not in source
