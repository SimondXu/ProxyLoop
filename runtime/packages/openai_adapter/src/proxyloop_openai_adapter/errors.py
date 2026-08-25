"""Stable, fail-closed errors for the runtime model boundary."""

from __future__ import annotations

from enum import StrEnum


class ModelFailureKind(StrEnum):
    """Allowlisted model-boundary failure categories."""

    CONFIGURATION = "configuration"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    INVALID_OUTPUT = "invalid_output"
    MODEL_METADATA = "model_metadata"
    STALE_PINS = "stale_pins"


class OpenAICompatibleAdapterError(RuntimeError):
    """A model proposal failed before it could reach deterministic policy."""

    def __init__(self, kind: ModelFailureKind) -> None:
        self.kind = kind
        super().__init__(f"model operation failed safely: {kind.value}")


__all__ = ["ModelFailureKind", "OpenAICompatibleAdapterError"]
