"""Which bundles exist and which may be served (ARCHITECTURE §14).

A bundle is a directory directly under a configured root that holds
``events.jsonl``; live runs sit one level deeper, under a ``runs`` root only:
``runs/live/<case_id>/<run_id>``. Held-out data has two barriers (AGENTS rule
11): ``sealed`` refuses any path through ``evidence/s4/test`` without opening
it, and a run whose split is ``test``, or not yet known, is never served. URLs
in served bytes are redacted (AGENTS rule 15).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from proxyloop.contract.bundle import EVENTS, MANIFEST
from proxyloop.contract.events import Event

URL = re.compile(rb"""https?://[^\s"'\\<>]+""", re.IGNORECASE)
REDACTED = b"<redacted-url>"
RUN_ID = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
SEALED = ("evidence", "s4", "test")  # held-out bundles, sealed until the report
LIVE = ("runs", "live")  # <runs root>/live/<case_id>/<run_id>


def redact(data: bytes) -> bytes:
    """Replace URLs; quotes and backslashes end a match, so JSON stays JSON."""
    return URL.sub(REDACTED, data)


def sealed(path: Path) -> bool:
    """True if the resolved path runs through ``evidence/s4/test`` (compared
    case-insensitively). It only resolves the path: it never opens a file."""
    parts, n = [part.lower() for part in path.resolve().parts], len(SEALED)
    return any(tuple(parts[i : i + n]) == SEALED for i in range(len(parts) - n + 1))


def held_out(event: Event) -> bool:
    return event.type == "session.started" and event.payload.get("split") == "test"


@dataclass(frozen=True, slots=True)
class Run:
    run_id: str
    root: Path
    path: Path

    def file(self, name: str) -> Path | None:
        """The bundle file, if it exists, resolves inside the run's root and is
        not sealed."""
        path = self.path / name
        if sealed(self.path) or sealed(path):
            return None
        inside = path.resolve().is_relative_to(self.root.resolve())
        return path if inside and path.is_file() else None

    def manifest(self) -> dict[str, object] | None:
        """``manifest.json``, or None while it is absent or does not parse (the
        kernel writes it at close, not atomically)."""
        if (path := self.file(MANIFEST)) is None:
            return None
        try:
            data: object = json.loads(path.read_bytes())
        except ValueError:  # bad JSON or bad UTF-8
            return None
        return cast(dict[str, object], data) if isinstance(data, dict) else None

    def started_split(self) -> str | None:
        """session.started's split, from the first line of ``events.jsonl``
        only; None while there is none or it does not parse."""
        if (path := self.file(EVENTS)) is None:
            return None
        with path.open("rb") as f:
            first = next((line for line in f if line.strip()), b"")
        try:
            event = Event.model_validate_json(first)
        except ValidationError:  # none yet, partial, or not an event
            return None
        split = event.payload.get("split")
        started = event.type == "session.started" and isinstance(split, str)
        return cast(str, split) if started else None

    def servable(self) -> bool:
        """Not sealed, its split is known (from the manifest or session.started),
        and neither says ``test``: fail closed. Reads nothing beyond those two."""
        if sealed(self.path):
            return False
        manifest = self.manifest()
        declared = manifest.get("split") if manifest else None
        known = {declared if isinstance(declared, str) else None, self.started_split()}
        return known != {None} and "test" not in known


def _dirs(parent: Path) -> list[Path]:
    """Subdirectories with a run-id-shaped name, none sealed: nothing inside a
    sealed one is touched."""
    return [
        child
        for child in parent.iterdir()
        if re.fullmatch(RUN_ID, child.name) and not sealed(child) and child.is_dir()
    ]


def _candidates(root: Path) -> list[Path]:
    """Depth one, plus depth two under ``runs/live`` (live cases)."""
    found = _dirs(root)
    live = root / LIVE[1]
    if root.name == LIVE[0] and live in found:
        found += [run for case in _dirs(live) for run in _dirs(case)]
    return found


def _found(roots: Sequence[Path]) -> dict[str, Run]:
    runs: dict[str, Run] = {}
    for root in roots:
        if sealed(root) or not root.is_dir():
            continue
        for child in _candidates(root):
            run = Run(child.name, root, child)
            if child.name not in runs and run.file(EVENTS) is not None:
                runs[child.name] = run
    return runs


def list_runs(roots: Sequence[Path]) -> dict[str, Run]:
    """The servable bundles by run_id. If one run_id exists under two roots, the
    first configured root decides (a held-out first copy hides the second)."""
    return {run_id: run for run_id, run in _found(roots).items() if run.servable()}


def find_run(roots: Sequence[Path], run_id: str) -> Run | None:
    """One servable bundle, found through the listing, never by joining input."""
    run = _found(roots).get(run_id)
    return run if run is not None and run.servable() else None


def default_roots(base: Path) -> list[Path]:
    """``base/runs`` and each directory ``base/evidence/<stage>``."""
    evidence = base / "evidence"
    stages = [p for p in evidence.iterdir() if p.is_dir()] if evidence.is_dir() else []
    return [base / "runs", *sorted(stages)]
