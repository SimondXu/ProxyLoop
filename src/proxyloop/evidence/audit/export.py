"""The blinded item export (EVAL §9 item 4): what the labeller sees.

Per item: an opaque id, the utterance, the previous rep line and the public
offers, and nothing else. No Ear label, model, condition, lane, run or bundle
id. The order is a seeded shuffle of the sampled items. The item id hashes the
frame's seed, run and utterance; it reveals none of them.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from pathlib import Path
from typing import Any

BLIND_FIELDS = ("item_id", "utterance", "previous_rep", "offers")


def blind(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "item_id": item["item_id"],
        "utterance": item["text"],
        "previous_rep": item["previous_rep"],
        "offers": item["offers"],
    }


def export(doc: Mapping[str, Any], seed: int) -> list[dict[str, Any]]:
    """The blinded rows of a frame's sampled items, in a seeded random order."""

    rows = [blind(i) for i in doc["items"] if i["sampled"]]
    rows.sort(key=lambda r: r["item_id"])
    random.Random(f"export\0{seed}").shuffle(rows)
    return rows


def write(rows: list[dict[str, Any]], path: Path) -> None:
    lines = (json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)
    path.write_text("".join(f"{line}\n" for line in lines), "utf-8")
