"""Offline replay of the r5 validity-smoke raw outputs through the current evaluator.

The committed r5 artifact is provenance and is never rewritten.  Its per-row
labels are re-derived here from the stored Slow/Fast raw outputs and hosted
call evidence, with the same smoke adapters and runner the r5 writer used, so
a label edit that keeps every count and fingerprint self-consistent is still
caught (the ``hosted_rescore`` pattern for r4).  Only wall-clock latencies
are carried over from r5; everything else must be re-derived identically.

The four private ``replay_v2`` names are deliberate: ``replay_v2.py`` is frozen
as r4 execution bytes (``hosted_rerun._R4_EXECUTION_PATHS``), so its offline
replay machinery is imported, never edited or re-exported (the
``hosted_rescore`` precedent).
"""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace

from .artifacts_v2 import R2_FRONTIER_INPUT_TOKEN_CAP, R2_FRONTIER_OUTPUT_TOKEN_CAP
from .fresh_fixtures import FreshPhase03A1ModelFixture
from .models import EvaluationConditionV2, EvaluationSummaryV2
from .openai_frontier import estimate_frontier_cost
from .replay_v2 import (
    _hosted_items,
    _qwen_generator,
    _ReplayCompletions,
    _selected_fixtures,
)
from .runner_v2 import run_frontier_condition_v2
from .validity_smoke import ValiditySmokeFrontierAdapter, ValiditySmokeQwenAdapter

_SMOKE_CONDITION = EvaluationConditionV2.UNTUNED_FAST_FRONTIER_SLOW_MEDIUM


def replay_validity_smoke_summary(
    recorded: EvaluationSummaryV2,
    *,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> EvaluationSummaryV2:
    """Re-run the r5 condition from ``fixtures`` and the captured raw outputs.

    ``fixtures`` are the prepared (public-provider-state) fixtures the r5
    writer ran.  No provider or local model is called.
    """

    if recorded.condition is not _SMOKE_CONDITION:
        raise ValueError("validity-smoke replay expects the medium Fast+Slow condition")
    selected = _selected_fixtures(recorded, fixtures)
    completions = _ReplayCompletions(deque(_hosted_items(recorded)))
    estimate = estimate_frontier_cost(
        input_token_cap=R2_FRONTIER_INPUT_TOKEN_CAP,
        output_token_cap=R2_FRONTIER_OUTPUT_TOKEN_CAP,
        call_cap=len(selected),
        usd_ceiling=100.0,
    )
    frontier = ValiditySmokeFrontierAdapter(
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        reasoning_effort="medium",
        input_token_cap=R2_FRONTIER_INPUT_TOKEN_CAP,
        max_output_tokens=R2_FRONTIER_OUTPUT_TOKEN_CAP,
        call_cap=len(selected),
        usd_ceiling=estimate.maximum_cost_usd,
    )
    qwen = ValiditySmokeQwenAdapter(generator=_qwen_generator(recorded, hosted=True))
    replayed = run_frontier_condition_v2(
        frontier,
        condition=recorded.condition,
        fixtures=selected,
        qwen=qwen,
    )
    if completions.items:
        raise AssertionError("offline replay left unused hosted call evidence")
    return _with_recorded_latencies(replayed, recorded)


def _with_recorded_latencies(
    replayed: EvaluationSummaryV2, recorded: EvaluationSummaryV2
) -> EvaluationSummaryV2:
    """Copy the wall-clock latencies, the one thing replay cannot reproduce.

    Only row ``latency_ms`` and ``hosted_calls[*].latency_ms`` come from r5;
    the latency percentiles are recomputed from them by ``from_episodes``, and
    every other row and summary field is the replay's own derivation.
    """

    source_rows = {row.episode_id: row for row in recorded.episodes}
    rows = []
    for row in replayed.episodes:
        source = source_rows[row.episode_id]
        if len(row.hosted_calls) != len(source.hosted_calls):
            raise ValueError(f"{row.episode_id} hosted call count differs on replay")
        calls = tuple(
            call.model_copy(update={"latency_ms": source_call.latency_ms})
            for call, source_call in zip(
                row.hosted_calls, source.hosted_calls, strict=True
            )
        )
        rows.append(
            row.model_copy(
                update={"latency_ms": source.latency_ms, "hosted_calls": calls}
            )
        )
    return EvaluationSummaryV2.from_episodes(
        condition=replayed.condition,
        run_status=replayed.run_status,
        not_run_reason=replayed.not_run_reason,
        expected_episode_count=replayed.expected_episode_count,
        model_call_count=replayed.model_call_count,
        episodes=tuple(rows),
        failure_slices=replayed.failure_slices,
        model_provenance=replayed.model_provenance,
        prompt_provenance=replayed.prompt_provenance,
        hosted_max_cost_microusd=replayed.hosted_max_cost_microusd,
    )


def check_validity_smoke_replay(
    recorded: EvaluationSummaryV2,
    *,
    fixtures: tuple[FreshPhase03A1ModelFixture, ...],
) -> tuple[str, ...]:
    """Every committed r5 row and summary field equals the current replay.

    Compared: every field of every row (including hosted call evidence,
    tokens, cost, fingerprints and raw outputs) and every summary field.  Only
    the wall-clock latencies are taken from r5 (``_with_recorded_latencies``).
    """

    try:
        replayed = replay_validity_smoke_summary(recorded, fixtures=fixtures)
    except (AssertionError, TypeError, ValueError) as error:
        return (f"summary replay failed: {type(error).__name__}: {error}",)
    replayed_rows = {row.episode_id: row for row in replayed.episodes}
    errors = [
        f"summary replay: {row.episode_id} differs from its stored raw outputs"
        for row in recorded.episodes
        if replayed_rows.get(row.episode_id) != row
    ]
    errors.extend(
        f"summary replay: {field} differs from the stored raw outputs"
        for field in EvaluationSummaryV2.model_fields
        if field != "episodes" and getattr(replayed, field) != getattr(recorded, field)
    )
    return tuple(errors)


__all__ = [
    "check_validity_smoke_replay",
    "replay_validity_smoke_summary",
]
