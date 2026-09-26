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
        return self._call(request, "/v1/completions", body, _completion_text)

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        raise TypeError("the vLLM Fast adapter serves text only")

    async def tokenize(
        self,
        messages: Sequence[Mapping[str, str]] | None = None,
        prompt: str | None = None,
    ) -> list[int]:
        """vLLM's ids for ``messages`` (its chat template, thinking off) or for a
        pre-rendered ``prompt`` (encoded as sent, no special tokens added) (P3)."""

        body: Json = {"model": self.ref.model_id}
        if prompt is not None:
            body |= {"prompt": prompt, "add_special_tokens": False}
        else:
            body |= {"messages": list(messages or ()), "add_generation_prompt": True}
            body["chat_template_kwargs"] = {"enable_thinking": False}
        return [int(i) for i in (await self._json("POST", "/tokenize", body))["tokens"]]

    async def attest(self) -> Json:
        """The served weights' ``GET /pl/attest`` document (ARCHITECTURE §13)."""

        return await self._json("GET", "/pl/attest")

    async def _json(self, method: str, path: str, body: Json | None = None) -> Json:
        resp = await self._http.request(method, path, json=body)
        if resp.status_code != 200:
            raise RuntimeError(f"{path} returned HTTP {resp.status_code}")
        doc: Json = resp.json()
        return doc
