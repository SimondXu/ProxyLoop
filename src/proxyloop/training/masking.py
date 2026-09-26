"""P5, the label self-check (ARCHITECTURE §12, TRAINING §6), as a pure function.

Port of the v0 idea (``v0-legacy:ml/training/phase03c_cloud/train.py:359-393``) over
one collated row instead of a trainer: the tokens that reach the loss must be exactly
the target completion (ending in ``<|im_end|>``), and the masked prefix must end with
the empty think block the renderer appends.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from proxyloop.contract.protocol import EMPTY_THINK

IGNORE_INDEX = -100
IM_END = "<|im_end|>"  # ends every training completion (TRAINING §6)


class Decoder(Protocol):
    def decode(self, token_ids: list[int], skip_special_tokens: bool = ...) -> str: ...

    def convert_tokens_to_ids(self, tokens: str) -> int: ...


def verify_trained_span(
    input_ids: Sequence[int],
    labels: Sequence[int],
    tokenizer: Decoder,
    expected_completion: str,
) -> dict[str, Any]:
    """Report on one row of a real batch; ``ok`` is the P5 verdict.

    Right padding is allowed after the trained span (label ``IGNORE_INDEX``); the
    trained positions must form one run whose labels equal the input ids.
    """
    if len(input_ids) != len(labels):
        raise ValueError(f"{len(input_ids)} input ids but {len(labels)} labels")
    if not expected_completion.endswith(IM_END):
        raise ValueError(f"the target completion must end with {IM_END}")
    trained = [i for i, label in enumerate(labels) if label != IGNORE_INDEX]
    contiguous = bool(trained) and trained == list(range(trained[0], trained[-1] + 1))
    start = trained[0] if trained else len(labels)
    trained_ids = [input_ids[i] for i in trained]
    trained_text = tokenizer.decode(trained_ids, skip_special_tokens=False)
    prefix_text = tokenizer.decode(list(input_ids[:start]), skip_special_tokens=False)
    im_end = tokenizer.convert_tokens_to_ids(IM_END)
    report: dict[str, Any] = {
        "trained_tokens": len(trained),
        "masked_prefix_tokens": start,
        "contiguous": contiguous,
        "labels_equal_input_ids": all(labels[i] == input_ids[i] for i in trained),
        "ends_with_im_end_id": trained_ids[-1:] == [im_end],
        "trained_text_equals_target": trained_text == expected_completion,
        "masked_prefix_ends_with_empty_think": prefix_text.endswith(EMPTY_THINK),
        "trained_text_head": trained_text[:80],
        "trained_text_tail": trained_text[-40:],
    }
    report["ok"] = all(
        report[k]
        for k in (
            "contiguous",
            "labels_equal_input_ids",
            "ends_with_im_end_id",
            "trained_text_equals_target",
            "masked_prefix_ends_with_empty_think",
        )
    )
    return report


def verify_batch(
    batch: dict[str, list[list[int]]],
    tokenizer: Decoder,
    targets: dict[tuple[int, ...], str],
) -> list[dict[str, Any]]:
    """P5 over every row of a collated, right-padded batch (lists, not tensors);
    ``targets`` maps each unpadded row's input ids to its completion."""
    rows = zip(
        batch["input_ids"], batch["labels"], batch["attention_mask"], strict=True
    )
    return [
        verify_trained_span(ids, labels, tokenizer, targets[tuple(ids[: sum(mask)])])
        for ids, labels, mask in rows
    ]
