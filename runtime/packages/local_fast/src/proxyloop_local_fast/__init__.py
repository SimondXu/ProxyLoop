"""Runtime HTTP client for the opt-in loopback local Fast gateway."""

from .adapter import (
    BACKEND_LABELS,
    DEFAULT_GATEWAY_URL,
    DEFAULT_TIMEOUT_S,
    LOCAL_FAST_ADAPTER_VERSION,
    LOCAL_FAST_PROVIDER,
    LOOPBACK_HOSTS,
    MAX_TIMEOUT_S,
    Backend,
    BackendLabel,
    LocalFastHttpAdapter,
    LocalFastStartupError,
    parse_loopback_url,
    validate_timeout,
)
from .config import (
    FAST_BACKEND_VARIABLE,
    FAST_GATEWAY_URL_VARIABLE,
    FAST_TIMEOUT_VARIABLE,
    fast_adapter_from_environment,
    selected_fast_backend,
)

__all__ = [
    "BACKEND_LABELS",
    "DEFAULT_GATEWAY_URL",
    "DEFAULT_TIMEOUT_S",
    "FAST_BACKEND_VARIABLE",
    "FAST_GATEWAY_URL_VARIABLE",
    "FAST_TIMEOUT_VARIABLE",
    "LOCAL_FAST_ADAPTER_VERSION",
    "LOCAL_FAST_PROVIDER",
    "LOOPBACK_HOSTS",
    "MAX_TIMEOUT_S",
    "Backend",
    "BackendLabel",
    "LocalFastHttpAdapter",
    "LocalFastStartupError",
    "fast_adapter_from_environment",
    "parse_loopback_url",
    "selected_fast_backend",
    "validate_timeout",
]
