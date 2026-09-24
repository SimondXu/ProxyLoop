"""The gateway core: the measured 03C generation path behind a fail-closed load.

``LocalFastGatewayCore`` wraps ``Phase03CQwenAdapter`` exactly as the 03C
local rescore builds it (8B bf16 spec, v6 prompt, greedy, seed 0, thinking
off, ``max_tokens`` 512).  ``load`` refuses to start on a base snapshot that
fails attestation, an adapter whose content differs from the committed
attestation, or a LoRA load that did not take (L4).

The last check exists because ``mlx_lm.tuner.utils.load_adapters`` calls
``model.load_weights(..., strict=False)`` and ``LoRALinear`` starts with
``lora_b = 0``: an adapter whose tensor names miss the model loads nothing,
and the "distilled" model silently *is* the untuned one.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from proxyloop_agent_core import SafeObservation
from proxyloop_contracts import FastModelView

from proxyloop_evaluation.fast_output import FastModelOutput
from proxyloop_evaluation.fast_parse import extract_fast_json
from proxyloop_evaluation.phase03c_experiment import Phase03CQwenAdapter
from proxyloop_evaluation.qwen_mlx import QwenGenerationText, QwenMLXStatus
from proxyloop_evaluation.qwen_spec import QWEN3_8B_BF16_SPEC

from .identity import (
    MAX_TOKENS,
    PROMPT_VERSION,
    Backend,
    GatewayIdentity,
    installed_mlx_versions,
)
from .mlx_adapter_conversion import ConversionAttestation, verify_mlx_adapter
from .trained_view import TrainedViewError, trained_view

GatewayStatus = Literal["succeeded", "invalid_output", "unrenderable"]
# Every INVALID_OUTPUT code ``Phase03CQwenAdapter.generate`` can return.
INVALID_OUTPUT_DETAIL_CODES: Final = frozenset(
    {
        "output_too_large",
        "thinking_leak",
        "duplicate_json_key",
        "invalid_json",
        "invalid_json_after_fence_strip",
        "json_object_required",
        "fast_action_intent_forbidden",
        "schema_validation_error",
        "canonical_validation_error",
        "generator_return_type",
    }
)
UNRENDERABLE_DETAIL_CODES: Final = frozenset(
    {"no_provider_event", "trained_view_invalid", "prompt_render_refused"}
)


class LoraLoadError(RuntimeError):
    """The loaded model does not carry exactly the attested LoRA layers."""


class GatewayModelError(RuntimeError):
    """The model runtime failed (not an output problem); the gateway answers 500."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def collect_lora_layers(
    model: object, *, nonzero: Callable[[object], bool]
) -> dict[str, bool]:
    """``{module path: lora_b has a non-zero entry}`` for every LoRA module."""

    named_modules = getattr(model, "named_modules", None)
    if not callable(named_modules):
        raise LoraLoadError("model does not expose named_modules")
    return {
        str(name): nonzero(module.lora_b)
        for name, module in named_modules()
        if hasattr(module, "lora_a") and hasattr(module, "lora_b")
    }


def check_lora_layers(layers: Mapping[str, bool], *, expected: frozenset[str]) -> None:
    """Refuse unless the LoRA modules are exactly ``expected``, all non-zero."""

    if set(layers) != expected:
        raise LoraLoadError(
            f"expected {len(expected)} LoRA layers, found {len(layers)} "
            "(or different module paths)"
        )
    zero = sorted(name for name, loaded in layers.items() if not loaded)
    if zero:
        raise LoraLoadError(
            f"{len(zero)} of {len(layers)} LoRA layers have all-zero lora_b; "
            "the adapter weights did not load"
        )


def _model_thread() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-fast-model")


def _mlx_nonzero(value: object) -> bool:
    mx = importlib.import_module("mlx.core")
    return bool(mx.any(value != 0).item())


@dataclass(frozen=True, slots=True)
class GatewayResult:
    """One decide call.  ``raw_output`` is for the parity harness only; the
    HTTP layer never returns or logs it (L9)."""

    status: GatewayStatus
    output: dict[str, object] | None
    detail_code: str | None
    input_tokens: int
    output_tokens: int
    generation_ms: int
    raw_output: str | None
    prompt_fingerprint: str | None


def _unrenderable(code: str) -> GatewayResult:
    return GatewayResult(
        status="unrenderable",
        output=None,
        detail_code=code,
        input_tokens=0,
        output_tokens=0,
        generation_ms=0,
        raw_output=None,
        prompt_fingerprint=None,
    )


class LocalFastGatewayCore:
    """All model work runs on one dedicated thread.

    MLX streams are thread-local: a model loaded on one thread failed with
    "There is no Stream(cpu, 0) in current thread" when a fresh HTTP handler
    thread generated first (observed on the live gateway).  ``load`` and every
    ``decide`` therefore run on ``model_thread``; callers on any thread block
    on the result.
    """

    def __init__(
        self,
        adapter: Phase03CQwenAdapter,
        identity: GatewayIdentity,
        model_thread: ThreadPoolExecutor,
    ) -> None:
        if adapter.prompt_version != PROMPT_VERSION:
            raise ValueError("the gateway serves the v6 prompt only")
        self._adapter = adapter
        self._identity = identity
        self._model_thread = model_thread

    @property
    def identity(self) -> GatewayIdentity:
        return self._identity

    @classmethod
    def load(
        cls,
        *,
        backend: Backend,
        model_path: Path,
        adapter_path: Path | None = None,
        attestation: ConversionAttestation | None = None,
    ) -> LocalFastGatewayCore:
        """Attest, load, and self-check; any failure refuses to start."""

        distilled = backend == "distilled"
        if distilled != (adapter_path is not None and attestation is not None):
            raise ValueError(
                "the distilled backend needs an adapter and its attestation; "
                "the untuned backend takes neither"
            )
        if adapter_path is not None and attestation is not None:
            verify_mlx_adapter(adapter_path, attestation)

        def load_on_model_thread() -> Phase03CQwenAdapter:
            # The constructor attests the base snapshot (attest_qwen_spec).
            adapter = Phase03CQwenAdapter(
                model_path=str(model_path),
                adapter_path=str(adapter_path) if adapter_path is not None else None,
                max_tokens=MAX_TOKENS,
                model_spec=QWEN3_8B_BF16_SPEC,
                prompt_version=PROMPT_VERSION,
            )
            # The same lazy loader generate() uses; loading here makes the
            # self-check run before the first request instead of during it.
            model, _, _ = adapter._load_mlx()
            check_lora_layers(
                collect_lora_layers(model, nonzero=_mlx_nonzero),
                expected=(
                    attestation.expected_lora_modules()
                    if attestation is not None
                    else frozenset()
                ),
            )
            return adapter

        model_thread = _model_thread()
        try:
            adapter = model_thread.submit(load_on_model_thread).result()
        except BaseException:
            model_thread.shutdown(wait=False)
            raise
        identity = GatewayIdentity(
            backend=backend,
            adapter_fingerprint=(
                attestation.content_fingerprint if attestation is not None else None
            ),
            mlx_versions=installed_mlx_versions(),
        )
        return cls(adapter, identity, model_thread)

    @classmethod
    def with_generator(
        cls,
        generator: Callable[[str], str | QwenGenerationText],
        *,
        backend: Backend = "distilled",
    ) -> LocalFastGatewayCore:
        """Test double: the real core and prompt path, no MLX (CI-safe)."""

        return cls(
            Phase03CQwenAdapter(
                generator=generator,
                max_tokens=MAX_TOKENS,
                model_spec=QWEN3_8B_BF16_SPEC,
                prompt_version=PROMPT_VERSION,
            ),
            GatewayIdentity(
                backend=backend,
                adapter_fingerprint="fake-generator"
                if backend == "distilled"
                else None,
                mlx_versions={},
            ),
            _model_thread(),
        )

    def decide(
        self, view: FastModelView, observation: SafeObservation
    ) -> GatewayResult:
        """Raises ``ObservationMismatchError`` (a request error) or
        ``GatewayModelError``; every other outcome is a ``GatewayResult``."""

        return self._model_thread.submit(self._decide, view, observation).result()

    def _decide(
        self, view: FastModelView, observation: SafeObservation
    ) -> GatewayResult:
        try:
            model_view = trained_view(view, observation)
        except TrainedViewError as error:
            return _unrenderable(error.code)
        try:
            # generate() builds the same prompt outside its own try block;
            # building it here first turns a refused render into a status.
            self._adapter.build_prompt(model_view)
        except (ValueError, KeyError, TypeError):
            return _unrenderable("prompt_render_refused")
        generated = self._adapter.generate(model_view)
        metadata = generated.metadata

        def result(
            status: GatewayStatus, output: dict[str, object] | None, detail: str | None
        ) -> GatewayResult:
            return GatewayResult(
                status=status,
                output=output,
                detail_code=detail,
                input_tokens=metadata.input_tokens or 0,
                output_tokens=metadata.output_tokens or 0,
                generation_ms=metadata.latency_ms or 0,
                raw_output=metadata.raw_output,
                prompt_fingerprint=metadata.prompt_fingerprint,
            )

        if metadata.status is QwenMLXStatus.SUCCEEDED:
            text, _ = extract_fast_json(metadata.raw_output or "")
            output = FastModelOutput.model_validate_json(text).model_dump(mode="json")
            return result("succeeded", output, None)
        if metadata.status is QwenMLXStatus.INVALID_OUTPUT:
            code = metadata.error_code or ""
            known = code in INVALID_OUTPUT_DETAIL_CODES
            return result("invalid_output", None, code if known else "invalid_output")
        raise GatewayModelError(metadata.error_code or "generation_error")


__all__ = [
    "INVALID_OUTPUT_DETAIL_CODES",
    "UNRENDERABLE_DETAIL_CODES",
    "GatewayModelError",
    "GatewayResult",
    "GatewayStatus",
    "LocalFastGatewayCore",
    "LoraLoadError",
    "check_lora_layers",
    "collect_lora_layers",
]
