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
        "claim_boundary": (
            "This report is local diagnostic evidence only; it is not a production "
            "capacity, real-model latency, OOM, autoscaling, or promoted-serving claim."
        ),
        "profile": {
            "adapter_mode": "scripted_plus_fake_timeout",
            "storage_mode": "memory",
            "credentials_used": False,
            "external_calls": False,
        },
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
    if args.check:
        assert report["requests"]["p50_ms"] >= 0
        assert report["requests"]["p95_ms"] >= report["requests"]["p50_ms"]
        assert report["requests"]["timeout_rate"] > 0
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
