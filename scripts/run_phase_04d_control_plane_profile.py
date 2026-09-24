"""Run the credential-free Phase 04D local control-plane diagnostic."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import resource
import sys
from dataclasses import dataclass
from time import perf_counter
from typing import Any, NoReturn

import httpx
from proxyloop_api import (
    InMemoryOperationRecorder,
    OperationRecord,
    ThinAgentRuntime,
    create_app,
)
from proxyloop_contracts import SlowWorkRequest
from proxyloop_openai_adapter import ModelFailureKind, OpenAICompatibleAdapterError

SCHEMA_VERSION = "phase-04d-control-plane-profile-v1"
EXPECTED_CATEGORIES = {"none", "model_timeout"}
CREATE_CASE_REQUEST = {
    "current_monthly_total": {"amount_minor": 9200, "currency": "USD"},
    "target_monthly_total": {"amount_minor": 7500, "currency": "USD"},
    "mobile_hotspot_required": True,
    "device_financing_change_forbidden": True,
}
CLAIM_BOUNDARY = (
    "This report is local diagnostic evidence only; it is not a production "
    "capacity, real-model latency, OOM, autoscaling, or promoted-serving claim."
)
PROFILE = {
    "adapter_mode": "scripted_plus_fake_timeout",
    "storage_mode": "memory",
    "credentials_used": False,
    "external_calls": False,
}
# Committed baseline for ``--check``: the report's key tree with leaf types.
# Timings, environment, and resource values vary per run, so only their type
# is fixed; the deterministic values are compared in ``_check_report``.
BASELINE_SHAPE: dict[str, Any] = {
    "schema_version": str,
    "result_role": str,
    "claim_boundary": str,
    "profile": {
        "adapter_mode": str,
        "storage_mode": str,
        "credentials_used": bool,
        "external_calls": bool,
    },
    "environment": {"python": str, "platform": str},
    "requests": {
        "count": int,
        "p50_ms": float,
        "p95_ms": float,
        "error_rate": float,
        "timeout_rate": float,
    },
    "resources": {
        "wall_time_ms": float,
        "cpu_time_ms": float,
        "max_rss": int,
        "max_rss_unit": str,
    },
    "outcomes": {
        "statuses": list,
        "error_categories": list,
        "operation_records": int,
    },
}


class _TimeoutSlowAdapter:
    def reason(self, _request: SlowWorkRequest) -> NoReturn:
        raise OpenAICompatibleAdapterError(ModelFailureKind.TIMEOUT)


@dataclass(frozen=True, slots=True)
class _RequestObservation:
    status: int
    latency_ms: float
    error_category: str


async def _journey(
    runtime: ThinAgentRuntime,
    recorder: InMemoryOperationRecorder,
) -> list[_RequestObservation]:
    observations: list[_RequestObservation] = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, recorder=recorder)),
        base_url="http://phase-04d.local",
    ) as client:
        requests = [
            ("post", "/cases", CREATE_CASE_REQUEST),
        ]
        for method, path, body in requests:
            started = perf_counter()
            response = await getattr(client, method)(path, json=body)
            observations.append(
                _RequestObservation(
                    status=response.status_code,
                    latency_ms=(perf_counter() - started) * 1000,
                    error_category=recorder.records[-1].error_category,
                )
            )
        if observations[-1].status == 201:
            case_id = response.json()["case_id"]
            started = perf_counter()
            event = await client.post(
                f"/cases/{case_id}/events",
                json={"content": "Please review the current offer."},
            )
            observations.append(
                _RequestObservation(
                    status=event.status_code,
                    latency_ms=(perf_counter() - started) * 1000,
                    error_category=recorder.records[-1].error_category,
                )
            )
    return observations


async def _run_profile(iterations: int) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    started_wall = perf_counter()
    started_usage = resource.getrusage(resource.RUSAGE_SELF)
    observations: list[_RequestObservation] = []
    records: list[OperationRecord] = []
    for _ in range(iterations):
        recorder = InMemoryOperationRecorder()
        observations.extend(await _journey(ThinAgentRuntime(), recorder))
        records.extend(recorder.records)
    failure_recorder = InMemoryOperationRecorder()
    failure_runtime = ThinAgentRuntime(
        slow=_TimeoutSlowAdapter(),
    )
    failure_observations = await _journey(failure_runtime, failure_recorder)
    observations.extend(failure_observations)
    records.extend(failure_recorder.records)
    ended_usage = resource.getrusage(resource.RUSAGE_SELF)
    latencies = sorted(item.latency_ms for item in observations)
    statuses = {item.status for item in observations}
    categories = {item.error_category for item in records}
    if not statuses <= {201, 200, 503}:
        raise AssertionError(f"unexpected diagnostic status: {sorted(statuses)}")
    if not categories <= EXPECTED_CATEGORIES:
        raise AssertionError(f"unexpected diagnostic category: {sorted(categories)}")
    request_count = len(observations)
    if len(records) != request_count:
        raise AssertionError(
            "diagnostic operation record count must equal request count"
        )
    errors = sum(item.status >= 400 for item in observations)
    timeout_errors = sum(item.error_category == "model_timeout" for item in records)
    return {
        "schema_version": SCHEMA_VERSION,
        "result_role": "local_diagnostic",
        "claim_boundary": CLAIM_BOUNDARY,
        "profile": dict(PROFILE),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "requests": {
            "count": request_count,
            "p50_ms": _percentile(latencies, 0.50),
            "p95_ms": _percentile(latencies, 0.95),
            "error_rate": errors / request_count,
            "timeout_rate": timeout_errors / request_count,
        },
        "resources": {
            "wall_time_ms": (perf_counter() - started_wall) * 1000,
            "cpu_time_ms": (
                (ended_usage.ru_utime - started_usage.ru_utime)
                + (ended_usage.ru_stime - started_usage.ru_stime)
            )
            * 1000,
            "max_rss": ended_usage.ru_maxrss,
            "max_rss_unit": "bytes" if sys.platform == "darwin" else "kilobytes",
        },
        "outcomes": {
            "statuses": sorted(statuses),
            "error_categories": sorted(categories),
            "operation_records": len(records),
        },
    }


def _shape_failures(value: Any, shape: Any, path: str) -> list[str]:
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            return [f"{path}: expected object, got {type(value).__name__}"]
        failures = [f"{_join(path, key)}: missing" for key in shape if key not in value]
        failures += [
            f"{_join(path, key)}: not in baseline" for key in value if key not in shape
        ]
        for key in shape:
            if key in value:
                failures += _shape_failures(value[key], shape[key], _join(path, key))
        return failures
    # Exact type: ``bool`` is an ``int`` subclass and must not pass for one.
    if type(value) is not shape:
        return [f"{path}: expected {shape.__name__}, got {type(value).__name__}"]
    return []


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _check_report(report: dict[str, Any], *, iterations: int) -> list[str]:
    """Return every difference from the committed baseline; empty means pass.

    ``iterations`` scripted journeys make two requests each and the timeout
    journey one, so counts and rates are exact. Timing is checked for ordering
    only, never against a threshold.
    """

    failures = _shape_failures(report, BASELINE_SHAPE, "")
    if failures:
        return failures
    count = 2 * iterations + 1
    expected: dict[str, tuple[Any, Any]] = {
        "schema_version": (report["schema_version"], SCHEMA_VERSION),
        "result_role": (report["result_role"], "local_diagnostic"),
        "claim_boundary": (report["claim_boundary"], CLAIM_BOUNDARY),
        "profile": (report["profile"], PROFILE),
        "requests.count": (report["requests"]["count"], count),
        "requests.error_rate": (report["requests"]["error_rate"], 1 / count),
        "requests.timeout_rate": (report["requests"]["timeout_rate"], 1 / count),
        "outcomes.statuses": (report["outcomes"]["statuses"], [200, 201, 503]),
        "outcomes.error_categories": (
            report["outcomes"]["error_categories"],
            sorted(EXPECTED_CATEGORIES),
        ),
        "outcomes.operation_records": (report["outcomes"]["operation_records"], count),
    }
    for path, (actual, wanted) in expected.items():
        if actual != wanted:
            failures.append(f"{path}: expected {wanted!r}, got {actual!r}")
    p50 = report["requests"]["p50_ms"]
    p95 = report["requests"]["p95_ms"]
    if p50 < 0:
        failures.append(f"requests.p50_ms: {p50} is negative")
    if p95 < p50:
        failures.append(f"requests.p95_ms: {p95} is below p50_ms {p50}")
    return failures


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 3)
    index = (len(values) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    return round(values[lower] + (values[upper] - values[lower]) * weight, 3)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(_run_profile(args.iterations))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if args.check:
        failures = _check_report(report, iterations=args.iterations)
        if failures:
            print(
                "Phase 04D profile check failed:",
                *failures,
                sep="\n- ",
                file=sys.stderr,
            )
            raise SystemExit(1)


if __name__ == "__main__":
    main()
