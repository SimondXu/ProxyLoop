"""The pinned P2 tokenizer. Loading fails loudly: P2 is never skipped."""

from __future__ import annotations

from functools import cache
from typing import Any, cast

REPO = "Qwen/Qwen3.5-9B"
REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"  # = S0-MOD-01's serving pin


@cache
def load_tokenizer() -> Any:
    from transformers import AutoTokenizer

    try:
        tok = AutoTokenizer.from_pretrained(REPO, revision=REVISION)  # pyright: ignore[reportUnknownMemberType]
    except Exception as exc:  # network, cache or revision problems
        raise RuntimeError(
            f"P2 needs the tokenizer {REPO}@{REVISION}; it could not be loaded: {exc}"
        ) from exc
    return cast(Any, tok)


def encode(text: str) -> list[int]:
    return list(load_tokenizer().encode(text, add_special_tokens=False))


def template_ids(messages: list[dict[str, str]]) -> list[int]:
    """The ids of ``apply_chat_template(tokenize=True)``, thinking off."""

    out = load_tokenizer().apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, enable_thinking=False
    )
    ids = out["input_ids"] if not isinstance(out, list) else out
    return [int(i) for i in ids]
