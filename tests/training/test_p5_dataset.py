"""P5 and dataset rows under the pinned tokenizer (Qwen/Qwen3.5-9B@c202236)."""

from __future__ import annotations

import json
from functools import cache
from typing import Any, cast

import pytest
from tests.golden.cases import GOLDEN
from tests.golden.tokenizer import load_tokenizer

from proxyloop.contract.protocol import EMPTY_THINK, fingerprint, render_prompt
from proxyloop.contract.views import FastView
from proxyloop.training.dataset import (
    MAX_SEQ_TOKENS,
    TOKEN_BUDGET,
    Row,
    build_row,
    max_padded_tokens,
    tokenize_row,
)
from proxyloop.training.masking import (
    IGNORE_INDEX,
    IM_END,
    verify_batch,
    verify_trained_span,
)
from training_jobs import sft

GOLDEN_VIEWS = sorted((GOLDEN / "views").glob("*.json"))


@cache
def tok() -> Any:
    return cast(Any, load_tokenizer())


def golden() -> list[tuple[str, str]]:
    docs = [json.loads(p.read_text("utf-8")) for p in GOLDEN_VIEWS]
    return [(d["profile"], json.dumps(d["view"])) for d in docs]


@cache
def smoke() -> list[tuple[Row, dict[str, list[int]]]]:
    """The 64 train-smoke rows, built exactly as training_jobs.sft.train builds them."""
    out: list[tuple[Row, dict[str, list[int]]]] = []
    for profile, view, turn in sft.smoke_rows(golden()):
        row = build_row(FastView.model_validate_json(view), profile, turn, tok())
        out.append((row, tokenize_row(row, tok())))
    return out


def test_smoke_rows_cover_every_golden_view_and_render_through_the_contract():
    rows = sft.smoke_rows(golden())
    assert len(rows) == 64 and {v for _, v, _ in rows} == {v for _, v in golden()}
    for (profile, view, _), (row, _) in zip(rows, smoke(), strict=True):
        fast_view = FastView.model_validate_json(view)
        assert row.prompt == render_prompt(fast_view, profile, tok())
        assert row.prompt.endswith(EMPTY_THINK)
        assert row.fingerprint == fingerprint(profile)
        assert row.completion.endswith(IM_END) and not row.completion.startswith(" ")


def test_p5_passes_on_every_smoke_row():
    for row, data in smoke():
        report = verify_trained_span(
            data["input_ids"], data["labels"], tok(), row.completion
        )
        assert report["ok"], report
        assert report["trained_text_equals_target"]
        assert report["masked_prefix_ends_with_empty_think"]
        assert report["ends_with_im_end_id"]


def pad_batch(rows: list[dict[str, list[int]]], pad_id: int) -> dict[str, Any]:
    width = max(len(r["input_ids"]) for r in rows)

    def pad(xs: list[int], value: int) -> list[int]:
        return xs + [value] * (width - len(xs))

    return {
        "input_ids": [pad(r["input_ids"], pad_id) for r in rows],
        "labels": [pad(r["labels"], IGNORE_INDEX) for r in rows],
        "attention_mask": [pad([1] * len(r["input_ids"]), 0) for r in rows],
    }


def test_p5_on_a_right_padded_batch():
    picked = [smoke()[0], smoke()[5], smoke()[12]]  # different lengths and lanes
    batch = pad_batch([d for _, d in picked], tok().pad_token_id)
    targets = {tuple(d["input_ids"]): r.completion for r, d in picked}
    assert all(r["ok"] for r in verify_batch(batch, tok(), targets))


def test_p5_catches_label_drift():
    row, data = smoke()[1]
    ids, labels = data["input_ids"], data["labels"]
    start = labels.index(next(x for x in labels if x != IGNORE_INDEX))
    # One prompt token too many trained (the classic off-by-one of a template change).
    early = [*labels[: start - 1], ids[start - 1], *labels[start:]]
    report = verify_trained_span(ids, early, tok(), row.completion)
    assert not report["ok"] and not report["trained_text_equals_target"]
    assert not report["masked_prefix_ends_with_empty_think"]
    # <|im_end|> masked out: the model would never learn to stop.
    no_end = [*labels[:-1], IGNORE_INDEX]
    report = verify_trained_span(ids, no_end, tok(), row.completion)
    assert not report["ok"] and not report["ends_with_im_end_id"]
    # A hole in the span.
    hole = [*labels[: start + 1], IGNORE_INDEX, *labels[start + 2 :]]
    report = verify_trained_span(ids, hole, tok(), row.completion)
    assert not report["ok"] and not report["contiguous"]
    # Labels that are not the input ids.
    wrong = [*labels[:-1], labels[-1] + 1]
    report = verify_trained_span(ids, wrong, tok(), row.completion)
    assert not report["ok"] and not report["labels_equal_input_ids"]
    # Nothing trained at all.
    assert not verify_trained_span(ids, [IGNORE_INDEX] * len(ids), tok(), IM_END)["ok"]


def test_p5_rejects_a_target_without_im_end_and_mismatched_lengths():
    _, data = smoke()[0]
    with pytest.raises(ValueError, match="im_end"):
        verify_trained_span(data["input_ids"], data["labels"], tok(), "Hello.")
    with pytest.raises(ValueError, match="labels"):
        verify_trained_span(data["input_ids"], data["labels"][1:], tok(), IM_END)


def test_teacher_turn_with_a_parse_issue_is_not_a_training_target():
    profile, view = golden()[0]
    fast_view = FastView.model_validate_json(view)
    for raw in ("", "@dance", "@slow: REVOKE everything"):
        with pytest.raises(ValueError, match="parse issues"):
            build_row(fast_view, profile, raw, tok())


def test_over_long_row_raises_instead_of_being_dropped():
    row, _ = smoke()[0]
    long = Row(row.profile, row.fingerprint, row.prompt, "word " * MAX_SEQ_TOKENS)
    with pytest.raises(ValueError, match=str(MAX_SEQ_TOKENS)):
        tokenize_row(long, tok())


def test_token_budget_is_rows_times_longest_row():
    lengths = [100, 4000, 3000, 50]
    assert max_padded_tokens([[0, 3], [1, 2]], lengths) == 8000
    with pytest.raises(ValueError, match=str(TOKEN_BUDGET)):
        max_padded_tokens([[0, 1, 2, 3, 3]], lengths)
