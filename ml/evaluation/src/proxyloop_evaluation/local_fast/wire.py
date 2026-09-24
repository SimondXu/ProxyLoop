"""Gateway side of ``local-fast-wire-v1`` (stdlib JSON only).

Interim owner: the frozen PR-9 design puts the one wire module in
``agent_core/local_fast_wire.py`` (PR-9a), which this ml-only change may not
touch.  Until 9a lands, the gateway decodes requests here against the frozen
endpoint table; when 9a merges, the gateway must switch to that module and
the golden fixtures must pin both sides, so the wire keeps a single owner.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Final

from proxyloop_agent_core import SafeObservation, SafeOffer
from proxyloop_contracts import FastModelView
from pydantic import ValidationError

LOCAL_FAST_WIRE_VERSION: Final = "local-fast-wire-v1"
MAX_REQUEST_BYTES: Final = 256 * 1024

_REQUEST_KEYS: Final = frozenset({"wire_version", "view", "observation"})
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


class WireError(ValueError):
    """A request body that is not a valid ``local-fast-wire-v1`` request."""


def encode_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WireError("duplicate JSON key")
        result[key] = value
    return result


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise WireError("timestamps must be UTC text ending in Z")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _object(value: object, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise WireError("object keys differ from the wire contract")
    return value


def _texts(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WireError("expected a list of text")
    return tuple(value)


def observation_from_dict(value: object) -> SafeObservation:
    """Inverse of ``SafeObservation.to_dict``; refuses anything non-canonical."""

    data = _object(value, _OBSERVATION_KEYS)
    offers_value = data["offers"]
    if not isinstance(offers_value, list):
        raise WireError("offers must be a list")
    try:
        offers = tuple(
            SafeOffer(
                offer_id=offer["offer_id"],
                provider_id=offer["provider_id"],
                monthly_price_minor=offer["monthly_price_minor"],
                total_cost_12_months_minor=offer["total_cost_12_months_minor"],
                currency=offer["currency"],
                features=_texts(offer["features"]),
                fees_minor=offer["fees_minor"],
                term_months=offer["term_months"],
                applied_changes=_texts(offer["applied_changes"]),
                expires_at=_utc(offer["expires_at"]),
            )
            for offer in (_object(item, _OFFER_KEYS) for item in offers_value)
        )
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
            offers=offers,
            requested_disclosures=_texts(data["requested_disclosures"]),
            needs_clarification=data["needs_clarification"],
            transfer_available=data["transfer_available"],
            approval_current=data["approval_current"],
            observed_at=_utc(data["observed_at"]),
            confirmation_evidence_available=data["confirmation_evidence_available"],
        )
    except (TypeError, ValueError, AttributeError) as error:
        raise WireError("observation is not a valid SafeObservation") from error
    if observation.to_dict() != data:
        raise WireError("observation is not in canonical form")
    return observation


def decode_decide_request(body: bytes) -> tuple[FastModelView, SafeObservation]:
    try:
        document = json.loads(
            body.decode("utf-8"), object_pairs_hook=_reject_duplicates
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise WireError("request body is not JSON") from error
    data = _object(document, _REQUEST_KEYS)
    if data["wire_version"] != LOCAL_FAST_WIRE_VERSION:
        raise WireError("unsupported wire version")
    try:
        # JSON mode: the strict contracts reject enum and datetime strings in
        # python mode.
        view = FastModelView.model_validate_json(json.dumps(data["view"]))
    except ValidationError as error:
        raise WireError("view is not a valid FastModelView") from error
    return view, observation_from_dict(data["observation"])


__all__ = [
    "LOCAL_FAST_WIRE_VERSION",
    "MAX_REQUEST_BYTES",
    "WireError",
    "decode_decide_request",
    "encode_json",
    "observation_from_dict",
]
