"""The run index: one row per bundle under ``runs/`` and ``evidence/``.

Each bundle is parsed on its own (not ``read_bundle``), so a bad bundle is a
row, not a crash. ``evidence/s4/test/`` is never listed (AGENTS rule 11), and a
bundle whose split is ``test`` is sealed: none of its events are read.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Literal

from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS, Manifest
from proxyloop.contract.events import Event, check_causes
from proxyloop.contract.llm import LLMCallRecord
from proxyloop.llm.spend import Charge

SEALED = ("evidence", "s4", "test")
Status = Literal["ok", "incomplete", "invalid", "sealed"]


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


def _sealed(parts: Sequence[str]) -> bool:
    return any(tuple(parts[i : i + 3]) == SEALED for i in range(len(parts)))


def bundles(root: Path) -> Iterator[Path]:
    """Every directory holding a bundle file, without descending into one."""
    root = root.resolve()
    if _sealed(root.parts):
        raise ValueError(f"{root} is sealed held-out data (AGENTS rule 11)")
    names = sorted(os.listdir(root))
    if any(name in names for name in (MANIFEST, EVENTS, PROMPTS)):
        yield root
        return
    for name in names:
        if not _sealed((*root.parts[-2:], name)) and (root / name).is_dir():
            yield from bundles(root / name)


def load(path: Path) -> Run:
    parts = path.parts
    kind, case_id, stage = "runs", None, None
    if "evidence" in parts:
        at = len(parts) - parts[::-1].index("evidence")
        kind, stage = "evidence", parts[at] if at < len(parts) - 1 else None
    elif len(parts) > 2 and parts[-3] == "live":
        kind, case_id = "live", parts[-2]
    run = Run(path.name, str(path), kind, "ok", case_id, stage)
    try:
        return _load(path, run)
    except (OSError, ValueError) as err:  # a pydantic ValidationError is a ValueError
        return replace(run, status="invalid", error=str(err))


def _load(path: Path, run: Run) -> Run:
    at: dict[str, object]
    if (path / MANIFEST).is_file():
        man = Manifest.model_validate_json((path / MANIFEST).read_text("utf-8"))
        at = {
            "run_id": man.run_id,
            "task_ref": man.task_ref,
            "split": man.split,
            "models": {
                r: {"endpoint": m.ref.endpoint, "model_id": m.ref.model_id}
                for r, m in sorted(man.models.items())
            },
            "reality": {r: str(k) for r, k in sorted(man.reality.items())},
        }
    elif (path / EVENTS).is_file():  # the split from session.started, read alone
        with (path / EVENTS).open(encoding="utf-8") as f:
            first = f.readline()
        start = Event.model_validate_json(first) if first.strip() else None
        if start is None or start.type != "session.started":
            return replace(run, status="incomplete", error=f"no {MANIFEST}, no split")
        at = {k: start.payload[k] for k in ("task_ref", "split")}
        at["run_id"] = start.run_id
    else:
        return replace(run, status="incomplete", error=f"no {MANIFEST} or {EVENTS}")
    if at["split"] == "test":
        return replace(run, run_id=at["run_id"], status="sealed")
    if not (path / EVENTS).is_file():
        return replace(run, **at, status="incomplete", error=f"no {EVENTS}")
    text = (path / EVENTS).read_text("utf-8")
    events = tuple(Event.model_validate_json(x) for x in text.splitlines() if x.strip())
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
    return [load(path) for root in roots for path in bundles(root)]


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
