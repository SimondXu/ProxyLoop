#!/usr/bin/env python3
"""Measure the per-turn Fast/Slow split of two frozen scripted scenarios.

``--write`` writes ``data/evaluation/fast-slow-split-scripted.json``;
``--check`` re-derives it and fails on drift. The scenarios run in process on
the default scripted adapters, through ``apply_command``, so receipts and
deduplication are real. The report is deterministic: it carries no latency, no
timestamps, and no model text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from proxyloop_agent_core import FAST_GATE_VERSION, ScriptedDialogueFastAdapter
from proxyloop_case_runtime import (
    SCRIPTED_CASE_ID,
    CaseCommand,
    CaseCommandType,
    CaseConflictError,
    InMemoryCaseRepository,
    ThinAgentRuntime,
)
from proxyloop_case_runtime.turn_split import fast_slow_split
from proxyloop_contracts import Money

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "data" / "evaluation" / "fast-slow-split-scripted.json"
SCHEMA_VERSION = "fast-slow-split-v1"
FAST_BACKEND = "scripted_dialogue"
CLAIM_BOUNDARY = (
    "scripted adapters; shares describe routing structure, not model quality or latency"
)
T0 = datetime(2035, 1, 1, tzinfo=UTC)
CONFIRMATION = (
    "Keep mobile hotspot and device financing unchanged. "
    "Continue with the fictional offer."
)


class _SteppingClock:
    """A fixed UTC clock that advances one second per read."""

    def __init__(self) -> None:
        self._now = T0

    def __call__(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


def _command_id(label: str) -> UUID:
    raw = bytearray(hashlib.sha256(f"fast-slow-split:{label}".encode()).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def _usd(amount_minor: int) -> Money:
    return Money(amount_minor=amount_minor, currency="USD")


def _create(label: str, target_minor: int, at: datetime = T0) -> CaseCommand:
    return CaseCommand(
        command_id=_command_id(label),
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.CREATE_CASE,
        occurred_at=at,
        current_monthly_total=_usd(9200),
        target_monthly_total=_usd(target_minor),
        mobile_hotspot_required=True,
        device_financing_change_forbidden=True,
    )


def _message(
    label: str, content: str, at: datetime, expected_revision: int
) -> CaseCommand:
    return CaseCommand(
        command_id=_command_id(label),
        case_id=SCRIPTED_CASE_ID,
        command_type=CaseCommandType.APPEND_EVENT,
        occurred_at=at,
        expected_revision=expected_revision,
        content=content,
        event_type="consumer_message",
    )


def run_demo_path() -> ThinAgentRuntime:
    """Create ($92 -> $75, compliant offer), confirm, approve: two turns.

    A repeated create (a double submit under a new command id) follows the
    first: it traces a succeeded Slow call, then conflicts, so the report
    counts it as an unapplied attempt.
    """

    runtime = _runtime()
    created = runtime.apply_command(_create("demo:create", 7500))
    try:
        runtime.apply_command(
            _create("demo:create-again", 7500, T0 + timedelta(seconds=30))
        )
    except CaseConflictError:
        pass
    else:
        raise RuntimeError("a repeated create_case must conflict")
    waiting = runtime.apply_command(
        _message(
            "demo:confirm",
            CONFIRMATION,
            T0 + timedelta(minutes=1),
            created.after_revision,
        )
    )
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None and waiting.approval_id is not None
    approval = state.snapshot.approval_requests[0]
    runtime.apply_command(
        CaseCommand(
            command_id=_command_id("demo:approve"),
            case_id=SCRIPTED_CASE_ID,
            command_type=CaseCommandType.DECIDE_APPROVAL,
            occurred_at=T0 + timedelta(minutes=2),
            expected_revision=waiting.after_revision,
            approval_id=approval.approval_id,
            decision="approved",
            expected_case_revision=approval.case_revision,
            expected_action_intent_revision=approval.action_intent_revision,
        )
    )
    return runtime


def run_dialogue_path() -> ThinAgentRuntime:
    """Create ($92 -> $75), then talk after the fictional offer has expired.

    Intake refuses a target below the fixed $72 offer, so an expired offer is
    the only non-compliant offer the Runtime can reach: consumer turns then
    create no approval. The offer lives 60 minutes and a strategy 30, so the
    first turn (+61 min) refreshes the strategy; four turns follow a minute
    apart, one comes 31 minutes after the refresh (a second refresh), and one
    more follows.
    """

    runtime = _runtime()
    revision = runtime.apply_command(_create("dialogue:create", 7500)).after_revision
    minutes = (61, 62, 63, 64, 65, 92, 93)
    for turn, minute in enumerate(minutes, start=1):
        revision = runtime.apply_command(
            _message(
                f"dialogue:{turn}",
                f"Consumer dialogue turn {turn}.",
                T0 + timedelta(minutes=minute),
                revision,
            )
        ).after_revision
    return runtime


def _runtime() -> ThinAgentRuntime:
    return ThinAgentRuntime(InMemoryCaseRepository(), clock=_SteppingClock())


def _split(runtime: ThinAgentRuntime) -> dict[str, object]:
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    traces = runtime.repository.list_model_traces(SCRIPTED_CASE_ID)
    fast_model = ScriptedDialogueFastAdapter.model_identity.model
    if any(trace.role == "fast" and trace.model != fast_model for trace in traces):
        raise RuntimeError("a Fast trace is not from the scripted dialogue adapter")
    return fast_slow_split(traces, state)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_report() -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "fast_backend": FAST_BACKEND,
        "fast_gate_version": FAST_GATE_VERSION,
        # The gate's rules read this Python's Unicode character database.
        "unicode_data_version": unicodedata.unidata_version,
        "claim_boundary": CLAIM_BOUNDARY,
        "scenarios": {
            "demo_path": _split(run_demo_path()),
            "dialogue_path": _split(run_dialogue_path()),
        },
    }
    return {**body, "report_fingerprint": _fingerprint(body)}


def write_report(path: Path = REPORT_PATH) -> None:
    path.write_text(_canonical_json(build_report()), encoding="utf-8")


def check_report(path: Path = REPORT_PATH) -> tuple[str, ...]:
    """The failures of the committed report; empty when it is current."""

    expected = _canonical_json(build_report())
    if not path.exists() or path.read_text(encoding="utf-8") != expected:
        return ("fast_slow_split_report_drift",)
    return ()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        write_report()
        print(f"wrote {REPORT_PATH.relative_to(ROOT)}")
        return 0
    failures = check_report()
    if failures:
        print("fast/slow split check failed: " + ", ".join(failures))
        return 1
    print("Fast/Slow split report is current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
