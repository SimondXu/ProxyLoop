from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from proxyloop_evaluation import fresh_fixtures
from proxyloop_evaluation.phase03b_experiment import (
    PHASE03B_PUBLIC_MARKER,
    _compact_public_observation,
    _public_snapshot,
)
from proxyloop_evaluation.phase03c_experiment import (
    PHASE03C_COMPILER_VERSION,
    PHASE03C_COMPILER_VERSION_V4,
    Phase03CQwenAdapter,
)
from proxyloop_evaluation.phase03c_prompt_set import (
    PROMPT_SET_MANIFEST_PATH,
    PROMPT_SET_SCHEMA_VERSION,
    STAGE1B_PROMPT_VERSION,
    PromptSetRow,
    build_parameterised_snapshot,
    build_prompt_set,
    check_prompt_set_manifest,
    load_prompt_set_manifest,
    render_prompt,
    render_prompt_view,
    resolve_row,
    write_prompt_set_manifest,
)
from proxyloop_evaluation.phase03c_scenarios import harvest_positions
from proxyloop_evaluation.qwen_mlx import _FORBIDDEN_KEYS
from proxyloop_provider_simulator.scenarios import BENCHMARK_SCENARIOS
from proxyloop_provider_simulator.splits import generate_split_manifest

ROOT = Path(__file__).resolve().parents[2]
SPLIT_MANIFEST = generate_split_manifest(BENCHMARK_SCENARIOS)
TRAIN_FAMILIES = frozenset(
    family_id
    for family_id, split in SPLIT_MANIFEST.family_assignments
    if split == "train"
)
HELD_OUT_FAMILIES = frozenset(
    family_id
    for family_id, split in SPLIT_MANIFEST.family_assignments
    if split != "train"
)


@pytest.fixture(scope="module")
def committed_rows() -> tuple[PromptSetRow, ...]:
    return load_prompt_set_manifest(ROOT / PROMPT_SET_MANIFEST_PATH)


def _sample(rows: tuple[PromptSetRow, ...]) -> tuple[PromptSetRow, ...]:
    """Three rows across split, configuration, family, and position."""

    by_id = {row.prompt_id: row for row in rows}
    return (
        by_id["direct-success@1.0::transparent-public-v1@1.0::p7::pos1"],
        by_id["fee-total-cost-trap@1.0::retention-gated-v1@1.0::p41::pos2"],
        by_id["multi-hazard@1.0::transparent-public-v1@1.0::p905::pos1"],
    )


def test_split_manifest_is_the_committed_frozen_assignment() -> None:
    committed = json.loads(
        (ROOT / "data/manifests/phase-01b-split.json").read_text(encoding="utf-8")
    )
    assert SPLIT_MANIFEST.content_hash == committed["content_hash"]
    assert len(TRAIN_FAMILIES) == 10
    assert len(HELD_OUT_FAMILIES) == 6


def test_committed_rows_cover_train_families_only(
    committed_rows: tuple[PromptSetRow, ...],
) -> None:
    assert len(committed_rows) == 4400
    assert sum(row.split == "train" for row in committed_rows) == 4000
    assert sum(row.split == "development" for row in committed_rows) == 400
    assert len({row.prompt_id for row in committed_rows}) == 4400
    assert {row.family_id for row in committed_rows} == TRAIN_FAMILIES
    assert not {row.family_id for row in committed_rows} & HELD_OUT_FAMILIES
    assert {row.entity_cluster for row in committed_rows} == {
        entity
        for entity, split in SPLIT_MANIFEST.entity_assignments
        if split == "train"
    }
    train_seeds = {row.seed for row in committed_rows if row.split == "train"}
    dev_seeds = {row.seed for row in committed_rows if row.split == "development"}
    assert train_seeds == set(range(1, 101))
    assert dev_seeds == set(range(900, 910))
    assert {row.position_index for row in committed_rows} == {1, 2}
    assert all(
        row.event_cursor == (1 if row.position_index == 1 else 3)
        for row in committed_rows
    )


def test_build_prompt_set_matches_committed_prefix(
    committed_rows: tuple[PromptSetRow, ...],
) -> None:
    rows = build_prompt_set(train_seeds=(1, 2), dev_seeds=(900,))
    assert len(rows) == 3 * 10 * 2 * 2
    by_id = {row.prompt_id: row for row in committed_rows}
    assert all(by_id[row.prompt_id] == row for row in rows)


def test_committed_manifest_is_rendered_with_the_stage1b_v4_prompt() -> None:
    document = json.loads((ROOT / PROMPT_SET_MANIFEST_PATH).read_text("utf-8"))
    assert STAGE1B_PROMPT_VERSION == "v4"
    assert document["compiler_version"] == PHASE03C_COMPILER_VERSION_V4


def test_sampled_rows_re_render_to_the_same_fingerprints(
    committed_rows: tuple[PromptSetRow, ...],
) -> None:
    adapter = Phase03CQwenAdapter(generator=lambda _: "{}", prompt_version="v4")
    v3_adapter = Phase03CQwenAdapter(generator=lambda _: "{}")
    for row in _sample(committed_rows):
        scenario, position = resolve_row(row)
        view = render_prompt_view(scenario, position)
        prompt = render_prompt(view)
        assert view.pins.event_cursor == row.event_cursor
        assert position.oracle_action == row.oracle_action
        assert position.oracle_offer_id == row.oracle_offer_id
        assert prompt.rendered == adapter.build_prompt(view).rendered
        assert prompt.fingerprint == row.prompt_fingerprint
        assert prompt.rendered != v3_adapter.build_prompt(view).rendered
        assert (
            render_prompt(view, prompt_version="v3").fingerprint
            == v3_adapter.build_prompt(view).fingerprint
        )
        assert render_prompt_view(scenario, position).model_dump() == view.model_dump()
        # The parameterised Case flowed into the public observation the
        # compact view renders, not the frozen Phase 01A bill.
        observation = _compact_public_observation(view)
        assert (
            observation["current_monthly_total_minor"]
            == scenario.parameters.current_monthly_minor
        )
        assert (
            observation["target_monthly_total_minor"]
            == scenario.parameters.target_monthly_minor
        )
        assert observation["required_features"] == list(
            scenario.parameters.required_features
        )
        # The frozen 03B system text itself says "evaluator fields"; the
        # leakage check is on the compact view the model reads.
        view_json = prompt.user.split("COMPACT_FAST_VIEW:\n", 1)[1].casefold()
        for forbidden in (*_FORBIDDEN_KEYS, "oracle", "expected_action"):
            assert forbidden not in view_json
        assert "expected_action" not in prompt.rendered.casefold()
        assert "oracle" not in prompt.rendered.casefold()


def test_sampled_rows_input_fingerprint_matches(
    committed_rows: tuple[PromptSetRow, ...],
) -> None:
    from proxyloop_contracts import canonical_fingerprint

    for row in _sample(committed_rows):
        scenario, position = resolve_row(row)
        assert canonical_fingerprint(render_prompt_view(scenario, position)) == (
            row.input_fingerprint
        )


def test_position_two_view_carries_the_follow_up_turn() -> None:
    row = PromptSetRow(
        prompt_id="",
        family_id="direct-success",
        entity_cluster="entity-01",
        configuration_id="transparent-public-v1",
        seed=3,
        position_index=1,
        event_cursor=1,
        split="train",
        scenario_id="direct-success@1.0::transparent-public-v1@1.0::p3",
        input_fingerprint="",
        prompt_fingerprint="",
        oracle_action="",
        oracle_offer_id=None,
        parameters_fingerprint="",
    )
    scenario, opening = resolve_row(row)
    follow_up = harvest_positions(scenario)[1]
    view_one = render_prompt_view(scenario, opening)
    view_two = render_prompt_view(scenario, follow_up)
    assert follow_up.event_cursor == 3
    assert view_two.pins.event_cursor == 3
    assert len(view_one.recent_events) == 1
    assert [event.event_cursor for event in view_two.recent_events] == [1, 2, 3]
    assert [str(event.actor) for event in view_two.recent_events] == [
        "provider",
        "consumer",
        "provider",
    ]
    assert view_one.latest_provider_event is not None
    assert view_two.latest_provider_event is not None
    assert view_two.latest_provider_event.event_cursor == 3
    assert view_two.latest_provider_event.content.startswith(PHASE03B_PUBLIC_MARKER)
    assert view_one.latest_provider_event.content != (
        view_two.latest_provider_event.content
    )
    assert view_two.recent_events[0].content == scenario.provider_turn.message
    assert render_prompt(view_one).fingerprint != render_prompt(view_two).fingerprint


def test_default_params_snapshot_equals_frozen_public_snapshot() -> None:
    for scenario in BENCHMARK_SCENARIOS[:4]:
        opening = harvest_positions(scenario)[0]
        snapshot = build_parameterised_snapshot(scenario, opening)
        assert snapshot.case == fresh_fixtures._build_snapshot(scenario).case
        assert snapshot == _public_snapshot(scenario)[0]


def test_render_rejects_wrong_position_cursor() -> None:
    scenario = BENCHMARK_SCENARIOS[0]
    opening = harvest_positions(scenario)[0]
    with pytest.raises(ValueError, match="cursor"):
        build_parameterised_snapshot(scenario, replace(opening, event_cursor=2))


def test_manifest_write_check_and_tamper(tmp_path: Path) -> None:
    path = tmp_path / "prompt-set.json"
    rows = write_prompt_set_manifest(path, train_seeds=(1,), dev_seeds=(900,))
    assert len(rows) == 80
    assert check_prompt_set_manifest(path, train_seeds=(1,), dev_seeds=(900,)) == ()
    assert load_prompt_set_manifest(path) == rows
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == PROMPT_SET_SCHEMA_VERSION
    assert document["compiler_version"] == PHASE03C_COMPILER_VERSION_V4
    assert document["split_manifest_content_hash"] == SPLIT_MANIFEST.content_hash
    assert document["split_counts"] == {"development": 40, "train": 40}
    assert document["position_counts"] == {"1": 40, "2": 40}
    assert "parameters_fingerprint" not in document["row_columns"]
    assert document["parameters_by_seed"] == {
        "1": rows[0].parameters_fingerprint,
        "900": rows[-1].parameters_fingerprint,
    }
    assert path.stat().st_size < 40_000

    tampered = json.loads(json.dumps(document))
    tampered["parameters_by_seed"]["900"] = "0" * 64
    path.write_text(json.dumps(tampered), encoding="utf-8")
    problems = check_prompt_set_manifest(path, train_seeds=(1,), dev_seeds=(900,))
    assert problems == (
        "manifest_drift:parameters_by_seed",
        "manifest_drift:rows:40",
    )

    document["rows"][0][document["row_columns"].index("prompt_fingerprint")] = "0" * 64
    path.write_text(json.dumps(document), encoding="utf-8")
    problems = check_prompt_set_manifest(path, train_seeds=(1,), dev_seeds=(900,))
    assert problems == ("manifest_drift:rows:1",)

    assert check_prompt_set_manifest(path, train_seeds=(1, 2), dev_seeds=(900,)) == (
        "manifest_drift:content_fingerprint",
        "manifest_drift:family_counts",
        "manifest_drift:parameters_by_seed",
        "manifest_drift:position_counts",
        "manifest_drift:row_count",
        "manifest_drift:split_counts",
        "manifest_drift:train_seed_range",
        "manifest_drift:rows:41",
    )
    assert check_prompt_set_manifest(tmp_path / "missing.json") == (
        f"missing_manifest:{tmp_path / 'missing.json'}",
    )


def test_manifest_records_and_checks_the_prompt_version(tmp_path: Path) -> None:
    path = tmp_path / "prompt-set-v3.json"
    v3_rows = write_prompt_set_manifest(
        path, train_seeds=(1,), dev_seeds=(900,), prompt_version="v3"
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["compiler_version"] == PHASE03C_COMPILER_VERSION
    assert (
        check_prompt_set_manifest(
            path, train_seeds=(1,), dev_seeds=(900,), prompt_version="v3"
        )
        == ()
    )
    v4_rows = build_prompt_set(train_seeds=(1,), dev_seeds=(900,))
    assert [row.prompt_id for row in v3_rows] == [row.prompt_id for row in v4_rows]
    assert [row.input_fingerprint for row in v3_rows] == [
        row.input_fingerprint for row in v4_rows
    ]
    assert all(
        v3.prompt_fingerprint != v4.prompt_fingerprint
        for v3, v4 in zip(v3_rows, v4_rows, strict=True)
    )
    # Checking a v3 manifest against the Stage 1b default (v4) drifts on the
    # compiler version, the content fingerprint, and every row.
    assert check_prompt_set_manifest(path, train_seeds=(1,), dev_seeds=(900,)) == (
        "manifest_drift:compiler_version",
        "manifest_drift:content_fingerprint",
        "manifest_drift:rows:80",
    )


def test_build_prompt_set_rejects_overlapping_seeds() -> None:
    with pytest.raises(ValueError, match="disjoint"):
        build_prompt_set(train_seeds=(1, 2), dev_seeds=(2,))
