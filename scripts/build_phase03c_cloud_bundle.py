"""Render the self-contained Phase 03C Stage 2/3 cloud bundle.

The bundle is everything ``ml/training/phase03c_cloud/`` needs on a GPU box
that has no ProxyLoop packages: ``train.jsonl`` (accepted teacher rows as
``messages``, byte-equal to the frozen prompt builder), ``valid.jsonl`` (the
400 oracle-labelled development rows), ``dev-eval.jsonl`` and
``heldout.jsonl`` (prompts plus the oracle target and the public observation
the offline scorer needs), ``schema.json`` (``FastModelOutput``'s JSON
schema for guided decoding), and ``bundle-manifest.json``.  ``--check``
re-renders every deterministic file and compares its hash with the committed
manifest; the JSONL files carry teacher text and stay git-ignored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Final, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from proxyloop_contracts import canonical_fingerprint  # noqa: E402
from proxyloop_evaluation.fast_output import FastModelOutput  # noqa: E402
from proxyloop_evaluation.phase03c_experiment import (  # noqa: E402
    PHASE03C_COMPILER_VERSIONS,
    PromptVersion,
)
from proxyloop_evaluation.phase03c_prompt_set import (  # noqa: E402
    PROMPT_SET_MANIFEST_PATH,
    PromptSetRow,
    load_prompt_set_manifest,
    prompt_builder,
    render_prompt_view,
    resolve_row,
)
from proxyloop_evaluation.phase03c_scenarios import (  # noqa: E402
    FastPosition,
    harvest_positions,
)
from proxyloop_evaluation.phase03c_training.dataset import (  # noqa: E402
    DatasetRow,
    assert_splits_disjoint,
    build_dev_rows,
    build_train_rows,
    canonical_dev_target,
    read_accepted_records,
    rows_by_prompt_id,
    sha256_file,
    teacher_manifest_path,
    write_jsonl,
)
from proxyloop_evaluation.qwen_spec import QWEN3_8B_BF16_SPEC  # noqa: E402
from proxyloop_provider_simulator.scenarios import (  # noqa: E402
    BENCHMARK_SCENARIOS,
    SCENARIO_FAMILIES,
    BenchmarkScenario,
    build_parameterised_scenarios,
)
from proxyloop_provider_simulator.splits import generate_split_manifest  # noqa: E402

BUNDLE_SCHEMA_VERSION: Final = "phase-03c-cloud-bundle-v1"
DEFAULT_OUT_DIR: Final = Path("data/experiments/phase-03c/cloud-bundle")
DEFAULT_HELDOUT_SEEDS: Final = range(950, 960)
MANIFEST_FILENAME: Final = "bundle-manifest.json"
SCHEMA_FILENAME: Final = "schema.json"
TRAIN_FILENAME: Final = "train.jsonl"
VALID_FILENAME: Final = "valid.jsonl"
DEV_EVAL_FILENAME: Final = "dev-eval.jsonl"
HELDOUT_FILENAME: Final = "heldout.jsonl"
MAX_LENGTH: Final = 2048
# Text -> token count for one fully templated conversation; injected so the
# bundle can be built and checked without any tokenizer.
TokenCounter = Callable[[Sequence[Mapping[str, str]]], int]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def heldout_families() -> tuple[tuple[str, str], ...]:
    """``(family_id, split)`` for the 3 development + 3 test families."""

    split_manifest = generate_split_manifest(BENCHMARK_SCENARIOS)
    families = tuple(
        (family.family_id, split_manifest.family_split(family.family_id))
        for family in SCENARIO_FAMILIES
        if split_manifest.family_split(family.family_id) != "train"
    )
    if Counter(split for _, split in families) != {"development": 3, "test": 3}:
        raise RuntimeError(f"unexpected held-out family splits: {families}")
    return families


def render_eval_row(
    scenario: BenchmarkScenario,
    position: FastPosition,
    *,
    split: str,
    prompt_version: PromptVersion,
) -> dict[str, object]:
    """One scoring row: prompt, oracle target, and the public observation."""

    view = render_prompt_view(scenario, position)
    prompt = prompt_builder(prompt_version).build_prompt(view)
    return {
        "prompt_id": f"{scenario.scenario_id}::pos{position.position_index}",
        "family_id": scenario.family_id,
        "entity_cluster": scenario.entity_cluster,
        "configuration_id": scenario.configuration_id,
        "seed": scenario.parameters.seed,
        "position_index": position.position_index,
        "event_cursor": position.event_cursor,
        "split": split,
        "scenario_id": scenario.scenario_id,
        "input_fingerprint": canonical_fingerprint(view),
        "prompt_fingerprint": prompt.fingerprint,
        "messages": [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ],
        "oracle_action": position.oracle_action,
        "oracle_target": json.loads(canonical_dev_target(position.oracle_action)),
        "public_observation": position.observation.to_dict(),
        "view": view.model_dump(mode="json"),
    }


def build_dev_eval_rows(
    rows: Iterable[PromptSetRow], *, prompt_version: PromptVersion
) -> tuple[dict[str, object], ...]:
    """Every development row of the prompt set, checked against its fingerprints."""

    output: list[dict[str, object]] = []
    for row in rows:
        if row.split != "development":
            continue
        scenario, position = resolve_row(row)
        rendered = render_eval_row(
            scenario, position, split="development", prompt_version=prompt_version
        )
        if rendered["prompt_id"] != row.prompt_id:
            raise ValueError(f"prompt_id_drift:{row.prompt_id}")
        if rendered["prompt_fingerprint"] != row.prompt_fingerprint:
            raise ValueError(f"prompt_fingerprint_drift:{row.prompt_id}")
        if rendered["input_fingerprint"] != row.input_fingerprint:
            raise ValueError(f"input_fingerprint_drift:{row.prompt_id}")
        if rendered["oracle_action"] != row.oracle_action:
            raise ValueError(f"oracle_action_drift:{row.prompt_id}")
        output.append(rendered)
    if not output:
        raise ValueError("no development rows in the prompt set")
    output.sort(key=_row_order)
    return tuple(output)


def build_heldout_rows(
    *, seeds: Iterable[int], prompt_version: PromptVersion
) -> tuple[dict[str, object], ...]:
    """3 development + 3 test families x 2 configurations x seeds x 2 positions."""

    split_by_family = dict(heldout_families())
    families = tuple(
        family for family in SCENARIO_FAMILIES if family.family_id in split_by_family
    )
    output: list[dict[str, object]] = []
    for scenario in build_parameterised_scenarios(seeds=seeds, families=families):
        for position in harvest_positions(scenario):
            output.append(
                render_eval_row(
                    scenario,
                    position,
                    split=split_by_family[scenario.family_id],
                    prompt_version=prompt_version,
                )
            )
    output.sort(key=_row_order)
    if len({row["prompt_id"] for row in output}) != len(output):
        raise RuntimeError("held-out prompt_ids must be unique")
    return tuple(output)


def _row_order(row: Mapping[str, object]) -> tuple[str, str, int, int]:
    return (
        str(row["family_id"]),
        str(row["configuration_id"]),
        int(cast(int, row["seed"])),
        int(cast(int, row["position_index"])),
    )


def write_rows(path: Path, rows: Sequence[Mapping[str, object]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return sha256_file(path)


def rows_sha256(rows: Sequence[Mapping[str, object]]) -> str:
    """The SHA-256 ``write_rows`` would produce, without touching disk."""

    digest = hashlib.sha256()
    for row in rows:
        digest.update((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    return digest.hexdigest()


def dataset_rows_sha256(rows: Sequence[DatasetRow]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update((row.to_line() + "\n").encode("utf-8"))
    return digest.hexdigest()


def schema_document() -> dict[str, object]:
    return cast(dict[str, object], FastModelOutput.model_json_schema())


def _percentile(values: Sequence[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def token_stats(
    rows: Sequence[DatasetRow], count_tokens: TokenCounter
) -> dict[str, object]:
    lengths = [count_tokens(row.messages) for row in rows]
    over = [
        row.prompt_id
        for row, length in zip(rows, lengths, strict=True)
        if length > MAX_LENGTH
    ]
    return {
        "rows": len(lengths),
        "max": max(lengths),
        "min": min(lengths),
        "p95": _percentile(lengths, 0.95),
        "total": sum(lengths),
        "max_length": MAX_LENGTH,
        "over_max_length": len(over),
        "over_max_length_prompt_ids": over[:20],
    }


def hf_token_counter(tokenizer_path: Path) -> TokenCounter:
    """Count tokens of the templated conversation with ``enable_thinking=False``."""

    from transformers import (  # type: ignore[import-not-found,unused-ignore]
        AutoTokenizer,
    )

    tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_path))

    def count(messages: Sequence[Mapping[str, str]]) -> int:
        text = tokenizer.apply_chat_template(
            [dict(item) for item in messages], tokenize=False, enable_thinking=False
        )
        return len(tokenizer(text, add_special_tokens=False)["input_ids"])

    return count


def git_commit() -> dict[str, object]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}
    return {"commit": head, "dirty": bool(dirty)}


def _family_counts(rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row["family_id"]) for row in rows).items()))


def _relative(path: Path) -> str:
    resolved = path.resolve()
    if resolved.is_relative_to(PROJECT_ROOT):
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    return path.as_posix()


def build_manifest(
    *,
    prompt_version: PromptVersion,
    prompt_set_path: Path,
    prompt_set_content_fingerprint: str,
    accepted_path: Path,
    train_rows: Sequence[DatasetRow],
    valid_rows: Sequence[DatasetRow],
    dev_eval_rows: Sequence[Mapping[str, object]],
    heldout_rows: Sequence[Mapping[str, object]],
    heldout_seeds: Sequence[int],
    files: Mapping[str, Mapping[str, object]],
    stats: Mapping[str, object] | None,
) -> dict[str, object]:
    spec = QWEN3_8B_BF16_SPEC
    teacher_manifest = teacher_manifest_path(accepted_path)
    document: dict[str, object] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "prompt_version": prompt_version,
        "compiler_version": PHASE03C_COMPILER_VERSIONS[prompt_version],
        "schema_fingerprint": _sha256_text(_canonical_json(schema_document())),
        "base_model": {
            "model": spec.source_lineage,
            "revision": spec.source_revision,
            "dtype": "bfloat16",
            "enable_thinking": False,
            "license": spec.license,
            "local_mlx_export": spec.model,
            "local_mlx_revision": spec.model_revision,
        },
        "git": git_commit(),
        "prompt_set": {
            "path": _relative(prompt_set_path),
            "content_fingerprint": prompt_set_content_fingerprint,
        },
        "accepted_source": {
            "path": _relative(accepted_path),
            "sha256": sha256_file(accepted_path),
            "teacher_manifest_sha256": (
                sha256_file(teacher_manifest) if teacher_manifest.is_file() else None
            ),
        },
        "heldout": {
            "seeds": {
                "first": min(heldout_seeds),
                "last": max(heldout_seeds),
                "count": len(heldout_seeds),
            },
            "families": dict(heldout_families()),
            "split_counts": dict(
                sorted(Counter(str(row["split"]) for row in heldout_rows).items())
            ),
        },
        "files": dict(files),
        "counts": {
            "train": len(train_rows),
            "valid": len(valid_rows),
            "dev_eval": len(dev_eval_rows),
            "heldout": len(heldout_rows),
        },
        "train_prompt_count": len({row.prompt_id for row in train_rows}),
        "family_counts": {
            "train": dict(sorted(Counter(row.family_id for row in train_rows).items())),
            "dev_eval": _family_counts(dev_eval_rows),
            "heldout": _family_counts(heldout_rows),
        },
        "max_length": MAX_LENGTH,
        "token_stats": dict(stats) if stats is not None else None,
    }
    document["dataset_fingerprint"] = _sha256_text(_canonical_json(document))
    return document


def prompt_set_content_fingerprint(path: Path) -> str:
    document = json.loads(path.read_text(encoding="utf-8"))
    fingerprint = (
        document.get("content_fingerprint") if isinstance(document, dict) else None
    )
    if not isinstance(fingerprint, str):
        raise ValueError(f"prompt set manifest has no content_fingerprint: {path}")
    return fingerprint


def write_bundle(
    *,
    accepted_path: Path,
    out_dir: Path,
    prompt_set_path: Path,
    prompt_version: PromptVersion,
    heldout_seeds: Sequence[int],
    count_tokens: TokenCounter | None = None,
) -> dict[str, object]:
    prompt_rows = load_prompt_set_manifest(prompt_set_path)
    records = read_accepted_records(accepted_path)
    train_rows = build_train_rows(
        records, rows_by_prompt_id(prompt_rows), prompt_version=prompt_version
    )
    valid_rows = build_dev_rows(prompt_rows, prompt_version=prompt_version)
    assert_splits_disjoint(train_rows, valid_rows)
    dev_eval_rows = build_dev_eval_rows(prompt_rows, prompt_version=prompt_version)
    heldout_rows = build_heldout_rows(
        seeds=heldout_seeds, prompt_version=prompt_version
    )
    train_families = {row.family_id for row in train_rows}
    heldout_family_ids = {str(row["family_id"]) for row in heldout_rows}
    if train_families & heldout_family_ids:
        raise ValueError(
            f"held-out families in train: {sorted(train_families & heldout_family_ids)}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    schema_text = json.dumps(schema_document(), indent=2, sort_keys=True) + "\n"
    (out_dir / SCHEMA_FILENAME).write_text(schema_text, encoding="utf-8")
    files: dict[str, dict[str, object]] = {}
    for name, sha, rows in (
        (TRAIN_FILENAME, write_jsonl(out_dir / TRAIN_FILENAME, train_rows), train_rows),
        (VALID_FILENAME, write_jsonl(out_dir / VALID_FILENAME, valid_rows), valid_rows),
        (
            DEV_EVAL_FILENAME,
            write_rows(out_dir / DEV_EVAL_FILENAME, dev_eval_rows),
            dev_eval_rows,
        ),
        (
            HELDOUT_FILENAME,
            write_rows(out_dir / HELDOUT_FILENAME, heldout_rows),
            heldout_rows,
        ),
    ):
        files[name] = {
            "rows": len(rows),
            "sha256": sha,
            "bytes": (out_dir / name).stat().st_size,
        }
    files[SCHEMA_FILENAME] = {
        "rows": None,
        "sha256": _sha256_text(schema_text),
        "bytes": len(schema_text.encode("utf-8")),
    }
    stats = (
        token_stats([*train_rows, *valid_rows], count_tokens)
        if count_tokens is not None
        else None
    )
    document = build_manifest(
        prompt_version=prompt_version,
        prompt_set_path=prompt_set_path,
        prompt_set_content_fingerprint=prompt_set_content_fingerprint(prompt_set_path),
        accepted_path=accepted_path,
        train_rows=train_rows,
        valid_rows=valid_rows,
        dev_eval_rows=dev_eval_rows,
        heldout_rows=heldout_rows,
        heldout_seeds=heldout_seeds,
        files=files,
        stats=stats,
    )
    (out_dir / MANIFEST_FILENAME).write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return document


def check_bundle(
    out_dir: Path, *, prompt_set_path: Path, heldout_seeds: Sequence[int]
) -> tuple[str, ...]:
    """Re-render the deterministic files and report drift from the manifest.

    ``train.jsonl`` depends on the git-ignored accepted file, so it is hashed
    only when present; ``valid.jsonl``, ``dev-eval.jsonl``, ``heldout.jsonl``,
    and ``schema.json`` are recomputed from the frozen prompt set and compared
    with the manifest whether or not the local files exist.
    """

    manifest_path = out_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return (f"missing_manifest:{_relative(manifest_path)}",)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION
    ):
        return (f"unsupported_manifest:{_relative(manifest_path)}",)
    problems: list[str] = []
    prompt_version = cast(PromptVersion, manifest.get("prompt_version"))
    if prompt_version not in PHASE03C_COMPILER_VERSIONS:
        return (f"prompt_version:{prompt_version}",)
    if manifest.get("compiler_version") != PHASE03C_COMPILER_VERSIONS[prompt_version]:
        problems.append("compiler_version")
    spec = QWEN3_8B_BF16_SPEC
    base = manifest.get("base_model", {})
    if base.get("model") != spec.source_lineage or base.get("revision") != (
        spec.source_revision
    ):
        problems.append("base_model")
    if manifest.get("prompt_set", {}).get(
        "content_fingerprint"
    ) != prompt_set_content_fingerprint(prompt_set_path):
        problems.append("prompt_set_content_fingerprint")
    schema_text = json.dumps(schema_document(), indent=2, sort_keys=True) + "\n"
    if manifest.get("schema_fingerprint") != _sha256_text(
        _canonical_json(schema_document())
    ):
        problems.append("schema_fingerprint")
    files = manifest.get("files", {})
    prompt_rows = load_prompt_set_manifest(prompt_set_path)
    expected: dict[str, str] = {
        SCHEMA_FILENAME: _sha256_text(schema_text),
        VALID_FILENAME: dataset_rows_sha256(
            build_dev_rows(prompt_rows, prompt_version=prompt_version)
        ),
        DEV_EVAL_FILENAME: rows_sha256(
            build_dev_eval_rows(prompt_rows, prompt_version=prompt_version)
        ),
        HELDOUT_FILENAME: rows_sha256(
            build_heldout_rows(seeds=heldout_seeds, prompt_version=prompt_version)
        ),
    }
    for name, sha in expected.items():
        if files.get(name, {}).get("sha256") != sha:
            problems.append(f"manifest_drift:{name}")
    for name in (TRAIN_FILENAME, VALID_FILENAME, DEV_EVAL_FILENAME, HELDOUT_FILENAME):
        path = out_dir / name
        if path.is_file() and sha256_file(path) != files.get(name, {}).get("sha256"):
            problems.append(f"file_drift:{name}")
    schema_path = out_dir / SCHEMA_FILENAME
    if schema_path.is_file() and schema_path.read_text(encoding="utf-8") != (
        schema_text
    ):
        problems.append(f"file_drift:{SCHEMA_FILENAME}")
    return tuple(problems)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / DEFAULT_OUT_DIR)
    parser.add_argument(
        "--prompt-version", choices=tuple(PHASE03C_COMPILER_VERSIONS), default="v6"
    )
    parser.add_argument(
        "--manifest", type=Path, default=PROJECT_ROOT / PROMPT_SET_MANIFEST_PATH
    )
    parser.add_argument("--heldout-seed-first", type=int, default=950)
    parser.add_argument("--heldout-seed-last", type=int, default=959)
    parser.add_argument(
        "--tokenizer-path",
        type=Path,
        default=None,
        help="Qwen3 tokenizer snapshot; adds templated token stats to the manifest",
    )
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    seeds = tuple(range(args.heldout_seed_first, args.heldout_seed_last + 1))
    started = time.perf_counter()
    if args.check:
        problems = check_bundle(
            args.out_dir, prompt_set_path=args.manifest, heldout_seeds=seeds
        )
        elapsed = time.perf_counter() - started
        if problems:
            for problem in problems:
                print(problem)
            return 1
        print(f"phase03c cloud bundle is consistent ({elapsed:.1f}s)")
        return 0
    if args.accepted is None:
        raise SystemExit("--accepted is required unless --check is given")
    counter = (
        hf_token_counter(args.tokenizer_path)
        if args.tokenizer_path is not None
        else None
    )
    try:
        document = write_bundle(
            accepted_path=args.accepted,
            out_dir=args.out_dir,
            prompt_set_path=args.manifest,
            prompt_version=cast(PromptVersion, args.prompt_version),
            heldout_seeds=seeds,
            count_tokens=counter,
        )
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    elapsed = time.perf_counter() - started
    counts = cast(Mapping[str, int], document["counts"])
    files = cast(Mapping[str, Mapping[str, object]], document["files"])
    total_bytes = sum(int(cast(int, entry["bytes"])) for entry in files.values())
    print(
        f"phase03c cloud bundle written to {args.out_dir} in {elapsed:.1f}s: "
        f"train={counts['train']} valid={counts['valid']} "
        f"dev_eval={counts['dev_eval']} heldout={counts['heldout']} "
        f"bytes={total_bytes} fingerprint={document['dataset_fingerprint']}"
    )
    stats = document.get("token_stats")
    if isinstance(stats, dict):
        print(
            f"token lengths: max={stats['max']} p95={stats['p95']} "
            f"over_{stats['max_length']}={stats['over_max_length']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
