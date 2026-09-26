"""Fast prompt profiles (ARCHITECTURE §6.3): data only; ``protocol`` renders."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from proxyloop.contract.base import Lane

SectionKind = Literal[
    "brief",
    "private_summary",
    "public_summary",
    "actions",
    "offers",
    "approval",
    "guidance",
    "hold",
    "status",
    "transcript",
    "trigger",
]


@dataclass(frozen=True)
class Profile:
    name: str
    lane: Lane
    system: str
    sections: tuple[tuple[str, SectionKind], ...]  # (header, kind), in order
    labels: tuple[str, str]  # transcript labels: (partner, agent)
    triggers: Mapping[str, str]  # TriggerKind -> template
    moves: Mapping[str, str] = field(default_factory=dict[str, str])  # GuideMove
    closing: str = "Respond now per the output format."
    p2_ids_sha256: str = ""  # sha256 of this profile's committed P2 golden ids
