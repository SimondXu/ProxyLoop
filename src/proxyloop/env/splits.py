"""Salted stratified family split, ported from v0.

Port of the rank in v0 ``provider_simulator/negotiation_splits.py:81-119``.
Within each stratum, families are ranked by ``sha256(f"{salt}:{family_id}")``
(hex digest order). Rank 0 is held out, rank 1 goes to development when the
stratum has at least three families, and the rest train. v0 used the salt
``"negotiation-split-v2"``. The v0 gate that required particular v0 strata in
held-out is not ported; callers own their own gate.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from enum import StrEnum


class Split(StrEnum):
    TRAIN = "train"
    DEVELOPMENT = "development"
    HELDOUT = "heldout"


def stratified_split(strata: Mapping[str, str], *, salt: str) -> dict[str, Split]:
    """Assign each family (``family_id -> stratum``) to a split."""

    members: dict[str, list[str]] = {}
    for family_id, stratum in strata.items():
        members.setdefault(stratum, []).append(family_id)
    splits: dict[str, Split] = {}
    for family_ids in members.values():
        ranked = sorted(family_ids, key=lambda family_id: _rank_key(salt, family_id))
        for rank, family_id in enumerate(ranked):
            if rank == 0:
                splits[family_id] = Split.HELDOUT
            elif rank == 1 and len(ranked) >= 3:
                splits[family_id] = Split.DEVELOPMENT
            else:
                splits[family_id] = Split.TRAIN
    return {family_id: splits[family_id] for family_id in sorted(splits)}


def _rank_key(salt: str, family_id: str) -> str:
    return hashlib.sha256(f"{salt}:{family_id}".encode()).hexdigest()


__all__ = ["Split", "stratified_split"]
