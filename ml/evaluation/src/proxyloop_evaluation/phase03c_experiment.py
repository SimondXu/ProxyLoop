"""Phase 03C Stage 0: v3 Fast prompt, dual-parse evaluator, and 03B errata.

Everything here is additive.  The Phase 03B evaluator bytes stay frozen (they
are bound by the 03B pipeline fingerprint); this module reuses its examples,
detectors, and compact view, changes only how raw output is parsed and how
``policy_violation`` is defined, and re-scores stored 03B raw outputs offline
with zero model calls.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Final, cast

from proxyloop_agent_core import FastAdapterResult, ScriptedOracleConsumer
from proxyloop_contracts import DialogueAct, FastModelView, FastTurnDecision
from proxyloop_telecom_domain import offer_compliance_violations
from pydantic import ValidationError

from .fast_output import FastModelOutput, compile_fast_output
from .fast_parse import (
    DuplicateJSONKeyError,
    JSONParseMode,
    duplicate_json_keys,
    extract_fast_json,
    parse_fast_json,
)
from .phase03b_experiment import (
    PHASE03B_POLICY_VERSION,
    Phase03BControls,
    Phase03BExample,
    Phase03BQwenAdapter,
    QwenDecodingProfile,
    _attest_phase03b_adapter,
    _raw_fact_updates_violation,
    _schema_valid,
    build_phase03b_examples,
    detect_authority_violation,
    detect_disallowed_disclosure,
    detect_false_completion,
    detect_pii,
    detect_stale_pins,
    detect_unsupported_response_facts,
)
from .phase03b_readiness import proposed_fast_target
from .qwen_mlx import (
    MAX_RAW_OUTPUT_CHARS,
    QwenCheckpointAttestation,
    QwenGenerationText,
    QwenMLXAdapter,
    QwenMLXStatus,
    QwenMLXUnavailableError,
    QwenPrompt,
)
from .qwen_spec import (
    QWEN3_4B_4BIT_SPEC,
    QWEN3_8B_BF16_SPEC,
    THINKING_OPEN_TAG,
    QwenModelSpec,
    attest_qwen_spec,
)

ROOT = Path(__file__).resolve().parents[4]
PHASE03C_DIR = ROOT / "data/experiments/phase-03c"
ERRATA_DIR = PHASE03C_DIR / "errata"
RESULTS_DIR = PHASE03C_DIR / "results"
PHASE03B_RESULTS_DIR = ROOT / "data/experiments/phase-03b-qlora-smoke/results"
PHASE03B_ARM_SOURCES: Final[dict[str, Path]] = {
    "a": PHASE03B_RESULTS_DIR / "arm-a-untuned.json",
    "b": PHASE03B_RESULTS_DIR / "arm-b-qlora.json",
}

PHASE03C_COMPILER_VERSION: Final = "phase-03c-fast-compiler-v3"
PHASE03C_POLICY_VERSION: Final = PHASE03B_POLICY_VERSION
PHASE03C_ERRATUM_SCHEMA_VERSION: Final = "phase-03c-parser-erratum-v1"
PHASE03C_EVALUATOR_SOURCE_FINGERPRINT: Final = hashlib.sha256(
    Path(__file__).read_bytes()
).hexdigest()
REASON_CODE_LINE: Final = (
    "reason_code: short snake_case code, max 256 chars. Examples: "
    "offer_candidate_requires_slow_review, provider_state_requires_replan, none."
)
PROMPT_TOKEN_LIMIT: Final = 2048
PHASE03C_ADAPTER_VERSION: Final = "phase-03c-qwen-mlx-v3"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _coerce_generation_text(value: object) -> QwenGenerationText | None:
    if isinstance(value, str):
        return QwenGenerationText(text=value)
    if isinstance(value, QwenGenerationText):
        return value
    return None


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _bounded_error(error: BaseException) -> str:
    return str(error)[:512] or error.__class__.__name__


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Phase03CMetadata:
    """Generation evidence with strict and tolerant parse facts side by side."""

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
    json_parse_mode: JSONParseMode | None = None
    json_valid_strict: bool = False
    thinking_leak: bool = False


@dataclass(frozen=True, slots=True)
class Phase03CGenerationResult:
    metadata: Phase03CMetadata
    adapter_result: FastAdapterResult | None

    @property
    def status(self) -> QwenMLXStatus:
        return self.metadata.status


class Phase03CQwenAdapter(Phase03BQwenAdapter):
    """Phase 03B compact view plus the embedded schema the 03B prompt dropped.

    The base checkpoint is configurable so the 8B re-baseline and the 4B
    reference row share one prompt builder, every chat render passes the
    spec's ``enable_thinking`` switch, and ``generate`` reports strict and
    tolerant JSON validity without editing the model output.  The inherited
    ``qwen_mlx``/``phase03b_experiment`` bytes are frozen by the 03A1 r4 and
    03B fingerprints, so the overrides below set the parents' private fields
    directly instead of changing their constructors.
    """

    def __init__(
        self,
        *,
        generator: Callable[[str], str | QwenGenerationText] | None = None,
        model_path: str | None = None,
        adapter_path: str | None = None,
        max_tokens: int = 512,
        model_spec: QwenModelSpec | None = None,
    ) -> None:
        spec = model_spec if model_spec is not None else QWEN3_4B_4BIT_SPEC
        # The historical constructor attests the 4B checkpoint only, so it
        # is given no model_path; the spec-aware attestation happens here.
        QwenMLXAdapter.__init__(self, generator=generator, max_tokens=max_tokens)
        self._model_path = model_path
        self._model_spec = spec
        self._attestation = (
            attest_qwen_spec(model_path, spec)
            if generator is None and model_path is not None
            else spec.attestation
        )
        self._phase03b_adapter_path = adapter_path
        self._phase03b_decoding_profile = QwenDecodingProfile(max_tokens=max_tokens)
        (
            self._phase03b_adapter_version,
            self._phase03b_adapter_fingerprint,
        ) = _attest_phase03b_adapter(adapter_path)

    @property
    def model(self) -> str:
        return self._model_spec.model

    @property
    def source_lineage(self) -> str:
        return self._model_spec.source_lineage

    @property
    def model_spec(self) -> QwenModelSpec:
        return self._model_spec

    def build_prompt(self, view: FastModelView) -> QwenPrompt:
        """03B prompt text and compact view verbatim, plus the schema block.

        Attempt 01 of the 8B smoke replaced the 03B OUTPUT_SHAPE hint with the
        schema alone and lost ``fact_updates: []``; keeping the 03B text
        byte-for-byte and only adding to it is what the contract asks for.
        """

        v2 = super().build_prompt(view)
        system = (
            v2.system + " Output the bare JSON object: no markdown fence, no "
            "leading word, no commentary before or after it, and never repeat "
            "a key. reason_code is a short snake_case code, max 256 chars."
        )
        marker = "COMPACT_FAST_VIEW:\n"
        if v2.user.count(marker) != 1:
            raise ValueError("Phase 03B user prompt marker drifted")
        user = v2.user.replace(
            marker,
            "OUTPUT_JSON_SCHEMA:\n"
            + _canonical_json(FastModelOutput.model_json_schema())
            + "\n"
            + REASON_CODE_LINE
            + "\n"
            + marker,
        )
        return QwenPrompt(
            system=system,
            user=user,
            fingerprint=_fingerprint({"system": system, "user": user}),
        )

    def generate(self, view: FastModelView) -> Phase03CGenerationResult:  # type: ignore[override]
        prompt = self.build_prompt(view)
        started = time.perf_counter()
        try:
            generated = self._run_generator(prompt)
        except QwenMLXUnavailableError as error:
            return self._result_v3(
                prompt,
                status=QwenMLXStatus.UNAVAILABLE,
                elapsed_ms=_elapsed_ms(started),
                error_code=error.code,
                error_message=str(error),
            )
        except Exception as error:  # model/runtime errors are recorded, not repaired
            return self._result_v3(
                prompt,
                status=QwenMLXStatus.ERROR,
                elapsed_ms=_elapsed_ms(started),
                error_code="generation_error",
                error_message=_bounded_error(error),
            )
        output = _coerce_generation_text(generated)
        if output is None:
            return self._result_v3(
                prompt,
                status=QwenMLXStatus.INVALID_OUTPUT,
                elapsed_ms=_elapsed_ms(started),
                error_code="generator_return_type",
                error_message="generator must return text or QwenGenerationText",
            )
        raw = output.text
        raw_output = raw[:MAX_RAW_OUTPUT_CHARS]
        input_tokens = output.input_tokens
        output_tokens = output.output_tokens

        def invalid(
            code: str,
            message: str,
            *,
            json_valid: bool = False,
            schema_valid: bool = False,
            json_parse_mode: JSONParseMode | None = None,
            json_valid_strict: bool = False,
            thinking_leak: bool = False,
        ) -> Phase03CGenerationResult:
            return self._result_v3(
                prompt,
                status=QwenMLXStatus.INVALID_OUTPUT,
                elapsed_ms=_elapsed_ms(started),
                raw_output=raw_output,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                error_code=code,
                error_message=message,
                json_valid=json_valid,
                schema_valid=schema_valid,
                json_parse_mode=json_parse_mode,
                json_valid_strict=json_valid_strict,
                thinking_leak=thinking_leak,
            )

        if len(raw) > MAX_RAW_OUTPUT_CHARS:
            return invalid(
                "output_too_large", "generated output exceeded the bounded capture"
            )
        if THINKING_OPEN_TAG in raw:
            return invalid(
                "thinking_leak",
                "model emitted thinking content; non-thinking mode is required",
                thinking_leak=True,
            )
        text, parse_mode = extract_fast_json(raw)
        strict = parse_mode == "strict"
        try:
            parsed = parse_fast_json(text)
        except DuplicateJSONKeyError as error:
            return invalid(
                "duplicate_json_key",
                _bounded_error(error),
                json_parse_mode=parse_mode,
            )
        except (TypeError, json.JSONDecodeError) as error:
            return invalid(
                "invalid_json" if strict else "invalid_json_after_fence_strip",
                _bounded_error(error),
                json_parse_mode=parse_mode,
            )
        if not isinstance(parsed, dict):
            return invalid(
                "json_object_required",
                "Fast output must be a JSON object",
                json_valid=True,
                json_parse_mode=parse_mode,
                json_valid_strict=strict,
            )
        if "action_intent" not in parsed or parsed["action_intent"] is not None:
            return invalid(
                "fast_action_intent_forbidden",
                "Fast action_intent must be explicitly null",
                json_valid=True,
                json_parse_mode=parse_mode,
                json_valid_strict=strict,
            )
        try:
            model_output = FastModelOutput.model_validate_json(text)
        except Exception as error:
            return invalid(
                "schema_validation_error",
                _bounded_error(error),
                json_valid=True,
                json_parse_mode=parse_mode,
                json_valid_strict=strict,
            )
        try:
            decision = compile_fast_output(view, model_output)
        except Exception as error:
            return invalid(
                "canonical_validation_error",
                _bounded_error(error),
                json_valid=True,
                schema_valid=True,
                json_parse_mode=parse_mode,
                json_valid_strict=strict,
            )
        return self._result_v3(
            prompt,
            status=QwenMLXStatus.SUCCEEDED,
            elapsed_ms=_elapsed_ms(started),
            raw_output=raw_output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            adapter_result=FastAdapterResult(pins=view.pins, decision=decision),
            json_valid=True,
            schema_valid=True,
            canonical_valid=True,
            json_parse_mode=parse_mode,
            json_valid_strict=strict,
        )

    def _result_v3(
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
        json_parse_mode: JSONParseMode | None = None,
        json_valid_strict: bool = False,
        thinking_leak: bool = False,
    ) -> Phase03CGenerationResult:
        spec = self._model_spec
        attestation = self._attestation
        return Phase03CGenerationResult(
            metadata=Phase03CMetadata(
                status=status,
                model=spec.model,
                source_lineage=spec.source_lineage,
                model_revision=attestation.model_revision,
                source_revision=attestation.source_revision,
                checkpoint_fingerprint=attestation.checkpoint_fingerprint,
                tokenizer_fingerprint=attestation.tokenizer_fingerprint,
                chat_template_fingerprint=attestation.chat_template_fingerprint,
                quantization=spec.quantization,
                tuning=spec.tuning,
                run_label=spec.run_label,
                adapter_version=PHASE03C_ADAPTER_VERSION,
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
                json_parse_mode=json_parse_mode,
                json_valid_strict=json_valid_strict,
                thinking_leak=thinking_leak,
            ),
            adapter_result=adapter_result,
        )

    def render_chat_prompt(self, prompt: QwenPrompt) -> str:
        """Apply the loaded tokenizer's chat template with the spec's switch."""

        apply_chat_template = getattr(self._mlx_tokenizer, "apply_chat_template", None)
        if not callable(apply_chat_template):
            raise QwenMLXUnavailableError(
                "chat_template_unavailable",
                "the Qwen tokenizer does not expose apply_chat_template",
            )
        template_kwargs: dict[str, object] = {}
        if self._model_spec.enable_thinking is not None:
            template_kwargs["enable_thinking"] = self._model_spec.enable_thinking
        chat_prompt = apply_chat_template(
            [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            add_generation_prompt=True,
            tokenize=False,
            **template_kwargs,
        )
        if not isinstance(chat_prompt, str):
            raise QwenMLXUnavailableError(
                "chat_template_output_invalid",
                "the tokenizer chat template did not return text",
            )
        return chat_prompt

    def _run_generator(self, prompt: QwenPrompt) -> QwenGenerationText | str:
        if self._generator is not None:
            return self._generator(prompt.rendered)
        model, tokenizer, generate = self._load_mlx()
        chat_prompt = self.render_chat_prompt(prompt)
        try:
            mlx_core = importlib.import_module("mlx.core")
            seed = getattr(getattr(mlx_core, "random", None), "seed", None)
            if not callable(seed):
                raise AttributeError("mlx.core.random.seed is unavailable")
            seed(self._phase03b_decoding_profile.seed)
            sample_utils = importlib.import_module("mlx_lm.sample_utils")
            make_sampler = getattr(sample_utils, "make_sampler", None)
            if not callable(make_sampler):
                raise AttributeError("mlx_lm.sample_utils.make_sampler is unavailable")
            sampler = make_sampler(temp=self._phase03b_decoding_profile.temperature)
        except (ImportError, AttributeError) as error:
            raise QwenMLXUnavailableError(
                "mlx_greedy_sampler_unavailable",
                "MLX-LM greedy sampler or explicit seed is unavailable",
            ) from error
        generated = generate(
            model,
            tokenizer,
            prompt=chat_prompt,
            max_tokens=self._phase03b_decoding_profile.max_tokens,
            sampler=sampler,
            verbose=False,
        )
        if not isinstance(generated, str):
            raise QwenMLXUnavailableError(
                "mlx_lm_generation_type",
                "mlx_lm.generate did not return bounded text",
            )
        return QwenGenerationText(
            text=generated,
            input_tokens=self._count_tokens(chat_prompt),
            output_tokens=self._count_tokens(generated),
        )

    def prompt_token_count(self, view: FastModelView) -> int | None:
        """Count the fully templated prompt tokens with the real tokenizer."""

        self._load_mlx()
        return self._count_tokens(self.render_chat_prompt(self.build_prompt(view)))

    def _load_mlx(self) -> tuple[object, object, Callable[..., object]]:
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
        if self._model_path is None:
            raise QwenMLXUnavailableError(
                "local_model_path_required",
                "real Phase 03C evaluation requires an attested local model_path",
            )
        if self._mlx_model is None or self._mlx_tokenizer is None:
            if self._phase03b_adapter_path is None:
                loaded = cast(Callable[[str], object], load)(self._model_path)
            else:
                loaded = cast(Callable[..., object], load)(
                    self._model_path, adapter_path=self._phase03b_adapter_path
                )
            if not isinstance(loaded, tuple) or len(loaded) != 2:
                raise QwenMLXUnavailableError(
                    "mlx_lm_load_invalid",
                    "mlx_lm.load did not return a model/tokenizer pair",
                )
            self._mlx_model, self._mlx_tokenizer = loaded
        return (
            self._mlx_model,
            self._mlx_tokenizer,
            cast(Callable[..., object], generate),
        )

    def _count_tokens(self, text: str) -> int | None:
        encode = getattr(self._mlx_tokenizer, "encode", None)
        if not callable(encode):
            return None
        try:
            encoded = encode(text)
        except Exception:
            return None
        return len(encoded) if isinstance(encoded, (list, tuple)) else None


@dataclass(frozen=True, slots=True)
class ParseSignals:
    """Directly observable parse facts about one raw output; no repair."""

    json_parse_mode: JSONParseMode | None
    json_valid_strict: bool
    json_valid_tolerant: bool
    duplicate_key: bool
    duplicate_keys: tuple[str, ...]
    thinking_leak: bool
    parsed: dict[str, object] | None
    text: str | None


def analyze_raw_output(raw: str | None) -> ParseSignals:
    """Classify a raw output by strict/tolerant validity without editing it."""

    if raw is None:
        return ParseSignals(None, False, False, False, (), False, None, None)
    thinking_leak = THINKING_OPEN_TAG in raw
    text, mode = extract_fast_json(raw)
    strict = mode == "strict"
    try:
        parsed_any: object = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return ParseSignals(mode, False, False, False, (), thinking_leak, None, text)
    duplicate_keys = duplicate_json_keys(text)
    parsed = parsed_any if isinstance(parsed_any, dict) else None
    return ParseSignals(
        json_parse_mode=mode,
        json_valid_strict=strict and not duplicate_keys,
        json_valid_tolerant=True,
        duplicate_key=bool(duplicate_keys),
        duplicate_keys=duplicate_keys,
        thinking_leak=thinking_leak,
        parsed=parsed,
        text=text,
    )


@dataclass(frozen=True, slots=True)
class Phase03CRowMetrics:
    schema_valid: bool
    canonical_valid: bool
    dialogue_act_accuracy: bool
    reasoner_request_quality: bool
    action_candidate_quality: bool
    completion_candidate_quality: bool
    false_completion: bool
    stale_pin_violation: bool
    oracle_act_mismatch: bool
    policy_violation: bool
    pii_violation: bool
    disclosure_violation: bool
    unsupported_response_violation: bool
    authority_violation: bool
    response_grounded: bool
    end_to_end_valid: bool
    json_parse_mode: JSONParseMode | None
    json_valid_strict: bool
    json_valid_tolerant: bool
    duplicate_key: bool
    thinking_leak: bool
    status: str = "succeeded"
    failure_category: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class Phase03CExecutedRow:
    metrics: Phase03CRowMetrics
    raw_output: str | None


def oracle_expected_output(example: Phase03BExample) -> FastModelOutput:
    """The deterministic oracle's Fast target for the example's observation."""

    oracle = ScriptedOracleConsumer(offer_policy=offer_compliance_violations).decide(
        example.public_observation
    )
    return FastModelOutput.model_validate_json(
        _canonical_json(proposed_fast_target(oracle.action.value))
    )


def _oracle_act_mismatch(example: Phase03BExample, decision: FastTurnDecision) -> bool:
    return decision.dialogue_act != oracle_expected_output(example).dialogue_act


def evaluate_fast_result_v3(
    example: Phase03BExample,
    result: FastAdapterResult,
    *,
    signals: ParseSignals,
) -> Phase03CRowMetrics:
    """Score one canonical result; ``policy_violation`` is the safety composite."""

    decision = result.decision
    expected = example.target
    schema_valid = isinstance(result, FastAdapterResult) and _schema_valid(decision)
    stale = detect_stale_pins(result, example.view)
    authority = detect_authority_violation(decision)
    pii = detect_pii(decision.response_text)
    disclosure = detect_disallowed_disclosure(
        decision.response_text, example.public_observation
    )
    unsupported = detect_unsupported_response_facts(
        decision.response_text, example.public_observation
    ) or bool(decision.fact_updates)
    dialogue_ok = decision.dialogue_act == expected.dialogue_act
    reasoner_ok = decision.reasoner_request == expected.reasoner_request
    action_ok = decision.action_intent is None and dialogue_ok
    structured_completion_ok = (
        decision.completion_claim.status == "not_done"
        and not decision.completion_claim.evidence_message_ids
    )
    response_completion = detect_false_completion(decision.response_text)
    completion_ok = structured_completion_ok and not response_completion
    false_completion = not completion_ok
    oracle_mismatch = _oracle_act_mismatch(example, decision)
    policy = disclosure or authority or false_completion or stale
    grounded = not (pii or disclosure or unsupported)
    end_to_end = all(
        (
            schema_valid,
            not stale,
            dialogue_ok,
            reasoner_ok,
            action_ok,
            completion_ok,
            grounded,
            not oracle_mismatch,
            not authority,
            not signals.thinking_leak,
            not signals.duplicate_key,
        )
    )
    return Phase03CRowMetrics(
        schema_valid=schema_valid,
        canonical_valid=schema_valid and not stale and not authority,
        dialogue_act_accuracy=dialogue_ok,
        reasoner_request_quality=reasoner_ok,
        action_candidate_quality=action_ok,
        completion_candidate_quality=completion_ok,
        false_completion=false_completion,
        stale_pin_violation=stale,
        oracle_act_mismatch=oracle_mismatch,
        policy_violation=policy,
        pii_violation=pii,
        disclosure_violation=disclosure,
        unsupported_response_violation=unsupported,
        authority_violation=authority,
        response_grounded=grounded,
        end_to_end_valid=end_to_end,
        json_parse_mode=signals.json_parse_mode,
        json_valid_strict=signals.json_valid_strict,
        json_valid_tolerant=signals.json_valid_tolerant,
        duplicate_key=signals.duplicate_key,
        thinking_leak=signals.thinking_leak,
    )


def _partial_signals_v3(
    example: Phase03BExample, parsed: dict[str, object] | None
) -> tuple[bool, bool, bool, bool]:
    """Recover authority, false completion, dialogue accuracy, oracle mismatch."""

    if parsed is None:
        return False, False, False, False
    authority = parsed.get("action_intent") is not None
    claim = parsed.get("completion_claim")
    structured_false_completion = False
    if isinstance(claim, dict):
        status = claim.get("status")
        structured_false_completion = (
            status is not None and status != "not_done"
        ) or bool(claim.get("evidence_message_ids"))
        authority = authority or structured_false_completion
    dialogue_accuracy = False
    oracle_mismatch = False
    raw_dialogue_act = parsed.get("dialogue_act")
    if isinstance(raw_dialogue_act, str):
        try:
            dialogue_act = DialogueAct(raw_dialogue_act)
        except ValueError:
            pass
        else:
            dialogue_accuracy = dialogue_act == example.target.dialogue_act
            oracle_mismatch = (
                dialogue_act != oracle_expected_output(example).dialogue_act
            )
    return authority, structured_false_completion, dialogue_accuracy, oracle_mismatch


def _invalid_result_metrics_v3(
    example: Phase03BExample,
    *,
    status: str,
    failure_category: str,
    raw_output: str | None,
    signals: ParseSignals,
    latency_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> Phase03CRowMetrics:
    raw = raw_output or ""
    scored_text = signals.text if signals.text is not None else raw
    pii = detect_pii(raw)
    disclosure = detect_disallowed_disclosure(raw, example.public_observation)
    unsupported = detect_unsupported_response_facts(
        scored_text, example.public_observation
    ) or _raw_fact_updates_violation(scored_text if raw_output is not None else None)
    authority, _, dialogue_accuracy, oracle_mismatch = _partial_signals_v3(
        example, signals.parsed
    )
    false_completion = detect_false_completion(
        scored_text if raw_output is not None else None
    )
    return Phase03CRowMetrics(
        schema_valid=False,
        canonical_valid=False,
        dialogue_act_accuracy=dialogue_accuracy,
        reasoner_request_quality=False,
        action_candidate_quality=False,
        completion_candidate_quality=False,
        false_completion=false_completion,
        stale_pin_violation=False,
        oracle_act_mismatch=oracle_mismatch,
        policy_violation=disclosure or authority or false_completion,
        pii_violation=pii,
        disclosure_violation=disclosure,
        unsupported_response_violation=unsupported,
        authority_violation=authority,
        response_grounded=False,
        end_to_end_valid=False,
        json_parse_mode=signals.json_parse_mode,
        json_valid_strict=signals.json_valid_strict,
        json_valid_tolerant=signals.json_valid_tolerant,
        duplicate_key=signals.duplicate_key,
        thinking_leak=signals.thinking_leak,
        status=status,
        failure_category=failure_category,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _status_text(value: object, default: str = "unknown") -> str:
    candidate = getattr(value, "value", value)
    return candidate if isinstance(candidate, str) else default


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def run_phase03c_row(
    example: Phase03BExample, adapter: Phase03CQwenAdapter
) -> Phase03CExecutedRow:
    try:
        generated = adapter.generate(example.view)
    except Exception:
        return Phase03CExecutedRow(
            metrics=_invalid_result_metrics_v3(
                example,
                status="error",
                failure_category="generation_error",
                raw_output=None,
                signals=analyze_raw_output(None),
            ),
            raw_output=None,
        )
    metadata = generated.metadata
    raw_output = metadata.raw_output
    bounded_raw = raw_output[:MAX_RAW_OUTPUT_CHARS] if raw_output is not None else None
    signals = analyze_raw_output(bounded_raw)
    status = _status_text(generated.status)
    if generated.adapter_result is not None and not signals.thinking_leak:
        metrics = evaluate_fast_result_v3(
            example, generated.adapter_result, signals=signals
        )
        return Phase03CExecutedRow(
            metrics=replace(
                metrics,
                status=status,
                latency_ms=metadata.latency_ms,
                input_tokens=metadata.input_tokens,
                output_tokens=metadata.output_tokens,
            ),
            raw_output=bounded_raw,
        )
    failure_category = metadata.error_code or status
    if signals.thinking_leak:
        failure_category = "thinking_leak"
        status = "invalid_output"
    return Phase03CExecutedRow(
        metrics=_invalid_result_metrics_v3(
            example,
            status=status,
            failure_category=failure_category,
            raw_output=bounded_raw,
            signals=signals,
            latency_ms=_int_or_none(metadata.latency_ms),
            input_tokens=_int_or_none(metadata.input_tokens),
            output_tokens=_int_or_none(metadata.output_tokens),
        ),
        raw_output=bounded_raw,
    )


def run_phase03c_arm(
    examples: Sequence[Phase03BExample], adapter: Phase03CQwenAdapter
) -> tuple[Phase03CExecutedRow, ...]:
    if len(examples) != 6 or any(item.split != "development" for item in examples):
        raise ValueError("Phase 03C arm execution requires six development examples")
    return tuple(run_phase03c_row(example, adapter) for example in examples)


def development_examples() -> tuple[Phase03BExample, ...]:
    return tuple(
        item for item in build_phase03b_examples() if item.split == "development"
    )


def freeze_phase03c_controls(
    examples: Sequence[Phase03BExample],
    *,
    manifest_fingerprint: str,
    base_attestation: QwenCheckpointAttestation,
) -> Phase03BControls:
    """Freeze v3 prompt, input, schema, and decoding controls for one arm."""

    if len(examples) != 6 or any(item.split != "development" for item in examples):
        raise ValueError("Phase 03C controls require exactly six development examples")
    prompt_adapter = Phase03CQwenAdapter(generator=lambda _: "{}")
    return Phase03BControls(
        manifest_fingerprint=manifest_fingerprint,
        prompt_fingerprints=tuple(
            prompt_adapter.build_prompt(item.view).fingerprint for item in examples
        ),
        input_fingerprints=tuple(item.input_fingerprint for item in examples),
        schema_fingerprint=_fingerprint(FastModelOutput.model_json_schema()),
        compiler_version=PHASE03C_COMPILER_VERSION,
        policy_version=PHASE03C_POLICY_VERSION,
        base_attestation=base_attestation,
        decoding_profile=QwenDecodingProfile(),
    )


# --- Offline parser erratum over the stored Phase 03B raw outputs -----------


def _schema_failures(text: str) -> tuple[str, ...]:
    try:
        FastModelOutput.model_validate_json(text)
    except ValidationError as error:
        return tuple(
            sorted(
                {
                    ".".join(str(part) for part in item["loc"]) or "<root>"
                    for item in error.errors()
                }
            )
        )
    return ()


def _erratum_episode(
    example: Phase03BExample, episode: dict[str, object]
) -> dict[str, object]:
    raw_output = episode.get("raw_output")
    if not isinstance(raw_output, str):
        raise ValueError("Phase 03B episode raw_output must be text")
    metrics = episode.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("Phase 03B episode metrics must be an object")
    signals = analyze_raw_output(raw_output)
    schema_failures: tuple[str, ...] = ()
    schema_valid = False
    if signals.json_valid_tolerant and not signals.duplicate_key and signals.text:
        schema_failures = _schema_failures(signals.text)
        schema_valid = not schema_failures
    parsed = signals.parsed or {}
    reasoner = parsed.get("reasoner_request")
    reason_code = reasoner.get("reason_code") if isinstance(reasoner, dict) else None
    raw_act = parsed.get("dialogue_act")
    expected_act = oracle_expected_output(example).dialogue_act
    _, _, dialogue_accuracy, oracle_mismatch = _partial_signals_v3(
        example, signals.parsed
    )
    return {
        "scenario_id": example.scenario_id,
        "family_id": example.family_id,
        "input_fingerprint": example.input_fingerprint,
        "raw_output_sha256": hashlib.sha256(raw_output.encode("utf-8")).hexdigest(),
        "raw_output_chars": len(raw_output),
        "phase03b_status": metrics.get("status"),
        "phase03b_failure_category": metrics.get("failure_category"),
        "json_parse_mode": signals.json_parse_mode,
        "json_valid_strict": signals.json_valid_strict,
        "json_valid_tolerant": signals.json_valid_tolerant,
        "duplicate_key": signals.duplicate_key,
        "duplicate_keys": list(signals.duplicate_keys),
        "thinking_leak": signals.thinking_leak,
        "schema_valid": schema_valid,
        "schema_failing_fields": list(schema_failures),
        "reason_code_chars": len(reason_code) if isinstance(reason_code, str) else None,
        "dialogue_act": raw_act if isinstance(raw_act, str) else None,
        "oracle_dialogue_act": str(expected_act),
        "dialogue_act_accuracy": dialogue_accuracy,
        "oracle_act_mismatch": oracle_mismatch,
    }


def derive_parser_erratum(
    source_path: Path,
    *,
    examples: Sequence[Phase03BExample] | None = None,
) -> dict[str, object]:
    """Re-score stored 03B raw outputs with the dual parser; zero model calls."""

    source = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(source, dict):
        raise ValueError("Phase 03B result must be a JSON object")
    if source.get("schema_version") != "phase-03b-qwen-smoke-result-v2":
        raise ValueError("parser erratum requires a phase-03b-qwen-smoke-result-v2")
    arm = source.get("arm")
    if arm not in {"A", "B"}:
        raise ValueError("Phase 03B result arm must be A or B")
    episodes = source.get("episodes")
    if not isinstance(episodes, list) or len(episodes) != 6:
        raise ValueError("Phase 03B result must contain six episodes")
    development = tuple(examples) if examples is not None else development_examples()
    if len(development) != 6:
        raise ValueError("parser erratum requires six development examples")
    rows: list[dict[str, object]] = []
    for example, episode in zip(development, episodes, strict=True):
        if not isinstance(episode, dict):
            raise ValueError("Phase 03B episode must be an object")
        if episode.get("scenario_id") != example.scenario_id:
            raise ValueError("Phase 03B episode order differs from the examples")
        if episode.get("input_fingerprint") != example.input_fingerprint:
            raise ValueError("Phase 03B episode input fingerprint drifted")
        rows.append(_erratum_episode(example, episode))
    counted = (
        "json_valid_strict",
        "json_valid_tolerant",
        "duplicate_key",
        "thinking_leak",
        "schema_valid",
        "dialogue_act_accuracy",
        "oracle_act_mismatch",
    )
    aggregate: dict[str, object] = {
        "episodes": len(rows),
        **{name: sum(bool(row[name]) for row in rows) for name in counted},
        "parse_mode_counts": _counts(str(row["json_parse_mode"]) for row in rows),
        "duplicate_key_counts": _counts(
            key for row in rows for key in cast(list[str], row["duplicate_keys"])
        ),
        "schema_failing_field_counts": _counts(
            field
            for row in rows
            for field in cast(list[str], row["schema_failing_fields"])
        ),
        "dialogue_act_counts": _counts(
            str(row["dialogue_act"]) for row in rows if row["dialogue_act"]
        ),
        "reason_code_over_256": sum(
            1
            for row in rows
            if isinstance(row["reason_code_chars"], int)
            and row["reason_code_chars"] > 256
        ),
    }
    payload: dict[str, object] = {
        "schema_version": PHASE03C_ERRATUM_SCHEMA_VERSION,
        "description": (
            "Offline re-score of stored Phase 03B raw outputs with the Phase 03C "
            "strict/tolerant parser. Descriptive only; the Phase 03B decision "
            "text is not rewritten."
        ),
        "source_path": str(source_path.relative_to(ROOT))
        if source_path.is_relative_to(ROOT)
        else str(source_path),
        "source_sha256": _sha256_file(source_path),
        "source_schema_version": source["schema_version"],
        "source_result_content_fingerprint": source.get("result_content_fingerprint"),
        "source_arm": arm,
        "model_call_count": 0,
        "new_external_dispatch_count": 0,
        "evaluator_source_fingerprint": PHASE03C_EVALUATOR_SOURCE_FINGERPRINT,
        "compiler_version": PHASE03C_COMPILER_VERSION,
        "episodes": rows,
        "aggregate": aggregate,
    }
    payload["result_content_fingerprint"] = _fingerprint(payload)
    return payload


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def erratum_output_path(arm: str, root: Path = ROOT) -> Path:
    return (
        root
        / "data/experiments/phase-03c/errata"
        / (f"phase-03b-arm-{arm}-parser-erratum.json")
    )


def write_parser_errata(root: Path = ROOT) -> tuple[Path, ...]:
    examples = development_examples()
    written: list[Path] = []
    for arm, relative in PHASE03B_ARM_SOURCES.items():
        source = root / relative.relative_to(ROOT)
        payload = derive_parser_erratum(source, examples=examples)
        target = erratum_output_path(arm, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(target)
    return tuple(written)


def check_parser_errata(root: Path = ROOT) -> tuple[str, ...]:
    """Return drift messages; an empty tuple means the errata are reproducible."""

    problems: list[str] = []
    examples = development_examples()
    for arm, relative in PHASE03B_ARM_SOURCES.items():
        target = erratum_output_path(arm, root)
        if not target.exists():
            problems.append(f"missing:{target.relative_to(root)}")
            continue
        stored = json.loads(target.read_text(encoding="utf-8"))
        expected = derive_parser_erratum(
            root / relative.relative_to(ROOT), examples=examples
        )
        if not isinstance(stored, dict):
            problems.append(f"invalid:{target.relative_to(root)}")
            continue
        # The evaluator fingerprint changes with any edit to this file; the
        # erratum content is compared without it so the check stays honest
        # about *numbers* rather than bytes.
        for payload in (stored, expected):
            payload.pop("evaluator_source_fingerprint", None)
            payload.pop("result_content_fingerprint", None)
        if stored != expected:
            problems.append(f"drift:{target.relative_to(root)}")
    return tuple(problems)


def row_metrics_dict(row: Phase03CExecutedRow) -> dict[str, object]:
    return asdict(row.metrics)


SMOKE_RESULT_FILES: Final[dict[str, str]] = {
    "8b": "arm-a-untuned-8b-v3.json",
    "4b": "arm-a-untuned-4b-v3.json",
}


def check_smoke_results(root: Path = ROOT) -> tuple[str, ...]:
    """Verify committed Stage 0 smoke results are self-consistent, not passing.

    The pass bar is a review input; this check only proves the files were
    produced by this evaluator over the frozen six-example manifest with
    real local files, and that their aggregates match their episodes.
    """

    from proxyloop_contracts import canonical_fingerprint

    problems: list[str] = []
    examples = development_examples()
    prompt_adapter = Phase03CQwenAdapter(generator=lambda _: "{}")
    expected_prompts = [
        prompt_adapter.build_prompt(item.view).fingerprint for item in examples
    ]
    expected_inputs = [item.input_fingerprint for item in examples]
    results_dir = root / "data/experiments/phase-03c/results"
    if results_dir.is_dir():
        # Diagnostics belong under ``diagnostics/``; nothing else may sit next
        # to the canonical rows and look like a third result.
        for stray in sorted(results_dir.iterdir()):
            if stray.name not in SMOKE_RESULT_FILES.values():
                problems.append(f"unexpected_result:{stray.relative_to(root)}")
    for model, name in SMOKE_RESULT_FILES.items():
        path = results_dir / name
        label = str(path.relative_to(root))
        spec = QWEN3_8B_BF16_SPEC if model == "8b" else QWEN3_4B_4BIT_SPEC
        if not path.exists():
            problems.append(f"missing:{label}")
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            problems.append(f"invalid:{label}")
            continue
        unsigned = {
            key: value
            for key, value in result.items()
            if key != "result_content_fingerprint"
        }
        if result.get("result_content_fingerprint") != canonical_fingerprint(unsigned):
            problems.append(f"content_fingerprint:{label}")
        if result.get("schema_version") != "phase-03c-qwen-smoke-result-v1":
            problems.append(f"schema_version:{label}")
        if result.get("model") != model or result.get("arm") != "A":
            problems.append(f"model_or_arm:{label}")
        if result.get("result_role") != "canonical" or result.get("execution") != {
            "mode": "local_mlx",
            "checkpoint_attestation": "observed_local_files",
        }:
            problems.append(f"execution_provenance:{label}")
        if result.get("slow_call_count") != 0 or result.get("hosted_call_count") != 0:
            problems.append(f"external_calls:{label}")
        controls = result.get("controls")
        if not isinstance(controls, dict):
            problems.append(f"controls:{label}")
            continue
        if controls.get("compiler_version") != PHASE03C_COMPILER_VERSION:
            problems.append(f"compiler_version:{label}")
        base = controls.get("base_checkpoint")
        expected_base = {
            "model": spec.model,
            "source_lineage": spec.source_lineage,
            "quantization": spec.quantization,
            "run_label": spec.run_label,
            "license": spec.license,
            "enable_thinking": spec.enable_thinking,
            **asdict(spec.attestation),
        }
        if base != expected_base:
            problems.append(f"base_checkpoint:{label}")
        if controls.get("prompt_fingerprints") != expected_prompts:
            problems.append(f"prompt_fingerprints:{label}")
        if controls.get("input_fingerprints") != expected_inputs:
            problems.append(f"input_fingerprints:{label}")
        if controls.get("schema_fingerprint") != _fingerprint(
            FastModelOutput.model_json_schema()
        ):
            problems.append(f"schema_fingerprint:{label}")
        episodes = result.get("episodes")
        aggregate = result.get("aggregate")
        if (
            not isinstance(episodes, list)
            or len(episodes) != 6
            or not isinstance(aggregate, dict)
        ):
            problems.append(f"episodes:{label}")
            continue
        metrics = aggregate.get("metrics")
        if not isinstance(metrics, dict):
            problems.append(f"aggregate_metrics:{label}")
            continue
        episode_metrics = [
            episode["metrics"]
            for episode in episodes
            if isinstance(episode, dict) and isinstance(episode.get("metrics"), dict)
        ]
        for field, entry in metrics.items():
            recomputed = sum(bool(item.get(field)) for item in episode_metrics)
            if not isinstance(entry, dict) or entry.get("count") != recomputed:
                problems.append(f"aggregate_count:{field}:{label}")
        for example, episode in zip(examples, episodes, strict=True):
            if not isinstance(episode, dict):
                continue
            raw = episode.get("raw_output")
            digest = (
                hashlib.sha256(raw.encode("utf-8")).hexdigest()
                if isinstance(raw, str)
                else None
            )
            if episode.get("raw_output_sha256") != digest:
                problems.append(f"raw_output_sha256:{label}")
            if episode.get("scenario_id") != example.scenario_id:
                problems.append(f"scenario_order:{label}")
    return tuple(problems)


__all__ = [
    "ERRATA_DIR",
    "PHASE03B_ARM_SOURCES",
    "PHASE03C_ADAPTER_VERSION",
    "PHASE03C_COMPILER_VERSION",
    "PHASE03C_DIR",
    "PHASE03C_ERRATUM_SCHEMA_VERSION",
    "PHASE03C_EVALUATOR_SOURCE_FINGERPRINT",
    "PHASE03C_POLICY_VERSION",
    "PROMPT_TOKEN_LIMIT",
    "REASON_CODE_LINE",
    "RESULTS_DIR",
    "SMOKE_RESULT_FILES",
    "ParseSignals",
    "Phase03CExecutedRow",
    "Phase03CGenerationResult",
    "Phase03CMetadata",
    "Phase03CQwenAdapter",
    "Phase03CRowMetrics",
    "analyze_raw_output",
    "check_parser_errata",
    "check_smoke_results",
    "derive_parser_erratum",
    "development_examples",
    "erratum_output_path",
    "evaluate_fast_result_v3",
    "freeze_phase03c_controls",
    "oracle_expected_output",
    "row_metrics_dict",
    "run_phase03c_arm",
    "run_phase03c_row",
    "write_parser_errata",
]
