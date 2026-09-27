"""FastLane (§6, §11; I3): one generation at a time, triggers coalesced; prompts
only from the contract renderer; relays are ``f2s.msg`` with ``msg_id == event_id``.

Generations (§9.4): one whose authority epoch moved while it streamed is stale:
``fast.cancelled`` before its first sentence (no turn, relay or speech), and its
trigger runs again on the new basis (an unacknowledged APPROVAL_NOTICE once).
The stream is not aborted. A newer partner line does not cancel a generation
(#144 credits its relays to its own view; the next generation answers it).
Condition R (``teacher_repair_*``): a generation at a decision point goes to the
teacher, as a ``fast_*`` call with the teacher's model (E1), ``resamples`` noted."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from proxyloop.contract import protocol as fp
from proxyloop.contract.base import Lane, canonical_json, sha256_text
from proxyloop.contract.llm import (
    LLMCallRecord,
    LLMClient,
    TextRequest,
    request_content,
)
from proxyloop.contract.messages import FastToSlow
from proxyloop.contract.views import FastView, Trigger, view_cp, view_user
from proxyloop.llm.parity import GoldenPrompt, check_parity
from proxyloop.llm.vllm import VLLMClient
from proxyloop.models.repair import substitutes

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

PROFILE: dict[Lane, str] = {"user": "pl_user_v1", "cp": "pl_cp_v2"}
URGENT = ("user_msg", "rep_spoke")  # served before Slow's messages and timers
_F2S = {  # "": the lane's own update type
    **{"note": "NOTE", "request": "REQUEST", "revoke": "REVOKE"},
    **{"correction": "USER_UPDATE", "fact": ""},
}
TOKENIZER = ("Qwen/Qwen3.5-9B", "c202236235762e1c871ad0ccb60c8ee5ba337b9a")  # ADR-0002


def load_tokenizer() -> fp.ChatTokenizer:  # the pinned one vLLM serves
    transformers: Any = importlib.import_module("transformers")
    auto = transformers.AutoTokenizer
    tok: fp.ChatTokenizer = auto.from_pretrained(TOKENIZER[0], revision=TOKENIZER[1])
    return tok


async def p3(client: VLLMClient, view: FastView, tok: fp.ChatTokenizer) -> bool:
    """P3 (§12): vLLM ids of the messages and the prompt == the pinned ones."""
    profile = PROFILE[view.lane]
    chat = tuple(
        m.model_dump(include={"role", "content"})
        for m in fp.render_messages(view, profile)
    )
    out: Any = tok.apply_chat_template(
        list(chat), tokenize=True, add_generation_prompt=True, enable_thinking=False
    )
    ids = cast(list[int], out["input_ids"] if isinstance(out, Mapping) else out)
    prompt = fp.render_prompt(view, profile, tok)
    golden = GoldenPrompt(profile, chat, prompt, tuple(ids))
    return (await check_parity(client, [golden])).passed


def _speaks(items: list[fp.TurnItem]) -> bool:  # a sentence has been released
    return any(isinstance(i, fp.Speech) for i in items)


@dataclass(slots=True)
class _Ask:  # a pending trigger
    trigger: Trigger
    cause: str
    acks: tuple[str, ...] = ()  # the APPROVAL_NOTICEs it voices
    again: bool = False  # it is re-run after a stale generation


class FastLane:
    def __init__(self, k: Kernel, lane: Lane) -> None:
        self._k, self._actor = k, f"fast.{lane}"
        self.lane: Lane = lane
        self.client = k.clients["fast_user" if lane == "user" else "fast_cp"]
        self._pending: list[_Ask] = []
        self._wake = asyncio.Event()
        self._n = 0

    def trigger(self, trigger: Trigger, cause: str, acks: tuple[str, ...] = ()) -> None:
        self._add(_Ask(trigger, cause, acks))
        self._wake.set()

    def _add(self, ask: _Ask, first: bool = False) -> None:
        """One of each kind (the newest absorbs the older one's acks); each
        Slow message once."""
        kind = ask.trigger.kind
        same = [a for a in self._pending if a.trigger.kind == kind != "slow_msg"]
        ask.acks = (*(x for a in same for x in a.acks), *ask.acks)
        self._pending = [a for a in self._pending if a not in same]
        self._pending.insert(0, ask) if first else self._pending.append(ask)

    async def run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._pending:
                urgent = [p for p in self._pending if p.trigger.kind in URGENT]
                chosen = (urgent or self._pending)[0]
                self._pending.remove(chosen)
                await self.generate(chosen)

    def view(self, trigger: Trigger) -> FastView:
        k, user = self._k, self.lane == "user"
        brief = k.task.fast_brief_user if user else k.task.fast_brief_cp
        return (view_user if user else view_cp)(k.bb, trigger, brief)

    def _request(self, view: FastView, client: LLMClient) -> tuple[TextRequest, str]:
        k, s, lane = self._k, self._k.cfg.fast_sampling, self.lane
        seed = int(sha256_text(f"{k.cfg.seed}:{lane}:{self._n}")[:8], 16)
        args: dict[str, Any] = dict(call_id=f"fast_{lane}:{self._n}", seed=seed)
        args |= dict(role=f"fast_{lane}", max_tokens=s.max_tokens)
        args |= dict(temperature=s.temperature, top_p=s.top_p)
        if client.ref.endpoint != "vllm":
            args["messages"] = fp.render_messages(view, PROFILE[lane])
        elif k.tok is None:
            raise RuntimeError("a vLLM Fast lane needs the pinned tokenizer")
        else:
            args["prompt"] = fp.render_prompt(view, PROFILE[lane], k.tok)
        view_sha = k.store("view", canonical_json(view.model_dump(mode="json")))
        return TextRequest(**args), view_sha

    async def generate(self, ask: _Ask) -> None:
        k, lane, trigger, cause = self._k, self.lane, ask.trigger, ask.cause
        if lane == "cp" and k.closed:
            return  # the call is over
        if trigger.kind == "approval_card" and k.bb.private.pending_approval is None:
            k.counts["notice_moot"] += 1  # decided before FastU could voice it
            return
        self._n += 1
        gen_id = f"{lane}-g{self._n}"
        gen: dict[str, object] = {"lane": lane, "gen_id": gen_id}
        guides = [m.msg_id for m in k.bb.s2f_pending.get(lane, ()) if m.guide]
        view, epoch = self.view(trigger), k.bb.epoch
        repair = k.teacher is not None and substitutes(view, k.cfg.ablations)
        client: LLMClient = k.teacher if repair and k.teacher else self.client
        request, view_sha = self._request(view, client)
        heard = [x.utt_id for x in view.transcript if x.speaker == "partner"]
        utt_ref = (heard or [None])[-1]  # what this prompt saw, not the board later
        kind = "prompt" if request.prompt is not None else "messages"
        asked = gen | {"trigger": trigger.kind, "view_sha": view_sha}
        asked |= {"prompt_sha": k.store(kind, request_content(request))}
        asked |= {"profile": PROFILE[lane], "basis_seq": k.bb.seq}
        asked |= {"model_ref": client.ref.model_dump(mode="json")}
        req = k.emit("fast.request", self._actor, asked, [cause]).event_id
        k.expect(request.call_id, req)
        parser, items, text = fp.StreamParser(lane), list[fp.TurnItem](), ""
        start, ttfs, record = k.now(), None, None
        async for delta in client.stream_text(request):
            if isinstance(delta, LLMCallRecord):
                record = delta  # the sink already wrote it
                continue
            text += delta
            items += parser.feed(delta)
            if ttfs is None and _speaks(items):
                ttfs = k.now() - start
        items += parser.close()  # a last sentence is released only here
        if ttfs is None and _speaks(items):
            ttfs = k.now() - start
        assert record is not None, "every call ends with its record"
        k.store("response", text)
        causes = [req, k.call_event(request.call_id)]
        if k.bb.epoch != epoch:  # stale: cancelled before its first sentence
            cancel = {"gen_id": gen_id, "reason": "epoch"}
            k.emit("fast.cancelled", self._actor, cancel, causes)
            if not (ask.again and trigger.kind == "approval_card"):
                self._add(_Ask(trigger, cause, ask.acks, again=True), first=True)
            return
        first = record.t_first_token
        ttft = None if first is None else first - record.t_start
        turned = gen | {"call_id": record.call_id, "ttft_ms": ttft, "ttfs_ms": ttfs}
        turned["items"] = [i.model_dump(mode="json") for i in items]
        if repair and k.teacher is not None:  # E1: the teacher's resample count
            turned["resamples"] = k.teacher.resamples.get(request.call_id, 0)
        turn = k.emit("fast.turn", self._actor, turned, causes).event_id
        slow_msg = [trigger.msg_id] if trigger.msg_id else []
        for msg_id in [*guides, *slow_msg, *ask.acks]:
            voiced = {"msg_id": msg_id, "gen_id": gen_id}
            k.emit("s2f.voiced", self._actor, voiced, [turn])
        self._relay(items, turn, gen_id, utt_ref)
        held = next((i.reason for i in items if isinstance(i, fp.Hold)), None)
        if lane == "cp" and held != ((hold := k.bb.public.cp_hold) and hold.reason):
            k.emit("chan.hold", self._actor, {"lane": "cp", "reason": held}, [turn])
        lines: list[tuple[str, str, str]] = []
        for n, item in enumerate(i for i in items if isinstance(i, fp.Speech)):
            utt = {"utt_id": f"{gen_id}-u{n}", "text": item.text}
            said = k.emit("fast.sentence", self._actor, gen | utt, [turn])
            lines.append((f"{gen_id}-u{n}", item.text, said.event_id))
        if lines:
            await k.speakers[lane].speak(lines)

    def _relay(
        self, items: list[fp.TurnItem], turn: str, gen_id: str, utt_ref: str | None
    ) -> None:
        k, lane = self._k, self.lane
        base = {"lane": lane, "gen_id": gen_id, "utt_ref": utt_ref}
        for item in items:
            if isinstance(item, fp.Relay):
                own = "USER_UPDATE" if lane == "user" else "CP_UPDATE"
                fields = {"type": _F2S[item.type] or own, "text": item.text}
                fields |= {"facts": item.facts, "correction": item.type == "correction"}
            elif isinstance(item, fp.Hold):
                hold = k.bb.public.cp_hold if lane == "cp" else None  # cp only
                if hold is not None and hold.reason == item.reason:
                    k.counts["hold_repeat"] += 1  # unchanged: Slow has it (ROOT-05)
                    continue
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
