"""Prepare or verify the small Phase 03B train/dev-only artifact set."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from proxyloop_evaluation.phase03b_experiment import (
    EXPERIMENT_DIR,
    ROOT,
    check_phase03b_artifacts,
    write_phase03b_artifacts,
)
from proxyloop_evaluation.qwen_mlx import (
    QwenCheckpointAttestation,
    attest_qwen_checkpoint,
)


def _load_local_tokenizer(model_path: Path) -> tuple[Any, str]:
    """Load only the tokenizer, with network access explicitly disabled."""

    from transformers import AutoTokenizer, __version__

    return (
        AutoTokenizer.from_pretrained(str(model_path), local_files_only=True),
        __version__,
    )


def _token_count(tokenizer: Any, messages: list[dict[str, str]], **kwargs: Any) -> int:
    tokens = tokenizer.apply_chat_template(
        messages,
        tools=None,
        return_dict=False,
        **kwargs,
    )
    return len(tokens)


def verify_token_fit(
    model_path: Path,
    *,
    root: Path = ROOT,
    tokenizer_loader: Callable[[Path], tuple[Any, str]] = _load_local_tokenizer,
    checkpoint_attester: Callable[
        [str], QwenCheckpointAttestation
    ] = attest_qwen_checkpoint,
) -> tuple[str, ...]:
    """Verify committed messages against one attested local tokenizer.

    This function is intentionally read-only.  It follows MLX-LM's
    ``ChatDataset`` calls for masked-prompt training: the full sequence is
    tokenized once, then the prompt is tokenized without the assistant target
    and with a generation prompt.
    """

    directory = root / EXPERIMENT_DIR.relative_to(ROOT)
    manifest_path = directory / "manifest.json"
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return (f"manifest_unreadable:{error}",)

    try:
        tokenizer, tokenizer_version = tokenizer_loader(model_path)
    except (AttributeError, ImportError, OSError, TypeError, ValueError) as error:
        return (f"tokenizer_load_error:{error}",)
    try:
        attestation = checkpoint_attester(str(model_path))
    except (AttributeError, OSError, TypeError, ValueError) as error:
        return (f"checkpoint_attestation_error:{error}",)

    base = manifest.get("base_checkpoint")
    if not isinstance(base, dict):
        return ("manifest_base_checkpoint_missing",)
    for field in (
        "model_revision",
        "source_revision",
        "checkpoint_fingerprint",
        "tokenizer_fingerprint",
        "chat_template_fingerprint",
    ):
        actual = getattr(attestation, field)
        if base.get(field) != actual:
            errors.append(f"checkpoint_identity_drift:{field}")

    token_fit = manifest.get("token_fit")
    if not isinstance(token_fit, dict):
        return ("manifest_token_fit_missing",)
    if token_fit.get("tokenizer_library") != "transformers":
        errors.append("tokenizer_library_drift")
    if token_fit.get("tokenizer_version") != tokenizer_version:
        errors.append("tokenizer_version_drift")
    if token_fit.get("checkpoint_fingerprint") != attestation.checkpoint_fingerprint:
        errors.append("token_fit_checkpoint_fingerprint_drift")
    if token_fit.get("tokenizer_fingerprint") != attestation.tokenizer_fingerprint:
        errors.append("token_fit_tokenizer_fingerprint_drift")
    max_sequence_length = token_fit.get("max_sequence_length")
    if not isinstance(max_sequence_length, int) or max_sequence_length < 1:
        return ("token_fit_max_sequence_length_invalid",)
    if token_fit.get("truncation") is not False:
        errors.append("token_fit_truncation_must_be_false")

    full_counts: list[tuple[str, int]] = []
    prompt_counts: list[tuple[str, int]] = []
    for filename in ("train.jsonl", "valid.jsonl"):
        path = directory / filename
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            errors.append(f"artifact_unreadable:{filename}:{error}")
            continue
        for line_number, line in enumerate(lines, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                errors.append(f"invalid_json:{filename}:{line_number}")
                continue
            if not isinstance(row, dict) or set(row) != {"messages"}:
                errors.append(f"messages_only_violation:{filename}:{line_number}")
                continue
            messages = row.get("messages")
            if not isinstance(messages, list) or not messages:
                errors.append(f"messages_invalid:{filename}:{line_number}")
                continue
            label = f"{filename}:{line_number}"
            try:
                full_count = _token_count(tokenizer, messages)
                prompt_count = _token_count(
                    tokenizer,
                    messages[:-1],
                    add_generation_prompt=messages[-1].get("role") == "assistant",
                )
            except (
                AttributeError,
                IndexError,
                KeyError,
                TypeError,
                ValueError,
            ) as error:
                errors.append(f"tokenizer_error:{label}:{error}")
                continue
            full_counts.append((label, full_count))
            prompt_counts.append((label, prompt_count))

    if len(full_counts) != 26 or len(prompt_counts) != 26:
        errors.append("token_fit_row_count_drift")
    if full_counts and prompt_counts:
        observed = {
            "rows": len(full_counts),
            "full_training_sequence_tokens": {
                "min": min(count for _, count in full_counts),
                "max": max(count for _, count in full_counts),
                "max_row": max(full_counts, key=lambda item: item[1])[0],
            },
            "evaluation_prompt_tokens": {
                "min": min(count for _, count in prompt_counts),
                "max": max(count for _, count in prompt_counts),
                "max_row": max(prompt_counts, key=lambda item: item[1])[0],
            },
        }
        if token_fit.get("observed") != observed:
            errors.append("token_fit_observed_drift")
        if any(
            count > max_sequence_length for _, count in (*full_counts, *prompt_counts)
        ):
            errors.append("token_fit_exceeds_max_sequence_length")

    return tuple(errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify-token-fit", action="store_true")
    parser.add_argument("--model-path")
    args = parser.parse_args()
    if args.verify_token_fit:
        if args.check or not args.model_path:
            parser.error(
                "--verify-token-fit requires --model-path and cannot write artifacts"
            )
        errors = verify_token_fit(Path(args.model_path))
        if errors:
            for error in errors:
                print(error)
            return 1
        print("phase03b token fit: verified")
        return 0
    if args.model_path:
        parser.error("--model-path is only valid with --verify-token-fit")
    if args.check:
        errors = check_phase03b_artifacts()
        if errors:
            for error in errors:
                print(error)
            return 1
        print("phase03b experiment artifacts: ok")
        return 0
    write_phase03b_artifacts()
    print("phase03b experiment artifacts: written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
