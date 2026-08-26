"""Redacted readiness checks for the configured Temporal dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from temporalio.client import Client


@dataclass(frozen=True, slots=True)
class TemporalReadinessResult:
    ready: bool
    dependency: str = "temporal"
    error_category: str = "none"


async def check_temporal_readiness(client: Client) -> TemporalReadinessResult:
    """Check Temporal health without returning driver or endpoint details."""

    try:
        ready = await client.service_client.check_health(retry=False)
    except Exception:
        return TemporalReadinessResult(
            ready=False,
            error_category="dependency_not_ready",
        )
    return TemporalReadinessResult(
        ready=bool(ready),
        error_category="none" if ready else "dependency_not_ready",
    )


def readiness_payload(result: TemporalReadinessResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "ok" if result.ready else "unavailable",
        "ready": result.ready,
        "dependency": result.dependency,
    }
    if not result.ready:
        payload["detail"] = {
            "code": "dependency_not_ready",
            "message": "configured dependency is not ready",
        }
    return payload


# Keep the short name convenient for callers that already have a readiness
# module and make the dependency explicit in the function's implementation.
check_readiness = check_temporal_readiness


__all__ = [
    "TemporalReadinessResult",
    "check_readiness",
    "check_temporal_readiness",
    "readiness_payload",
]
