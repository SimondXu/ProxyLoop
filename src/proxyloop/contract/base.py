"""Shared building blocks of the contract types."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

Lane = Literal["user", "cp"]
HoldReason = Literal["offer", "decision", "fact_request", "pressure", "unclear"]
HOLD_REASONS: tuple[HoldReason, ...] = (
    "offer",
    "decision",
    "fact_request",
    "pressure",
    "unclear",
)
FACT_KEY = r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def canonical_json(value: object) -> str:
    """Sorted keys, no whitespace, UTF-8 text: the hashing form."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
