"""Write or verify the Phase 03C Stage 1b parameterised prompt-set manifest.

``--write`` renders every train-family instance position (10 train families
x 2 configurations x seeds 1..100 train / 900..909 development x 2 positions,
zero model calls) and writes metadata plus fingerprints only.  ``--check``
re-renders the set and exits non-zero on any manifest drift.
"""

from __future__ import annotations

import argparse
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from proxyloop_evaluation.phase03c_experiment import (
    PHASE03C_COMPILER_VERSIONS,
    PromptVersion,
)
from proxyloop_evaluation.phase03c_prompt_set import (
    PROMPT_SET_MANIFEST_PATH,
    STAGE1B_PROMPT_VERSION,
    check_prompt_set_manifest,
    write_prompt_set_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument(
        "--prompt-version",
        choices=tuple(PHASE03C_COMPILER_VERSIONS),
        default=STAGE1B_PROMPT_VERSION,
    )
    args = parser.parse_args(argv)
    path = ROOT / PROMPT_SET_MANIFEST_PATH
    prompt_version = cast(PromptVersion, args.prompt_version)
    started = time.perf_counter()
    if args.write:
        rows = write_prompt_set_manifest(path, prompt_version=prompt_version)
        elapsed = time.perf_counter() - started
        counts = Counter(row.split for row in rows)
        print(
            f"wrote {path.relative_to(ROOT)} in {elapsed:.1f}s "
            f"({path.stat().st_size} bytes)"
        )
        print(
            f"{len(rows)} prompts: {counts['train']} train, "
            f"{counts['development']} development"
        )
        return 0
    problems = check_prompt_set_manifest(path, prompt_version=prompt_version)
    elapsed = time.perf_counter() - started
    if problems:
        for problem in problems:
            print(problem)
        return 1
    print(f"phase03c prompt set is consistent ({elapsed:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
