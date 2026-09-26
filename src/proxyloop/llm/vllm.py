"""Fast on vLLM (ADR-0002): ``/v1/completions`` streaming with the pre-rendered prompt.

The prompt comes from ``contract.protocol.render_prompt`` (the one renderer);
this adapter never builds prompt text. Thinking is off in that prompt, so a
``reasoning_effort`` has no meaning here and is refused.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence

from proxyloop.contract.llm import LLMCallRecord, TextRequest, ToolRequest, ToolResponse
from proxyloop.llm.http import HTTPAdapter, Json


def _completion_text(chunk: Json) -> str | None:
    choices: list[Json] = chunk.get("choices") or []
    return "".join(c.get("text") or "" for c in choices) or None


class VLLMClient(HTTPAdapter):
    ENDPOINTS = ("vllm",)

    def stream_text(self, request: TextRequest) -> AsyncIterator[str | LLMCallRecord]:
        if request.prompt is None:
            raise ValueError("vLLM takes the pre-rendered prompt, not messages")
        if self.ref.reasoning_effort is not None:
            raise ValueError("the pre-rendered prompt turns thinking off")
        body: Json = {
            "model": self.ref.model_id,
            "prompt": request.prompt,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request.seed is not None:
            body["seed"] = request.seed
        return self._stream(request, "/v1/completions", body, _completion_text)

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        raise TypeError(
            "the vLLM Fast adapter serves text only; tools go to a chat endpoint"
        )

    async def tokenize(self, messages: Sequence[Mapping[str, str]]) -> list[int]:
        """vLLM's own chat-template ids for ``messages``, thinking off (P3)."""

        resp = await self._http.post(
            "/tokenize",
            json={
                "model": self.ref.model_id,
                "messages": list(messages),
                "add_generation_prompt": True,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"/tokenize returned HTTP {resp.status_code}")
        return [int(i) for i in resp.json()["tokens"]]

    async def attest(self) -> Json:
        """The served weights' ``GET /pl/attest`` document (ARCHITECTURE §13)."""

        resp = await self._http.get("/pl/attest")
        if resp.status_code != 200:
            raise RuntimeError(f"/pl/attest returned HTTP {resp.status_code}")
        doc: Json = resp.json()
        return doc
