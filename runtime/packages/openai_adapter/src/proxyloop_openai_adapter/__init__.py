"""Runtime-owned OpenAI-compatible Fast/Slow adapter."""

from .adapter import OpenAICompatibleAdapter
from .errors import ModelFailureKind, OpenAICompatibleAdapterError
from .outputs import (
    AcceptOfferCapabilityModelOutput,
    CapabilityModelOutput,
    FastModelOutput,
    NonOfferCapabilityModelOutput,
    SlowModelOutput,
    StrategyModelOutput,
    compile_fast_output,
    compile_slow_output,
)

__all__ = [
    "AcceptOfferCapabilityModelOutput",
    "CapabilityModelOutput",
    "FastModelOutput",
    "ModelFailureKind",
    "NonOfferCapabilityModelOutput",
    "OpenAICompatibleAdapter",
    "OpenAICompatibleAdapterError",
    "SlowModelOutput",
    "StrategyModelOutput",
    "compile_fast_output",
    "compile_slow_output",
]
