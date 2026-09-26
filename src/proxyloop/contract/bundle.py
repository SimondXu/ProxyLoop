"""The run bundle ``runs/<run_id>/`` and its manifest ``pl.bundle/1`` (§14).

``read_bundle`` parses and validates; recomputing shas and walking chains is
``evidence-check``'s job (SYS).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from proxyloop.contract.base import Frozen
from proxyloop.contract.config import SessionConfig, config_hash
from proxyloop.contract.events import Event, check_causes
from proxyloop.contract.llm import AdapterKind, LLMRole, ModelRef
from proxyloop.contract.state import Spend

BUNDLE_SCHEMA = "pl.bundle/1"
MANIFEST, EVENTS, PROMPTS = "manifest.json", "events.jsonl", "prompts.jsonl"


class RoleModel(Frozen):
    ref: ModelRef
    served_model: str | None = None  # the served name, e.g. a LoRA slot
    adapter_shards: dict[str, str] = Field(default_factory=dict[str, str])  # sha256


class Manifest(Frozen):
    model_config = ConfigDict(
        frozen=True, extra="forbid", validate_by_name=True, serialize_by_alias=True
    )

    schema_: Literal["pl.bundle/1"] = Field(default="pl.bundle/1", alias="schema")
    run_id: str
    git_sha: str
    contract_version: str
    cfg: SessionConfig
    cfg_hash: str
    task_ref: str
    instance_hash: str
    split: Literal["train", "dev", "test"]
    fingerprints: dict[str, str]  # renderer fingerprint per profile
    models: dict[LLMRole, RoleModel]
    attestation: dict[str, str] | None = None  # file -> sha256 from /pl/attest
    p3: Literal["pass", "fail", "not_applicable"]
    reality: dict[LLMRole, AdapterKind]  # the adapter kind each role ran with
    spend: Spend

    @model_validator(mode="after")
    def _cfg(self) -> Self:
        if self.cfg_hash != config_hash(self.cfg):
            raise ValueError("cfg_hash does not match cfg")
        return self


class PromptRecord(Frozen):
    """One ``prompts.jsonl`` line: a view, prompt, messages or response by sha."""

    sha: str
    kind: Literal["view", "prompt", "messages", "response"]
    content: str


@dataclass(frozen=True, slots=True)
class Bundle:
    manifest: Manifest
    events: tuple[Event, ...]
    prompts: Mapping[str, PromptRecord]


def _jsonl(path: Path) -> list[str]:
    return [line for line in path.read_text("utf-8").splitlines() if line.strip()]


def read_bundle(path: Path) -> Bundle:
    manifest = Manifest.model_validate(json.loads((path / MANIFEST).read_text("utf-8")))
    events = tuple(Event.model_validate_json(line) for line in _jsonl(path / EVENTS))
    check_causes(events)
    records = [
        PromptRecord.model_validate_json(line) for line in _jsonl(path / PROMPTS)
    ]
    return Bundle(manifest, events, {r.sha: r for r in records})
