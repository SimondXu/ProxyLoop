"""Attestation (ARCHITECTURE §13): sha256 of every served shard, tokenizer file and
adapter file.

`attest_files` runs at container start, before vLLM. Shard and tokenizer digests are
cached on the HF volume per (real path, size, mtime_ns); adapter digests are always
computed fresh. Each file is recorded as "cached" or "fresh". `AttestMiddleware` (vLLM
`--middleware`) serves the document at GET /pl/attest from the vLLM API server process.
Never the index file, never greedy outputs.
"""

import functools
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from serving import config

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

ROUTE = "/pl/attest"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_all(
    group: str,
    files: dict[str, Path],
    cache: dict[str, dict[str, Any]],
    source: dict[str, str],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, path in files.items():
        real = path.resolve()
        stat = real.stat()
        entry = cache.get(str(real))
        fresh = not entry or (entry["size"], entry["mtime_ns"]) != (
            stat.st_size,
            stat.st_mtime_ns,
        )
        if fresh:
            cache[str(real)] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(real),
            }
        source[f"{group}/{name}"] = "fresh" if fresh else "cached"
        out[name] = cache[str(real)]["sha256"]
    return out


def attest_files(
    model_dir: Path, adapter_dirs: dict[str, Path], cache_path: Path
) -> dict[str, Any]:
    shards = {p.name: p for p in sorted(model_dir.glob("*.safetensors"))}
    tokenizer = {n: model_dir / n for n in config.TOKENIZER_FILES}
    missing = [str(p) for p in tokenizer.values() if not p.is_file()]
    missing += [
        f"{d}/adapter_config.json"
        for d in adapter_dirs.values()
        if not (d / "adapter_config.json").is_file()
    ]
    if not shards or missing:
        raise FileNotFoundError(
            f"attestation inputs missing: shards={len(shards)} {missing}"
        )
    cache: dict[str, dict[str, Any]] = (
        json.loads(cache_path.read_text()) if cache_path.is_file() else {}
    )
    started = time.monotonic()
    source: dict[str, str] = {}
    doc: dict[str, Any] = {
        "schema": "pl.attest/1",
        "model": {"id": config.MODEL_ID, "revision": config.MODEL_REVISION},
        "shards": _hash_all("shards", shards, cache, source),
        "tokenizer": _hash_all("tokenizer", tokenizer, cache, source),
        # adapters get a throwaway cache: always hashed fresh, never persisted
        "adapters": {
            slot: _hash_all(
                f"adapters/{slot}",
                {str(p.relative_to(d)): p for p in sorted(d.rglob("*")) if p.is_file()},
                {},
                source,
            )
            for slot, d in sorted(adapter_dirs.items())
        },
    }
    doc.update(digest_source=source, hash_seconds=round(time.monotonic() - started, 3))
    cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True))
    return doc


def authorized(header: str | None, key: str) -> bool:
    scheme, _, token = (header or "").partition(" ")
    return (
        bool(key)
        and scheme.lower() == "bearer"
        and hmac.compare_digest(token.encode(), key.encode())
    )


@functools.cache
def _document() -> dict[str, Any]:
    return json.loads(Path(os.environ["PL_ATTEST_FILE"]).read_text())


class AttestMiddleware:
    """Pure ASGI: answers GET /pl/attest (bearer); every other scope passes through
    untouched."""

    def __init__(self, app: "ASGIApp") -> None:
        self.app = app

    async def __call__(self, scope: "Scope", receive: "Receive", send: "Send") -> None:
        if scope["type"] != "http" or scope["path"] != ROUTE:
            await self.app(scope, receive, send)
            return
        from starlette.datastructures import Headers
        from starlette.responses import JSONResponse

        if scope["method"] != "GET":
            response = JSONResponse({"error": "method not allowed"}, status_code=405)
        elif not authorized(
            Headers(scope=scope).get("authorization"),
            os.environ.get("VLLM_API_KEY", ""),
        ):
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
        else:
            response = JSONResponse(_document())
        await response(scope, receive, send)
