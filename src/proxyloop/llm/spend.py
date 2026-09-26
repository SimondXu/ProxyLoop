"""``SpendLedger``: prices every ``llm.call`` record and stops a runaway episode.

Three pricing bases, so no call is ever silently priced at zero:
- ``tokens``: relay models with a rate solved in ADR-0001 (Decision 7);
- ``gpu_time``: vLLM calls. Modal bills the GPU per second, per job, outside
  any call; GPU $ come from Modal usage (PLAN §0.8), never from this ledger;
- ``unpriced``: no measured rate (TeamRouter's world model, ADR-0005; GPT
  output rates, ADR-0001) or no usage reported. Counted, never summed.

The runaway guard raises ``RunawaySpend`` once the priced total passes
``RUNAWAY_FACTOR`` times the projected episode cost; the charge that crossed
the line travels with the exception.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from proxyloop.contract.base import Frozen
from proxyloop.contract.llm import Endpoint, LLMCallRecord, LLMRole
from proxyloop.contract.state import Spend

RUNAWAY_FACTOR = 10


@dataclass(frozen=True)
class Rate:
    usd_per_m_input: float
    usd_per_m_output: float


# ADR-0001 Decision 7: solved from the relay's total_usage deltas (USD per 1M tokens).
RELAY_RATES: Mapping[str, Rate] = {
    "claude-sonnet-5": Rate(3.00, 15.00),
    "claude-haiku-4-5-20251001": Rate(1.001, 5.006),
    "claude-opus-4-8": Rate(5.00, 25.00),
}


class Charge(Frozen):
    """The ``spend.charged`` payload for one ``llm.call``."""

    call_id: str
    role: LLMRole
    attempt: int
    endpoint: Endpoint | None
    model_id: str
    basis: Literal["tokens", "gpu_time", "unpriced"]
    micro_usd: int | None = Field(default=None, ge=0)  # None unless basis is tokens


class RunawaySpend(RuntimeError):
    def __init__(self, message: str, charge: Charge) -> None:
        super().__init__(message)
        self.charge = charge


class SpendLedger:
    def __init__(
        self, projected_episode_micro_usd: int, rates: Mapping[str, Rate] = RELAY_RATES
    ) -> None:
        if projected_episode_micro_usd <= 0:
            raise ValueError("the projected episode cost must be positive")
        self.limit_micro_usd = RUNAWAY_FACTOR * projected_episode_micro_usd
        self._rates = rates
        self._by_role: dict[str, int] = {}
        self.unpriced_calls = 0

    def price(self, record: LLMCallRecord) -> Charge:
        ref, usage = record.model_ref, record.usage
        rate = self._rates.get(ref.model_id) if ref.endpoint == "relay" else None
        micro: int | None = None
        if ref.endpoint == "vllm":
            basis = "gpu_time"
        elif rate is not None and usage is not None:
            basis = "tokens"
            micro = round(
                usage.prompt_tokens * rate.usd_per_m_input
                + usage.completion_tokens * rate.usd_per_m_output
            )  # USD per 1M tokens == micro-USD per token
        else:
            basis = "unpriced"
        return Charge(
            call_id=record.call_id,
            role=record.role,
            attempt=record.attempt,
            endpoint=ref.endpoint,
            model_id=ref.model_id,
            basis=basis,
            micro_usd=micro,
        )

    def charge(self, record: LLMCallRecord) -> Charge:
        charge = self.price(record)
        if charge.basis == "unpriced":
            self.unpriced_calls += 1
        if charge.micro_usd:
            role = charge.role
            self._by_role[role] = self._by_role.get(role, 0) + charge.micro_usd
        total = self.spend.micro_usd
        if total > self.limit_micro_usd:
            raise RunawaySpend(
                f"runaway spend: {total} micro-USD > {self.limit_micro_usd} "
                f"({RUNAWAY_FACTOR}x the projected episode cost)",
                charge,
            )
        return charge

    @property
    def spend(self) -> Spend:
        return Spend(micro_usd=sum(self._by_role.values()), by_role=dict(self._by_role))
