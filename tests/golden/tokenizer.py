"""The pinned P2 tokenizer. Loading fails loudly: P2 is never skipped."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from functools import cache
from typing import Any, Protocol, cast

REPO = "Qwen/Qwen3.5-9B"
REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"  # = S0-MOD-01's serving pin


class HFTokenizer(Protocol):
    """The two HF tokenizer methods P2 uses (transformers ships no usable types)."""

    def encode(self, text: str, add_special_tokens: bool = ...) -> list[int]: ...

    def apply_chat_template(
        self, conversation: list[dict[str, str]], /, **kwargs: Any
    ) -> Any: ...


@cache
def load_tokenizer() -> HFTokenizer:
    transformers: Any = importlib.import_module("transformers")
    try:
        tok = transformers.AutoTokenizer.from_pretrained(REPO, revision=REVISION)
    except Exception as exc:  # network, cache or revision problems
        raise RuntimeError(
            f"P2 needs the tokenizer {REPO}@{REVISION}; it could not be loaded: {exc}"
        ) from exc
    return cast(HFTokenizer, tok)


def encode(text: str) -> list[int]:
    return list(load_tokenizer().encode(text, add_special_tokens=False))


def template_ids(messages: list[dict[str, str]]) -> list[int]:
    """The ids of ``apply_chat_template(tokenize=True)``, thinking off."""

    out = load_tokenizer().apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, enable_thinking=False
    )
    return list(cast(Mapping[str, list[int]], out)["input_ids"])
