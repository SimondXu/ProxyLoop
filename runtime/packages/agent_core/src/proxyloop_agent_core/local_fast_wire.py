"""``local-fast-wire-v1``: the one owner of the local Fast gateway wire.

Both sides import this module: the runtime HTTP adapter encodes requests and
decodes responses; the ml gateway decodes requests and encodes responses.
Standard-library JSON only; the golden fixtures under
``tests/fixtures/local-fast-wire/`` pin the bytes.

Every body is canonical JSON (sorted keys, no whitespace, UTF-8). Decoding is
strict: exact key sets, no duplicate keys, no NaN, and allow-listed status and
detail codes. A ``WireError`` carries one allow-listed code and no content.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, cast

from proxyloop_contracts import FastModelView

from .observation import SafeObservation, SafeOffer

LOCAL_FAST_WIRE_VERSION: Final = "local-fast-wire-v1"
IDENTITY_PATH: Final = "/v1/identity"
DECIDE_PATH: Final = "/v1/fast/decide"
MAX_REQUEST_BYTES: Final = 256 * 1024
MAX_RESPONSE_BYTES: Final = 64 * 1024

GatewayBackend = Literal["distilled", "untuned"]
BACKEND_LABELS: Final[dict[str, str]] = {
    "distilled": "local opt-in candidate",
    "untuned": "untuned local baseline",
}
DecideStatus = Literal["succeeded", "invalid_output", "unrenderable"]
DECIDE_STATUSES: Final = frozenset({"succeeded", "invalid_output", "unrenderable"})
# The gateway's detail for an ``invalid_output`` answer: every INVALID_OUTPUT
# code the 03C generation path returns, plus the gateway's catch-all.
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
        "invalid_output",
    }
)
UNRENDERABLE_DETAIL_CODES: Final = frozenset(
    {"no_provider_event", "trained_view_invalid", "prompt_render_refused"}
)
# Why a response body is not ``local-fast-wire-v1``.
WIRE_ERROR_CODES: Final = frozenset(
    {
        "body_not_json",
        "body_duplicate_key",
        "body_shape_invalid",
        "wire_version_mismatch",
        "detail_code_unknown",
        "identity_fingerprint_invalid",
    }
)
# What the runtime client itself finds wrong with an answer.
CLIENT_DETAIL_CODES: Final = frozenset(
    {
        "http_status_unexpected",
        "http_response_invalid",
        "response_too_large",
        "output_schema_invalid",
        "fact_updates_not_empty",
        "output_compile_refused",
        "observation_required",
    }
)
FAST_OUTPUT_KEYS: Final = frozenset(
    {
        "dialogue_act",
        "fact_updates",
        "reasoner_request",
        "completion_claim",
        "response_text",
        "action_intent",
    }
)
_REQUEST_KEYS: Final = frozenset({"wire_version", "view", "observation"})
_RESPONSE_KEYS: Final = frozenset(
    {"wire_version", "identity_fingerprint", "status", "output", "detail_code", "usage"}
)
_USAGE_KEYS: Final = frozenset({"input_tokens", "output_tokens", "generation_ms"})
_IDENTITY_TEXT_KEYS: Final = (
    "base_model",
    "base_revision",
    "prompt_version",
    "compiler_version",
    "observation_renderer_version",
    "trained_view_version",
    "decoding_fingerprint",
)
_IDENTITY_KEYS: Final = frozenset(
    {
        "wire_version",
        "backend",
        "label",
        "adapter_fingerprint",
        "mlx_versions",
        "identity_fingerprint",
        *_IDENTITY_TEXT_KEYS,
    }
)
_OBSERVATION_KEYS: Final = frozenset(
    {
        "schema_version",
        "case_id",
        "case_revision",
        "constraint_set_revision",
        "current_monthly_total_minor",
        "target_monthly_total_minor",
        "currency",
        "required_features",
        "forbidden_changes",
        "allowed_disclosures",
        "provider_id",
        "provider_message",
        "offers",
        "requested_disclosures",
        "needs_clarification",
        "transfer_available",
        "approval_current",
        "observed_at",
        "confirmation_evidence_available",
    }
)
_OFFER_KEYS: Final = frozenset(
    {
        "offer_id",
        "provider_id",
        "monthly_price_minor",
        "total_cost_12_months_minor",
        "currency",
        "features",
        "fees_minor",
        "term_months",
        "applied_changes",
        "expires_at",
    }
)
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
# An identity field: printable ASCII without spaces, at most 128 characters.
_TOKEN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,127}")


class WireError(ValueError):
    """A body that is not valid ``local-fast-wire-v1``; content-free."""

    def __init__(self, code: str) -> None:
        if code not in WIRE_ERROR_CODES:
            raise ValueError("wire error code is not allow-listed")
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DecideResponse:
    identity_fingerprint: str
    status: DecideStatus
    output: dict[str, Any] | None
    detail_code: str | None
    input_tokens: int
    output_tokens: int
    generation_ms: int


@dataclass(frozen=True, slots=True)
class GatewayIdentity:
    backend: GatewayBackend
    label: str
    base_model: str
    base_revision: str
    adapter_fingerprint: str | None
    prompt_version: str
    compiler_version: str
    observation_renderer_version: str
    trained_view_version: str
    decoding_fingerprint: str
    mlx_versions: tuple[tuple[str, str | None], ...]
    identity_fingerprint: str


def encode_json(value: object) -> bytes:
    """The canonical wire encoding."""

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(encode_json(value)).hexdigest()


def encode_decide_request(view: FastModelView, observation: SafeObservation) -> bytes:
    return encode_json(
        {
            "wire_version": LOCAL_FAST_WIRE_VERSION,
            "view": view.model_dump(mode="json"),
            "observation": observation.to_dict(),
        }
    )


def decode_decide_request(body: bytes) -> tuple[FastModelView, SafeObservation]:
    """Gateway side; the view is re-validated by the strict contract."""

    data = _object(_load(body), _REQUEST_KEYS)
    _check_version(data)
    try:
        # JSON mode: the strict contracts refuse enum and datetime strings in
        # python mode. A pydantic ValidationError is a ValueError.
        view = FastModelView.model_validate_json(json.dumps(data["view"]))
    except ValueError as error:
        raise WireError("body_shape_invalid") from error
    return view, observation_from_dict(data["observation"])


def observation_from_dict(value: object) -> SafeObservation:
    """Inverse of ``SafeObservation.to_dict``; refuses non-canonical input."""

    data = _object(value, _OBSERVATION_KEYS)
    offers = data["offers"]
    if not isinstance(offers, list):
        raise WireError("body_shape_invalid")
    try:
        observation = SafeObservation(
            schema_version=data["schema_version"],
            case_id=data["case_id"],
            case_revision=data["case_revision"],
            constraint_set_revision=data["constraint_set_revision"],
            current_monthly_total_minor=data["current_monthly_total_minor"],
            target_monthly_total_minor=data["target_monthly_total_minor"],
            currency=data["currency"],
            required_features=_texts(data["required_features"]),
            forbidden_changes=_texts(data["forbidden_changes"]),
            allowed_disclosures=_texts(data["allowed_disclosures"]),
            provider_id=data["provider_id"],
            provider_message=data["provider_message"],
            offers=tuple(_offer(item) for item in offers),
            requested_disclosures=_texts(data["requested_disclosures"]),
            needs_clarification=data["needs_clarification"],
            transfer_available=data["transfer_available"],
            approval_current=data["approval_current"],
            observed_at=_utc(data["observed_at"]),
            confirmation_evidence_available=data["confirmation_evidence_available"],
        )
    except (TypeError, ValueError, AttributeError) as error:
        if isinstance(error, WireError):
            raise
        raise WireError("body_shape_invalid") from error
    if observation.to_dict() != data:
        raise WireError("body_shape_invalid")
    return observation


def encode_decide_response(response: DecideResponse) -> bytes:
    """Gateway side."""

    return encode_json(
        {
            "wire_version": LOCAL_FAST_WIRE_VERSION,
            "identity_fingerprint": response.identity_fingerprint,
            "status": response.status,
            "output": response.output,
            "detail_code": response.detail_code,
            "usage": {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "generation_ms": response.generation_ms,
            },
        }
    )


def decode_decide_response(body: bytes) -> DecideResponse:
    """Runtime side; raises ``WireError``."""

    data = _object(_load(body), _RESPONSE_KEYS)
    _check_version(data)
    fingerprint = data["identity_fingerprint"]
    status = data["status"]
    output = data["output"]
    detail = data["detail_code"]
    # Every allow-list test is guarded: an unhashable value must be a
    # WireError, never a TypeError that escapes the Fast call (review I1).
    if (
        not _is_sha256(fingerprint)
        or not isinstance(status, str)
        or status not in DECIDE_STATUSES
    ):
        raise WireError("body_shape_invalid")
    if status == "succeeded":
        if detail is not None:
            raise WireError("body_shape_invalid")
        _object(output, FAST_OUTPUT_KEYS)
    else:
        if output is not None:
            raise WireError("body_shape_invalid")
        allowed = (
            INVALID_OUTPUT_DETAIL_CODES
            if status == "invalid_output"
            else UNRENDERABLE_DETAIL_CODES
        )
        if not isinstance(detail, str):
            raise WireError("body_shape_invalid")
        if detail not in allowed:
            raise WireError("detail_code_unknown")
    usage = _object(data["usage"], _USAGE_KEYS)
    counts = [usage[key] for key in ("input_tokens", "output_tokens", "generation_ms")]
    if not all(type(count) is int and count >= 0 for count in counts):
        raise WireError("body_shape_invalid")
    return DecideResponse(
        identity_fingerprint=fingerprint,
        status=cast(DecideStatus, status),
        output=output,
        detail_code=detail,
        input_tokens=counts[0],
        output_tokens=counts[1],
        generation_ms=counts[2],
    )


def decode_identity(body: bytes) -> GatewayIdentity:
    """Runtime side: the ``/v1/identity`` body, its fingerprint recomputed.

    ``identity_fingerprint`` is the canonical SHA-256 of every other field.
    """

    data = _object(_load(body), _IDENTITY_KEYS)
    _check_version(data)
    backend = data["backend"]
    if (
        not isinstance(backend, str)
        or backend not in BACKEND_LABELS
        or data["label"] != BACKEND_LABELS[backend]
    ):
        raise WireError("body_shape_invalid")
    # Tokens, so a composed trace identity stays within ExternalRef (M2).
    if not all(_is_token(data[key]) for key in _IDENTITY_TEXT_KEYS):
        raise WireError("body_shape_invalid")
    adapter = data["adapter_fingerprint"]
    # Only the distilled backend serves an adapter.
    if not (_is_token(adapter) if backend == "distilled" else adapter is None):
        raise WireError("body_shape_invalid")
    versions = data["mlx_versions"]
    if not isinstance(versions, dict) or not all(
        _is_token(name) and (value is None or _is_token(value))
        for name, value in versions.items()
    ):
        raise WireError("body_shape_invalid")
    fingerprint = data["identity_fingerprint"]
    payload = {
        key: value for key, value in data.items() if key != "identity_fingerprint"
    }
    if not _is_sha256(fingerprint) or canonical_sha256(payload) != fingerprint:
        raise WireError("identity_fingerprint_invalid")
    return GatewayIdentity(
        backend=cast(GatewayBackend, backend),
        label=data["label"],
        base_model=data["base_model"],
        base_revision=data["base_revision"],
        adapter_fingerprint=adapter,
        prompt_version=data["prompt_version"],
        compiler_version=data["compiler_version"],
        observation_renderer_version=data["observation_renderer_version"],
        trained_view_version=data["trained_view_version"],
        decoding_fingerprint=data["decoding_fingerprint"],
        mlx_versions=tuple(sorted(versions.items())),
        identity_fingerprint=fingerprint,
    )


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WireError("body_duplicate_key")
        result[key] = value
    return result


def _reject_constant(_: str) -> object:
    raise WireError("body_not_json")


def _load(body: bytes) -> object:
    try:
        return json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except WireError:
        raise
    except (ValueError, RecursionError) as error:
        # ValueError covers JSONDecodeError, UnicodeDecodeError, and an integer
        # past the int conversion digit limit (review I1).
        raise WireError("body_not_json") from error


def _object(value: object, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise WireError("body_shape_invalid")
    return value


def _check_version(data: dict[str, Any]) -> None:
    if data["wire_version"] != LOCAL_FAST_WIRE_VERSION:
        raise WireError("wire_version_mismatch")


def _is_token(value: object) -> bool:
    return isinstance(value, str) and _TOKEN.fullmatch(value) is not None


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _texts(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WireError("body_shape_invalid")
    return tuple(value)


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise WireError("body_shape_invalid")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _offer(value: object) -> SafeOffer:
    data = _object(value, _OFFER_KEYS)
    return SafeOffer(
        offer_id=data["offer_id"],
        provider_id=data["provider_id"],
        monthly_price_minor=data["monthly_price_minor"],
        total_cost_12_months_minor=data["total_cost_12_months_minor"],
        currency=data["currency"],
        features=_texts(data["features"]),
        fees_minor=data["fees_minor"],
        term_months=data["term_months"],
        applied_changes=_texts(data["applied_changes"]),
        expires_at=_utc(data["expires_at"]),
    )


__all__ = [
    "BACKEND_LABELS",
    "CLIENT_DETAIL_CODES",
    "DECIDE_PATH",
    "DECIDE_STATUSES",
    "FAST_OUTPUT_KEYS",
    "IDENTITY_PATH",
    "INVALID_OUTPUT_DETAIL_CODES",
    "LOCAL_FAST_WIRE_VERSION",
    "MAX_REQUEST_BYTES",
    "MAX_RESPONSE_BYTES",
    "UNRENDERABLE_DETAIL_CODES",
    "WIRE_ERROR_CODES",
    "DecideResponse",
    "DecideStatus",
    "GatewayBackend",
    "GatewayIdentity",
    "WireError",
    "canonical_sha256",
    "decode_decide_request",
    "decode_decide_response",
    "decode_identity",
    "encode_decide_request",
    "encode_decide_response",
    "encode_json",
    "observation_from_dict",
]
