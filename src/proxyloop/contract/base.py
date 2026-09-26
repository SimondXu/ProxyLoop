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
# Render bounds (ADR-0004): a FastView with every bounded field at its maximum
# still fits CONTEXT_BUDGET_CHARS; the transcript and action log absorb the rest.
MAX_BRIEF, MAX_PRIVATE_SUMMARY, MAX_PUBLIC_TEXT = 800, 1_200, 400
MAX_READBACK_TEXT, MAX_FACT_VALUE, MAX_SLOT_VALUE = 600, 120, 24
MAX_OFFERS, MAX_SLOTS, MAX_GUIDE_SLOTS, MAX_SLOT_REF = 6, 10, 3, 80
MAX_GUIDES, MAX_SLOT_FIELD = 3, 40


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def canonical_json(value: object) -> str:
    """Sorted keys, no whitespace, UTF-8 text: the hashing form."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
