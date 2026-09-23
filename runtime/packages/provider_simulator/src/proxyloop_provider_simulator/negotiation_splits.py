"""Versioned V2 split and safety-family set (audit D1-10, design decision 4).

The V1 split (``splits.py``, alphabetical within fixed counts) and
``multi_turn.SAFETY_FAMILIES_V1`` stay frozen for the committed V1 evidence.

The V2 split is stratified. Each family belongs to one stratum derived from
its hazards (success, offer hazard, evidence, fact request); within a stratum
families are ranked by a salted hash of the family id alone. Rank 0 is held
out, rank 1 goes to development when the stratum has at least three
families, and the rest train. So every stratum is represented in held-out,
held-out always contains a completable and a hazard family (gated), and
adding or relabelling a family can only move families of its own stratum.
Both policy instances follow their family (families are held out whole);
assignments are recorded by id only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from .negotiation_catalog import (
    EVIDENCE_HAZARDS,
    FACT_REQUEST_HAZARDS,
    OFFER_TERM_HAZARDS,
    NegotiationFamily,
    NegotiationScenario,
)

NEGOTIATION_SPLIT_VERSION = "negotiation-split-v2"

# Families where a wrong terminal action causes a harmful side effect or a
# privacy leak: every hazard family.  Success families and the pure
# fact-request family (clarification) are not safety families.  This matches
# the intent of the pinned ``SAFETY_FAMILIES_V1`` now that ``forged-evidence``
# and ``multi-hazard`` test what they name (P-C/P-D acceptance).
SAFETY_FAMILIES_V2 = frozenset(
    {
        "fee-total-cost-trap",
        "required-feature-loss",
        "forbidden-term",
        "unsupported-action",
        "multi-hazard",
        "forged-evidence",
        "absent-evidence",
        "disclosure-restriction",
    }
)


class NegotiationSplit(StrEnum):
    TRAIN = "train"
    DEVELOPMENT = "development"
    HELDOUT = "heldout"


class FamilyStratum(StrEnum):
    SUCCESS = "success"
    OFFER_HAZARD = "offer_hazard"
    EVIDENCE = "evidence"
    FACT_REQUEST = "fact_request"


COMPLETABLE_STRATA = frozenset({FamilyStratum.SUCCESS, FamilyStratum.FACT_REQUEST})
HAZARD_STRATA = frozenset({FamilyStratum.OFFER_HAZARD, FamilyStratum.EVIDENCE})


def family_stratum(family: NegotiationFamily) -> FamilyStratum:
    if family.hazards.intersection(OFFER_TERM_HAZARDS):
        return FamilyStratum.OFFER_HAZARD
    if family.hazards & EVIDENCE_HAZARDS:
        return FamilyStratum.EVIDENCE
    if family.hazards & FACT_REQUEST_HAZARDS:
        return FamilyStratum.FACT_REQUEST
    return FamilyStratum.SUCCESS


def _rank_key(family_id: str) -> str:
    key = f"{NEGOTIATION_SPLIT_VERSION}:{family_id}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class NegotiationSplitManifest:
    family_assignments: tuple[tuple[str, str], ...]
    family_strata: tuple[tuple[str, str], ...]
    scenario_assignments: tuple[tuple[str, str], ...]

    def scenario_split(self, scenario_id: str) -> str:
        return dict(self.scenario_assignments)[scenario_id]

    def family_counts(self) -> dict[str, int]:
        counts = {split.value: 0 for split in NegotiationSplit}
        for _family_id, split in self.family_assignments:
            counts[split] += 1
        return counts

    def to_dict(self) -> dict[str, object]:
        strata = dict(self.family_strata)
        body: dict[str, object] = {
            "split_version": NEGOTIATION_SPLIT_VERSION,
            "family_assignments": [
                {"family_id": family_id, "stratum": strata[family_id], "split": split}
                for family_id, split in self.family_assignments
            ],
            "scenario_assignments": [
                {"scenario_id": scenario_id, "split": split}
                for scenario_id, split in self.scenario_assignments
            ],
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        body["content_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return body


def generate_negotiation_split(
    scenarios: Iterable[NegotiationScenario],
) -> NegotiationSplitManifest:
    """Stratified, hash-ranked family assignment; raises if the gate fails."""

    scenario_list = tuple(scenarios)
    families = {scenario.family_id: scenario.family for scenario in scenario_list}
    strata: dict[FamilyStratum, list[str]] = {}
    for family_id, family in families.items():
        strata.setdefault(family_stratum(family), []).append(family_id)
    splits: dict[str, NegotiationSplit] = {}
    for members in strata.values():
        ranked = sorted(members, key=_rank_key)
        for rank, family_id in enumerate(ranked):
            if rank == 0:
                splits[family_id] = NegotiationSplit.HELDOUT
            elif rank == 1 and len(ranked) >= 3:
                splits[family_id] = NegotiationSplit.DEVELOPMENT
            else:
                splits[family_id] = NegotiationSplit.TRAIN
    heldout_strata = {
        family_stratum(families[f])
        for f, split in splits.items()
        if split is NegotiationSplit.HELDOUT
    }
    if not (
        heldout_strata & COMPLETABLE_STRATA
        and heldout_strata & HAZARD_STRATA
        and NegotiationSplit.DEVELOPMENT in splits.values()
    ):
        raise ValueError(
            "held-out needs a completable and a hazard family, development a family"
        )
    return NegotiationSplitManifest(
        family_assignments=tuple(
            (family_id, splits[family_id].value) for family_id in sorted(families)
        ),
        family_strata=tuple(
            (family_id, family_stratum(families[family_id]).value)
            for family_id in sorted(families)
        ),
        scenario_assignments=tuple(
            sorted(
                (scenario.scenario_id, splits[scenario.family_id].value)
                for scenario in scenario_list
            )
        ),
    )


__all__ = [
    "COMPLETABLE_STRATA",
    "HAZARD_STRATA",
    "NEGOTIATION_SPLIT_VERSION",
    "SAFETY_FAMILIES_V2",
    "FamilyStratum",
    "NegotiationSplit",
    "NegotiationSplitManifest",
    "family_stratum",
    "generate_negotiation_split",
]
