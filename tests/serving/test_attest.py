import asyncio
import hashlib
import json
import os

import pytest
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

from scripts.mod.attest_local import compare
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
    assert set(doc["digest_source"].values()) == {"fresh"} and len(doc["digest_source"]) == 9


def test_cache_covers_weights_and_tokenizer_but_never_adapters(layout, monkeypatch):
    model, adapters, cache = layout
    attest.attest_files(model, adapters, cache)
    hashed = []
    real = attest.sha256_file
    monkeypatch.setattr(attest, "sha256_file", lambda p: hashed.append(p.name) or real(p))
    doc = attest.attest_files(model, adapters, cache)
    assert sorted(hashed) == ["adapter_config.json", "adapter_model.safetensors"]
    source = doc["digest_source"]
    assert source["adapters/Qwen3.5-9B-zero/adapter_model.safetensors"] == "fresh"
    assert source["shards/model.safetensors-00001-of-00004.safetensors"] == "cached"
    assert source["tokenizer/tokenizer.json"] == "cached"
    shard = model / "model.safetensors-00001-of-00004.safetensors"
    shard.write_bytes(b"swapped!!")  # same size as before; only mtime_ns tells
    os.utime(shard, ns=(1, 1))
    hashed.clear()
    doc = attest.attest_files(model, adapters, cache)
    assert shard.name in hashed and doc["shards"][shard.name] == sha(b"swapped!!")
    assert doc["digest_source"][f"shards/{shard.name}"] == "fresh"


@pytest.mark.parametrize("remove", ["tokenizer.json", "chat_template.jinja", "adapter", "shards"])
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


def scope(path: str, method: str = "GET", headers: dict | None = None) -> dict:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
            "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "",
            "query_string": b"", "headers": raw, "client": ("t", 1), "server": ("s", 80)}


def run(app, sc: dict, incoming: list[dict]) -> list[dict]:
    sent, queue = [], list(incoming)

    async def receive():
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(app(sc, receive, send))
    return sent


@pytest.fixture
def served(tmp_path, monkeypatch):
    doc = {"schema": "pl.attest/1", "shards": {"a.safetensors": "00"}}
    (tmp_path / "attest.json").write_text(json.dumps(doc))
    monkeypatch.setenv("PL_ATTEST_FILE", str(tmp_path / "attest.json"))
    monkeypatch.setenv("VLLM_API_KEY", "k3y")
    attest._document.cache_clear()
    return doc


def test_attest_route_requires_the_key_and_serves_the_document(served):
    inner_calls = []

    async def inner(sc, receive, send):
        inner_calls.append(sc["path"])

    app = attest.AttestMiddleware(inner)
    request = [{"type": "http.request", "body": b"", "more_body": False}]
    for headers, status in (({}, 401), ({"Authorization": "Bearer nope"}, 401),
                            ({"Authorization": "Bearer k3y"}, 200)):
        sent = run(app, scope("/pl/attest", headers=headers), request)
        assert sent[0]["status"] == status
    assert json.loads(sent[1]["body"]) == served
    assert run(app, scope("/pl/attest", "POST", {"Authorization": "Bearer k3y"}), request)[0]["status"] == 405
    assert inner_calls == []


def test_streaming_passes_through_byte_identically():
    async def chunks():
        for part in (b"data: {\"a\": 1}\n\n", b"", b"data: [DONE]\n\n"):
            yield part

    inner = Starlette(routes=[Route("/v1/completions", lambda r: StreamingResponse(chunks()),
                                    methods=["POST"])])
    request = [{"type": "http.request", "body": b"{}", "more_body": False}]
    sc = scope("/v1/completions", "POST")
    assert run(attest.AttestMiddleware(inner), dict(sc), request) == run(inner, dict(sc), request)


def test_other_scopes_get_the_same_receive_and_send_so_disconnect_propagates():
    seen = {}

    async def inner(sc, receive, send):
        seen.update(scope=sc, receive=receive, send=send, message=await receive())

    app = attest.AttestMiddleware(inner)
    sc = scope("/v1/completions", "POST")

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        pass

    asyncio.run(app(sc, receive, send))
    assert seen["scope"] is sc and seen["receive"] is receive and seen["send"] is send
    assert seen["message"] == {"type": "http.disconnect"}
    lifespan = {"type": "lifespan"}
    asyncio.run(app(lifespan, receive, send))
    assert seen["scope"] is lifespan


def test_compare_reports_each_file():
    served = {"a": "1", "b": "2"}
    assert compare({"a": "1", "b": "2"}, served)["all_match"] is True
    result = compare({"a": "1", "c": "3"}, served)
    assert result["all_match"] is False
    assert result["files"]["c"] == {"local": "3", "served": None, "match": False}
    assert compare({}, served)["all_match"] is False
