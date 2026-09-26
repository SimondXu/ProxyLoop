"""Recompute shard sha256s locally and compare them with the served /pl/attest document (ADR-0002).

    python -m scripts.mod.attest_local --shards 1,4 --against docs/decisions/data/vllm-probe.json \
        --out docs/decisions/data/vllm-attest-local.json

Downloads the named shards at the pinned revision onto the machine it runs on.
"""

import argparse
import json
import platform
import sys
from pathlib import Path

from serving import config
from serving.attest import sha256_file


def compare(local: dict[str, str], served: dict[str, str]) -> dict:
    files = {n: {"local": sha, "served": served.get(n), "match": served.get(n) == sha}
             for n, sha in sorted(local.items())}
    return {"files": files, "all_match": bool(files) and all(f["match"] for f in files.values())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["all_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
