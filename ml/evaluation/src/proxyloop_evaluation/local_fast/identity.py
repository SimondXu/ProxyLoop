"""What a local Fast gateway serves, bound into one fingerprint (L3, L10).

The identity names the backend and its label, the attested base snapshot, the
adapter content fingerprint (distilled only), the prompt and compiler
versions, how the observation is rendered, and the decoding profile.  The
parity report records the identity it measured; the runtime (PR-9a) probes it
at start and compares it on every response.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass, field
from typing import Final, Literal

from proxyloop_agent_core.local_fast_wire import LOCAL_FAST_WIRE_VERSION

from proxyloop_evaluation.phase03b_experiment import (
    PHASE03B_PUBLIC_MARKER,
    QwenDecodingProfile,
)
from proxyloop_evaluation.phase03c_experiment import PHASE03C_COMPILER_VERSIONS
from proxyloop_evaluation.qwen_spec import QWEN3_8B_BF16_SPEC

from .trained_view import TRAINED_VIEW_VERSION

Backend = Literal["distilled", "untuned"]
BACKENDS: Final[tuple[Backend, ...]] = ("distilled", "untuned")
BACKEND_LABELS: Final[dict[Backend, str]] = {
    "distilled": "local opt-in candidate",
    "untuned": "untuned local baseline",
}
PROMPT_VERSION: Final = "v6"
MAX_TOKENS: Final = 512
MLX_PACKAGES: Final = ("mlx", "mlx-lm")


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def decoding_fingerprint() -> str:
    """The served profile: greedy, seed 0, ``max_tokens`` 512, thinking off."""

    return canonical_sha256(
        {
            "profile": QwenDecodingProfile(max_tokens=MAX_TOKENS).fingerprint,
            "enable_thinking": QWEN3_8B_BF16_SPEC.enable_thinking,
        }
    )


def installed_mlx_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in MLX_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


@dataclass(frozen=True)
class GatewayIdentity:
    backend: Backend
    adapter_fingerprint: str | None
    mlx_versions: dict[str, str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.backend not in BACKENDS:
            raise ValueError("backend must be distilled or untuned")
        if (self.backend == "distilled") != (self.adapter_fingerprint is not None):
            raise ValueError("only the distilled backend carries an adapter")

    def payload(self) -> dict[str, object]:
        return {
            "wire_version": LOCAL_FAST_WIRE_VERSION,
            "backend": self.backend,
            "label": BACKEND_LABELS[self.backend],
            "base_model": QWEN3_8B_BF16_SPEC.model,
            "base_revision": QWEN3_8B_BF16_SPEC.model_revision,
            "adapter_fingerprint": self.adapter_fingerprint,
            "prompt_version": PROMPT_VERSION,
            "compiler_version": PHASE03C_COMPILER_VERSIONS[PROMPT_VERSION],
            "observation_renderer_version": PHASE03B_PUBLIC_MARKER,
            "trained_view_version": TRAINED_VIEW_VERSION,
            "decoding_fingerprint": decoding_fingerprint(),
            "mlx_versions": dict(sorted(self.mlx_versions.items())),
        }

    @property
    def identity_fingerprint(self) -> str:
        return canonical_sha256(self.payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.payload(), "identity_fingerprint": self.identity_fingerprint}


__all__ = [
    "BACKENDS",
    "BACKEND_LABELS",
    "MAX_TOKENS",
    "PROMPT_VERSION",
    "Backend",
    "GatewayIdentity",
    "canonical_sha256",
    "decoding_fingerprint",
    "installed_mlx_versions",
]
