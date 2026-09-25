#!/usr/bin/env python
"""Serve the local opt-in Fast backend on 127.0.0.1 (``local-fast-wire-v1``).

    HF_HUB_OFFLINE=1 python -m scripts.run_local_fast_gateway \
        --backend distilled --model-path <Qwen3-8B-MLX-bf16 snapshot dir>

Refuses to start unless ``HF_HUB_OFFLINE=1`` (nothing may be downloaded), the
base snapshot attests, the distilled adapter matches the committed
attestation, and every attested LoRA layer loaded with non-zero weights.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence
from pathlib import Path

from proxyloop_evaluation.local_fast.gateway_core import LocalFastGatewayCore
from proxyloop_evaluation.local_fast.http_server import LOOPBACK_HOST, serve
from proxyloop_evaluation.local_fast.identity import BACKENDS
from proxyloop_evaluation.local_fast.mlx_adapter_conversion import load_attestation

ROOT = Path(__file__).resolve().parents[1]
ATTESTATION = ROOT / "ml/serving/phase-03c-cloud-run-01-mlx-attestation.json"
DEFAULT_ADAPTER = (
    ROOT / "data/experiments/phase-03c/training/cloud-run-01/train/mlx/adapters"
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--adapter-path", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--host", default=LOOPBACK_HOST)
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        raise SystemExit("set HF_HUB_OFFLINE=1: the gateway never downloads")
    if args.host != LOOPBACK_HOST:
        raise SystemExit("the local Fast gateway binds 127.0.0.1 only")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    distilled = args.backend == "distilled"
    core = LocalFastGatewayCore.load(
        backend=args.backend,
        model_path=args.model_path,
        adapter_path=args.adapter_path if distilled else None,
        attestation=load_attestation(ATTESTATION) if distilled else None,
    )
    serve(core, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
