"""Explicit process configuration for the local Runtime server."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping

from proxyloop_openai_adapter import OpenAICompatibleAdapter

from .postgres_repository import PostgresCaseRepository
from .repository import CaseRepository, InMemoryCaseRepository
from .runtime import ThinAgentRuntime


def runtime_from_environment(
    *,
    mode: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ThinAgentRuntime:
    """Build a Runtime with independent model and storage selections."""

    values = os.environ if environ is None else environ
    storage_mode = values.get("PROXYLOOP_STORAGE_MODE", "memory")
    if storage_mode == "memory":
        repository: CaseRepository = InMemoryCaseRepository()
    elif storage_mode == "postgres":
        database_url = values.get("PROXYLOOP_DATABASE_URL")
        if not database_url or not database_url.strip():
            raise ValueError("postgres storage requires PROXYLOOP_DATABASE_URL")
        repository = PostgresCaseRepository(database_url)
    else:
        raise ValueError("PROXYLOOP_STORAGE_MODE must be memory or postgres")
    selected = mode or values.get("PROXYLOOP_RUNTIME_MODE", "scripted")
    if selected == "scripted":
        return ThinAgentRuntime(repository)
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
    return ThinAgentRuntime(repository, fast=adapter, slow=adapter)


__all__ = ["runtime_from_environment"]
