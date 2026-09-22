"""Phase 03C Stage 1b parameterised prompt set.

Renders one leakage-safe ``FastModelView`` per harvested Fast position of
every train-family instance (10 train families x 2 configurations x seeds x
2 positions) and records only metadata plus fingerprints in
``data/manifests/phase-03c-prompt-set.json``.  The snapshot construction
mirrors ``fresh_fixtures._build_snapshot`` and ``phase03b_experiment
._public_snapshot`` but reads the instance's own ``build_case(parameters)``
Case and places the position's Provider turn as the latest visible event, so
the frozen Phase 03C prompt builder renders the parameterised public
observation.  No model is called anywhere here.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

from proxyloop_agent_core import CaseCoordinator
from proxyloop_contracts import (
    CaseContextSnapshot,
    EventActor,
    FactLedger,
    FastModelView,
    ModelInputPins,
    VisibleCaseEvent,
    canonical_fingerprint,
)
from proxyloop_provider_simulator.scenarios import (
    BENCHMARK_SCENARIOS,
    PROVIDER_CONFIGURATIONS,
    SCENARIO_FAMILIES,
    BenchmarkScenario,
    ScenarioFamily,
    build_parameterised_scenarios,
)
from proxyloop_provider_simulator.splits import SplitManifest, generate_split_manifest

from proxyloop_evaluation import fresh_fixtures
from proxyloop_evaluation.phase03b_experiment import PHASE03B_PUBLIC_MARKER
from proxyloop_evaluation.phase03b_readiness import proposed_fast_target
from proxyloop_evaluation.phase03c_experiment import (
    PHASE03C_COMPILER_VERSIONS,
    Phase03CQwenAdapter,
    PromptVersion,
)
from proxyloop_evaluation.phase03c_scenarios import (
    FastPosition,
    _cached_case,
    _oracle,
    build_parameterised_observation,
    harvest_positions,
    parameters_fingerprint,
)
from proxyloop_evaluation.qwen_mlx import QwenPrompt, _assert_safe_keys

PROMPT_SET_SCHEMA_VERSION: Final = "phase-03c-prompt-set-v1"
PROMPT_SET_MANIFEST_PATH: Final = Path("data/manifests/phase-03c-prompt-set.json")
# Stage 1c renders with v6 (the rule-precedence fix of the v5 block); the
# committed v4 pilot, v5 re-pilot, and Stage 0 v3 artifacts keep their own
# versions.
STAGE1B_PROMPT_VERSION: Final[PromptVersion] = "v6"
DEFAULT_TRAIN_SEEDS: Final = range(1, 101)
# Within-family development split: the contract's "~400 prompts" from the
# 900-949 pool, i.e. its first ten seeds.
DEFAULT_DEV_SEEDS: Final = range(900, 910)

PromptSplit = Literal["train", "development"]


@dataclass(frozen=True, slots=True)
class PromptSetRow:
    """Metadata and fingerprints of one rendered prompt; never its text."""

    prompt_id: str
    family_id: str
    entity_cluster: str
    configuration_id: str
    seed: int
    position_index: int
    event_cursor: int
    split: PromptSplit
    scenario_id: str
    input_fingerprint: str
    prompt_fingerprint: str
    oracle_action: str
    oracle_offer_id: str | None
    parameters_fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def train_families(split_manifest: SplitManifest) -> tuple[ScenarioFamily, ...]:
    """The ten train families of the frozen Phase 01B split, catalogue order."""

    return tuple(
        family
        for family in SCENARIO_FAMILIES
        if split_manifest.family_split(family.family_id) == "train"
    )


def _consumer_message(scenario: BenchmarkScenario) -> str:
    """The canonical response the harvest submitted after the opening turn."""

    opening = build_parameterised_observation(scenario, scenario.provider_turn)
    action = _oracle().decide(opening).action.value
    response_text = proposed_fast_target(action)["response_text"]
    if not isinstance(response_text, str):
        raise TypeError("proposed_fast_target response_text must be text")
    return response_text


def _public_content(position: FastPosition) -> str:
    return f"{PHASE03B_PUBLIC_MARKER}\n" + json.dumps(
        position.observation.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def build_parameterised_snapshot(
    scenario: BenchmarkScenario, position: FastPosition
) -> CaseContextSnapshot:
    """Snapshot at ``position`` whose Case is ``build_case(scenario.parameters)``.

    Position 1 reproduces ``phase03b_experiment._public_snapshot`` for the
    frozen catalogue (same stable ids, timestamps, strategy, and planning
    basis).  Position 2 appends the consumer message and the Provider
    follow-up so the latest visible event is that follow-up.
    """

    if position.position_index not in (1, 2):
        raise ValueError("position_index must be 1 or 2")
    case = _cached_case(scenario.parameters)
    turn = position.provider_turn
    opening = scenario.provider_turn
    manifest = fresh_fixtures._capability_manifest()
    ledger = FactLedger(
        contract_type="fact_ledger",
        schema_version="1.0",
        revision=1,
        ledger_id=fresh_fixtures._stable_uuid4(f"ledger:{scenario.scenario_id}"),
        case_id=case.case_id,
        created_at=case.created_at,
        updated_at=turn.observed_at,
        entries=(),
    )
    offers = tuple(
        fresh_fixtures._canonical_provider_offer(
            item,
            case_id=case.case_id,
            provider_id=turn.provider_id,
            observed_at=turn.observed_at,
        )
        for item in turn.offers
    )
    strategy = fresh_fixtures._strategy(case)
    provider_config_ref = f"{scenario.configuration_id}@2.0"
    basis = fresh_fixtures._planning_basis(
        case=case,
        ledger=ledger,
        offers=offers,
        provider_config_ref=provider_config_ref,
        manifest=manifest,
    )
    pins = ModelInputPins(
        contract_type="model_input_pins",
        schema_version="1.0",
        revision=1,
        case_id=case.case_id,
        case_revision=case.revision,
        constraint_set_revision=case.constraint_set_revision,
        fact_ledger_revision=ledger.revision,
        strategy_id=strategy.strategy_id,
        strategy_revision=strategy.revision,
        planning_basis_fingerprint=basis.planning_basis_fingerprint,
        event_cursor=position.event_cursor,
        provider_config_ref=provider_config_ref,
        capability_manifest_version=manifest.manifest_version,
    )

    def event(
        cursor: int, actor: EventActor, event_type: str, content: str, at: datetime
    ) -> VisibleCaseEvent:
        return VisibleCaseEvent(
            contract_type="visible_case_event",
            schema_version="1.0",
            revision=1,
            event_id=fresh_fixtures._stable_uuid4(
                f"event:{scenario.scenario_id}:r2:{cursor}"
            ),
            case_id=case.case_id,
            event_cursor=cursor,
            occurred_at=at,
            actor=actor,
            event_type=event_type,
            content=content,
        )

    events: tuple[VisibleCaseEvent, ...]
    if position.position_index == 1:
        if position.event_cursor != 1:
            raise ValueError("position 1 must sit at event cursor 1")
        events = (
            event(
                1,
                EventActor.PROVIDER,
                "provider_turn",
                _public_content(position),
                opening.observed_at,
            ),
        )
    else:
        if position.event_cursor != 3:
            raise ValueError("position 2 must sit at event cursor 3")
        events = (
            event(
                1,
                EventActor.PROVIDER,
                "provider_turn",
                opening.message,
                opening.observed_at,
            ),
            event(
                2,
                EventActor.CONSUMER,
                "consumer_message",
                _consumer_message(scenario),
                opening.observed_at + timedelta(seconds=1),
            ),
            event(
                3,
                EventActor.PROVIDER,
                "provider_turn",
                _public_content(position),
                turn.observed_at,
            ),
        )
    snapshot = CaseContextSnapshot(
        contract_type="case_context_snapshot",
        schema_version="1.0",
        revision=1,
        case=case,
        fact_ledger=ledger,
        strategy=strategy,
        offers=offers,
        action_intents=(),
        approval_requests=(),
        visible_events=events,
        event_cursor=position.event_cursor,
        planning_basis=basis,
        pins=pins,
        provider_config_ref=provider_config_ref,
        capability_manifest=manifest,
    )
    return CaseContextSnapshot.model_validate(snapshot.model_dump(mode="python"))


def _model_input_keys(view: FastModelView) -> dict[str, object]:
    """The view as the frozen Qwen builders read it.

    ``qwen_mlx.build_prompt`` projects ``pins`` without
    ``capability_manifest_version`` and ``planning_basis`` down to its
    fingerprint (the capability vocabulary revision is not model input);
    every other key is checked as-is, plus the public observation embedded
    in the marker event.
    """

    serialized = view.model_dump(mode="json")
    pins = dict(serialized["pins"])
    pins.pop("capability_manifest_version", None)
    serialized["pins"] = pins
    serialized["planning_basis"] = {
        "planning_basis_fingerprint": view.planning_basis.planning_basis_fingerprint
    }
    event = view.latest_provider_event
    if event is None or not event.content.startswith(PHASE03B_PUBLIC_MARKER):
        raise ValueError("prompt view requires the public observation marker")
    serialized["public_observation"] = json.loads(event.content.split("\n", 1)[1])
    return serialized


def render_prompt_view(
    scenario: BenchmarkScenario, position: FastPosition
) -> FastModelView:
    """Project the leakage-safe Fast view the prompt builder consumes."""

    view = CaseCoordinator.project_fast_view(
        build_parameterised_snapshot(scenario, position)
    )
    _assert_safe_keys(_model_input_keys(view))
    return view


@lru_cache(maxsize=len(PHASE03C_COMPILER_VERSIONS))
def prompt_builder(
    prompt_version: PromptVersion = STAGE1B_PROMPT_VERSION,
) -> Phase03CQwenAdapter:
    """The shared prompt-only adapter; its generator is never called."""

    return Phase03CQwenAdapter(generator=lambda _: "{}", prompt_version=prompt_version)


def render_prompt(
    view: FastModelView, *, prompt_version: PromptVersion = STAGE1B_PROMPT_VERSION
) -> QwenPrompt:
    """The one Phase 03C prompt for ``view`` (byte-equal to the smoke path)."""

    return prompt_builder(prompt_version).build_prompt(view)


def resolve_row(row: PromptSetRow) -> tuple[BenchmarkScenario, FastPosition]:
    """Rebuild the scenario instance and harvested position a row names."""

    family = next(item for item in SCENARIO_FAMILIES if item.family_id == row.family_id)
    configuration = next(
        item
        for item in PROVIDER_CONFIGURATIONS
        if item.configuration_id == row.configuration_id
    )
    (scenario,) = build_parameterised_scenarios(
        seeds=(row.seed,), families=(family,), configurations=(configuration,)
    )
    if scenario.scenario_id != row.scenario_id:
        raise ValueError(f"scenario_id_mismatch:{row.prompt_id}")
    position = harvest_positions(scenario)[row.position_index - 1]
    if position.event_cursor != row.event_cursor:
        raise ValueError(f"event_cursor_mismatch:{row.prompt_id}")
    return scenario, position


def _rows_for_scenario(
    scenario: BenchmarkScenario,
    *,
    split: PromptSplit,
    params_fingerprint: str,
    prompt_version: PromptVersion,
) -> tuple[PromptSetRow, ...]:
    rows = []
    for position in harvest_positions(scenario):
        view = render_prompt_view(scenario, position)
        rows.append(
            PromptSetRow(
                prompt_id=f"{scenario.scenario_id}::pos{position.position_index}",
                family_id=scenario.family_id,
                entity_cluster=scenario.entity_cluster,
                configuration_id=scenario.configuration_id,
                seed=scenario.parameters.seed,
                position_index=position.position_index,
                event_cursor=position.event_cursor,
                split=split,
                scenario_id=scenario.scenario_id,
                input_fingerprint=canonical_fingerprint(view),
                prompt_fingerprint=render_prompt(
                    view, prompt_version=prompt_version
                ).fingerprint,
                oracle_action=position.oracle_action,
                oracle_offer_id=position.oracle_offer_id,
                parameters_fingerprint=params_fingerprint,
            )
        )
    return tuple(rows)


def build_prompt_set(
    *,
    train_seeds: Iterable[int] = DEFAULT_TRAIN_SEEDS,
    dev_seeds: Iterable[int] = DEFAULT_DEV_SEEDS,
    prompt_version: PromptVersion = STAGE1B_PROMPT_VERSION,
) -> tuple[PromptSetRow, ...]:
    """Render every train-family instance position and return its rows.

    Rows are ordered by family, configuration, seed, and position.  The
    development split reuses the train families with disjoint seeds; the
    split manifest's development and test families never appear.
    """

    train_list = tuple(train_seeds)
    dev_list = tuple(dev_seeds)
    if set(train_list) & set(dev_list):
        raise ValueError("train and development seeds must be disjoint")
    split_manifest = generate_split_manifest(BENCHMARK_SCENARIOS)
    families = train_families(split_manifest)
    if len(families) != 10:
        raise RuntimeError(f"expected_10_train_families:{len(families)}")
    rows: list[PromptSetRow] = []
    seed_plan: tuple[tuple[PromptSplit, tuple[int, ...]], ...] = (
        ("train", train_list),
        ("development", dev_list),
    )
    for split, seeds in seed_plan:
        for seed in seeds:
            # One seed at a time keeps the per-parameters Case cache warm.
            params_fingerprint = parameters_fingerprint((seed,))
            for scenario in build_parameterised_scenarios(
                seeds=(seed,), families=families, configurations=PROVIDER_CONFIGURATIONS
            ):
                if split_manifest.family_split(scenario.family_id) != "train":
                    raise RuntimeError(f"non_train_family:{scenario.family_id}")
                rows.extend(
                    _rows_for_scenario(
                        scenario,
                        split=split,
                        params_fingerprint=params_fingerprint,
                        prompt_version=prompt_version,
                    )
                )
    rows.sort(
        key=lambda row: (
            row.family_id,
            row.configuration_id,
            row.seed,
            row.position_index,
        )
    )
    if len({row.prompt_id for row in rows}) != len(rows):
        raise RuntimeError("prompt_ids must be unique")
    return tuple(rows)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _seed_range(seeds: tuple[int, ...]) -> dict[str, int]:
    return {"first": min(seeds), "last": max(seeds), "count": len(seeds)}


def prompt_set_manifest(
    rows: tuple[PromptSetRow, ...],
    *,
    train_seeds: Iterable[int] = DEFAULT_TRAIN_SEEDS,
    dev_seeds: Iterable[int] = DEFAULT_DEV_SEEDS,
    prompt_version: PromptVersion = STAGE1B_PROMPT_VERSION,
) -> dict[str, object]:
    """The manifest document: counts, fingerprints, and metadata-only rows.

    Rows are stored column-wise (``row_columns`` names the order) and the
    per-seed ``parameters_fingerprint`` once in ``parameters_by_seed`` so the
    committed file carries no repeated key names or hashes;
    ``content_fingerprint`` is taken over the logical row dicts (including
    the looked-up parameters fingerprint) and is independent of that layout.
    """

    if not rows:
        raise ValueError("rows must be non-empty")
    row_dicts = [row.to_dict() for row in rows]
    parameters_by_seed: dict[str, str] = {}
    for row in rows:
        previous = parameters_by_seed.setdefault(
            str(row.seed), row.parameters_fingerprint
        )
        if previous != row.parameters_fingerprint:
            raise ValueError(f"seed {row.seed} has conflicting parameters")
    columns = [column for column in row_dicts[0] if column != "parameters_fingerprint"]
    split_counts = Counter(row.split for row in rows)
    family_counts = Counter(row.family_id for row in rows)
    position_counts = Counter(str(row.position_index) for row in rows)
    return {
        "schema_version": PROMPT_SET_SCHEMA_VERSION,
        "compiler_version": PHASE03C_COMPILER_VERSIONS[prompt_version],
        "split_manifest_content_hash": generate_split_manifest(
            BENCHMARK_SCENARIOS
        ).content_hash,
        "train_seed_range": _seed_range(tuple(train_seeds)),
        "development_seed_range": _seed_range(tuple(dev_seeds)),
        "row_count": len(rows),
        "split_counts": dict(sorted(split_counts.items())),
        "family_counts": dict(sorted(family_counts.items())),
        "position_counts": dict(sorted(position_counts.items())),
        "content_fingerprint": _sha256(row_dicts),
        "parameters_by_seed": dict(
            sorted(parameters_by_seed.items(), key=lambda item: int(item[0]))
        ),
        "row_columns": columns,
        "rows": [[row[column] for column in columns] for row in row_dicts],
    }


def _render_manifest(document: dict[str, object]) -> str:
    """Indent the header; keep one compact line per row so the file stays small."""

    header = {key: value for key, value in document.items() if key != "rows"}
    rows = document["rows"]
    if not isinstance(rows, list):
        raise TypeError("manifest rows must be a list")
    header_text = json.dumps(header, indent=2, sort_keys=True)
    row_lines = ",\n".join("    " + _canonical_json(row) for row in rows)
    return header_text[:-2] + ',\n  "rows": [\n' + row_lines + "\n  ]\n}\n"


def write_prompt_set_manifest(
    path: Path,
    *,
    train_seeds: Iterable[int] = DEFAULT_TRAIN_SEEDS,
    dev_seeds: Iterable[int] = DEFAULT_DEV_SEEDS,
    prompt_version: PromptVersion = STAGE1B_PROMPT_VERSION,
) -> tuple[PromptSetRow, ...]:
    train_list = tuple(train_seeds)
    dev_list = tuple(dev_seeds)
    rows = build_prompt_set(
        train_seeds=train_list, dev_seeds=dev_list, prompt_version=prompt_version
    )
    document = prompt_set_manifest(
        rows,
        train_seeds=train_list,
        dev_seeds=dev_list,
        prompt_version=prompt_version,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_manifest(document), encoding="utf-8")
    return rows


def prompt_set_compiler_version(path: Path) -> str:
    """The ``compiler_version`` the manifest's fingerprints were rendered with."""

    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(
        document.get("compiler_version"), str
    ):
        raise ValueError(f"unsupported prompt set manifest: {path}")
    return str(document["compiler_version"])


def load_prompt_set_manifest(path: Path) -> tuple[PromptSetRow, ...]:
    """Read the committed rows back without re-rendering anything."""

    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != PROMPT_SET_SCHEMA_VERSION
    ):
        raise ValueError(f"unsupported prompt set manifest: {path}")
    columns = document["row_columns"]
    parameters_by_seed = document["parameters_by_seed"]
    rows = []
    for values in document["rows"]:
        fields = dict(zip(columns, values, strict=True))
        fields["parameters_fingerprint"] = parameters_by_seed[str(fields["seed"])]
        rows.append(PromptSetRow(**fields))
    return tuple(rows)


def check_prompt_set_manifest(
    path: Path,
    *,
    train_seeds: Iterable[int] = DEFAULT_TRAIN_SEEDS,
    dev_seeds: Iterable[int] = DEFAULT_DEV_SEEDS,
    prompt_version: PromptVersion = STAGE1B_PROMPT_VERSION,
) -> tuple[str, ...]:
    """Re-render the prompt set and report every field that drifted."""

    if not path.is_file():
        return (f"missing_manifest:{path}",)
    committed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(committed, dict):
        return (f"malformed_manifest:{path}",)
    train_list = tuple(train_seeds)
    dev_list = tuple(dev_seeds)
    rows = build_prompt_set(
        train_seeds=train_list, dev_seeds=dev_list, prompt_version=prompt_version
    )
    expected = prompt_set_manifest(
        rows,
        train_seeds=train_list,
        dev_seeds=dev_list,
        prompt_version=prompt_version,
    )
    problems = [
        f"manifest_drift:{key}"
        for key in sorted(set(committed) | set(expected))
        if key != "rows" and committed.get(key) != expected.get(key)
    ]
    # Compare the logical rows (columnar rows joined with the per-seed
    # table) so tampering with either surfaces as row drift.  Unreadable
    # committed rows simply count as drifted.
    expected_by_id = {row.prompt_id: row for row in rows}
    committed_by_id: dict[str, PromptSetRow] = {}
    with contextlib.suppress(KeyError, TypeError, ValueError):
        committed_by_id = {row.prompt_id: row for row in load_prompt_set_manifest(path)}
    drifted = sum(
        committed_by_id.get(prompt_id) != expected_by_id.get(prompt_id)
        for prompt_id in set(committed_by_id) | set(expected_by_id)
    )
    if drifted:
        problems.append(f"manifest_drift:rows:{drifted}")
    return tuple(problems)


__all__ = [
    "DEFAULT_DEV_SEEDS",
    "DEFAULT_TRAIN_SEEDS",
    "PROMPT_SET_MANIFEST_PATH",
    "PROMPT_SET_SCHEMA_VERSION",
    "STAGE1B_PROMPT_VERSION",
    "PromptSetRow",
    "build_parameterised_snapshot",
    "build_prompt_set",
    "check_prompt_set_manifest",
    "load_prompt_set_manifest",
    "prompt_builder",
    "prompt_set_compiler_version",
    "prompt_set_manifest",
    "render_prompt",
    "render_prompt_view",
    "resolve_row",
    "train_families",
    "write_prompt_set_manifest",
]
