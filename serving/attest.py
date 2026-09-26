"""Attestation (ARCHITECTURE §13): sha256 of every served shard, tokenizer file and adapter file.

Container: `attest_files` runs at container start, before vLLM; `attest_middleware` (loaded into
the vLLM API server by `--middleware`) serves the result at GET /pl/attest. Digests are cached on
the HF volume per (real path, size, mtime_ns), so an unchanged volume is not re-read and a changed
file is re-hashed. Never the index file, never greedy outputs.
Mac: `python -m serving.attest --shards 1,4 --against <probe.json> --out <json>` recomputes two
shards downloaded at the pinned revision and compares them with the served digests.
"""

import argparse
import functools
import hashlib
import hmac
import json
import os
import platform
import sys
import time
from pathlib import Path

from serving import config


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_all(files: dict[str, Path], cache: dict) -> dict[str, str]:
    out = {}
    for name, path in files.items():
        real = path.resolve()
        stat = real.stat()
        entry = cache.get(str(real))
        if not entry or (entry["size"], entry["mtime_ns"]) != (stat.st_size, stat.st_mtime_ns):
            entry = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(real)}
            cache[str(real)] = entry
        out[name] = entry["sha256"]
    return out


def attest_files(model_dir: Path, adapter_dirs: dict[str, Path], cache_path: Path) -> dict:
    shards = {p.name: p for p in sorted(model_dir.glob("*.safetensors"))}
    tokenizer = {n: model_dir / n for n in config.TOKENIZER_FILES}
    missing = [str(p) for p in tokenizer.values() if not p.is_file()]
    missing += [f"{d}/adapter_config.json" for d in adapter_dirs.values()
                if not (d / "adapter_config.json").is_file()]
    if not shards or missing:
        raise FileNotFoundError(f"attestation inputs missing: shards={len(shards)} {missing}")
    cache = json.loads(cache_path.read_text()) if cache_path.is_file() else {}
    started = time.monotonic()
    doc = {"schema": "pl.attest/1", "model": {"id": config.MODEL_ID, "revision": config.MODEL_REVISION},
           "shards": _hash_all(shards, cache), "tokenizer": _hash_all(tokenizer, cache),
           "adapters": {slot: _hash_all({str(p.relative_to(d)): p for p in sorted(d.rglob("*"))
                                         if p.is_file()}, cache)
                        for slot, d in sorted(adapter_dirs.items())}}
    doc["hash_seconds"] = round(time.monotonic() - started, 3)
    cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True))
    return doc


def authorized(header: str | None, key: str) -> bool:
    scheme, _, token = (header or "").partition(" ")
    return bool(key) and scheme.lower() == "bearer" and hmac.compare_digest(token.encode(), key.encode())


@functools.cache
def _document() -> dict:
    return json.loads(Path(os.environ["PL_ATTEST_FILE"]).read_text())


async def attest_middleware(request, call_next):
    """vLLM `--middleware`: GET /pl/attest in the serving process, bearer-authenticated."""
    if request.url.path != "/pl/attest":
        return await call_next(request)
    from starlette.responses import JSONResponse

    if request.method != "GET":
        return JSONResponse({"error": "method not allowed"}, status_code=405)
    if not authorized(request.headers.get("authorization"), os.environ.get("VLLM_API_KEY", "")):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse(_document())


def compare(local: dict[str, str], served: dict[str, str]) -> dict:
    files = {n: {"local": sha, "served": served.get(n), "match": served.get(n) == sha}
             for n, sha in sorted(local.items())}
    return {"files": files, "all_match": bool(files) and all(f["match"] for f in files.values())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recompute shard sha256s; compare with /pl/attest.")
    parser.add_argument("--shards", default="1,4")
    parser.add_argument("--against", required=True, help="probe JSON with the served attest document")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    from huggingface_hub import hf_hub_download

    names = [f"model.safetensors-{int(i):05d}-of-00004.safetensors" for i in args.shards.split(",")]
    local = {n: sha256_file(Path(hf_hub_download(config.MODEL_ID, n, revision=config.MODEL_REVISION)))
             for n in names}
    served = json.loads(Path(args.against).read_text())["attest"]["shards"]
    result = {"model": {"id": config.MODEL_ID, "revision": config.MODEL_REVISION},
              "host": platform.platform(), **compare(local, served)}
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["all_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
