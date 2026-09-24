"""``PROXYLOOP_FAST_BACKEND``: the one parse of the local Fast selection.

The API calls this now; the Temporal worker will call it in PR-11. The caller
decides which runtime and orchestration modes may use a local backend.
Rollback is setting the variable back to ``scripted`` and restarting; nothing
switches backends automatically.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Final

from .adapter import (
    BACKEND_LABELS,
    DEFAULT_GATEWAY_URL,
    DEFAULT_TIMEOUT_S,
    MAX_TIMEOUT_S,
    Backend,
    LocalFastHttpAdapter,
)

FAST_BACKEND_VARIABLE: Final = "PROXYLOOP_FAST_BACKEND"
FAST_GATEWAY_URL_VARIABLE: Final = "PROXYLOOP_FAST_GATEWAY_URL"
FAST_TIMEOUT_VARIABLE: Final = "PROXYLOOP_FAST_TIMEOUT_S"


def selected_fast_backend(values: Mapping[str, str]) -> str:
    """``scripted`` (the default), ``distilled`` or ``untuned``."""

    backend = values.get(FAST_BACKEND_VARIABLE, "scripted")
    if backend != "scripted" and backend not in BACKEND_LABELS:
        raise ValueError(
            f"{FAST_BACKEND_VARIABLE} must be scripted, distilled, or untuned"
        )
    return backend


def fast_adapter_from_environment(
    values: Mapping[str, str],
) -> LocalFastHttpAdapter | None:
    """``None`` for scripted; else a connected adapter, or a refusal to start."""

    backend = selected_fast_backend(values)
    if backend == "scripted":
        return None
    timeout_text = values.get(FAST_TIMEOUT_VARIABLE, str(DEFAULT_TIMEOUT_S))
    try:
        timeout = float(timeout_text)
    except ValueError as error:
        raise ValueError(_timeout_message()) from error
    if not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT_S:
        raise ValueError(_timeout_message())
    local: Backend = "distilled" if backend == "distilled" else "untuned"
    return LocalFastHttpAdapter.connect(
        base_url=values.get(FAST_GATEWAY_URL_VARIABLE, DEFAULT_GATEWAY_URL),
        backend=local,
        timeout_s=timeout,
    )


def _timeout_message() -> str:
    return f"{FAST_TIMEOUT_VARIABLE} must be a number in (0, {MAX_TIMEOUT_S:g}]"


__all__ = [
    "FAST_BACKEND_VARIABLE",
    "FAST_GATEWAY_URL_VARIABLE",
    "FAST_TIMEOUT_VARIABLE",
    "fast_adapter_from_environment",
    "selected_fast_backend",
]
