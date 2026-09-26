"""The rep's Mouth: voices a ``PublicIntent`` (ARCHITECTURE §10.1).

The model rephrases the intent's template line. Number fidelity: every number
of the intent's values, as digits (identifiers such as a confirmation number
verbatim), and no other number. At most 2
regenerations, then the template itself, flagged ``fidelity_fallback``
(``rep.mouth.fidelity_ok = false``).
"""

from __future__ import annotations

from decimal import Decimal

from proxyloop.contract.llm import ChatMessage, LLMClient, TextRequest
from proxyloop.env import world
from proxyloop.env.counterparty.policy import IntentKind, PublicIntent
from proxyloop.env.tasks.schema import CounterpartySpec

LINES: dict[IntentKind, str] = {
    "greet": "Thanks for calling {company}. First I need to verify your identity.",
    "ask_identity": "I still need to verify your identity.",
    "how_can_help": "Thanks, you are verified. How can I help today?",
    "offer": "I can offer you this:",
    "final_offer": "This is my best and final offer:",
    "no_better": "I am afraid I cannot do better than what I offered.",
    "readback": "Here are the full terms:",
    "confirm_accept": "To confirm, do you accept these terms?",
    "confirmed": "Done, the offer is accepted. Your confirmation number is:",
    "ack_decline": "Understood.",
    "offer_unavailable": "Sorry, that offer is no longer available.",
    "offer_expired": "",  # silent
    "ok_hold": "Sure, I will hold.",
    "check_in": "Hello, are you still there?",
    "transfer": "Let me transfer you to a supervisor.",
    "hang_up": "I cannot hear you, so I am ending the call. Goodbye.",
    "clarify": "Sorry, how can I help with your account?",
}
IDENTIFIERS = frozenset({"confirmation"})  # voiced verbatim, never as a number
SYSTEM = """You are {persona} You are on a phone call with someone calling for \
your customer. Rephrase the given line as one short, natural spoken line (at most \
two sentences) with the same meaning and every value. Write every number in \
digits exactly as given, and say no other number. Output only the line."""


def _label(key: str) -> str:
    return key.replace(":", " ").replace("_", " ").replace(".", " ")


def template(intent: PublicIntent, company: str) -> str:
    line = LINES[intent.kind].format(company=company)
    if intent.ask:
        line += " Please give your " + " and ".join(map(_label, intent.ask)) + "."
    values = "; ".join(f"{_label(k)}: {v}" for k, v in intent.say)
    return f"{line} {values}." if values else line


def fidelity_ok(text: str, intent: PublicIntent) -> bool:
    """Every value's number (identifiers verbatim, as text) and no other number."""

    required: set[Decimal] = set()
    allowed: set[Decimal] = set()  # digits inside key names ("account.last4")
    for key, value in intent.say:
        if key in IDENTIFIERS and value not in text:
            return False
        required |= world.numbers(value)
        allowed |= world.numbers(key)
    for key in intent.ask:
        allowed |= world.numbers(key)
    return required <= world.numbers(text) <= required | allowed


class Mouth:
    def __init__(
        self, client: LLMClient, writer: world.World, spec: CounterpartySpec
    ) -> None:
        self._client, self._world, self._company = client, writer, spec.company
        self._system = SYSTEM.format(persona=spec.persona.strip())
        self.timeout_s = world.TIMEOUT_S

    async def say(
        self, intent: PublicIntent, heard: str, cause: str
    ) -> tuple[str, str]:
        """Voice ``intent``; its calls, then ``rep.mouth``."""

        line = template(intent, self._company)
        prompt = f"The caller said: {heard or '(nothing yet)'}\nLine: {line}"
        messages = (
            ChatMessage(role="system", content=self._system),
            ChatMessage(role="user", content=prompt),
        )
        call_ids = [f"mouth:{cause}:{n}" for n in range(world.MAX_REGENERATIONS + 1)]

        async def attempt(n: int) -> str:
            request = TextRequest(
                call_id=call_ids[n],
                role="mouth",
                messages=messages,
                max_tokens=world.MAX_TOKENS,
                temperature=0.7,
            )
            return (await self._world.text(self._client, request, cause)).strip()

        def check(text: str) -> str:
            if not text or not fidelity_ok(text, intent):
                raise world.Invalid("number fidelity")
            return text

        text, attempts, ok = await world.bounded(
            attempt,
            check,
            what="mouth",
            timeout_s=self.timeout_s,
            exhausted=lambda: line,
        )
        payload = {"intent": intent.model_dump(mode="json"), "text": text}
        payload |= {"fidelity_ok": ok, "attempts": attempts}
        causes = [cause, *self._world.calls(call_ids[:attempts])]
        return text, self._world.emit("rep.mouth", "world.mouth", payload, causes)
