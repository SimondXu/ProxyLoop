"""FastLane (§6, §11; I3): one generation at a time per lane, coalescing triggers.
``fast.request -> llm.call (sink) -> fast.turn -> fast.sentence``, prompts only
from the contract renderer, relays as ``f2s.msg`` with ``msg_id == event_id``."""

from __future__ import annotations

import asyncio
import importlib
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from proxyloop.contract import protocol as fp
from proxyloop.contract.base import Lane, canonical_json, sha256_text
from proxyloop.contract.llm import LLMCallRecord, TextRequest, request_content
from proxyloop.contract.messages import FastToSlow
from proxyloop.contract.views import Trigger, view_cp, view_user

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

PROFILE: dict[Lane, str] = {"user": "pl_user_v1", "cp": "pl_cp_v1"}
URGENT = ("user_msg", "rep_spoke")  # served before Slow's messages and timers
_F2S = {  # "": the lane's own update type
    **{"note": "NOTE", "request": "REQUEST", "revoke": "REVOKE"},
    **{"correction": "USER_UPDATE", "fact": ""},
}
TOKENIZER = ("Qwen/Qwen3.5-9B", "c202236235762e1c871ad0ccb60c8ee5ba337b9a")  # ADR-0002


def load_tokenizer() -> fp.ChatTokenizer:
    """The pinned HF tokenizer vLLM serves, for ``fp.render_prompt``."""
    transformers: Any = importlib.import_module("transformers")
    auto = transformers.AutoTokenizer
    tok: fp.ChatTokenizer = auto.from_pretrained(TOKENIZER[0], revision=TOKENIZER[1])
    return tok


class FastLane:
    def __init__(self, k: Kernel, lane: Lane) -> None:
        self._k, self._actor = k, f"fast.{lane}"
        self.lane: Lane = lane
        self._client = k.clients["fast_user" if lane == "user" else "fast_cp"]
        self._pending: list[tuple[Trigger, str]] = []
        self._wake = asyncio.Event()
        self._n = 0

    def trigger(self, trigger: Trigger, cause: str) -> None:
        if trigger.kind != "slow_msg":  # one of each kind; each Slow message once
            self._pending = [p for p in self._pending if p[0].kind != trigger.kind]
        self._pending.append((trigger, cause))
        self._wake.set()

    async def run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._pending:
                urgent = [p for p in self._pending if p[0].kind in URGENT]
                chosen = (urgent or self._pending)[0]
                self._pending.remove(chosen)
                await self.generate(*chosen)

    def _request(self, trigger: Trigger) -> tuple[TextRequest, str]:
        k, s, lane = self._k, self._k.cfg.fast_sampling, self.lane
        brief = k.task.fast_brief_user if lane == "user" else k.task.fast_brief_cp
        view = (view_user if lane == "user" else view_cp)(k.bb, trigger, brief)
        seed = int(sha256_text(f"{k.cfg.seed}:{lane}:{self._n}")[:8], 16)
        args: dict[str, Any] = dict(call_id=f"fast_{lane}:{self._n}", seed=seed)
        args |= dict(role=f"fast_{lane}", max_tokens=s.max_tokens)
        args |= dict(temperature=s.temperature, top_p=s.top_p)
        if self._client.ref.endpoint != "vllm":
            args["messages"] = fp.render_messages(view, PROFILE[lane])
        elif k.tok is None:
            raise RuntimeError("a vLLM Fast lane needs the pinned tokenizer")
        else:
            args["prompt"] = fp.render_prompt(view, PROFILE[lane], k.tok)
        view_sha = k.store("view", canonical_json(view.model_dump(mode="json")))
        return TextRequest(**args), view_sha

    async def generate(self, trigger: Trigger, cause: str) -> None:
        k, lane = self._k, self.lane
        self._n += 1
        gen_id = f"{lane}-g{self._n}"
        gen: dict[str, object] = {"lane": lane, "gen_id": gen_id}
        request, view_sha = self._request(trigger)
        kind = "prompt" if request.prompt is not None else "messages"
        asked = gen | {"trigger": trigger.kind, "view_sha": view_sha}
        asked |= {"prompt_sha": k.store(kind, request_content(request))}
        asked |= {"profile": PROFILE[lane], "basis_seq": k.bb.seq}
        asked |= {"model_ref": self._client.ref.model_dump(mode="json")}
        ask = k.emit("fast.request", self._actor, asked, [cause])
        k.expect(request.call_id, ask.event_id)
        parser, items, text = fp.StreamParser(lane), list[fp.TurnItem](), ""
        start, ttfs, record = k.now(), None, None
        async for delta in self._client.stream_text(request):
            if isinstance(delta, LLMCallRecord):
                record = delta  # the sink already wrote it
                continue
            text += delta
            items += parser.feed(delta)
            if ttfs is None and any(isinstance(i, fp.Speech) for i in items):
                ttfs = k.now() - start
        items += parser.close()
        assert record is not None, "every call ends with its record"
        k.store("response", text)
        first = record.t_first_token
        ttft = None if first is None else first - record.t_start
        turned = gen | {"call_id": record.call_id, "ttft_ms": ttft, "ttfs_ms": ttfs}
        turned["items"] = [i.model_dump(mode="json") for i in items]
        causes = [ask.event_id, k.call_event(request.call_id)]
        turn = k.emit("fast.turn", self._actor, turned, causes).event_id
        if trigger.msg_id is not None:
            voiced = {"msg_id": trigger.msg_id, "gen_id": gen_id}
            k.emit("s2f.voiced", self._actor, voiced, [turn])
        self._relay(items, turn, gen_id)
        lines: list[tuple[str, str, str]] = []
        for n, item in enumerate(i for i in items if isinstance(i, fp.Speech)):
            utt = {"utt_id": f"{gen_id}-u{n}", "text": item.text}
            said = k.emit("fast.sentence", self._actor, gen | utt, [turn])
            lines.append((f"{gen_id}-u{n}", item.text, said.event_id))
        if lines:
            await k.speakers[lane].speak(lines)

    def _relay(self, items: list[fp.TurnItem], turn: str, gen_id: str) -> None:
        k, lane = self._k, self.lane
        heard = [x.utt_id for x in k.bb.channels[lane].lines if x.speaker == "partner"]
        base = {"lane": lane, "gen_id": gen_id, "utt_ref": (heard or [None])[-1]}
        for item in items:
            if isinstance(item, fp.Relay):
                own = "USER_UPDATE" if lane == "user" else "CP_UPDATE"
                fields = {"type": _F2S[item.type] or own, "text": item.text}
                fields |= {"facts": item.facts, "correction": item.type == "correction"}
            elif isinstance(item, fp.Hold):
                fields = {"type": "HOLD", "text": item.reason}
            else:
                continue
            msg_id = k.next_event_id()
            try:
                msg = FastToSlow.model_validate(base | fields | {"msg_id": msg_id})
            except ValidationError:  # over a contract bound: counted, never repaired
                k.counts["relay_rejected"] += 1
                continue
            ev = k.emit("f2s.msg", self._actor, msg.model_dump(mode="json"), [turn])
            assert ev.event_id == msg_id, "an f2s msg_id is its event_id"
