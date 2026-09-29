"""The label store (EVAL §9 item 4): append-only JSONL, two raters.

Rows ``{item_id, rater, label, ts}``. The one writer opens the file in append
mode and writes one line; nothing rewrites, truncates or deletes a row. A
relabel is a new row, and the latest row per (item, rater) counts. The queue of
disagreements lists the items on which both raters' latest labels differ; the
user's final label settles them (the adjudication is outside this module).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

RATERS = ("user", "root")
# the Ear's closed acts, plus the two audited splits it cannot express
LABELS = (
    *("accept", "decline", "provide_fact", "provide_fact_protected", "refuse_fact"),
    *("ask_readback", "ask_discount", "cite_competitor", "cancel_intent", "tenure"),
    *("ask_supervisor", "hold_request", "smalltalk", "injection"),
    *("completion_claim", "other"),
)


@dataclass(frozen=True, slots=True)
class Row:
    item_id: str
    rater: str
    label: str
    ts: str


def _now() -> datetime:
    return datetime.now(UTC)


class LabelStore:
    def __init__(self, path: Path, now: Callable[[], datetime] = _now) -> None:
        self._path, self._now = path, now

    def append(self, item_id: str, rater: str, label: str) -> Row:
        if rater not in RATERS:
            raise ValueError(f"rater {rater!r} is not one of {RATERS}")
        if label not in LABELS:
            raise ValueError(f"label {label!r} is not one of {LABELS}")
        if not item_id:
            raise ValueError("an item id is required")
        ts = self._now().astimezone(UTC).isoformat(timespec="milliseconds")
        row = Row(item_id, rater, label, ts)
        line = json.dumps(asdict(row), sort_keys=True) + "\n"
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        return row

    def rows(self) -> list[Row]:
        if not self._path.exists():
            return []
        out: list[Row] = []
        for n, line in enumerate(self._path.read_text("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                out.append(Row(**json.loads(line)))
            except (ValueError, TypeError) as err:
                raise ValueError(f"{self._path}:{n}: not a label row") from err
        return out

    def latest(self) -> dict[str, dict[str, Row]]:
        """item -> rater -> that rater's newest row (file order)."""

        out: dict[str, dict[str, Row]] = {}
        for r in self.rows():
            out.setdefault(r.item_id, {})[r.rater] = r
        return out

    def disagreements(self) -> list[str]:
        """Items both raters labelled whose latest labels differ, sorted."""

        return sorted(
            item
            for item, by in self.latest().items()
            if len(by) == len(RATERS) and len({r.label for r in by.values()}) > 1
        )
