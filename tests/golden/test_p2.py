"""P2: HF token ids of the golden prompts under the pinned tokenizer.

These tests load ``Qwen/Qwen3.5-9B`` at a fixed revision and fail (never skip)
when it cannot be loaded.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.contract.protocol import (
    EMPTY_THINK,
    PROFILES,
    render_messages,
    render_prompt,
)
from tests.golden.cases import CASES, GOLDEN, Case
from tests.golden.tokenizer import (
    REPO,
    REVISION,
    encode,
    load_tokenizer,
    template_ids,
)

P2: dict[str, Any] = json.loads((GOLDEN / "p2_ids.json").read_text("utf-8"))


def _ids(name: str) -> list[int]:
    return [int(i) for i in P2["cases"][name].split()]


def test_pinned_tokenizer_and_empty_think_bytes() -> None:
    assert P2["tokenizer"] == {"repo": REPO, "revision": REVISION}
    think = P2["empty_think"]
    assert think["text"] == EMPTY_THINK
    assert bytes.fromhex(think["hex"]) == b"<think>\n\n</think>\n\n"
    assert encode(EMPTY_THINK) == think["ids"]
    minimal = [{"role": "user", "content": "Hi"}]
    text = load_tokenizer().apply_chat_template(
        minimal, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    assert text.endswith("<|im_start|>assistant\n" + EMPTY_THINK)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_golden_ids(case: Case) -> None:
    prompt = render_prompt(case.view(), case.profile, load_tokenizer())
    assert encode(prompt) == _ids(case.name)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_chat_template_paths_agree(case: Case) -> None:
    """tokenize=True ids == tokenize=False text + encode (the escalation check)."""

    messages = [
        m.model_dump(include={"role", "content"})
        for m in render_messages(case.view(), case.profile)
    ]
    ids = template_ids(messages)
    assert ids == _ids(case.name)
    assert ids[-len(P2["empty_think"]["ids"]) :] == P2["empty_think"]["ids"]


def test_profile_digests_bind_the_committed_ids() -> None:
    for name, profile in PROFILES.items():
        ids = {c.name: _ids(c.name) for c in CASES if c.profile == name}
        digest = sha256_text(canonical_json(ids))
        assert P2["profiles"][name] == digest == profile.p2_ids_sha256


def test_worst_case_is_recorded() -> None:
    lengths = {c.name: len(_ids(c.name)) for c in CASES}
    worst = max(lengths, key=lambda n: lengths[n])
    assert P2["worst_case"] == {"case": worst, "tokens": lengths[worst]}
