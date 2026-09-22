"""Chat-format training data for ``mlx_lm.lora`` from accepted teacher rows.

``train.jsonl`` carries the accepted records' ``messages`` verbatim after
proving that each system/user pair is byte-equal to the frozen prompt builder
for the prompt-set row it names (the 03A1-V train/eval drift lesson).
``valid.jsonl`` carries the oracle-labelled development rows with the same
prompt and the canonical oracle target as the assistant turn.  Development
prompt ids never appear in the train file.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from proxyloop_evaluation.phase03b_readiness import proposed_fast_target
from proxyloop_evaluation.phase03c_experiment import (
    PHASE03C_COMPILER_VERSIONS,
    PromptVersion,
)
from proxyloop_evaluation.phase03c_prompt_set import (
    PromptSetRow,
    prompt_builder,
    render_prompt_view,
    resolve_row,
)

DATASET_MANIFEST_SCHEMA_VERSION: Final = "phase-03c-training-dataset-v1"
DATASET_MANIFEST_FILENAME: Final = "dataset-manifest.json"
TRAIN_FILENAME: Final = "train.jsonl"
VALID_FILENAME: Final = "valid.jsonl"
_ACCEPTED_SUFFIX: Final = "-accepted.jsonl"
_TEACHER_MANIFEST_SUFFIX: Final = "-phase-03c-teacher-manifest.json"
_RECORD_KEYS: Final = frozenset(
    {
        "content_hash",
        "generator",
        "lexical_fingerprint",
        "messages",
        "prompt_fingerprint",
        "prompt_id",
        "schema_fingerprint",
    }
)
_ROLES: Final = ("system", "user", "assistant")

# ``apply_chat_template(messages, return_dict=False)`` -> token ids, as the
# mlx_lm ``ChatDataset`` calls it; injected so tests never load a tokenizer.
ChatTokenCounter = Callable[[Sequence[Mapping[str, str]]], int]


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class AcceptedRecord:
    """One git-ignored accepted teacher row as ``teacher_pipeline`` wrote it."""

    prompt_id: str
    content_hash: str
    messages: tuple[dict[str, str], ...]

    @property
    def system(self) -> str:
        return self.messages[0]["content"]

    @property
    def user(self) -> str:
        return self.messages[1]["content"]

    @property
    def assistant(self) -> str:
        return self.messages[2]["content"]


@dataclass(frozen=True, slots=True)
class DatasetRow:
    """One ``{"messages": [...]}`` line plus the metadata the manifest counts."""

    prompt_id: str
    family_id: str
    split: str
    messages: tuple[dict[str, str], ...]

    def to_line(self) -> str:
        return json.dumps({"messages": list(self.messages)}, ensure_ascii=False)


def _message(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


def read_accepted_records(path: Path) -> tuple[AcceptedRecord, ...]:
    """Parse the accepted JSONL and reject any record that is not a full triple."""

    records: list[AcceptedRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            document = json.loads(line)
            if not isinstance(document, dict) or set(document) != _RECORD_KEYS:
                raise ValueError(f"accepted_record_shape:{path.name}:{line_number}")
            messages = document["messages"]
            if not isinstance(messages, list) or [
                item.get("role") if isinstance(item, dict) else None
                for item in messages
            ] != list(_ROLES):
                raise ValueError(f"accepted_record_roles:{path.name}:{line_number}")
            if any(not isinstance(item["content"], str) for item in messages):
                raise ValueError(f"accepted_record_content:{path.name}:{line_number}")
            records.append(
                AcceptedRecord(
                    prompt_id=str(document["prompt_id"]),
                    content_hash=str(document["content_hash"]),
                    messages=tuple(
                        _message(str(item["role"]), str(item["content"]))
                        for item in messages
                    ),
                )
            )
    if not records:
        raise ValueError(f"accepted_records_empty:{path}")
    return tuple(records)


def teacher_manifest_path(accepted_path: Path) -> Path:
    """The committed ``<model>-phase-03c-teacher-manifest.json`` sibling."""

    name = accepted_path.name
    if not name.endswith(_ACCEPTED_SUFFIX):
        raise ValueError(f"accepted_path_name:{name}")
    model = name[: -len(_ACCEPTED_SUFFIX)]
    return accepted_path.with_name(model + _TEACHER_MANIFEST_SUFFIX)


def rows_by_prompt_id(rows: Iterable[PromptSetRow]) -> dict[str, PromptSetRow]:
    return {row.prompt_id: row for row in rows}


def rendered_prompt_pair(
    row: PromptSetRow, *, prompt_version: PromptVersion
) -> tuple[str, str]:
    """The (system, user) pair the frozen builder renders for ``row``."""

    scenario, position = resolve_row(row)
    prompt = prompt_builder(prompt_version).build_prompt(
        render_prompt_view(scenario, position)
    )
    if prompt.fingerprint != row.prompt_fingerprint:
        raise ValueError(f"prompt_fingerprint_drift:{row.prompt_id}")
    return prompt.system, prompt.user


def build_train_rows(
    records: Sequence[AcceptedRecord],
    rows: Mapping[str, PromptSetRow],
    *,
    prompt_version: PromptVersion,
) -> tuple[DatasetRow, ...]:
    """Accepted messages verbatim, after proving prompt byte-equality per row.

    Every record must name a ``train`` row of the prompt set, and its system
    and user text must equal the builder's output byte-for-byte; any
    mismatch fails the whole dataset rather than dropping the row.
    """

    rendered: dict[str, tuple[str, str]] = {}
    output: list[DatasetRow] = []
    for record in records:
        row = rows.get(record.prompt_id)
        if row is None:
            raise ValueError(f"unknown_prompt_id:{record.prompt_id}")
        if row.split != "train":
            raise ValueError(f"non_train_prompt_in_accepted:{record.prompt_id}")
        if record.prompt_id not in rendered:
            rendered[record.prompt_id] = rendered_prompt_pair(
                row, prompt_version=prompt_version
            )
        system, user = rendered[record.prompt_id]
        if record.system != system:
            raise ValueError(f"system_prompt_mismatch:{record.prompt_id}")
        if record.user != user:
            raise ValueError(f"user_prompt_mismatch:{record.prompt_id}")
        output.append(
            DatasetRow(
                prompt_id=record.prompt_id,
                family_id=row.family_id,
                split="train",
                messages=record.messages,
            )
        )
    return tuple(output)


def canonical_dev_target(oracle_action: str) -> str:
    """The assistant text of a development row: the oracle target, canonical."""

    return canonical_json(proposed_fast_target(oracle_action))


def build_dev_rows(
    rows: Iterable[PromptSetRow], *, prompt_version: PromptVersion
) -> tuple[DatasetRow, ...]:
    """Every development row with the same prompt and its oracle target."""

    output: list[DatasetRow] = []
    for row in rows:
        if row.split != "development":
            continue
        system, user = rendered_prompt_pair(row, prompt_version=prompt_version)
        output.append(
            DatasetRow(
                prompt_id=row.prompt_id,
                family_id=row.family_id,
                split="development",
                messages=(
                    _message("system", system),
                    _message("user", user),
                    _message("assistant", canonical_dev_target(row.oracle_action)),
                ),
            )
        )
    if not output:
        raise ValueError("no development rows in the prompt set")
    return tuple(output)


def assert_splits_disjoint(
    train_rows: Sequence[DatasetRow], dev_rows: Sequence[DatasetRow]
) -> None:
    overlap = {row.prompt_id for row in train_rows} & {
        row.prompt_id for row in dev_rows
    }
    if overlap:
        raise ValueError(f"development_prompt_in_train:{sorted(overlap)[:3]}")


def write_jsonl(path: Path, rows: Sequence[DatasetRow]) -> str:
    """Write one compact line per row and return the file's SHA-256."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(row.to_line() + "\n")
    return sha256_file(path)


def _percentile(values: Sequence[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def measure_token_stats(
    rows: Sequence[DatasetRow],
    count_tokens: ChatTokenCounter,
    *,
    max_seq_length: int,
) -> dict[str, object]:
    """Length of every fully templated conversation, as the trainer sees it.

    ``mlx_lm`` truncates the *tail* of any sequence longer than
    ``max_seq_length`` with only a warning, which would silently cut the
    assistant target; the count of such rows is recorded so the runner can
    refuse to train on them.
    """

    lengths = [count_tokens(row.messages) for row in rows]
    over = [
        row.prompt_id
        for row, length in zip(rows, lengths, strict=True)
        if length > max_seq_length
    ]
    return {
        "rows": len(lengths),
        "max": max(lengths),
        "min": min(lengths),
        "p95": _percentile(lengths, 0.95),
        "total": sum(lengths),
        "max_seq_length": max_seq_length,
        "over_max_seq_length": len(over),
        "over_max_seq_length_prompt_ids": over[:20],
    }


def _family_counts(rows: Sequence[DatasetRow]) -> dict[str, int]:
    return dict(sorted(Counter(row.family_id for row in rows).items()))


def dataset_manifest(
    *,
    train_rows: Sequence[DatasetRow],
    dev_rows: Sequence[DatasetRow],
    train_sha256: str,
    valid_sha256: str,
    prompt_version: PromptVersion,
    prompt_set_content_fingerprint: str,
    accepted_path: Path,
    accepted_sha256: str,
    teacher_manifest_sha256: str | None,
    token_stats: Mapping[str, object] | None,
) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": DATASET_MANIFEST_SCHEMA_VERSION,
        "prompt_version": prompt_version,
        "compiler_version": PHASE03C_COMPILER_VERSIONS[prompt_version],
        "prompt_set_content_fingerprint": prompt_set_content_fingerprint,
        "accepted_source": {
            "path": accepted_path.as_posix(),
            "sha256": accepted_sha256,
            "teacher_manifest_sha256": teacher_manifest_sha256,
        },
        "files": {
            TRAIN_FILENAME: {"rows": len(train_rows), "sha256": train_sha256},
            VALID_FILENAME: {"rows": len(dev_rows), "sha256": valid_sha256},
        },
        "split_counts": {"train": len(train_rows), "development": len(dev_rows)},
        "train_prompt_count": len({row.prompt_id for row in train_rows}),
        "family_counts": {
            "train": _family_counts(train_rows),
            "development": _family_counts(dev_rows),
        },
        "token_stats": dict(token_stats) if token_stats is not None else None,
    }
    document["dataset_fingerprint"] = sha256_text(canonical_json(document))
    return document


def load_dataset_manifest(data_dir: Path) -> dict[str, object]:
    path = data_dir / DATASET_MANIFEST_FILENAME
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != DATASET_MANIFEST_SCHEMA_VERSION
    ):
        raise ValueError(f"unsupported dataset manifest: {path}")
    return document


def check_dataset_files(data_dir: Path, document: Mapping[str, object]) -> None:
    """Require the JSONL files next to the manifest to match its hashes."""

    files = document["files"]
    if not isinstance(files, dict):
        raise ValueError("dataset manifest files entry is not a mapping")
    for name in (TRAIN_FILENAME, VALID_FILENAME):
        expected = files[name]["sha256"]
        path = data_dir / name
        if not path.is_file():
            raise ValueError(f"dataset_file_missing:{name}")
        if sha256_file(path) != expected:
            raise ValueError(f"dataset_file_drift:{name}")


def write_dataset(
    *,
    accepted_path: Path,
    out_dir: Path,
    prompt_set_rows: Sequence[PromptSetRow],
    prompt_set_content_fingerprint: str,
    prompt_version: PromptVersion,
    count_tokens: ChatTokenCounter | None = None,
    max_seq_length: int = 2048,
) -> dict[str, object]:
    """Build both splits, write them, and return the written manifest."""

    records = read_accepted_records(accepted_path)
    index = rows_by_prompt_id(prompt_set_rows)
    train_rows = build_train_rows(records, index, prompt_version=prompt_version)
    dev_rows = build_dev_rows(prompt_set_rows, prompt_version=prompt_version)
    assert_splits_disjoint(train_rows, dev_rows)
    train_sha256 = write_jsonl(out_dir / TRAIN_FILENAME, train_rows)
    valid_sha256 = write_jsonl(out_dir / VALID_FILENAME, dev_rows)
    teacher_manifest = teacher_manifest_path(accepted_path)
    token_stats = (
        measure_token_stats(
            [*train_rows, *dev_rows], count_tokens, max_seq_length=max_seq_length
        )
        if count_tokens is not None
        else None
    )
    document = dataset_manifest(
        train_rows=train_rows,
        dev_rows=dev_rows,
        train_sha256=train_sha256,
        valid_sha256=valid_sha256,
        prompt_version=prompt_version,
        prompt_set_content_fingerprint=prompt_set_content_fingerprint,
        accepted_path=accepted_path,
        accepted_sha256=sha256_file(accepted_path),
        teacher_manifest_sha256=(
            sha256_file(teacher_manifest) if teacher_manifest.is_file() else None
        ),
        token_stats=token_stats,
    )
    (out_dir / DATASET_MANIFEST_FILENAME).write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return document


__all__ = [
    "DATASET_MANIFEST_FILENAME",
    "DATASET_MANIFEST_SCHEMA_VERSION",
    "TRAIN_FILENAME",
    "VALID_FILENAME",
    "AcceptedRecord",
    "ChatTokenCounter",
    "DatasetRow",
    "assert_splits_disjoint",
    "build_dev_rows",
    "build_train_rows",
    "canonical_dev_target",
    "canonical_json",
    "check_dataset_files",
    "dataset_manifest",
    "load_dataset_manifest",
    "measure_token_stats",
    "read_accepted_records",
    "rendered_prompt_pair",
    "rows_by_prompt_id",
    "sha256_file",
    "sha256_text",
    "teacher_manifest_path",
    "write_dataset",
    "write_jsonl",
]
