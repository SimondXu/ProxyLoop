"""The sampling frame (EVAL §9 item 4): strata, seeded draws, inclusion
probabilities.

Strata, each split by speaker model (the Fast condition):
``positive/<class>``  the Ear labelled the utterance with the class;
``flagged/<class>``   the Ear did not, and the lexical detector flags it;
``random/all``        every candidate.
Each cell draws a simple random sample without replacement, independently of
the others, seeded by (seed, cell). An item may lie in several cells, so its
inclusion probability is ``1 - prod(1 - pi_cell)`` over the cells it lies in;
that ``pi`` is what a Horvitz-Thompson estimate weighs by. A cell's ``pi`` is
``n / N`` and the ``pi`` of a cell sum to its ``n`` (a cell smaller than its
share is taken whole). The model and condition stay in the frame file only.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from proxyloop.evidence.audit import lexicon
from proxyloop.evidence.audit.items import CLASSES, Candidate

FRAME_SCHEMA = "pl.ear_audit_frame/1"
DEFAULT_SIZES: Mapping[str, int] = {"positive": 60, "flagged": 60, "random": 150}


@dataclass(frozen=True, slots=True)
class Cell:
    stratum: str  # "<kind>/<class>"
    model: str
    N: int
    n: int

    @property
    def key(self) -> str:
        return f"{self.stratum}|{self.model}"

    @property
    def pi(self) -> float:
        return self.n / self.N if self.N else 0.0


@dataclass
class Frame:
    seed: int
    sizes: dict[str, int]
    cells: list[Cell] = field(default_factory=list[Cell])
    items: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def sampled(self) -> list[dict[str, Any]]:
        return [i for i in self.items if i["sampled"]]


def strata_of(c: Candidate) -> list[str]:
    """The strata a candidate lies in (its cells add the speaker model)."""

    out = ["random/all"]
    if c.ear_class is not None:
        out.append(f"positive/{c.ear_class}")
    out += [f"flagged/{f}" for f in c.flags if f != c.ear_class]
    return out


def allocate(sizes: Mapping[str, int], n: int) -> dict[str, int]:
    """Split ``n`` over models as evenly as the sizes allow: a model with fewer
    items than its share is taken whole and the rest is shared by the others."""

    left, todo = n, sorted(sizes, key=lambda m: (sizes[m], m))
    out: dict[str, int] = {}
    for i, model in enumerate(todo):
        share = min(sizes[model], left // (len(todo) - i))
        out[model] = share
        left -= share
    for model in todo:  # the remainder, one each, to models with room
        if left and out[model] < sizes[model]:
            out[model] += 1
            left -= 1
    return out


def build(
    cands: Sequence[Candidate], seed: int, sizes: Mapping[str, int] | None = None
) -> Frame:
    sizes = dict(DEFAULT_SIZES if sizes is None else sizes)
    members: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for c in cands:
        for s in strata_of(c):
            members[s][c.speaker_model].append(c.item_id)
    frame = Frame(seed, sizes)
    cells_of: dict[str, list[Cell]] = defaultdict(list)  # item -> its cells
    drawn: set[str] = set()
    universe = [f"positive/{k}" for k in CLASSES] + [f"flagged/{k}" for k in CLASSES]
    for stratum in [*universe, "random/all"]:
        by_model = members.get(stratum, {})
        n = sizes[stratum.split("/")[0]]
        share = allocate({m: len(ids) for m, ids in by_model.items()}, n)
        for model in sorted(by_model):
            ids = sorted(by_model[model])  # sorted: the draw depends on the seed only
            cell = Cell(stratum, model, len(ids), share[model])
            frame.cells.append(cell)
            drawn |= set(random.Random(f"{seed}\0{cell.key}").sample(ids, cell.n))
            for i in ids:
                cells_of[i].append(cell)
    for c in cands:
        miss = 1.0
        for cell in cells_of[c.item_id]:
            miss *= 1 - cell.pi
        row = c.as_json()
        row["offers"] = list(c.offers)
        row |= {"cells": {x.key: x.pi for x in cells_of[c.item_id]}}
        row |= {"pi": 1 - miss, "sampled": c.item_id in drawn}
        frame.items.append(row)
    return frame


def dump(frame: Frame, path: Path) -> None:
    doc = {
        "schema": FRAME_SCHEMA,
        "seed": frame.seed,
        "sizes": frame.sizes,
        "lexicon": lexicon.LEXICON_VERSION,
        "cells": [{"cell": c.key, "N": c.N, "n": c.n, "pi": c.pi} for c in frame.cells],
        "items": frame.items,
    }
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", "utf-8")


def load(path: Path) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(path.read_text("utf-8"))
    if doc.get("schema") != FRAME_SCHEMA:
        raise ValueError(f"{path} is not a {FRAME_SCHEMA} frame")
    return doc
