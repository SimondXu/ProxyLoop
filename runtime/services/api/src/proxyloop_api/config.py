"""Explicit process configuration for the local Runtime server."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping

from proxyloop_openai_adapter import OpenAICompatibleAdapter

from .runtime import ThinAgentRuntime


def runtime_from_environment(
    *,
    mode: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ThinAgentRuntime:
    """Build scripted Runtime by default or explicitly opt into model mode."""

    values = os.environ if environ is None else environ
    selected = mode or values.get("PROXYLOOP_RUNTIME_MODE", "scripted")
    if selected == "scripted":
        return ThinAgentRuntime()
    if selected != "model":
        raise ValueError("PROXYLOOP_RUNTIME_MODE must be scripted or model")
    required = {
        "PROXYLOOP_MODEL_API_KEY": values.get("PROXYLOOP_MODEL_API_KEY"),
        "PROXYLOOP_MODEL_BASE_URL": values.get("PROXYLOOP_MODEL_BASE_URL"),
        "PROXYLOOP_MODEL_NAME": values.get("PROXYLOOP_MODEL_NAME"),
    }
    if any(not value for value in required.values()):
        raise ValueError("model mode requires API key, base URL, and model name")
    timeout_text = values.get("PROXYLOOP_MODEL_TIMEOUT", "30")
    try:
        timeout = float(timeout_text)
    except ValueError as exc:
        raise ValueError("PROXYLOOP_MODEL_TIMEOUT must be a positive number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("PROXYLOOP_MODEL_TIMEOUT must be a positive number")
    adapter = OpenAICompatibleAdapter(
        api_key=required["PROXYLOOP_MODEL_API_KEY"] or "",
        base_url=required["PROXYLOOP_MODEL_BASE_URL"] or "",
        model=required["PROXYLOOP_MODEL_NAME"] or "",
        timeout=timeout,
    )
    return ThinAgentRuntime(fast=adapter, slow=adapter)


__all__ = ["runtime_from_environment"]
