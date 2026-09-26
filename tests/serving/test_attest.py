import hashlib
import json
import os

import pytest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from serving import attest, config


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def layout(tmp_path):
    model = tmp_path / "snapshot"
    model.mkdir()
    files = {"model.safetensors-00001-of-00004.safetensors": b"shard-one",
             "model.safetensors-00004-of-00004.safetensors": b"shard-four",
             "model.safetensors.index.json": b"{}", "config.json": b"{}"}
    files.update({name: name.encode() for name in config.TOKENIZER_FILES})
    for name, data in files.items():
        (model / name).write_bytes(data)
    adapter = tmp_path / "adapters" / "zero-all"
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_bytes(b'{"r": 32}')
    (adapter / "adapter_model.safetensors").write_bytes(b"lora")
    return model, {"Qwen3.5-9B-zero": adapter}, tmp_path / "cache.json"


def test_digests_cover_shards_tokenizer_and_adapter_files_only(layout):
    model, adapters, cache = layout
    doc = attest.attest_files(model, adapters, cache)
    assert doc["shards"] == {"model.safetensors-00001-of-00004.safetensors": sha(b"shard-one"),
                             "model.safetensors-00004-of-00004.safetensors": sha(b"shard-four")}
    assert doc["tokenizer"] == {n: sha(n.encode()) for n in config.TOKENIZER_FILES}
    assert doc["adapters"] == {"Qwen3.5-9B-zero": {"adapter_config.json": sha(b'{"r": 32}'),
                                                   "adapter_model.safetensors": sha(b"lora")}}
    assert "index" not in json.dumps({k: doc[k] for k in ("shards", "tokenizer", "adapters")})
    assert doc["model"] == {"id": config.MODEL_ID, "revision": config.MODEL_REVISION}


def test_cache_skips_unchanged_files_and_rehashes_changed_ones(layout, monkeypatch):
    model, adapters, cache = layout
    attest.attest_files(model, adapters, cache)
    hashed = []
    real = attest.sha256_file
    monkeypatch.setattr(attest, "sha256_file", lambda p: hashed.append(p.name) or real(p))
    attest.attest_files(model, adapters, cache)
    assert hashed == []
    shard = model / "model.safetensors-00001-of-00004.safetensors"
    shard.write_bytes(b"swapped!!")  # same size would still change mtime_ns
    os.utime(shard, ns=(1, 1))
    doc = attest.attest_files(model, adapters, cache)
    assert hashed == [shard.name]
    assert doc["shards"][shard.name] == sha(b"swapped!!")


@pytest.mark.parametrize("remove", ["tokenizer.json", "chat_template.jinja", "adapter",
                                    "shards"])
def test_missing_inputs_fail_loudly(layout, remove):
    model, adapters, cache = layout
    if remove == "adapter":
        (adapters["Qwen3.5-9B-zero"] / "adapter_config.json").unlink()
    elif remove == "shards":
        for p in model.glob("*.safetensors"):
            p.unlink()
    else:
        (model / remove).unlink()
    with pytest.raises(FileNotFoundError):
        attest.attest_files(model, adapters, cache)


@pytest.mark.parametrize(("header", "ok"), [
    ("Bearer k3y", True), ("bearer k3y", True), ("Bearer k3", False), ("Basic k3y", False),
    (None, False), ("Bearer", False), ("Bearer ключ", False)])
def test_authorized(header, ok):
    assert attest.authorized(header, "k3y") is ok
    assert attest.authorized(header, "") is False


@pytest.fixture
def client(tmp_path, monkeypatch):
    doc = {"schema": "pl.attest/1", "shards": {"a.safetensors": "00"}}
    (tmp_path / "attest.json").write_text(json.dumps(doc))
    monkeypatch.setenv("PL_ATTEST_FILE", str(tmp_path / "attest.json"))
    monkeypatch.setenv("VLLM_API_KEY", "k3y")
    attest._document.cache_clear()
    app = Starlette(routes=[Route("/health", lambda request: PlainTextResponse("ok"))])
    # vLLM registers a coroutine with FastAPI's app.middleware("http"), i.e. BaseHTTPMiddleware.
    app.add_middleware(BaseHTTPMiddleware, dispatch=attest.attest_middleware)
    return TestClient(app), doc


def test_attest_route_requires_the_key_and_serves_the_document(client):
    test_client, doc = client
    assert test_client.get("/pl/attest").status_code == 401
    assert test_client.get("/pl/attest", headers={"Authorization": "Bearer nope"}).status_code == 401
    resp = test_client.get("/pl/attest", headers={"Authorization": "Bearer k3y"})
    assert resp.status_code == 200 and resp.json() == doc
    assert test_client.post("/pl/attest", headers={"Authorization": "Bearer k3y"}).status_code == 405
    assert test_client.get("/health").text == "ok"


def test_compare_reports_each_file():
    served = {"a": "1", "b": "2"}
    assert attest.compare({"a": "1", "b": "2"}, served)["all_match"] is True
    result = attest.compare({"a": "1", "c": "3"}, served)
    assert result["all_match"] is False
    assert result["files"]["c"] == {"local": "3", "served": None, "match": False}
    assert attest.compare({}, served)["all_match"] is False
