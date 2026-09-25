"""M1 stack parity (E2): the pre-registered bar and its per-row statistics.

Frozen before any local model run (``harness/context/pr9-local-distilled-
fast-design.md`` §3.1, root answer Q2): stack parity *holds* iff the local
distilled arm's act agreement with the oracle is >= 0.95 **and** its per-row
act concordance with the committed cloud A3 outputs is >= 0.95 (point
rates).  Failing the bar relabels the backend "stack parity not
established"; it does not remove it.  The untuned arm is reported with no
bar.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Final

from proxyloop_evaluation.fast_parse import (
    DuplicateJSONKeyError,
    extract_fast_json,
    parse_fast_json,
)

PARITY_SCHEMA_VERSION: Final = "phase-03c-local-parity-v1"
BAR_MIN_ACT_AGREEMENT: Final = 0.95
BAR_MIN_CLOUD_CONCORDANCE: Final = 0.95
PARITY_HELD: Final = "stack parity held"
PARITY_NOT_ESTABLISHED: Final = "stack parity not established"
# local backend -> the cloud held-out arm it is compared with
CLOUD_ARMS: Final[dict[str, str]] = {"distilled": "A3", "untuned": "A1"}


def parsed_act(raw: str | None) -> str | None:
    """The ``dialogue_act`` a raw output names, or ``None`` if unparseable.

    Tolerant extraction (a fenced object still names an act), no repair.
    Two unparseable outputs count as concordant: both name no act.
    """

    if raw is None:
        return None
    text, _ = extract_fast_json(raw)
    try:
        parsed = parse_fast_json(text)
    except (DuplicateJSONKeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    act = parsed.get("dialogue_act")
    return act if isinstance(act, str) else None


def nearest_rank(values: Sequence[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100 * len(ordered)))
    return ordered[rank - 1]


def verdict(act_agreement: float, cloud_concordance: float) -> str:
    held = (
        act_agreement >= BAR_MIN_ACT_AGREEMENT
        and cloud_concordance >= BAR_MIN_CLOUD_CONCORDANCE
    )
    return PARITY_HELD if held else PARITY_NOT_ESTABLISHED


__all__ = [
    "BAR_MIN_ACT_AGREEMENT",
    "BAR_MIN_CLOUD_CONCORDANCE",
    "CLOUD_ARMS",
    "PARITY_HELD",
    "PARITY_NOT_ESTABLISHED",
    "PARITY_SCHEMA_VERSION",
    "nearest_rank",
    "parsed_act",
    "verdict",
]
