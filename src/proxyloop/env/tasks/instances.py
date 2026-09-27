"""Instances of a family: seeded perturbations that keep its semantics.

Instance 0 is the file itself. Instance ``n`` shifts every monthly price (the
ladder's, the stated and the hidden limits') by the same whole-dollar offset,
every non-zero one-time fee and fee limit by another, jitters each offer's TTL
by ±25 %, and an ``after_turn_k`` stop's k by up to 2. Every order between a
price and a limit is kept, so a trap stays a trap; a zero fee limit ("no
upfront fees") stays zero. Other profile facts are unchanged. Whether each
instance is still completable is ``reference.completable``'s job.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from decimal import Decimal

from proxyloop.env.tasks.schema import Task

PRICE_SHIFT = (-5, 5)  # whole dollars
FEE_SHIFT = (0, 10)


def _usd(value: str, by: int) -> str:
    shifted = Decimal(value) + by
    return f"{shifted:.2f}" if "." in value else str(shifted)


def _nonzero(value: str, by: int) -> str:
    return value if Decimal(value) == 0 else _usd(value, by)


def instance(task: Task, seed: int) -> Task:
    if seed == 0:
        return task
    rng = random.Random(f"{task.family}:{seed}")
    dp, df = rng.randint(*PRICE_SHIFT), rng.randint(*FEE_SHIFT)

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
