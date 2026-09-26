"""Task schema (EVAL §2): Pine's fields plus ours, one family per YAML file.

``profile`` and ``counterparty`` are world-side hidden data: agent modules get
only the briefs, through the kernel. The ``stop`` and ``authorization`` fields
arrive with the S1 families that use them.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from proxyloop.contract import base
from proxyloop.contract.base import FACT_KEY, Frozen, Lane
from proxyloop.contract.messages import OFFER_REF
from proxyloop.contract.state import READBACK_FIELD
from proxyloop.env.ledger import LedgerMode

FactKey = Annotated[str, StringConstraints(pattern=rf"^{FACT_KEY}$")]
TermField = Annotated[str, StringConstraints(pattern=READBACK_FIELD)]
Brief = Annotated[str, StringConstraints(min_length=1, max_length=base.MAX_BRIEF)]


class ReplyDelay(Frozen):
    range: tuple[float, float]

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not 0 <= self.range[0] <= self.range[1]:
            raise ValueError("reply_delay_s.range needs 0 <= low <= high")
        return self


class UserSpec(Frozen):
    reply_delay_s: ReplyDelay  # no patience, no strikes (ARCHITECTURE §10.2)


class Profile(Frozen):
    persona: str = Field(min_length=1)
    facts: dict[FactKey, str] = Field(min_length=1)


class Disclosure(Frozen):
    shareable: tuple[FactKey, ...] = ()  # profile facts that may be declassified


class OfferSpec(Frozen):
    """A ladder rung: ``terms`` are said when offering, ``hidden`` only on a
    read-back."""

    offer_ref: str = Field(pattern=rf"^{OFFER_REF}$")
    terms: dict[TermField, str] = Field(min_length=1)
    hidden: dict[TermField, str] = Field(default_factory=dict[str, str])
    ttl_s: float = Field(gt=0)

    @property
    def all_terms(self) -> dict[str, str]:
        return self.terms | self.hidden

    @model_validator(mode="after")
    def _terms(self) -> Self:
        if self.terms.keys() & self.hidden.keys():
            raise ValueError("a term is either said or hidden, not both")
        if not self.all_terms.get("term_months", "").isdigit():
            raise ValueError("an offer needs an integer term_months")
        return self


class Patience(Frozen):
    silence_s: float = Field(default=6, gt=0)
    hold_s: float = Field(ge=20, le=60)
    strikes: int = Field(default=3, ge=1)


class CounterpartySpec(Frozen):
    company: str = Field(min_length=1)
    persona: str = Field(min_length=1)
    identity: tuple[FactKey, ...] = Field(min_length=1)  # profile facts it checks
    ladder: tuple[OfferSpec, ...] = Field(min_length=1)
    patience: Patience
    ledger: LedgerMode = LedgerMode.HONEST

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if len({o.offer_ref for o in self.ladder}) != len(self.ladder):
            raise ValueError("offer_refs must be unique")
        return self


class Gold(Frozen):
    check: Literal["ledger", "portal", "ledger+no_deal", "no_commit_after_stop"]


class Task(Frozen):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    family: str = Field(pattern=r"^[a-z0-9-]+$")
    version: int = Field(ge=1)
    stratum: Literal["cp_success", "cp_hazard", "cross", "portal"]
    mode: Literal["info_only", "full"]
    channels: tuple[Lane, ...] = Field(min_length=1)
    fast_brief_user: Brief
    fast_brief_cp: Brief
    slow_brief: Brief
    profile: Profile
    user_goal: str = Field(min_length=1)
    probes: tuple[str, ...] = ()
    disclosure: Disclosure
    user: UserSpec
    counterparty: CounterpartySpec
    gold: Gold

    @model_validator(mode="after")
    def _facts(self) -> Self:
        named = {*self.counterparty.identity, *self.disclosure.shareable}
        if unknown := sorted(named - self.profile.facts.keys()):
            raise ValueError(f"unknown profile facts {unknown}")
        return self
