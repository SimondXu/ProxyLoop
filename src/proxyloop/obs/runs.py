"""The run index: one row per bundle under ``runs/`` and ``evidence/``.

Each bundle is parsed on its own (not ``read_bundle``), so a bad bundle is a
row, not a crash. ``evidence/s4/test/`` is sealed (AGENTS rule 11): it is known
by its inode, never listed, and no directory, root or file whose resolved path
passes through it is read. A bundle whose split is ``test`` is sealed too:
none of its events are read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS, Manifest
from proxyloop.contract.events import Event, check_causes
from proxyloop.contract.llm import Endpoint, LLMCallRecord, LLMRole

SEALED = ("evidence", "s4", "test")
Status = Literal["ok", "incomplete", "invalid", "sealed"]
FILES = (MANIFEST, EVENTS, PROMPTS)


class Charge(BaseModel):
    """The ``spend.charged`` payload, read here without importing the ledger
    (obs imports only the contract): a drifted payload makes the bundle invalid."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str
    role: LLMRole
    attempt: int
    endpoint: Endpoint | None
    model_id: str
    basis: Literal["tokens", "gpu_time", "unpriced"]
    micro_usd: int | None = Field(ge=0)


@dataclass(frozen=True)
class Cost:
    """One ``spend.charged`` and the ``llm.call`` it prices (None: missing)."""

    charge: Charge
    record: LLMCallRecord | None


@dataclass(frozen=True)
class Run:
    run_id: str
    path: str
    kind: Literal["runs", "live", "evidence"]
    status: Status
    case_id: str | None = None
    stage: str | None = None
    started: str | None = None
    task_ref: str | None = None
    split: str | None = None
    models: dict[str, dict[str, str | None]] = field(
        default_factory=dict[str, dict[str, str | None]]
    )
    reality: dict[str, str] = field(default_factory=dict[str, str])
    ended: str | None = None
    duration_ms: int | None = None
    events: int | None = None
    events_sha256: str | None = None
    priced_micro_usd: int | None = None
    unpriced_calls: int | None = None
    unmatched_charges: int | None = None  # spend.charged with no llm.call
    uncharged_calls: int | None = None  # llm.call with no spend.charged
    error: str | None = None
    costs: tuple[Cost, ...] = ()
    uncharged: tuple[LLMCallRecord, ...] = ()

    def row(self) -> dict[str, object]:
        skip = ("costs", "uncharged")
        return {
            f.name: getattr(self, f.name) for f in fields(self) if f.name not in skip
        }


class Seal:
    """Knows ``evidence/s4/test`` by (st_dev, st_ino), wherever a path meets it
    and in whatever case the file system accepts."""

    def __init__(self) -> None:
        self._inodes: set[tuple[int, int]] = set()
        self._learned: set[Path] = set()

    def covers(self, path: Path) -> bool:
        real = path.resolve()
        if any(tuple(p.casefold() for p in real.parts[i : i + 3]) == SEALED
               for i in range(len(real.parts))):  # fmt: skip
            return True
        for at in (*reversed(real.parents), real):  # top down: never stat inside
            if at not in self._learned:
                self._learned.add(at)
                self._learn(at / SEALED[0] / SEALED[1] / SEALED[2])
            try:
                st = at.stat()
            except OSError:
                return False  # nothing there to read
            if (st.st_dev, st.st_ino) in self._inodes:
                return True
        return False

    def _learn(self, sealed: Path) -> None:
        try:
            st = sealed.stat()  # the directory itself; it is never listed
        except OSError:
            return
        self._inodes.add((st.st_dev, st.st_ino))


def bundles(root: Path, seal: Seal) -> Iterator[Path]:
    """Every directory holding a bundle file, without descending into one."""
    root = root.resolve()
    if seal.covers(root):
        raise ValueError(f"{root} is sealed held-out data (AGENTS rule 11)")
    seen: set[tuple[int, int]] = set()
    stack = [root]
    while stack:
        here = stack.pop()
        st = here.stat()
        if (st.st_dev, st.st_ino) in seen:  # a symlink loop
            continue
        seen.add((st.st_dev, st.st_ino))
        names = sorted(os.listdir(here))
        if any(name in names for name in FILES):
            yield here
            continue
        subdirs = [here / n for n in names]
        subdirs = [p for p in subdirs if not seal.covers(p) and p.is_dir()]
        stack.extend(reversed(subdirs))


def load(path: Path, root: Path, seal: Seal) -> Run:
    root, rel = root.resolve(), path.relative_to(root.resolve()).parts
    kind, case_id, stage = "runs", None, None
    if root.name.casefold() == "evidence" and len(rel) > 1:
        kind, stage = "evidence", rel[0]
    elif root.parent.name.casefold() == "evidence":
        kind, stage = "evidence", root.name
    elif len(rel) == 3 and rel[0] == "live":
        kind, case_id = "live", rel[1]
    run = Run(path.name, str(path), kind, "ok", case_id, stage)
    if why := sealed(path, seal):
        return replace(run, status="sealed", error=why)
    try:
        return _load(path, run)
    except ValidationError as err:  # the type and location only, never input values
        where = [
            "{}@{}".format(e["type"], ".".join(map(str, e["loc"])))
            for e in err.errors()
        ]
        return replace(run, status="invalid", error="; ".join(where))
    except (OSError, ValueError) as err:
        return replace(run, status="invalid", error=f"{type(err).__name__}: {err}")


def sealed(path: Path, seal: Seal) -> str | None:
    """Why the bundle at ``path`` may be sealed data (None: it is not)."""
    if any(seal.covers(path / name) for name in FILES):
        return "a file resolves into sealed data"
    if any(f.is_file() and f.stat().st_nlink > 1 for f in (path / n for n in FILES)):
        return "hard-linked file"  # maybe sealed
    return None


def head(path: Path) -> dict[str, object] | None:
    """What a bundle says of itself before any event is read: the manifest, or
    else session.started on the first line alone. None: neither is there."""
    if (path / MANIFEST).is_file():
        man = Manifest.model_validate_json((path / MANIFEST).read_text("utf-8"))
        return {
            "run_id": man.run_id,
            "task_ref": man.task_ref,
            "split": man.split,
            "models": {
                r: {"endpoint": m.ref.endpoint, "model_id": m.ref.model_id}
                for r, m in sorted(man.models.items())
            },
            "reality": {r: str(k) for r, k in sorted(man.reality.items())},
        }
    if not (path / EVENTS).is_file():
        return None
    with (path / EVENTS).open(encoding="utf-8") as f:  # the split, read alone
        first = f.readline()
    start = Event.model_validate_json(first) if first.strip() else None
    if start is None or start.type != "session.started":
        return None
    return {k: start.payload[k] for k in ("task_ref", "split")} | {
        "run_id": start.run_id
    }


def _load(path: Path, run: Run) -> Run:
    at = head(path)
    if at is None:
        has = (path / EVENTS).is_file()
        why = f"no {MANIFEST}, no split" if has else f"no {MANIFEST} or {EVENTS}"
        return replace(run, status="incomplete", error=why)
    if at["split"] == "test":
        return replace(run, run_id=at["run_id"], status="sealed")
    if not (path / EVENTS).is_file():
        return replace(run, **at, status="incomplete", error=f"no {EVENTS}")
    raw = (path / EVENTS).read_bytes()
    lines = raw.decode("utf-8").splitlines()
    events = tuple(Event.model_validate_json(x) for x in lines if x.strip())
    check_causes(events)
    if any(e.run_id != at["run_id"] for e in events):
        raise ValueError("an event's run_id is not the bundle's")
    calls = [LLMCallRecord.model_validate(e.payload) for e in events if _is(e, "llm")]
    charges = [Charge.model_validate(e.payload) for e in events if _is(e, "spend")]
    by_key = {(c.call_id, c.attempt): c for c in calls}
    charged = {(c.call_id, c.attempt) for c in charges}
    if len(by_key) != len(calls) or len(charged) != len(charges):
        raise ValueError("a (call_id, attempt) is recorded or charged twice")
    if any((c.basis == "tokens") != (c.micro_usd is not None) for c in charges):
        raise ValueError("micro_usd is set iff the basis is tokens")
    costs = tuple(Cost(c, by_key.get((c.call_id, c.attempt))) for c in charges)
    uncharged = tuple(r for k, r in by_key.items() if k not in charged)
    ended = [e.payload["reason"] for e in events if e.type == "session.ended"]
    started = [e for e in events if e.type == "session.started"] or events[:1]
    return replace(
        run,
        **at,
        status="ok" if (path / MANIFEST).is_file() else "incomplete",
        error=None if (path / MANIFEST).is_file() else f"no {MANIFEST}",
        started=started[0].wall.isoformat() if started else None,
        ended=str(ended[-1]) if ended else None,
        duration_ms=events[-1].t_ms if events else None,
        events=len(events),
        events_sha256=hashlib.sha256(raw).hexdigest(),
        priced_micro_usd=sum(c.micro_usd or 0 for c in charges),  # tokens basis only
        unpriced_calls=sum(c.basis == "unpriced" for c in charges),
        unmatched_charges=sum(c.record is None for c in costs),
        uncharged_calls=len(uncharged),
        costs=costs,
        uncharged=uncharged,
    )


def _is(event: Event, kind: Literal["llm", "spend"]) -> bool:
    return event.type == ("llm.call" if kind == "llm" else "spend.charged")


def index(roots: Sequence[Path]) -> list[Run]:
    """Every bundle under ``roots``. Copies of one run_id (an evidence copy of a
    run) must have identical events; otherwise every copy is invalid."""
    seal = Seal()
    runs = [load(path, root, seal) for root in roots for path in bundles(root, seal)]
    shas: dict[str, set[str | None]] = defaultdict(set)
    for r in runs:
        if r.status == "ok":
            shas[r.run_id].add(r.events_sha256)
    clash = {run_id for run_id, s in shas.items() if len(s) > 1}
    return [
        replace(r, status="invalid", error="run_id collision", costs=(), uncharged=())
        if r.status == "ok" and r.run_id in clash
        else r
        for r in runs
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m proxyloop.obs.runs")
    parser.add_argument("--root", type=Path, action="append")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    roots = args.root or [p for p in (Path("runs"), Path("evidence")) if p.is_dir()]
    runs = index(roots)
    if args.json:
        print(json.dumps([r.row() for r in runs], indent=1, sort_keys=True))
        return 0
    for r in runs:
        where = r.stage or r.case_id or "-"
        print(
            f"{r.status:<10} {r.kind:<8} {r.run_id:<26} {where:<10} {r.task_ref or '-'}"
            f"  split={r.split} ended={r.ended} events={r.events}"
            f" priced={r.priced_micro_usd} unpriced={r.unpriced_calls}"
            + (f"  error={r.error.splitlines()[0]}" if r.error else "")
        )
    counts = {s: sum(r.status == s for r in runs) for s in Status.__args__}
    print(" ".join(f"{s}={n}" for s, n in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
