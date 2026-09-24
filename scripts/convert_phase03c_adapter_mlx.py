#!/usr/bin/env python
"""Convert the Phase 03C PEFT adapter to the MLX format ``mlx_lm`` loads.

The PEFT weights and the converted weights are git-ignored and never
committed; only the hashes in ``ml/serving/`` are.  The expected source hash
is the ``adapter_sha256`` the 03C run manifest recorded.  Without
``--write-attestation`` the result must equal the committed attestation.

    python -m scripts.convert_phase03c_adapter_mlx \
        --source data/experiments/phase-03c/training/cloud-run-01/train/adapter
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from proxyloop_evaluation.local_fast.mlx_adapter_conversion import (
    convert_peft_lora_to_mlx,
    load_attestation,
    render_attestation,
)

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "data/experiments/phase-03c/training/cloud-run-01/train"
DEFAULT_SOURCE = RUN_DIR / "adapter"
DEFAULT_OUT = RUN_DIR / "mlx/adapters"
RUN_MANIFEST = RUN_DIR / "run-manifest.json"
ATTESTATION = ROOT / "ml/serving/phase-03c-cloud-run-01-mlx-attestation.json"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--attestation", type=Path, default=ATTESTATION)
    parser.add_argument(
        "--write-attestation",
        action="store_true",
        help="write the attestation instead of requiring it to match",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = json.loads(RUN_MANIFEST.read_text(encoding="utf-8"))
    expected = str(manifest["adapter_sha256"]["adapter_model.safetensors"])
    attestation = convert_peft_lora_to_mlx(
        args.source, args.out, expected_source_sha256=expected
    )
    rendered = render_attestation(attestation)
    print(rendered, end="")
    if args.write_attestation:
        args.attestation.parent.mkdir(parents=True, exist_ok=True)
        args.attestation.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.attestation.relative_to(ROOT)}")
        return 0
    if load_attestation(args.attestation) != attestation:
        raise SystemExit("converted adapter differs from the committed attestation")
    print(f"matches {args.attestation.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
