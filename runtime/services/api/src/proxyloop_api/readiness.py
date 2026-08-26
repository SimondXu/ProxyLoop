"""Process-local liveness and configured dependency readiness probes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from proxyloop_case_runtime import StorageUnavailableError, ThinAgentRuntime


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    """Stable control-plane readiness state without Case data."""

    ready: bool
    dependency: str
    error_category: str = "none"


def liveness_payload(runtime: ThinAgentRuntime) -> dict[str, object]:
    """Return process-only liveness metadata; no adapter or storage calls."""

    return {
        "status": "ok",
        "live": True,
        "adapter_mode": runtime.adapter_mode,
        "storage_mode": runtime.storage_mode,
    }


def check_readiness(runtime: ThinAgentRuntime) -> ReadinessResult:
    """Probe only the configured local storage dependency.

    Scripted/model selection is metadata and is deliberately never probed.
    """

    if runtime.storage_mode == "memory":
        return ReadinessResult(ready=True, dependency="memory")
    checker = getattr(runtime.repository, "check_readiness", None)
    if not callable(checker):
        return ReadinessResult(
            ready=False,
            dependency="postgres",
            error_category="dependency_not_ready",
        )
    try:
        checker()
    except StorageUnavailableError:
        return ReadinessResult(
            ready=False,
            dependency="postgres",
            error_category="dependency_not_ready",
        )
    except Exception:
        return ReadinessResult(
            ready=False,
            dependency="postgres",
            error_category="dependency_not_ready",
        )
    return ReadinessResult(ready=True, dependency="postgres")


def readiness_payload(
    runtime: ThinAgentRuntime,
    result: ReadinessResult,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "ok" if result.ready else "unavailable",
        "ready": result.ready,
        "dependency": result.dependency,
        "adapter_mode": runtime.adapter_mode,
        "storage_mode": runtime.storage_mode,
    }
    if not result.ready:
        payload["detail"] = {
            "code": "dependency_not_ready",
            "message": "configured dependency is not ready",
        }
    return payload


__all__ = [
    "ReadinessResult",
    "check_readiness",
    "liveness_payload",
    "readiness_payload",
]
