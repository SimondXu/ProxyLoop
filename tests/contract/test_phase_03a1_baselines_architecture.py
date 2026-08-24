from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVALUATION = ROOT / "ml" / "evaluation" / "src" / "proxyloop_evaluation"


def imported_roots(source: Path) -> set[str]:
    roots: set[str] = set()
    for path in source.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def test_model_evaluation_surface_is_ml_only() -> None:
    required = (
        EVALUATION / "__init__.py",
        EVALUATION / "models.py",
        EVALUATION / "fast_output.py",
        EVALUATION / "slow_output.py",
        EVALUATION / "artifacts.py",
        EVALUATION / "runner.py",
        EVALUATION / "qwen_mlx.py",
        EVALUATION / "openai_frontier.py",
        EVALUATION / "replay.py",
        ROOT / "scripts" / "run_phase_03a1_baselines.py",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    assert not missing, f"missing Phase 03A1-B surface: {missing}"


def test_runtime_lock_remains_free_of_model_dependencies() -> None:
    with (ROOT / "runtime" / "pyproject.toml").open("rb") as project_file:
        runtime = tomllib.load(project_file)
    serialized = str(runtime).casefold()
    for dependency in ("mlx", "openai", "transformers", "torch", "vllm"):
        assert dependency not in serialized


def test_model_sdk_imports_are_lazy_and_confined_to_evaluation() -> None:
    runtime_imports = imported_roots(ROOT / "runtime")
    assert not runtime_imports & {"mlx", "mlx_lm", "openai", "transformers"}

    qwen = (EVALUATION / "qwen_mlx.py").read_text(encoding="utf-8")
    frontier = (EVALUATION / "openai_frontier.py").read_text(encoding="utf-8")
    assert "importlib" in qwen and "mlx_lm" in qwen
    assert "from openai import OpenAI" in frontier
    assert "imported only when a real client is needed" in frontier


def test_baseline_make_gate_is_offline_and_part_of_preflight() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "baselines:" in makefile
    assert "baselines-check:" in makefile
    assert "run_phase_03a1_baselines.py" in makefile
    assert "harness-check baselines-check" in makefile


def test_baseline_contract_keeps_training_and_authority_out_of_scope() -> None:
    build = (ROOT / "harness/build/phase-03a1-baselines.md").read_text(encoding="utf-8")
    for marker in (
        "quantized_untuned",
        "not_run_missing_credentials",
        "Invalid JSON/schema output is measured as failure",
        "Only Evidence-backed",
        "Do not train",
    ):
        assert marker in build


def test_hosted_runner_requires_explicit_budget_and_environment_credential() -> None:
    runner = (ROOT / "scripts" / "run_phase_03a1_baselines.py").read_text(
        encoding="utf-8"
    )
    assert "--approve-max-cost-usd" in runner
    assert "not os.environ.get(FRONTIER_API_KEY_ENV)" in runner
    assert "11_010_048" in (EVALUATION / "runner.py").read_text(encoding="utf-8")
    frontier = (EVALUATION / "openai_frontier.py").read_text(encoding="utf-8")
    assert "max_retries=0" in frontier
    assert "FAILED_PROVIDER_CALL" in frontier


def test_qwen_provenance_is_file_attested_not_cli_declared() -> None:
    cli = (ROOT / "scripts" / "run_phase_03a1_baselines.py").read_text(encoding="utf-8")
    qwen = (EVALUATION / "qwen_mlx.py").read_text(encoding="utf-8")
    assert "--model-revision" not in cli
    assert "--source-revision" not in cli
    assert "attest_qwen_checkpoint" in qwen
    assert "QWEN_CHECKPOINT_FINGERPRINT" in qwen
