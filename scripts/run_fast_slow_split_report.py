#!/usr/bin/env python3
"""Measure the per-turn Fast/Slow split of two frozen scripted scenarios.

``--write`` writes ``data/evaluation/fast-slow-split-scripted.json`` (or, with
``--fast-backend distilled|untuned`` and a running local gateway, the local
report ``fast-slow-split-<backend>.json``);
``--check`` re-derives it and fails on drift. The scenarios run in process on
the default scripted adapters, through ``apply_command``, so receipts and
deduplication are real. The report is deterministic: it carries no latency, no
timestamps, and no model text.

Version 2 (PR-14) adds the Judge: its calls and the Slow retries are counted
apart from the Fast/Slow counts and shares, which keep their version 1 values;
no verdict is reported (decision 7). The script never imports the Judge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from proxyloop_agent_core import FAST_GATE_VERSION, ScriptedDialogueFastAdapter
from proxyloop_agent_core.fast_observation import FAST_OBSERVATION_VERSION
from proxyloop_agent_core.local_fast_wire import (
    BACKEND_LABELS,
    LOCAL_FAST_WIRE_VERSION,
    canonical_sha256,
)
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
from proxyloop_local_fast import (
    ADAPTER_MODE_BY_BACKEND,
    DEFAULT_GATEWAY_URL,
    DEFAULT_TIMEOUT_S,
    Backend,
    LocalFastHttpAdapter,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "data" / "evaluation" / "fast-slow-split-scripted.json"
SCHEMA_VERSION = "fast-slow-split-v2"
FAST_BACKEND = "scripted_dialogue"
# The model name every Judge trace must carry (the scripted Judge's).
SCRIPTED_JUDGE_MODEL = "scripted_judge"
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


def run_demo_path(runtime: ThinAgentRuntime | None = None) -> ThinAgentRuntime:
    """Create ($92 -> $75, compliant offer), confirm, approve: two turns.

    A repeated create (a double submit under a new command id) follows the
    first: it traces a succeeded Slow call, then conflicts, so the report
    counts it as an unapplied attempt.
    """

    runtime = runtime if runtime is not None else _runtime()
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


def run_dialogue_path(runtime: ThinAgentRuntime | None = None) -> ThinAgentRuntime:
    """Create ($92 -> $75), then talk after the fictional offer has expired.

    Intake refuses a target below the fixed $72 offer, so an expired offer is
    the only non-compliant offer the Runtime can reach: consumer turns then
    create no approval. The offer lives 60 minutes and a strategy 30, so the
    first turn (+61 min) refreshes the strategy; four turns follow a minute
    apart, one comes 31 minutes after the refresh (a second refresh), and one
    more follows.
    """

    runtime = runtime if runtime is not None else _runtime()
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
    if any(
        trace.role == "judge" and trace.model != SCRIPTED_JUDGE_MODEL
        for trace in traces
    ):
        raise RuntimeError("a Judge trace is not from the scripted Judge")
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
        "judge_backend": SCRIPTED_JUDGE_MODEL,
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


# --- local backends (PR-9b): the real runtime against a running gateway ------

LOCAL_BACKENDS = ("distilled", "untuned")
# A local report written now carries the Judge's calls (PR-14), so it is v2.
LOCAL_SCHEMA_VERSION = "fast-slow-split-local-v2"
# The committed local reports were observed before the Judge existed and only
# the local model can regenerate them: v1, still accepted by the check. Their
# Fast/Slow structure equals the v2 scripted replay's (the Judge adds no Slow
# or Fast call on the default Slow), which the check compares.
PRE_JUDGE_LOCAL_SCHEMA_VERSION = "fast-slow-split-local-v1"
LOCAL_CLAIM_BOUNDARY = (
    "local opt-in candidate (distilled) or untuned local baseline, served by the "
    "loopback MLX gateway on one Apple-silicon machine; sequential calls; the "
    "two scripted scenarios through ThinAgentRuntime with the scripted Slow. "
    "Turn structure equals the scripted replay by construction (Fast cannot "
    "change routing); the Fast outcome and the measured block are what the "
    "backend changes. Not p95, capacity, concurrency or production latency; "
    "E1-E5 and the four Phase 03C caveats apply (decision 18)."
)
# Keys that would carry model or conversation text; none may appear.
TEXT_KEYS = frozenset(
    {"response_text", "content", "raw_output", "text", "prompt", "message", "output"}
)
TURN_STRUCTURE_KEYS = (
    "turn",
    "trigger_event_type",
    "class",
    "slow_calls",
    "fast_calls",
)


M1_PARITY_REPORT = (
    ROOT / "data" / "experiments" / "phase-03c" / "local-parity" / "parity-report.json"
)
ATTESTATION = ROOT / "ml" / "serving" / "phase-03c-cloud-run-01-mlx-attestation.json"


def local_report_path(backend: str) -> Path:
    return ROOT / "data" / "evaluation" / f"fast-slow-split-{backend}.json"


def attested_identity(backend: str) -> dict[str, Any] | None:
    """The gateway identity a committed local report must carry.

    It is the identity the M1 parity report recorded for this backend (whose
    own check binds it to the attested adapter and the decoding profile), and
    the distilled adapter fingerprint must equal the committed attestation's
    ``content_fingerprint`` (the untuned backend has none).  ``None`` when the
    two committed sources disagree.
    """

    identity = json.loads(M1_PARITY_REPORT.read_text(encoding="utf-8"))["arms"][
        backend
    ]["identity"]
    attestation = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    adapter = (
        attestation["output"]["content_fingerprint"] if backend == "distilled" else None
    )
    if identity.get("adapter_fingerprint") != adapter:
        return None
    return dict(identity)


class _TimedFast:
    """Delegates to the real local adapter and times each call (wall clock).

    The report's stepping clock drives the Case, so trace latencies are not
    wall time; this wrapper is the measured source.  It forwards every
    protocol the coordinator and the runtime dispatch on.
    """

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter
        self.calls: list[dict[str, Any]] = []

    @property
    def model_identity(self) -> Any:
        return self._adapter.model_identity

    @property
    def fast_backend_label(self) -> str:
        return str(self._adapter.fast_backend_label)

    def decide(self, view: Any) -> Any:
        return self._adapter.decide(view)

    def decide_observed(self, view: Any, observation: Any) -> Any:
        started = time.monotonic()
        outcome = "succeeded"
        try:
            return self._adapter.decide_observed(view, observation)
        except Exception as error:
            outcome = str(getattr(error, "reason_code", type(error).__name__))
            raise
        finally:
            self.calls.append(
                {
                    "turn": view.pins.event_cursor,
                    "fast_call_ms": round((time.monotonic() - started) * 1000),
                    "outcome": outcome,
                }
            )


def _nearest_rank(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(len(ordered) * percentile / 100)) - 1]


def _local_scenario(
    run: Any, adapter: Any, backend: str
) -> tuple[dict[str, object], dict[str, object]]:
    timed = _TimedFast(adapter)
    runtime = ThinAgentRuntime(
        InMemoryCaseRepository(), clock=_SteppingClock(), fast=timed
    )
    commands: list[int] = []
    original = runtime.apply_command

    def apply_timed(command: CaseCommand) -> Any:
        started = time.monotonic()
        try:
            return original(command)
        finally:
            commands.append(round((time.monotonic() - started) * 1000))

    runtime.apply_command = apply_timed  # type: ignore[method-assign]
    run(runtime)
    state = runtime.repository.get(SCRIPTED_CASE_ID)
    assert state is not None
    traces = runtime.repository.list_model_traces(SCRIPTED_CASE_ID)
    expected_model = adapter.model_identity.model
    for trace in traces:
        if trace.role == "fast" and (
            trace.model != expected_model
            or not trace.model_version.startswith(f"{backend}:")
        ):
            raise RuntimeError("a Fast trace is not from the local backend")
        if trace.role == "judge" and trace.model != SCRIPTED_JUDGE_MODEL:
            raise RuntimeError("a Judge trace is not from the scripted Judge")
    split = fast_slow_split(traces, state)
    fast_ms = [int(call["fast_call_ms"]) for call in timed.calls]
    tokens = [
        {
            "turn": trace.input_pins.event_cursor if trace.input_pins else None,
            "input_tokens": trace.input_tokens,
            "output_tokens": trace.output_tokens,
        }
        for trace in traces
        if trace.role == "fast"
    ]
    measured: dict[str, object] = {
        "fast_calls": timed.calls,
        "fast_call_ms": {
            "p50": _nearest_rank(fast_ms, 50),
            "max": max(fast_ms, default=None),
        },
        "command_ms": {
            "p50": _nearest_rank(commands, 50),
            "max": max(commands, default=None),
        },
        "fast_tokens": tokens,
    }
    return split, measured


def _host_facts() -> dict[str, object]:
    def sysctl(name: str) -> str | None:
        try:
            result = subprocess.run(
                ["sysctl", "-n", name], capture_output=True, text=True, check=True
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return result.stdout.strip() or None

    memory = sysctl("hw.memsize")
    return {
        "chip": sysctl("machdep.cpu.brand_string"),
        "memory_bytes": int(memory) if memory else None,
        "os": f"macOS {platform.mac_ver()[0]}" if platform.mac_ver()[0] else None,
        "machine": platform.machine(),
    }


def build_local_report(
    backend: Backend, gateway_url: str, timeout_s: float
) -> dict[str, object]:
    adapter = LocalFastHttpAdapter.connect(
        base_url=gateway_url,
        backend=backend,
        timeout_s=timeout_s,
    )
    identity = json.loads(_identity_body(adapter))
    demo, demo_measured = _local_scenario(run_demo_path, adapter, backend)
    dialogue, dialogue_measured = _local_scenario(run_dialogue_path, adapter, backend)
    body: dict[str, object] = {
        "schema_version": LOCAL_SCHEMA_VERSION,
        "fast_backend": backend,
        "label": BACKEND_LABELS[backend],
        "adapter_mode": ADAPTER_MODE_BY_BACKEND[backend],
        "gateway_identity": identity,
        "fast_timeout_s": timeout_s,
        "fast_gate_version": FAST_GATE_VERSION,
        "fast_observation_version": FAST_OBSERVATION_VERSION,
        "unicode_data_version": unicodedata.unidata_version,
        "host": _host_facts(),
        "claim_boundary": LOCAL_CLAIM_BOUNDARY,
        "scenarios": {"demo_path": demo, "dialogue_path": dialogue},
        "measured": {"demo_path": demo_measured, "dialogue_path": dialogue_measured},
    }
    return {**body, "report_fingerprint": _fingerprint(body)}


def _identity_body(adapter: LocalFastHttpAdapter) -> str:
    identity = adapter.gateway_identity
    payload = {
        "wire_version": LOCAL_FAST_WIRE_VERSION,
        "backend": identity.backend,
        "label": identity.label,
        "base_model": identity.base_model,
        "base_revision": identity.base_revision,
        "adapter_fingerprint": identity.adapter_fingerprint,
        "prompt_version": identity.prompt_version,
        "compiler_version": identity.compiler_version,
        "observation_renderer_version": identity.observation_renderer_version,
        "trained_view_version": identity.trained_view_version,
        "decoding_fingerprint": identity.decoding_fingerprint,
        "mlx_versions": dict(identity.mlx_versions),
        "identity_fingerprint": identity.identity_fingerprint,
    }
    return json.dumps(payload, sort_keys=True)


def _text_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        found = {key for key in value if key in TEXT_KEYS}
        for item in value.values():
            found |= _text_keys(item)
        return found
    if isinstance(value, list):
        return set().union(*(_text_keys(item) for item in value)) if value else set()
    return set()


def _turn_aggregates(turns: list[dict[str, Any]]) -> dict[str, object]:
    """The aggregates that follow from the per-turn records alone."""

    count = len(turns)
    by_class = {
        name: sum(turn["class"] == name for turn in turns)
        for name in ("slow_only", "fast_only", "slow_then_fast", "no_model")
    }
    dialogue = [turn for turn in turns if turn["fast_calls"]]

    def share(part: int, whole: int) -> float:
        return round(part / whole, 6) if whole else 0.0

    return {
        "turns": count,
        "turns_by_class": by_class,
        "fast_only_turn_share": share(by_class["fast_only"], count),
        "slow_involved_turn_share": share(
            sum(bool(turn["slow_calls"]) for turn in turns), count
        ),
        "dialogue_turns": len(dialogue),
        "fast_model_line_rate": share(
            sum(turn["delivered"] == "model" for turn in dialogue), len(dialogue)
        ),
        "gate_fallback_rate": share(
            sum(turn["fallback_cause"] == "gate" for turn in dialogue), len(dialogue)
        ),
        "fallback_cause_counts": {
            cause: sum(turn["fallback_cause"] == cause for turn in turns)
            for cause in ("gate", "failure")
        },
    }


def _measured_consistent(split: dict[str, Any], measured: dict[str, Any]) -> bool:
    """The timed calls agree with the per-turn Fast outcomes.

    Every applied turn has at most one Fast call; unapplied calls are counted
    in the aggregates.  A call the gateway answered (``succeeded``) is a turn
    whose trace succeeded or was rejected; any other outcome is a failed turn.
    """

    calls = measured.get("fast_calls")
    if not isinstance(calls, list):
        return False
    applied = [turn for turn in split["turns"] if turn["fast_calls"]]
    unapplied = sum(
        split["aggregates"]["unapplied_calls_by_role_and_result"]["fast"].values()
    )
    fast_ms = [int(call["fast_call_ms"]) for call in calls]
    if (
        len(calls) != len(applied) + unapplied
        or len(measured.get("fast_tokens", [])) != len(calls)
        or measured.get("fast_call_ms")
        != {"p50": _nearest_rank(fast_ms, 50), "max": max(fast_ms, default=None)}
    ):
        return False
    for turn in applied:
        at_turn = [call for call in calls if call["turn"] == turn["turn"]]
        if not at_turn:
            return False
        answered = at_turn[-1]["outcome"] == "succeeded"
        codes = turn["fast_reject_codes"]
        gate = bool(codes) and all(code.startswith("fast_gate_") for code in codes)
        expected: tuple[bool, str | None, str]
        if turn["fast_result"] == "failed":
            expected = (False, "failure", "fallback")
        elif turn["fast_result"] == "rejected":
            expected = (True, "gate" if gate else None, "fallback" if gate else "none")
        elif turn["fast_result"] == "succeeded":
            expected = (True, None, "model")
        else:
            return False
        if (answered, turn["fallback_cause"], turn["delivered"]) != expected:
            return False
    return True


def check_local_report(
    backend: str,
    scripted: dict[str, Any],
    path: Path | None = None,
    reference_identity: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    """Integrity only: the model outputs are not replayable without the model.

    ``reference_identity`` defaults to :func:`attested_identity`; tests of
    reports from the in-test fake gateway pass the fake's identity.
    """

    path = path if path is not None else local_report_path(backend)
    if not path.exists():
        return (f"{path.name}_missing",)
    text = path.read_text(encoding="utf-8")
    report = json.loads(text)
    failures: list[str] = []
    body = {key: value for key, value in report.items() if key != "report_fingerprint"}
    if text != _canonical_json(report) or report.get("report_fingerprint") != (
        _fingerprint(body)
    ):
        failures.append("fingerprint_or_encoding")
    if (
        report.get("schema_version")
        not in {LOCAL_SCHEMA_VERSION, PRE_JUDGE_LOCAL_SCHEMA_VERSION}
        or report.get("fast_backend") != backend
        or report.get("label") != BACKEND_LABELS[backend]
        or report.get("adapter_mode") != ADAPTER_MODE_BY_BACKEND[backend]
        or report.get("fast_gate_version") != FAST_GATE_VERSION
        or report.get("fast_observation_version") != FAST_OBSERVATION_VERSION
    ):
        failures.append("schema_or_labels")
    identity = dict(report.get("gateway_identity", {}))
    fingerprint = identity.pop("identity_fingerprint", None)
    if identity.get("backend") != backend or canonical_sha256(identity) != fingerprint:
        failures.append("gateway_identity")
    attested = (
        reference_identity
        if reference_identity is not None
        else attested_identity(backend)
    )
    if attested is None or report.get("gateway_identity") != attested:
        failures.append("gateway_identity_not_attested")
    if _text_keys(report):
        failures.append("text_keys_present")
    for name, split in report.get("scenarios", {}).items():
        turns = split["turns"]
        expected = _turn_aggregates(turns)
        if any(
            split["aggregates"].get(key) != value for key, value in expected.items()
        ):
            failures.append(f"{name}_aggregates")
        reference = scripted["scenarios"][name]["turns"]
        structure = [[turn[key] for key in TURN_STRUCTURE_KEYS] for turn in turns]
        if structure != [
            [turn[key] for key in TURN_STRUCTURE_KEYS] for turn in reference
        ]:
            failures.append(f"{name}_structure_differs_from_scripted")
        measured = report.get("measured", {}).get(name)
        if not isinstance(measured, dict) or not _measured_consistent(split, measured):
            failures.append(f"{name}_measured_inconsistent")
    if set(report.get("scenarios", {})) != set(scripted["scenarios"]) or set(
        report.get("measured", {})
    ) != set(scripted["scenarios"]):
        failures.append("scenario_set")
    return tuple(failures)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument(
        "--fast-backend", choices=("scripted", *LOCAL_BACKENDS), default="scripted"
    )
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL)
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args(argv)
    if args.write:
        if args.fast_backend == "scripted":
            write_report()
            print(f"wrote {REPORT_PATH.relative_to(ROOT)}")
            return 0
        local: Backend = "distilled" if args.fast_backend == "distilled" else "untuned"
        report = build_local_report(local, args.gateway_url, args.timeout_s)
        path = local_report_path(args.fast_backend)
        path.write_text(_canonical_json(report), encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
        return 0
    failures = list(check_report())
    scripted = build_report()
    for backend in LOCAL_BACKENDS:
        failures.extend(
            f"{backend}:{failure}" for failure in check_local_report(backend, scripted)
        )
    if failures:
        print("fast/slow split check failed: " + ", ".join(failures))
        return 1
    print("Fast/Slow split reports are current (scripted replayed; local integrity).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
