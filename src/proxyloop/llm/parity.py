"""P3 (ARCHITECTURE §12): vLLM ``/tokenize`` ids equal the committed P2 golden ids.

The kernel refuses to start a session whose ``ParityResult`` did not pass.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from proxyloop.llm.vllm import VLLMClient


@dataclass(frozen=True)
class GoldenPrompt:
    """One P2 case: its rendered messages, its ``render_prompt`` text (what vLLM
    is sent) and the ids P2 committed for them."""

    name: str
    messages: tuple[Mapping[str, str], ...]
    prompt: str
    ids: tuple[int, ...]


@dataclass(frozen=True)
class ParityResult:
    requested_model: str
    equal: Mapping[str, bool]  # per golden case: both /tokenize paths match

    @property
    def passed(self) -> bool:
        return bool(self.equal) and all(self.equal.values())


async def check_parity(
    client: VLLMClient, goldens: Sequence[GoldenPrompt]
) -> ParityResult:
    equal: dict[str, bool] = {}
    for golden in goldens:
        chat = await client.tokenize(messages=golden.messages)
        sent = await client.tokenize(prompt=golden.prompt)
        equal[golden.name] = tuple(chat) == tuple(sent) == golden.ids
    return ParityResult(requested_model=client.ref.model_id, equal=equal)
