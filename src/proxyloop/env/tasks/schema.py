"""Task schema (EVAL §2): Pine's fields plus ours, one family per YAML file.

``profile``, ``counterparty``, ``principal`` and ``stop`` are world-side hidden
data: agent modules get only the briefs, through the kernel. A ``full`` task has
a ``principal`` (what the sim approver grants); ``stop`` is the unscripted stop
or mind change of ``x-user-mind-change``. New fields default to ``None`` so the
instance hash (``exclude_none``) of an older task is unchanged. ``user_goal``
states a number only as a ``{fact.key}`` reference, so the goal and the facts
never disagree (instances, mind changes): ``Task.goal(facts)`` renders it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, ValidationError, model_validator

from proxyloop.contract import base
from proxyloop.contract.base import FACT_KEY, Frozen, Lane
from proxyloop.contract.messages import OFFER_REF
from proxyloop.contract.state import READBACK_FIELD
from proxyloop.env.ledger import LedgerMode

FactKey = Annotated[str, StringConstraints(pattern=rf"^{FACT_KEY}$")]
TermField = Annotated[str, StringConstraints(pattern=READBACK_FIELD)]
GOAL_REF = re.compile(rf"\{{({FACT_KEY})\}}")
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


Money = Annotated[str, StringConstraints(pattern=r"^\d+(?:\.\d\d)?$")]  # dollars
Bound = Literal["max_monthly_price_usd", "max_term_months", "max_one_time_fees_usd"]


class Limits(Frozen):
    max_monthly_price_usd: Money | None = None
    max_term_months: int | None = Field(default=None, ge=1)
    max_one_time_fees_usd: Money | None = None


class Principal(Frozen):
    """What the principal grants (ARCHITECTURE §10.2). ``envelope`` names the
    profile facts in which the user states their limits: a mandate within them
    is granted. ``limits`` are the unstated limits an approval card is judged
    by (default: the envelope). The sim approver answers after a delay sampled
    from ``approver_delay_s``."""

    envelope: dict[Bound, FactKey] = Field(min_length=1)
    limits: Limits | None = None
    approver_delay_s: ReplyDelay


class Stop(Frozen):
    """The user's unscripted stop, or with ``change`` a mind change: the
    profile facts the user changes, said in the stop reply (EVAL §2)."""

    trigger: Literal["after_card", "after_offer", "after_turn_k"]
    k: int | None = Field(default=None, ge=1)  # after_turn_k only
    text_hint: Brief
    change: dict[FactKey, str] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _k(self) -> Self:
        if (self.k is not None) != (self.trigger == "after_turn_k"):
            raise ValueError("stop.k is set exactly for after_turn_k")
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
    principal: Principal | None = None
    stop: Stop | None = None

    @model_validator(mode="after")
    def _facts(self) -> Self:
        named = {*self.counterparty.identity, *self.disclosure.shareable}
        if self.principal is not None:
            named |= set(self.principal.envelope.values())
        named |= set(self.stop.change or ()) if self.stop is not None else set()
        named |= set(GOAL_REF.findall(self.user_goal))
        if re.search(r"\d", GOAL_REF.sub("", self.user_goal)):
            raise ValueError("user_goal states numbers only as {fact.key}")
        if unknown := sorted(named - self.profile.facts.keys()):
            raise ValueError(f"unknown profile facts {unknown}")
        return self

    def goal(self, facts: Mapping[str, str]) -> str:
        """``user_goal`` with each ``{fact.key}`` said as its value in ``facts``."""

        return GOAL_REF.sub(lambda m: facts[m.group(1)], self.user_goal)

    @model_validator(mode="after")
    def _principal(self) -> Self:
        if (self.principal is not None) != (self.mode == "full"):
            raise ValueError("a principal is given exactly in full mode")
        if self.stop is not None and self.principal is None:
            raise ValueError("a stop needs a full-mode principal")
        if self.principal is not None:
            stated = {
                b: self.profile.facts[k] for b, k in self.principal.envelope.items()
            }
            try:
                Limits.model_validate(stated)
            except ValidationError as err:
                raise ValueError(f"an envelope fact is not a limit: {err}") from err
        stop = self.stop is not None and self.stop.change is None
        if stop != (self.gold.check == "no_commit_after_stop"):
            raise ValueError("gold no_commit_after_stop goes with a stop")
        return self
