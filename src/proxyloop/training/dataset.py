"""SFT rows from stored FastViews, through the one renderer (TRAINING §6, I3).

The prompt is ``render_prompt`` and nothing else (AGENTS rule 4); the completion is
the teacher turn in canonical form plus ``<|im_end|>``. Prompt and completion are
tokenised separately, as vLLM sees them (prompt ids, then generated ids).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from proxyloop.contract.protocol import (
    ChatTokenizer,
    ParseIssue,
    fingerprint,
    format_turn,
    parse_turn,
    render_prompt,
)
from proxyloop.contract.views import FastView
from proxyloop.training.masking import IGNORE_INDEX, IM_END

# TRAINING §8: an over-long row is a bug; the run aborts, the row is never dropped.
MAX_SEQ_TOKENS = 4096
TOKEN_BUDGET = 16384  # padded tokens per micro-batch (rows x longest row)


class Tokenizer(ChatTokenizer, Protocol):
    def encode(self, text: str, add_special_tokens: bool = ...) -> list[int]: ...


@dataclass(frozen=True)
class Row:
    profile: str
    fingerprint: str
    prompt: str
    completion: str


def build_row(view: FastView, profile: str, teacher_raw: str, tok: Tokenizer) -> Row:
    items = parse_turn(teacher_raw, view.lane)
    if issues := [i.reason for i in items if isinstance(i, ParseIssue)]:
        raise ValueError(f"the teacher turn has parse issues {issues}: not a target")
    return Row(
        profile=profile,
        fingerprint=fingerprint(profile),
        prompt=render_prompt(view, profile, tok),
        completion=format_turn(items) + IM_END,
    )


def tokenize_row(row: Row, tok: Tokenizer) -> dict[str, list[int]]:
    """``input_ids`` and ``labels``: the prompt is masked, the completion trained."""
    prompt = tok.encode(row.prompt, add_special_tokens=False)
    completion = tok.encode(row.completion, add_special_tokens=False)
    if len(prompt) + len(completion) > MAX_SEQ_TOKENS:
        raise ValueError(
            f"row has {len(prompt) + len(completion)} tokens > {MAX_SEQ_TOKENS}"
        )
    return {
        "input_ids": prompt + completion,
        "labels": [IGNORE_INDEX] * len(prompt) + completion,
    }


def max_padded_tokens(micro_batches: Iterable[list[int]], lengths: list[int]) -> int:
    """Largest padded size (rows x longest row) over planned micro-batches of row
    indices; raises over ``TOKEN_BUDGET`` before any training step runs."""
    worst = max(len(b) * max(lengths[i] for i in b) for b in micro_batches)
    if worst > TOKEN_BUDGET:
        raise ValueError(f"a micro-batch pads to {worst} > {TOKEN_BUDGET} tokens")
    return worst
