"""Deterministic family/entity split manifest for Phase 01B."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from .scenarios import BenchmarkScenario


class SplitName(StrEnum):
    TRAIN = "train"
    DEVELOPMENT = "development"
    TEST = "test"


@dataclass(frozen=True, slots=True)
class SplitManifest:
    """Canonical family/entity/scenario assignments and their content hash."""

    schema_version: str
    family_assignments: tuple[tuple[str, str], ...]
    entity_assignments: tuple[tuple[str, str], ...]
    scenario_assignments: tuple[tuple[str, str], ...]
    content_hash: str

    @property
    def family_counts(self) -> dict[str, int]:
        return _counts(self.family_assignments)

    @property
    def entity_counts(self) -> dict[str, int]:
        return _counts(self.entity_assignments)

    @property
    def scenario_counts(self) -> dict[str, int]:
        return _counts(self.scenario_assignments)

    def family_split(self, family_id: str) -> str:
        return _lookup(self.family_assignments, family_id)

    def entity_split(self, entity_cluster: str) -> str:
        return _lookup(self.entity_assignments, entity_cluster)

    def scenario_split(self, scenario_id: str) -> str:
        return _lookup(self.scenario_assignments, scenario_id)

    def to_dict(self) -> dict[str, object]:
        """Return the canonical content, including its computed fingerprint."""

        return {
            "schema_version": self.schema_version,
            "family_assignments": [
                {"family_id": key, "split": value}
                for key, value in self.family_assignments
            ],
            "entity_assignments": [
                {"entity_cluster": key, "split": value}
                for key, value in self.entity_assignments
            ],
            "scenario_assignments": [
                {"scenario_id": key, "split": value}
                for key, value in self.scenario_assignments
            ],
            "content_hash": self.content_hash,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)


def generate_split_manifest(
    scenarios: Iterable[BenchmarkScenario],
) -> SplitManifest:
    """Assign connected family/entity components to stable 10/3/3 splits.

    The sort and union steps make the result independent of input order.  A
    component is the connected set of family IDs and entity clusters, so
    derivatives from either side of the relationship cannot cross a split.
    """

    scenario_list = tuple(scenarios)
    if not scenario_list:
        raise ValueError("at least one benchmark scenario is required")

    family_to_entity: dict[str, str] = {}
    for scenario in scenario_list:
        previous_entity = family_to_entity.setdefault(
            scenario.family_id, scenario.entity_cluster
        )
        if previous_entity != scenario.entity_cluster:
            raise ValueError(
                f"family {scenario.family_id} has conflicting entity clusters"
            )
    scenario_ids = {scenario.scenario_id for scenario in scenario_list}
    if len(scenario_ids) != len(scenario_list):
        raise ValueError("scenario IDs must be unique")
    if len(family_to_entity) != 16:
        raise ValueError("Phase 01B requires exactly 16 scenario families")

    components = _connected_components(family_to_entity)
    if len(components) != 16:
        raise ValueError(
            "Phase 01B requires exactly 16 connected family/entity components"
        )

    ordered_components = sorted(components, key=lambda component: component[0])
    split_by_component: dict[str, str] = {}
    for index, component in enumerate(ordered_components):
        split = _split_for_index(index)
        for member in component:
            split_by_component[member] = split

    family_assignments = tuple(
        sorted(
            (family_id, split_by_component[family_id]) for family_id in family_to_entity
        )
    )
    entity_to_split: dict[str, str] = {}
    for family_id, entity in family_to_entity.items():
        split = split_by_component[family_id]
        previous = entity_to_split.setdefault(entity, split)
        if previous != split:
            raise ValueError("one entity cluster cannot cross benchmark splits")
    entity_assignments = tuple(sorted(entity_to_split.items()))
    scenario_assignments = tuple(
        sorted(
            (
                scenario.scenario_id,
                split_by_component[scenario.family_id],
            )
            for scenario in scenario_list
        )
    )
    content = {
        "schema_version": "1.0",
        "family_assignments": [
            {"family_id": key, "split": value} for key, value in family_assignments
        ],
        "entity_assignments": [
            {"entity_cluster": key, "split": value} for key, value in entity_assignments
        ],
        "scenario_assignments": [
            {"scenario_id": key, "split": value} for key, value in scenario_assignments
        ],
    }
    canonical_content = json.dumps(content, separators=(",", ":"), sort_keys=True)
    content_hash = hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()
    return SplitManifest(
        schema_version="1.0",
        family_assignments=family_assignments,
        entity_assignments=entity_assignments,
        scenario_assignments=scenario_assignments,
        content_hash=content_hash,
    )


def _connected_components(
    family_to_entity: dict[str, str],
) -> tuple[tuple[str, ...], ...]:
    parent = {member: member for pair in family_to_entity.items() for member in pair}

    def find(member: str) -> str:
        root = member
        while parent[root] != root:
            root = parent[root]
        while parent[member] != member:
            next_member = parent[member]
            parent[member] = root
            member = next_member
        return root

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for family_id, entity in family_to_entity.items():
        union(family_id, entity)

    components: dict[str, set[str]] = {}
    for member in parent:
        components.setdefault(find(member), set()).add(member)
    return tuple(
        tuple(sorted(member for member in members if member in family_to_entity))
        for members in components.values()
    )


def _split_for_index(index: int) -> str:
    if index < 10:
        return SplitName.TRAIN.value
    if index < 13:
        return SplitName.DEVELOPMENT.value
    return SplitName.TEST.value


def _counts(assignments: tuple[tuple[str, str], ...]) -> dict[str, int]:
    counts = {split.value: 0 for split in SplitName}
    for _, split in assignments:
        counts[split] += 1
    return counts


def _lookup(assignments: tuple[tuple[str, str], ...], key: str) -> str:
    for candidate, split in assignments:
        if candidate == key:
            return split
    raise KeyError(key)


__all__ = ["SplitManifest", "SplitName", "generate_split_manifest"]
