"""The rep's deterministic policy (ARCHITECTURE §10.1), from per-family data.

GREET -> IDENTIFY -> DISCOVER -> OFFER(k) -> FINAL -> CONFIRM -> CONFIRMED |
TRANSFER | ENDED. The rep knows only the acts it heard, its offers and the
clock (no agent state). Each distinct lever unlocks the next ladder rung;
hidden terms are said only on a read-back; offers expire after their TTL;
silence over ``silence_s`` while the floor is free (``floor``), or a hold over
``hold_s``, is a strike, and the last strike hangs up.

World rule (for S1-SYS-04 to confirm): accepting an open offer by name commits
at once (``rep.commit_heard``) and the ledger binds all its terms, hidden ones
included, as a real rep's system would; that is the trap the agent must avoid
by asking for a read-back first. An accept is by name only if the heard text
says the offer's ref or its monthly price. An ambiguous accept (neither, or a
price that is not the offer's) makes the rep read every term back and ask for
confirmation; a plain "yes" then commits.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, get_args

from proxyloop.contract.base import Frozen, sha256_text
from proxyloop.env.counterparty.ear import EarAct, Lever
from proxyloop.env.ledger import Ledger
from proxyloop.env.tasks.schema import CounterpartySpec, OfferSpec
from proxyloop.env.world import numbers

State = Literal[
    "GREET",
    "IDENTIFY",
    "DISCOVER",
    "OFFER",
    "FINAL",
    "CONFIRM",
    "CONFIRMED",
    "TRANSFER",
    "ENDED",
]
IntentKind = Literal[
    "greet",
    "ask_identity",
    "how_can_help",
    "offer",
    "final_offer",
    "no_better",
    "readback",
    "confirm_accept",
    "confirmed",
    "ack_decline",
    "offer_unavailable",
    "offer_expired",
    "ok_hold",
    "check_in",
    "transfer",
    "hang_up",
    "clarify",
]
LEVERS: frozenset[str] = frozenset(get_args(Lever))
TERMINAL: frozenset[State] = frozenset({"CONFIRMED", "TRANSFER", "ENDED"})


class PublicIntent(Frozen):
    """What the rep says next; ``say`` holds every value the Mouth must voice."""

    kind: IntentKind
    offer_ref: str | None = None
    say: tuple[tuple[str, str], ...] = ()
    ask: tuple[str, ...] = ()  # profile keys the rep asks for


@dataclass(frozen=True, slots=True)
class BoundTerms:  # what a confirmation binds; ``Ledger`` needs ``term_months``
    offer_ref: str
    revision: int
    term_months: int
    terms: tuple[tuple[str, str], ...]  # every other term


@dataclass(frozen=True, slots=True)
class Commit:
    offer_ref: str
    confirmation_id: str
    bound: BoundTerms | None  # None: the ledger is absent


@dataclass(frozen=True, slots=True)
class Decision:
    from_: State
    to: State
    intent: PublicIntent
    rung: int | None
    commit: Commit | None = None
    strike: bool = False


@dataclass(slots=True)
class _Offer:
    spec: OfferSpec
    expires_ms: int
    status: Literal["open", "expired", "accepted"] = "open"


def _norm(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


class Policy:
    def __init__(
        self, spec: CounterpartySpec, identity: Mapping[str, str], t0_ms: int = 0
    ) -> None:
        self.spec, self.identity = spec, dict(identity)
        self.state: State = "GREET"
        self.rung, self.strikes = -1, 0
        self.offers: dict[str, _Offer] = {}
        self.ledger: Ledger[BoundTerms] = Ledger(spec.ledger)
        self._verified: set[str] = set()
        self._levers: set[str] = set()
        self._pending: str | None = None
        self._hold_since: int | None = None
        self._free_since: int | None = t0_ms  # None: someone has the floor

    @property
    def done(self) -> bool:
        return self.state in TERMINAL

    def made(self) -> dict[str, dict[str, str]]:
        """The offers made so far, with the terms said when offering."""

        return {ref: dict(o.spec.terms) for ref, o in self.offers.items()}

    def floor(self, free: bool, t_ms: int) -> None:
        """Either party took the floor, or released it: silence counts only
        while it is free."""

        self._free_since = t_ms if free else None

    def step(self, act: EarAct, utt_id: str, heard: str, t_ms: int) -> list[Decision]:
        """The reaction to one heard utterance, after any expiries. The rep
        answers, so it takes the floor."""

        if self.done:
            return []
        out = self._expire(t_ms)
        self._free_since, self._hold_since = None, None
        before = self.state
        intent, commit = self._react(act, utt_id, heard, t_ms)
        return [*out, Decision(before, self.state, intent, self._rung(), commit)]

    def tick(self, t_ms: int) -> list[Decision]:
        """Timers: offer expiry, silence and hold strikes, the hang-up."""

        if self.done:
            return []
        out = self._expire(t_ms)
        p, hold = self.spec.patience, self._hold_since
        since, limit = (
            (self._free_since, p.silence_s) if hold is None else (hold, p.hold_s)
        )
        if since is None or t_ms - since < 1000 * limit:
            return out
        self.strikes += 1  # the rep speaks up: it takes the floor
        self._free_since, self._hold_since = None, None if hold is None else t_ms
        before = self.state
        self.state = "ENDED" if self.strikes >= p.strikes else self.state
        intent = PublicIntent(kind="hang_up" if self.done else "check_in")
        return [*out, Decision(before, self.state, intent, self._rung(), strike=True)]

    def _react(
        self, act: EarAct, utt_id: str, heard: str, t_ms: int
    ) -> tuple[PublicIntent, Commit | None]:
        a = act.act
        if a == "ask_supervisor":
            self.state = "TRANSFER"
            return PublicIntent(kind="transfer"), None
        if a == "hold_request":
            self._hold_since = t_ms
            return PublicIntent(kind="ok_hold"), None
        if self.state == "GREET":
            self.state = "IDENTIFY"
            if a != "provide_fact":
                return PublicIntent(kind="greet", ask=self._missing()), None
        if self.state == "IDENTIFY":
            key, value = act.key or "", _norm(act.value or "")
            if (
                a == "provide_fact"
                and value
                and value == _norm(self.identity.get(key, ""))
            ):
                self._verified.add(key)
            if missing := self._missing():
                return PublicIntent(kind="ask_identity", ask=missing), None
            self.state = "DISCOVER"
            return PublicIntent(kind="how_can_help"), None
        if a in LEVERS:
            return self._lever(a, t_ms), None
        if a == "accept":
            return self._accept(act, utt_id, heard)
        if a == "ask_readback":
            offer = self.offers.get(act.offer_ref or self._latest() or "")
            if offer is None or offer.status != "open":
                return PublicIntent(
                    kind="offer_unavailable", offer_ref=act.offer_ref
                ), None
            return self._terms("readback", offer.spec), None
        if a == "decline":
            if self.state == "CONFIRM":
                self.state, self._pending = self._offer_state(), None
            return PublicIntent(kind="ack_decline"), None
        return PublicIntent(kind="clarify"), None

    def _lever(self, lever: str, t_ms: int) -> PublicIntent:
        ladder = self.spec.ladder
        if lever in self._levers or self.rung + 1 >= len(ladder):
            return PublicIntent(kind="no_better")
        self._levers.add(lever)
        self.rung += 1
        spec = ladder[self.rung]
        self.offers[spec.offer_ref] = _Offer(spec, t_ms + int(1000 * spec.ttl_s))
        self.state, self._pending = self._offer_state(), None
        kind = "final_offer" if self.state == "FINAL" else "offer"
        return PublicIntent(
            kind=kind, offer_ref=spec.offer_ref, say=tuple(spec.terms.items())
        )

    def _accept(
        self, act: EarAct, utt_id: str, heard: str
    ) -> tuple[PublicIntent, Commit | None]:
        offer = self.offers.get(act.offer_ref or "")
        named = offer is not None and self._named(offer.spec, heard)
        if not named and self.state == "CONFIRM" and self._pending is not None:
            offer, named = self.offers[self._pending], True  # "yes" to the read-back
        elif not named:
            offer = offer or self.offers.get(self._latest() or "")
        if offer is None:
            return PublicIntent(kind="clarify"), None
        if offer.status != "open":
            return PublicIntent(
                kind="offer_unavailable", offer_ref=offer.spec.offer_ref
            ), None
        price = Decimal(offer.spec.terms.get("monthly_price", "NaN"))
        said = act.price_usd
        if not named or (said is not None and Decimal(str(said)) != price):
            self.state, self._pending = "CONFIRM", offer.spec.offer_ref
            return self._terms("confirm_accept", offer.spec), None
        spec = offer.spec
        offer.status, self.state, self._pending = "accepted", "CONFIRMED", None
        confirmation = (
            f"{int(sha256_text(f'{spec.offer_ref}:{utt_id}')[:8], 16) % 10**6:06d}"
        )
        terms = spec.all_terms
        months = int(terms.pop("term_months"))
        self.ledger.write(
            confirmation,
            BoundTerms(spec.offer_ref, 1, months, tuple(sorted(terms.items()))),
        )
        say = (("confirmation", confirmation),)
        intent = PublicIntent(kind="confirmed", offer_ref=spec.offer_ref, say=say)
        return intent, Commit(
            spec.offer_ref, confirmation, self.ledger.lookup(confirmation)
        )

    def _terms(self, kind: IntentKind, spec: OfferSpec) -> PublicIntent:
        return PublicIntent(
            kind=kind, offer_ref=spec.offer_ref, say=tuple(spec.all_terms.items())
        )

    def _expire(self, t_ms: int) -> list[Decision]:
        out: list[Decision] = []
        for ref, offer in self.offers.items():
            if offer.status == "open" and t_ms >= offer.expires_ms:
                offer.status = "expired"
                intent = PublicIntent(kind="offer_expired", offer_ref=ref)
                out.append(Decision(self.state, self.state, intent, self._rung()))
        return out

    @staticmethod
    def _named(spec: OfferSpec, heard: str) -> bool:
        price = spec.terms.get("monthly_price")
        said_price = price is not None and Decimal(price) in numbers(heard)
        return said_price or spec.offer_ref.casefold() in heard.casefold()

    def _missing(self) -> tuple[str, ...]:
        return tuple(k for k in self.spec.identity if k not in self._verified)

    def _latest(self) -> str | None:
        return self.spec.ladder[self.rung].offer_ref if self.rung >= 0 else None

    def _offer_state(self) -> State:
        if self.rung < 0:
            return "DISCOVER"
        return "FINAL" if self.rung == len(self.spec.ladder) - 1 else "OFFER"

    def _rung(self) -> int | None:
        return self.rung if self.rung >= 0 else None
