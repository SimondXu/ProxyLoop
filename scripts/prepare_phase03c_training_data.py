"""Write the Phase 03C Stage 2 chat-format training data for ``mlx_lm.lora``.

``train.jsonl`` is the accepted teacher JSONL's ``messages`` verbatim after a
byte-for-byte check of every system/user pair against the frozen prompt
builder; ``valid.jsonl`` is the 400 oracle-labelled development rows with
the canonical oracle target as the assistant turn; ``dataset-manifest.json``
records counts, hashes, and (with ``--tokenizer-path``) the templated token
lengths the trainer will see.  Both JSONL files carry teacher text and stay
git-ignored; the manifest is committed.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from proxyloop_evaluation.phase03c_experiment import (  # noqa: E402
    PHASE03C_COMPILER_VERSIONS,
    PromptVersion,
)
from proxyloop_evaluation.phase03c_prompt_set import (  # noqa: E402
    PROMPT_SET_MANIFEST_PATH,
    load_prompt_set_manifest,
)
from proxyloop_evaluation.phase03c_training.config import RECIPE  # noqa: E402
from proxyloop_evaluation.phase03c_training.dataset import (  # noqa: E402
    ChatTokenCounter,
    write_dataset,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--prompt-version", choices=tuple(PHASE03C_COMPILER_VERSIONS), default="v6"
    )
    parser.add_argument(
        "--manifest", type=Path, default=PROJECT_ROOT / PROMPT_SET_MANIFEST_PATH
    )
    parser.add_argument(
        "--tokenizer-path",
        type=Path,
        default=None,
        help="model snapshot whose tokenizer measures templated token lengths",
    )
    parser.add_argument("--max-seq-length", type=int, default=RECIPE.max_seq_length)
    return parser.parse_args(argv)


def prompt_set_content_fingerprint(path: Path) -> str:
    document = json.loads(path.read_text(encoding="utf-8"))
    fingerprint = (
        document.get("content_fingerprint") if isinstance(document, dict) else None
    )
    if not isinstance(fingerprint, str):
        raise ValueError(f"prompt set manifest has no content_fingerprint: {path}")
    return fingerprint


def chat_token_counter(tokenizer_path: Path) -> ChatTokenCounter:
    """Count tokens exactly as ``mlx_lm.tuner.datasets.ChatDataset`` renders."""

    utils = importlib.import_module("mlx_lm.utils")
    tokenizer = utils.load_tokenizer(tokenizer_path)

    def count(messages: Sequence[Mapping[str, str]]) -> int:
        tokens = tokenizer.apply_chat_template(list(messages), return_dict=False)
        return len(cast(Sequence[int], tokens))

    return count


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    rows = load_prompt_set_manifest(args.manifest)
    counter = (
        chat_token_counter(args.tokenizer_path)
        if args.tokenizer_path is not None
        else None
    )
    try:
        document = write_dataset(
            accepted_path=args.accepted,
            out_dir=args.out_dir,
            prompt_set_rows=rows,
            prompt_set_content_fingerprint=prompt_set_content_fingerprint(
                args.manifest
            ),
            prompt_version=cast(PromptVersion, args.prompt_version),
            count_tokens=counter,
            max_seq_length=args.max_seq_length,
        )
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    counts = cast(Mapping[str, int], document["split_counts"])
    stats = document.get("token_stats")
    print(
        f"phase03c training data written to {args.out_dir}: "
        f"train={counts['train']} development={counts['development']} "
        f"fingerprint={document['dataset_fingerprint']}"
    )
    if isinstance(stats, dict):
        print(
            f"token lengths: max={stats['max']} p95={stats['p95']} "
            f"over_{stats['max_seq_length']}={stats['over_max_seq_length']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
