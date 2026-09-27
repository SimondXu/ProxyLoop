"""Instances of a family: seeded perturbations that keep its semantics.

Instance 0 is the file itself. Instance ``n`` shifts every monthly price (the
ladder's, the stated and the hidden limits') by the same offset (-8..8 dollars
plus 0, 49 or 99 cents), every non-zero one-time fee and fee limit by another
(0..10 dollars), jitters each offer's TTL by ±25 %, and an ``after_turn_k``
stop's k by up to 2. Every order between a price and a limit is kept, so a
trap stays a trap; a zero fee limit ("no upfront fees") stays zero. Other
profile facts are unchanged; the goal follows the facts (``Task.goal``).

A draw in which an offer's money amount equals a number the user knows or the
approver judges by (``collisions``: e.g. a price equal to the competitor's) is
redrawn, deterministically: instance ``n`` is the first non-colliding draw of
``f"{family}:{n}:{attempt}"``, attempt 0, 1, ... Whether each instance is
still completable is ``reference.completable``'s job.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from decimal import Decimal

from proxyloop.env import world
from proxyloop.env.tasks.schema import Task

PRICE_SHIFT, CENTS = (-8, 8), ("0", "0.49", "0.99")  # dollars, and cents
FEE_SHIFT = (0, 10)
DRAWS = 20


def _usd(value: str, by: Decimal) -> str:
    shifted = Decimal(value) + by
    return f"{shifted:.2f}" if "." in value or shifted % 1 else str(shifted)


def _nonzero(value: str, by: Decimal) -> str:
    return value if Decimal(value) == 0 else _usd(value, by)


def collisions(task: Task) -> set[Decimal]:
    """Offer money amounts that equal a number the user knows (a profile or
    changed fact) or a hidden limit."""

    money = {
        Decimal(v)
        for o in task.counterparty.ladder
        for k, v in o.all_terms.items()
        if k == "monthly_price" or k.startswith(("fee:", "credit:"))
    } - {Decimal(0)}
    known = [*task.profile.facts.values()]
    if task.principal is not None and task.principal.limits is not None:
        known += [str(v) for v in task.principal.limits.model_dump().values() if v]
    if task.stop is not None:
        known += [*(task.stop.change or {}).values()]
    return money & {n for v in known for n in world.numbers(v)}


def instance(task: Task, seed: int) -> Task:
    if seed == 0:
        return task
    for attempt in range(DRAWS):
        drawn = _draw(task, seed, random.Random(f"{task.family}:{seed}:{attempt}"))
        if not collisions(drawn):
            return drawn
    raise ValueError(f"{task.family} instance {seed}: every draw collides")


def _draw(task: Task, seed: int, rng: random.Random) -> Task:
    dp = Decimal(rng.randint(*PRICE_SHIFT)) + Decimal(rng.choice(CENTS))
    df = Decimal(rng.randint(*FEE_SHIFT))

    def terms(said: dict[str, str]) -> dict[str, str]:
        return {
            k: _usd(v, dp)
            if k == "monthly_price"
            else _nonzero(v, df)
            if k.startswith("fee:")
            else v
            for k, v in said.items()
        }

    ladder = tuple(
        o.model_copy(
            update={
                "ttl_s": float(round(o.ttl_s * rng.uniform(0.75, 1.25))),
                "terms": terms(o.terms),
                "hidden": terms(o.hidden),
            }
        )
        for o in task.counterparty.ladder
    )
    cp = task.counterparty.model_copy(update={"ladder": ladder})
    update: dict[str, object] = {"id": f"{task.id}-i{seed}", "counterparty": cp}
    shift: dict[str, Callable[[str], str]] = {
        "max_monthly_price_usd": lambda v: _usd(v, dp),
        "max_one_time_fees_usd": lambda v: _nonzero(v, df),
    }
    if (principal := task.principal) is not None:
        by_key = {k: shift[b] for b, k in principal.envelope.items() if b in shift}

        def facts(given: dict[str, str]) -> dict[str, str]:
            return {k: by_key[k](v) if k in by_key else v for k, v in given.items()}

        update["profile"] = task.profile.model_copy(
            update={"facts": facts(task.profile.facts)}
        )
        if (limits := principal.limits) is not None:
            hidden = {b: getattr(limits, b) for b in shift}
            shifted = {b: shift[b](v) for b, v in hidden.items() if v is not None}
            limits = limits.model_copy(update=shifted)
            update["principal"] = principal.model_copy(update={"limits": limits})
        if (stop := task.stop) is not None:
            k = None if stop.k is None else stop.k + rng.randint(0, 2)
            change = None if stop.change is None else facts(stop.change)
            update["stop"] = stop.model_copy(update={"k": k, "change": change})
    return Task.model_validate(task.model_copy(update=update).model_dump(mode="json"))
