"""Optional, untuned Qwen Fast adapter for local MLX evaluation.

The module is importable without MLX installed.  The only model-facing seam is
``FastModelView``; deterministic policy, state, and completion authority stay
in ``agent_core``.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from proxyloop_agent_core import FastAdapterResult
from proxyloop_contracts import FastModelView

from .fast_output import FastModelOutput, compile_fast_output

QWEN_MLX_MODEL = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
QWEN_SOURCE_LINEAGE = "Qwen/Qwen3-4B-Instruct-2507"
QWEN_RUN_LABEL = "quantized_untuned"
QWEN_QUANTIZATION = "4bit"
QWEN_TUNING = "untuned"
QWEN_MODEL_REVISION = "50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b"
QWEN_SOURCE_REVISION = "cdbee75f17c01a7cc42f958dc650907174af0554"
QWEN_CHECKPOINT_FINGERPRINT = (
    "941705797578fb931fdef40b55c03ae60274b48fe03f1626f01197b52394de50"
)
QWEN_TOKENIZER_FINGERPRINT = (
    "5b06e759eb78534dbbf01b5ffc3faa43c9607921494151f7ca758b352f08722b"
)
QWEN_CHAT_TEMPLATE_FINGERPRINT = (
    "40c21f34cf67d8c760ef72f8ad3ae5afad514299d4b06e91dd9a8d705af7b541"
)
ADAPTER_VERSION = "phase-03a1-b-qwen-mlx-v1"
MAX_RAW_OUTPUT_CHARS = 16_384

_FORBIDDEN_KEYS = frozenset(
    {
        "manifest",
        "private",
        "evaluator",
        "oracle",
        "gold",
        "expected_action",
        "expected_outcome",
        "family_id",
        "entity_cluster",
        "configuration_id",
        "reward",
        "cot",
        "chain_of_thought",
        "raw_prompt",
        "free_form_memory",
    }
)

_FAST_OUTPUT_KEYS = (
    "dialogue_act",
    "fact_updates",
    "reasoner_request",
    "completion_claim",
    "response_text",
    "action_intent",
)


class QwenMLXStatus(StrEnum):
    SUCCEEDED = "succeeded"
    UNAVAILABLE = "unavailable"
    INVALID_OUTPUT = "invalid_output"
    ERROR = "error"


class QwenMLXAdapterError(RuntimeError):
    """Base typed failure raised by the FastAdapter compatibility method."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class QwenMLXUnavailableError(QwenMLXAdapterError):
    """MLX or the requested model runtime is not available."""


class QwenMLXOutputError(QwenMLXAdapterError):
    """The model did not produce a valid canonical Fast decision."""


@dataclass(frozen=True, slots=True)
class QwenPrompt:
    """The one frozen system/user prompt sent to a generator."""

    system: str
    user: str
    fingerprint: str

    @property
    def rendered(self) -> str:
        return f"<system>\n{self.system}\n</system>\n<user>\n{self.user}\n</user>"


@dataclass(frozen=True, slots=True)
class QwenGenerationText:
    """Optional usage metadata returned by an injected generator."""

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class QwenMLXMetadata:
    status: QwenMLXStatus
    model: str
    source_lineage: str
    model_revision: str
    source_revision: str
    checkpoint_fingerprint: str
    tokenizer_fingerprint: str
    chat_template_fingerprint: str
    quantization: str
    tuning: str
    run_label: str
    adapter_version: str
    prompt_fingerprint: str
    raw_output: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    error_code: str | None = None
    error_message: str | None = None
    json_valid: bool = False
    schema_valid: bool = False
    canonical_valid: bool = False


@dataclass(frozen=True, slots=True)
class QwenMLXGenerationResult:
    metadata: QwenMLXMetadata
    adapter_result: FastAdapterResult | None

    @property
    def status(self) -> QwenMLXStatus:
        return self.metadata.status


Generator = Callable[[str], str | QwenGenerationText]


@dataclass(frozen=True, slots=True)
class QwenCheckpointAttestation:
    model_revision: str
    source_revision: str
    checkpoint_fingerprint: str
    tokenizer_fingerprint: str
    chat_template_fingerprint: str


def attest_qwen_checkpoint(model_path: str) -> QwenCheckpointAttestation:
    """Hash the actual frozen snapshot rather than trusting CLI provenance."""

    snapshot = Path(model_path)
    if not snapshot.is_dir() or snapshot.name != QWEN_MODEL_REVISION:
        raise ValueError("Qwen model path is not the frozen snapshot revision")
    rows: dict[str, dict[str, object]] = {}
    for path in sorted(snapshot.iterdir(), key=lambda item: item.name):
        if path.name.startswith(".") or not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        rows[path.name] = {"sha256": digest.hexdigest(), "size": path.stat().st_size}
    required = {
        "model.safetensors",
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "chat_template.jinja",
    }
    if not required <= rows.keys():
        raise ValueError("Qwen snapshot is missing required model/tokenizer files")
    tokenizer_names = {
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
        "merges.txt",
        "added_tokens.json",
        "special_tokens_map.json",
    }
    checkpoint_fingerprint = _object_fingerprint(rows)
    tokenizer_fingerprint = _object_fingerprint(
        {name: rows[name] for name in sorted(tokenizer_names) if name in rows}
    )
    chat_template_fingerprint = str(rows["chat_template.jinja"]["sha256"])
    observed = (
        checkpoint_fingerprint,
        tokenizer_fingerprint,
        chat_template_fingerprint,
    )
    expected = (
        QWEN_CHECKPOINT_FINGERPRINT,
        QWEN_TOKENIZER_FINGERPRINT,
        QWEN_CHAT_TEMPLATE_FINGERPRINT,
    )
    if observed != expected:
        raise ValueError("Qwen checkpoint attestation does not match the frozen files")
    return QwenCheckpointAttestation(
        model_revision=QWEN_MODEL_REVISION,
        source_revision=QWEN_SOURCE_REVISION,
        checkpoint_fingerprint=checkpoint_fingerprint,
        tokenizer_fingerprint=tokenizer_fingerprint,
        chat_template_fingerprint=chat_template_fingerprint,
    )


class QwenMLXAdapter:
    """A lazy local MLX adapter implementing the Fast adapter seam.

    ``generator`` is intentionally injectable for offline contract tests.  If
    omitted, the adapter imports ``mlx_lm`` only when ``generate`` is called.
    Missing MLX is a typed unavailable result, never a scripted success.
    """

    def __init__(
        self,
        *,
        generator: Generator | None = None,
        model_path: str | None = None,
        max_tokens: int = 512,
    ) -> None:
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        self._generator = generator
        self._model_path = model_path
        self._attestation = (
            attest_qwen_checkpoint(model_path)
            if generator is None and model_path is not None
            else QwenCheckpointAttestation(
                model_revision=QWEN_MODEL_REVISION,
                source_revision=QWEN_SOURCE_REVISION,
                checkpoint_fingerprint=QWEN_CHECKPOINT_FINGERPRINT,
                tokenizer_fingerprint=QWEN_TOKENIZER_FINGERPRINT,
                chat_template_fingerprint=QWEN_CHAT_TEMPLATE_FINGERPRINT,
            )
        )
        self._max_tokens = max_tokens
        self._mlx_model: object | None = None
        self._mlx_tokenizer: object | None = None

    @property
    def model(self) -> str:
        return QWEN_MLX_MODEL

    @property
    def source_lineage(self) -> str:
        return QWEN_SOURCE_LINEAGE

    @property
    def checkpoint_attestation(self) -> QwenCheckpointAttestation:
        return self._attestation

    def build_prompt(self, view: FastModelView) -> QwenPrompt:
        if not isinstance(view, FastModelView):
            raise TypeError("Qwen MLX accepts only canonical FastModelView")

        serialized = view.model_dump(mode="json")
        # Keep this projection explicit.  In particular, the model does not
        # need the capability vocabulary revision to produce a Fast decision.
        prompt_view: dict[str, object] = {
            "contract_type": serialized["contract_type"],
            "schema_version": serialized["schema_version"],
            "case_id": serialized["case_id"],
            "pins": {
                "case_id": serialized["pins"]["case_id"],
                "case_revision": serialized["pins"]["case_revision"],
                "constraint_set_revision": serialized["pins"][
                    "constraint_set_revision"
                ],
                "fact_ledger_revision": serialized["pins"]["fact_ledger_revision"],
                "strategy_id": serialized["pins"]["strategy_id"],
                "strategy_revision": serialized["pins"]["strategy_revision"],
                "planning_basis_fingerprint": serialized["pins"][
                    "planning_basis_fingerprint"
                ],
                "event_cursor": serialized["pins"]["event_cursor"],
                "provider_config_ref": serialized["pins"]["provider_config_ref"],
            },
            "planning_basis": {
                "planning_basis_fingerprint": serialized["planning_basis"][
                    "planning_basis_fingerprint"
                ]
            },
            "goal": serialized["goal"],
            "constraints": serialized["constraints"],
            "verified_facts": serialized["verified_facts"],
            "strategy": serialized["strategy"],
            "recent_events": serialized["recent_events"],
            "latest_provider_event": serialized["latest_provider_event"],
            "pending_slow_work": serialized["pending_slow_work"],
            "allowed_dialogue_acts": serialized["allowed_dialogue_acts"],
            "allowed_disclosures": serialized["allowed_disclosures"],
        }
        _assert_safe_keys(prompt_view)
        user = (
            "Produce one strict Fast semantic proposal for this typed view.\n"
            "OUTPUT_JSON_SCHEMA:\n"
            + json.dumps(
                FastModelOutput.model_json_schema(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\nTYPED_FAST_VIEW:\n"
            + json.dumps(
                prompt_view,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        system = (
            "You are the low-latency Fast dialogue decision component. Return "
            "only one JSON object with exactly these keys: "
            + ", ".join(_FAST_OUTPUT_KEYS)
            + ". Infrastructure IDs, timestamps, and state pins are compiled "
            "outside the model. Set action_intent to null. Do not add commentary."
        )
        fingerprint_payload = json.dumps(
            {"system": system, "user": user},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()
        return QwenPrompt(system=system, user=user, fingerprint=fingerprint)

    def generate(self, view: FastModelView) -> QwenMLXGenerationResult:
        prompt = self.build_prompt(view)
        started = time.perf_counter()
        try:
            generated = self._run_generator(prompt)
        except QwenMLXUnavailableError as error:
            return self._result(
                prompt,
                status=QwenMLXStatus.UNAVAILABLE,
                elapsed_ms=_elapsed_ms(started),
                error_code=error.code,
                error_message=str(error),
            )
        except Exception as error:  # model/runtime errors are recorded, not repaired
            return self._result(
                prompt,
                status=QwenMLXStatus.ERROR,
                elapsed_ms=_elapsed_ms(started),
                error_code="generation_error",
                error_message=_bounded_error(error),
            )

        output = _coerce_generation_text(generated)
        if output is None:
            return self._result(
                prompt,
                status=QwenMLXStatus.INVALID_OUTPUT,
                elapsed_ms=_elapsed_ms(started),
                error_code="generator_return_type",
                error_message="generator must return text or QwenGenerationText",
            )
        raw = output.text
        bounded_raw = raw[:MAX_RAW_OUTPUT_CHARS]
        if len(raw) > MAX_RAW_OUTPUT_CHARS:
            return self._result(
                prompt,
                status=QwenMLXStatus.INVALID_OUTPUT,
                elapsed_ms=_elapsed_ms(started),
                raw_output=bounded_raw,
                input_tokens=output.input_tokens,
                output_tokens=output.output_tokens,
                error_code="output_too_large",
                error_message="generated output exceeded the bounded capture limit",
            )

        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            return self._result(
                prompt,
                status=QwenMLXStatus.INVALID_OUTPUT,
                elapsed_ms=_elapsed_ms(started),
                raw_output=bounded_raw,
                input_tokens=output.input_tokens,
                output_tokens=output.output_tokens,
                error_code="invalid_json",
                error_message=_bounded_error(error),
            )
        if not isinstance(parsed, dict):
            return self._result(
                prompt,
                status=QwenMLXStatus.INVALID_OUTPUT,
                elapsed_ms=_elapsed_ms(started),
                raw_output=bounded_raw,
                input_tokens=output.input_tokens,
                output_tokens=output.output_tokens,
                error_code="json_object_required",
                error_message="Fast output must be a JSON object",
                json_valid=True,
            )
        if "action_intent" not in parsed or parsed["action_intent"] is not None:
            return self._result(
                prompt,
                status=QwenMLXStatus.INVALID_OUTPUT,
                elapsed_ms=_elapsed_ms(started),
                raw_output=bounded_raw,
                input_tokens=output.input_tokens,
                output_tokens=output.output_tokens,
                error_code="fast_action_intent_forbidden",
                error_message="Phase 03A1 Fast action_intent must be explicitly null",
                json_valid=True,
            )
        try:
            model_output = FastModelOutput.model_validate_json(raw)
        except Exception as error:
            return self._result(
                prompt,
                status=QwenMLXStatus.INVALID_OUTPUT,
                elapsed_ms=_elapsed_ms(started),
                raw_output=bounded_raw,
                input_tokens=output.input_tokens,
                output_tokens=output.output_tokens,
                error_code="schema_validation_error",
                error_message=_bounded_error(error),
                json_valid=True,
            )

        try:
            decision = compile_fast_output(view, model_output)
        except Exception as error:
            return self._result(
                prompt,
                status=QwenMLXStatus.INVALID_OUTPUT,
                elapsed_ms=_elapsed_ms(started),
                raw_output=bounded_raw,
                input_tokens=output.input_tokens,
                output_tokens=output.output_tokens,
                error_code="canonical_validation_error",
                error_message=_bounded_error(error),
                json_valid=True,
                schema_valid=True,
            )

        return self._result(
            prompt,
            status=QwenMLXStatus.SUCCEEDED,
            elapsed_ms=_elapsed_ms(started),
            raw_output=bounded_raw,
            adapter_result=FastAdapterResult(pins=view.pins, decision=decision),
            input_tokens=output.input_tokens,
            output_tokens=output.output_tokens,
            json_valid=True,
            schema_valid=True,
            canonical_valid=True,
        )

    def decide(self, view: FastModelView) -> FastAdapterResult:
        """Implement the shared FastAdapter seam with typed failures."""

        result = self.generate(view)
        if result.adapter_result is not None:
            return result.adapter_result
        error_code = result.metadata.error_code or "qwen_mlx_error"
        message = result.metadata.error_message or error_code
        if result.status is QwenMLXStatus.UNAVAILABLE:
            raise QwenMLXUnavailableError(error_code, message)
        raise QwenMLXOutputError(error_code, message)

    def _run_generator(self, prompt: QwenPrompt) -> QwenGenerationText | str:
        if self._generator is not None:
            return self._generator(prompt.rendered)
        try:
            mlx_lm = importlib.import_module("mlx_lm")
        except ModuleNotFoundError as error:
            raise QwenMLXUnavailableError(
                "mlx_lm_unavailable",
                "mlx_lm is not installed; local Qwen evaluation was not run",
            ) from error

        load = getattr(mlx_lm, "load", None)
        generate = getattr(mlx_lm, "generate", None)
        if not callable(load) or not callable(generate):
            raise QwenMLXUnavailableError(
                "mlx_lm_api_unavailable",
                "mlx_lm does not expose the required load/generate API",
            )
        if self._mlx_model is None or self._mlx_tokenizer is None:
            loaded = cast(Callable[[str], object], load)(self._model_path or self.model)
            if not isinstance(loaded, tuple) or len(loaded) != 2:
                raise QwenMLXUnavailableError(
                    "mlx_lm_load_invalid",
                    "mlx_lm.load did not return a model/tokenizer pair",
                )
            self._mlx_model, self._mlx_tokenizer = loaded
        model = self._mlx_model
        tokenizer = self._mlx_tokenizer
        apply_chat_template = getattr(tokenizer, "apply_chat_template", None)
        if not callable(apply_chat_template):
            raise QwenMLXUnavailableError(
                "chat_template_unavailable",
                "the Qwen tokenizer does not expose apply_chat_template",
            )
        messages = [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ]
        chat_prompt = apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=False,
        )
        if not isinstance(chat_prompt, str):
            raise QwenMLXUnavailableError(
                "chat_template_output_invalid",
                "the tokenizer chat template did not return text",
            )
        generated = cast(Callable[..., object], generate)(
            model,
            tokenizer,
            prompt=chat_prompt,
            max_tokens=self._max_tokens,
            verbose=False,
        )
        if not isinstance(generated, str):
            raise QwenMLXUnavailableError(
                "mlx_lm_generation_type",
                "mlx_lm.generate did not return bounded text",
            )
        return QwenGenerationText(
            text=generated,
            input_tokens=_token_count(tokenizer, chat_prompt),
            output_tokens=_token_count(tokenizer, generated),
        )

    def _result(
        self,
        prompt: QwenPrompt,
        *,
        status: QwenMLXStatus,
        elapsed_ms: int | None,
        raw_output: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        adapter_result: FastAdapterResult | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        json_valid: bool = False,
        schema_valid: bool = False,
        canonical_valid: bool = False,
    ) -> QwenMLXGenerationResult:
        return QwenMLXGenerationResult(
            metadata=QwenMLXMetadata(
                status=status,
                model=self.model,
                source_lineage=self.source_lineage,
                model_revision=self._attestation.model_revision,
                source_revision=self._attestation.source_revision,
                checkpoint_fingerprint=self._attestation.checkpoint_fingerprint,
                tokenizer_fingerprint=self._attestation.tokenizer_fingerprint,
                chat_template_fingerprint=(self._attestation.chat_template_fingerprint),
                quantization=QWEN_QUANTIZATION,
                tuning=QWEN_TUNING,
                run_label=QWEN_RUN_LABEL,
                adapter_version=ADAPTER_VERSION,
                prompt_fingerprint=prompt.fingerprint,
                raw_output=raw_output,
                latency_ms=elapsed_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                error_code=error_code,
                error_message=error_message,
                json_valid=json_valid,
                schema_valid=schema_valid,
                canonical_valid=canonical_valid,
            ),
            adapter_result=adapter_result,
        )


def _coerce_generation_text(value: object) -> QwenGenerationText | None:
    if isinstance(value, str):
        return QwenGenerationText(text=value)
    if isinstance(value, QwenGenerationText):
        return value
    return None


def _object_fingerprint(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _assert_safe_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized in _FORBIDDEN_KEYS or any(
                forbidden in normalized for forbidden in _FORBIDDEN_KEYS
            ):
                raise ValueError(f"forbidden Fast prompt key: {key}")
            _assert_safe_keys(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_safe_keys(child)


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _token_count(tokenizer: object, text: str) -> int | None:
    encode = getattr(tokenizer, "encode", None)
    if not callable(encode):
        return None
    try:
        encoded = encode(text)
    except Exception:
        return None
    if isinstance(encoded, (list, tuple)):
        return len(encoded)
    return None


def _bounded_error(error: BaseException) -> str:
    return str(error)[:512] or error.__class__.__name__


__all__ = [
    "ADAPTER_VERSION",
    "MAX_RAW_OUTPUT_CHARS",
    "QWEN_CHAT_TEMPLATE_FINGERPRINT",
    "QWEN_CHECKPOINT_FINGERPRINT",
    "QWEN_MLX_MODEL",
    "QWEN_MODEL_REVISION",
    "QWEN_QUANTIZATION",
    "QWEN_RUN_LABEL",
    "QWEN_SOURCE_LINEAGE",
    "QWEN_SOURCE_REVISION",
    "QWEN_TOKENIZER_FINGERPRINT",
    "QWEN_TUNING",
    "QwenCheckpointAttestation",
    "QwenGenerationText",
    "QwenMLXAdapter",
    "QwenMLXAdapterError",
    "QwenMLXGenerationResult",
    "QwenMLXMetadata",
    "QwenMLXOutputError",
    "QwenMLXStatus",
    "QwenMLXUnavailableError",
    "QwenPrompt",
    "attest_qwen_checkpoint",
]
