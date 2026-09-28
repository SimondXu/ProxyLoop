"""The keys-free demo harness (S1-SYS-32; tests only, I8).

``DemoStarter`` implements ``proxyloop.serve.cases.Starter`` for the browser
E2E: one stub option per lane, labelled ``stub · test_fake``, and the one
family under test. A start runs the real ``run_session`` through the real
``kernel.web.Starter``'s launch (one live case, returned after seq 0) on a
``test_fake`` config (``tests.support.sessions.fake_config``), with the real
``HumanWebChannel`` for the user (and for the rep when ``rep="human"``), the
SimRep's real policy, Guard and the fence, and returns the real ``WebCase``.

Only the model outputs are scripted. Each fake answers from the request the
kernel sends it, as a model would: nothing here reads the board, the log or the
world. ``Reactive`` records every call through the kernel's sink, as a real
adapter does, after a latency on the session's clock. The scripts:

- ``fast_user``: relays the task, the identity facts (``fact``) and a stop
  (``revoke``); conveys Slow's messages and the card.
- ``fast_cp``: stalls with a hold while a fact or a decision is pending, voices
  Slow's guidance, and relays each stated term as a ``fact``.
- ``SlowScript``: asks the user for identity (with keys) while the status
  bar's readiness line says the call waits for it (S1-SYS-21), records the
  user's identity and the rep's offer from the relays, identifies again when
  the rep asks and identity is public, asks for a read-back of each revision,
  requests approval once the status bar says the read-back is confirmed,
  accepts once its wake says the card was decided and the status bar says it
  was granted, and, once the case is COMMITTED, ``check_account``s the
  confirmation id a REP line said (citing that line) and ``finish``es
  ``completed``: Guard verifies it (S1-SYS-44). When the case is NEEDS_REPLAN
  on the user's relayed revoke (a stop), it tells the user and ``finish``es
  ``escalate``.
- ``rep_ear``/``rep_mouth``: classify the heard line by its words; voice the
  policy's template line with its values said naturally.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal

from tests.support.fakes import RepeatingLLM
from tests.support.manual_clock import ManualClock
from tests.support.sessions import act, ear, fake_config

from proxyloop.contract.llm import (
    LLMClient,
    LLMRole,
    ModelRef,
    TextRequest,
    ToolRequest,
)
from proxyloop.core.clock import Clock, WallClock
from proxyloop.env.tasks.loader import load_task, resolve, task_ref_of
from proxyloop.guard.readiness import IDENTITY
from proxyloop.kernel.channels import HumanWebChannel
from proxyloop.kernel.speaker import Sleep
from proxyloop.kernel.web import Starter, WebCase
from proxyloop.llm.http import RecordSink
from proxyloop.serve.cases import LaneKey, ModelOption, StartRefused

FAMILY = "x-out-of-envelope-approval"  # a piloted, train-only family (I9)
LABEL = "stub · test_fake"
# ModelOption has no adapter kind and serve requires a contract endpoint, so a
# stub names one; its label, its model id and every event say test_fake.
OPTIONS = tuple(
    ModelOption(
        id=f"stub:{lane}",
        lane=lane,
        label=LABEL,
        endpoint="teamrouter" if lane == "slow" else "vllm",
        model_id=f"{lane}-fake",
        default=True,
    )
    for lane in ("fast_user", "fast_cp", "slow")
)
LATENCY_S: Mapping[str, float] = {"fast_user": 1.5, "fast_cp": 0.4, "slow": 0.6}
WORLD_S = 0.1  # the Ear's and the Mouth's
Request = TextRequest | ToolRequest
Answer = Callable[[Request], str]


class _Session(ManualClock):
    """The session's ``Clock`` as the ``ManualClock`` the fakes read: every
    reading is the session's; ``advance`` is a no-op (time flows on its own)."""

    def __init__(self, clock: Clock) -> None:
        super().__init__()
        self._session = clock

    def advance(self, ms: int) -> None:
        return None

    def monotonic_ms(self) -> int:
        return self._session.monotonic_ms()

    def wall(self) -> datetime:
        return self._session.wall()


class Reactive(RepeatingLLM):
    """A ``test_fake`` whose answer is a function of the request, given after
    ``seconds`` on the session's ``sleep``; each call's record goes to ``sink``."""

    def __init__(
        self,
        ref: ModelRef,
        answer: Answer,
        clock: Clock,
        sleep: Sleep,
        seconds: float,
        sink: RecordSink,
    ) -> None:
        super().__init__(ref, [], _Session(clock), False, sink)  # it times records
        self._answer, self._sleep, self._seconds = answer, sleep, seconds

    async def _next(self, request: Request) -> tuple[str, int]:
        start = self._clock.monotonic_ms()
        try:
            await self._sleep(self._seconds)
        except asyncio.CancelledError:
            self._record(request, None, start, "cancelled")
            raise
        self.calls += 1
        return self._answer(request), start


def _last(request: Request) -> str:
    return request.messages[-1].content if request.messages else ""


def _section(prompt: str, name: str) -> str:
    end = r"(?:\n\n[A-Z][A-Z ]+:|\Z)"
    found = re.search(rf"^{name}:\n?(.*?){end}", prompt, re.M | re.S)
    return found.group(1).strip() if found else ""


def _said(prompt: str, who: str) -> str:  # the last line of USER, REP, ...
    lines = _section(prompt, "CONVERSATION SO FAR").splitlines()
    said = [x.split(": ", 1)[1] for x in lines if x.startswith(f"{who}: ")]
    return said[-1] if said else ""


def _money(text: str) -> str | None:
    found = re.search(r"(\d+(?:\.\d\d)?) dollars|\$(\d+(?:\.\d\d)?)", text)
    return None if found is None else f"{float(found.group(1) or found.group(2)):.2f}"


_MONTHS = re.compile(r"(\d+)\s*-?\s*months?\b")  # "24 months", "a 24-month term"


def fast_user(request: Request) -> str:
    prompt = _last(request)
    trigger, said = _section(prompt, "TRIGGER"), _said(prompt, "USER")
    if trigger.startswith("An approval card"):
        return "They made an offer outside your limits. Please review the card."
    if trigger.startswith("The case agent sent"):
        return trigger.split('"')[1]
    if not trigger.startswith("The user just sent"):
        return "@wait"
    if "stop" in said.casefold():
        return "Understood, I will stop.\n@slow: revoke the user said stop"
    name = re.search(r"name is ([A-Z][a-z]+(?: [A-Z][a-z]+)+)", said)
    last4 = re.search(r"\b(\d{4})\b", said)
    if name and last4:
        facts = f"account.holder_name={name.group(1)}; account.last4={last4.group(1)}"
        return f"Thanks, I will pass that on.\n@slow: fact {facts}"
    return f"Sure, I will call them now.\n@slow: request {said}"


_STATED = {  # a relayed term, and the words that state it
    "fees_none=true": "no fees",
    "changes_none=true": "no other changes",
    "expires=none": "no expiry",
}


def fast_cp(request: Request) -> str:
    prompt = _last(request)
    trigger, guide = (
        _section(prompt, "TRIGGER"),
        _section(prompt, "CASE AGENT GUIDANCE"),
    )
    hold = "Thank you, one moment please.\n@slow: {}\n@hold {}"
    if trigger.startswith("New guidance"):  # the newest cp guide only (the fold)
        name = re.search(r"holder_name = ([^;)]+)", guide)
        last4 = re.search(r"last4 = (\d{4})", guide)
        if guide.startswith("- Identify") and name and last4:
            return (
                f"The account holder is {name.group(1)}, and the last four digits "
                f"are {last4.group(1)}."
            )
        if guide.startswith("- Ask them to read back"):
            return "Could you please read back all the terms of that offer?"
        if guide.startswith("- Say you are getting"):
            return "I am getting that detail from the account holder, one moment."
        return "@wait"
    rep = _said(prompt, "REP")
    if "verify your identity" in rep:
        return hold.format(
            "the rep asks for the account holder identity", "fact_request"
        )
    if "you are verified" in rep:
        return "I am calling to ask for a lower monthly price on this plan."
    price, term = _money(rep), _MONTHS.search(rep)
    if price and term:
        facts = [f"monthly_price={price}", f"term_months={term.group(1)}"]
        facts += [fact for fact, words in _STATED.items() if words in rep]
        return hold.format("fact " + "; ".join(facts), "offer")
    return "@wait"


_SLOTS = {  # field -> unit (only for the cents conversion; Guard derives role/unit)
    "monthly_price": "usd_minor",
    "term_months": "months",
    "fees_none": "bool",
    "changes_none": "bool",
    "expires": "iso",
}
_RELAY = re.compile(r"\[(USER CHAT|REP CALL)\] (.*) \(utt (\S+)\)")
_ASK = "The company needs the account holder name and the last 4 digits."
_STOPPED = "Stopped as you asked: nothing was accepted."
_FACT = re.compile(r"([a-z][a-z0-9_.]*)=([^;]+?)(?=;|$)")
# a REP line in [CONVERSATIONS] that says a confirmation id: its utt id and the id
_CONFIRMED = re.compile(r'^\S+ (\S+) REP: ".*confirmation number is:? (\w+)', re.M)


def _said_in(note: str) -> str:
    """A relay note's facts and text: after its type, as written (``relay_only``)
    or as one JSON string (``transcript``, ADR-0016: ``prompt.note(quoted=True)``)."""
    said = note.partition(" ")[2]
    return str(json.loads(said)) if said.startswith('"') else said


def _record(facts: Mapping[str, str], utt: str) -> dict[str, object]:
    slots: list[dict[str, str]] = []
    for field, value in facts.items():
        unit = _SLOTS[field]
        said = str(round(float(value) * 100)) if unit == "usd_minor" else value
        slots.append({"field": field, "value": said, "utt_ref": utt})
    return {"tool": "record_offer", "offer_ref": "o1", "offer_slots": slots}


class SlowScript:
    """Slow's steps, from the relays and the status bar of its newest turn. The
    ``check_account`` step reads the rep's line in [CONVERSATIONS], so it needs
    ``slow_view=transcript`` (the demo's default, ADR-0016)."""

    def __init__(self) -> None:
        self.asked_identity = False

    def __call__(self, request: Request) -> str:
        notes, calls = _last(request), list[dict[str, object]]()
        status = notes[notes.find("[STATUS]") :]
        slots = [f"fact:{k}" for k in IDENTITY]
        shown = [rf'{re.escape(k)}="[^"]*" \[public\]' for k in IDENTITY]
        public = all(re.search(x, status) for x in shown)
        if "readiness: call not open; missing:" in status and not self.asked_identity:
            self.asked_identity = True  # readiness first: before the call opens
            calls.append({"tool": "ask_user", "text": _ASK, "keys": list(IDENTITY)})
        # o1 is recorded from the offer, then once more, whole, from a read-back
        offer = re.search(r"o1 r\d+ \(([^)]*)\)", status)
        new = offer is None
        partial = offer is not None and "required slots not recorded" in status
        revoked = False  # a relayed revoke from the user lane (a stop)
        for lane, note, utt in _RELAY.findall(notes):
            revoked |= lane == "USER CHAT" and note.partition(" ")[0] == "revoke"
            body = _said_in(note)
            facts = dict(_FACT.findall(body))
            if lane == "USER CHAT" and "account.last4" in facts:
                for key in IDENTITY:
                    fact = {"key": key, "value": facts[key], "utt_ref": utt}
                    calls.append({"tool": "record_fact", **fact})
                calls.append({"tool": "guide_fast", "move": "identify", "slots": slots})
            elif lane == "REP CALL" and "identity" in body and public:
                calls.append({"tool": "guide_fast", "move": "identify", "slots": slots})
            elif lane == "REP CALL" and "identity" in body and not self.asked_identity:
                self.asked_identity = True
                keys = list(IDENTITY)
                calls.append({"tool": "ask_user", "text": _ASK, "keys": keys})
                calls.append({"tool": "guide_fast", "move": "hold_for_fact"})
            elif (
                lane == "REP CALL"
                and "monthly_price" in facts
                and (new or (partial and "fees_none" in facts))
            ):
                new = partial = False  # one record per step
                calls.append(_record(facts, utt))
                slots = ["offer:o1"]
                calls.append(
                    {"tool": "guide_fast", "move": "ask_readback", "slots": slots}
                )
        if "read-back confirmed" in status and "approvals: none" in status:
            calls.append({"tool": "request_approval", "offer_ref": "o1"})
        if "approval.decided" in notes and " granted" in status:
            calls.append({"tool": "accept_offer", "offer_ref": "o1"})
        confirmed = _CONFIRMED.findall(notes)
        if "case: COMMITTED" in status and confirmed:  # the rep's id, as said
            utt, conf = confirmed[-1]
            calls.append(
                {"tool": "check_account", "confirmation_id": conf, "utt_ref": utt}
            )
            calls.append({"tool": "finish", "outcome": "completed", "summary": conf})
        if "case: NEEDS_REPLAN" in status and revoked:
            calls.append({"tool": "tell_user", "text": _STOPPED})
            calls.append({"tool": "finish", "outcome": "escalate", "summary": "stop"})
        return act("The case, as relayed.", *calls)


def rep_ear(request: Request) -> str:
    prompt = _last(request)
    heard = prompt.split("The caller said: ", 1)[-1]
    offers = dict(re.findall(r"(\S+): monthly_price (\S+?)[,;\n]", prompt))
    if "we accept" in heard:
        named = [ref for ref, price in offers.items() if f"${price}" in heard]
        args: dict[str, object] = {"price_usd": float(_money(heard) or 0)}
        args |= {"offer_ref": named[0]} if named else {}
        return ear("accept", **args)
    name = re.search(r"holder is ([A-Z][a-z]+(?: [A-Z][a-z]+)+)", heard)
    last4 = re.search(r"\b(\d{4})\b", heard)
    if name and last4:
        facts = [
            {"key": "account.holder_name", "value": name[1]},
            {"key": "account.last4", "value": last4[1]},
        ]
        return ear("provide_fact", facts=facts)
    if "one moment" in heard:
        return ear("hold_request")
    if "lower monthly price" in heard:
        return ear("ask_discount")
    if "read back" in heard:
        return ear("ask_readback")
    return ear("other")


def rep_mouth(request: Request) -> str:
    """The policy's template line (``Line:``) from this request, its money said
    as dollars a month; every other value is kept as the world wrote it."""
    line = _last(request).split("Line: ", 1)[-1]
    line = re.sub(r"monthly price: (\d+(?:\.\d+)?)", r"\1 dollars a month", line)
    return line.replace("confirmation: ", "")


class DemoStarter(Starter):
    """Implements ``proxyloop.serve.cases.Starter`` on ``test_fake`` models;
    ``latency_s`` is per role, on the session's clock."""

    def __init__(
        self,
        runs: Path,
        *,
        clock: Clock | None = None,
        sleep: Sleep | None = None,
        latency_s: Mapping[str, float] = LATENCY_S,
    ) -> None:
        self._now, self._wait = clock or WallClock(), sleep or asyncio.sleep
        super().__init__(runs, clock=self._now, sleep=self._wait, clients=self._make)
        self._tasks = (task_ref_of(FAMILY, load_task(FAMILY).version, None, 0),)
        self._latency = latency_s

    def _make(self, role: LLMRole, ref: ModelRef, sink: RecordSink) -> LLMClient:
        scripts: dict[str, Answer] = {"fast_user": fast_user, "fast_cp": fast_cp}
        scripts |= {"slow": SlowScript(), "ear": rep_ear, "mouth": rep_mouth}
        if role not in scripts:
            raise AssertionError(f"no script for {role}")
        wait = self._latency.get(role, WORLD_S)
        return Reactive(ref, scripts[role], self._now, self._wait, wait, sink)

    def model_options(self) -> list[ModelOption]:
        return list(OPTIONS)

    async def start_case(
        self,
        task_ref: str,
        models: Mapping[LaneKey, str],
        rep: Literal["sim", "human"] = "sim",
    ) -> WebCase:
        if self._run is not None and not self._run.done():
            raise StartRefused("busy")
        if task_ref not in self._tasks:  # no other family file is opened
            raise StartRefused("unknown_task")
        lanes = {o.id: o.lane for o in OPTIONS}
        for lane, option in models.items():
            if option not in lanes:
                raise StartRefused("unknown_model")
            if lanes[option] != lane:
                raise StartRefused("wrong_lane")
        user = HumanWebChannel()
        human = HumanWebChannel() if rep == "human" else None
        return await self._launch(fake_config(), resolve(task_ref), user, human)

    async def stop(self) -> None:
        """Cancel the live run, if any: its bundle closes ``stopped``."""
        if self._run is not None:
            self._run.cancel()
            await asyncio.gather(self._run, return_exceptions=True)
