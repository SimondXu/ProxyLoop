"""Strict local configuration for the Temporal orchestration adapter."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TemporalSettings:
    target_host: str = "127.0.0.1:7233"
    namespace: str = "default"
    task_queue: str = "proxyloop-case-workflow"
    continue_as_new_after: int = 32


def temporal_settings_from_environment(
    environ: Mapping[str, str] | None = None,
) -> TemporalSettings:
    values = os.environ if environ is None else environ
    target_host = values.get("PROXYLOOP_TEMPORAL_ADDRESS", "127.0.0.1:7233")
    namespace = values.get("PROXYLOOP_TEMPORAL_NAMESPACE", "default")
    task_queue = values.get("PROXYLOOP_TEMPORAL_TASK_QUEUE", "proxyloop-case-workflow")
    threshold_text = values.get("PROXYLOOP_TEMPORAL_CONTINUE_AS_NEW_AFTER", "32")
    if not target_host.strip():
        raise ValueError("Temporal mode requires PROXYLOOP_TEMPORAL_ADDRESS")
    if not namespace.strip():
        raise ValueError("Temporal mode requires PROXYLOOP_TEMPORAL_NAMESPACE")
    if not task_queue.strip():
        raise ValueError("Temporal mode requires PROXYLOOP_TEMPORAL_TASK_QUEUE")
    try:
        threshold = int(threshold_text)
    except ValueError as exc:
        raise ValueError(
            "PROXYLOOP_TEMPORAL_CONTINUE_AS_NEW_AFTER must be an integer"
        ) from exc
    if threshold < 1 or threshold > 1000:
        raise ValueError(
            "PROXYLOOP_TEMPORAL_CONTINUE_AS_NEW_AFTER must be between 1 and 1000"
        )
    return TemporalSettings(
        target_host=target_host,
        namespace=namespace,
        task_queue=task_queue,
        continue_as_new_after=threshold,
    )


__all__ = ["TemporalSettings", "temporal_settings_from_environment"]
