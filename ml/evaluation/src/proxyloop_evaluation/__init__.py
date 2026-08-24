"""Phase 03A1 model-evaluation package."""

from .artifacts import check_baseline_artifacts, write_report
from .fast_output import FastModelOutput, compile_fast_output
from .models import (
    BaselineCondition,
    BaselineReport,
    ConditionSummary,
    EpisodeBaselineResult,
    ModelProvenance,
    PromptProvenance,
    RunStatus,
)
from .runner import (
    compose_report,
    frontier_report,
    initial_report,
    not_run_condition,
    qwen_report,
    run_frontier_condition,
)
from .slow_output import (
    CapabilityModelOutput,
    SlowModelOutput,
    StrategyModelOutput,
    compile_slow_output,
)

__all__ = [
    "BaselineCondition",
    "BaselineReport",
    "CapabilityModelOutput",
    "ConditionSummary",
    "EpisodeBaselineResult",
    "FastModelOutput",
    "ModelProvenance",
    "PromptProvenance",
    "RunStatus",
    "SlowModelOutput",
    "StrategyModelOutput",
    "check_baseline_artifacts",
    "compile_fast_output",
    "compile_slow_output",
    "compose_report",
    "frontier_report",
    "initial_report",
    "not_run_condition",
    "qwen_report",
    "run_frontier_condition",
    "write_report",
]
