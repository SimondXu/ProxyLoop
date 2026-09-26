"""The run bundle: manifest JSON-schema snapshot and ``read_bundle``."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.contract.samples import QWEN, session_config

from proxyloop.contract import CONTRACT_VERSION
from proxyloop.contract.base import sha256_text
from proxyloop.contract.bundle import (
    EVENTS,
    MANIFEST,
    PROMPTS,
    Manifest,
    PromptRecord,
    RoleModel,
    read_bundle,
)
from proxyloop.contract.config import config_hash
from proxyloop.contract.events import Event
from proxyloop.contract.llm import AdapterKind
from proxyloop.contract.state import Spend

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "manifest.schema.json"


def test_manifest_json_schema_matches_the_snapshot() -> None:
    current = Manifest.model_json_schema(by_alias=True)
    if os.environ.get("PL_UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(
            json.dumps(current, indent=1, sort_keys=True) + "\n", "utf-8"
        )
    assert json.loads(SNAPSHOT.read_text("utf-8")) == current


def _manifest() -> Manifest:
    cfg = session_config()
    return Manifest(
        run_id="r1",
        git_sha="abc123",
        contract_version=CONTRACT_VERSION,
        cfg=cfg,
        cfg_hash=config_hash(cfg),
        task_ref="cp-direct-discount@1",
        instance_hash="i1",
        split="train",
        fingerprints={"pl_cp_v1": "f" * 64},
        models={"fast_cp": RoleModel(ref=QWEN, served_model="Qwen3.5-9B")},
        p3="pass",
        reality={"fast_cp": AdapterKind.REAL_HTTP},
        spend=Spend(),
    )


def test_cfg_hash_must_match() -> None:
    body = _manifest().model_dump() | {"cfg_hash": "0" * 64}
    with pytest.raises(ValueError, match="cfg_hash"):
        Manifest.model_validate(body)


def test_read_bundle_round_trip(tmp_path: Path) -> None:
    manifest = _manifest()
    event = Event(
        run_id="r1",
        seq=0,
        event_id="r1:0",
        t_ms=0,
        wall=datetime(2026, 9, 26, tzinfo=UTC),
        type="user.msg",
        actor="ui",
        stream="agent",
        epoch=0,
        payload={"text": "hi"},
    )
    record = PromptRecord(sha=sha256_text("hi"), kind="response", content="hi")
    (tmp_path / MANIFEST).write_text(manifest.model_dump_json(), "utf-8")
    (tmp_path / EVENTS).write_text(event.model_dump_json() + "\n", "utf-8")
    (tmp_path / PROMPTS).write_text(record.model_dump_json() + "\n", "utf-8")
    bundle = read_bundle(tmp_path)
    assert bundle.manifest == manifest
    assert bundle.events == (event,)
    assert bundle.prompts == {record.sha: record}
    assert (
        json.loads((tmp_path / MANIFEST).read_text("utf-8"))["schema"] == "pl.bundle/1"
    )
