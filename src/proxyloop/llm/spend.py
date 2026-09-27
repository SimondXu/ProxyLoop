"""``SpendLedger``: prices every ``llm.call`` record and stops a runaway episode.

Three pricing bases, so no call is ever silently priced at zero:
- ``tokens``: relay models with a rate solved in ADR-0001 (Decision 7), and
  OpenRouter models with a listed rate (``OPENROUTER_RATES``);
- ``gpu_time``: vLLM calls. Modal bills the GPU per second, per job, outside
  any call; GPU $ come from Modal usage (PLAN §0.8), never from this ledger;
- ``unpriced``: no measured rate (TeamRouter's world model, ADR-0005; GPT
  output rates, ADR-0001) or no usage reported. Counted, never summed.

Three runaway guards raise ``RunawaySpend``, with the charge that crossed the line
(the S0 guard, root decision under PLAN §0.5a, 2026-09-26):
- the priced total passes the absolute session cap (``SESSION_CAP_MICRO_USD``);
- the hosted tokens (every call but ``gpu_time``) pass the factor times the
  projected tokens per episode;
- the unpriced calls pass the factor times the projected calls per episode (no
  rate is invented for them).
The factor is ``RUNAWAY_FACTOR``, or ``UNPRICED_FACTOR`` when a session's model
has no rate: its spend has no $ bound, so the projection itself is the limit.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from proxyloop.contract.base import Frozen
from proxyloop.contract.llm import Endpoint, LLMCallRecord, LLMRole, ModelRef
from proxyloop.contract.state import Spend

RUNAWAY_FACTOR = 3  # was 10 (S0-SYS-04)
UNPRICED_FACTOR = 1  # a session with an unpriced model (main root, #133)
SESSION_CAP_MICRO_USD = 2_000_000  # $2 per session, whatever the projection


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

# OpenRouter's list prices, as read by the main root from
# https://openrouter.ai/api/v1/models on 2026-09-27 (USD per 1M tokens): a rate
# setting, not a result. A response's ``usage.cost`` is never the price.
OPENROUTER_RATES: Mapping[str, Rate] = {
    "openai/gpt-6-luna": Rate(0.10, 0.50),
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
        self,
        projected_tokens: int,
        projected_calls: int,
        cap_micro_usd: int = SESSION_CAP_MICRO_USD,
        rates: Mapping[str, Rate] = RELAY_RATES,
        refs: Iterable[ModelRef] = (),
        openrouter_rates: Mapping[str, Rate] = OPENROUTER_RATES,
    ) -> None:
        """``refs``: the session's models, known at its start; ``rates`` and
        ``openrouter_rates``: the relay's and OpenRouter's, by model id."""
        if min(projected_tokens, projected_calls, cap_micro_usd) <= 0:
            raise ValueError("the episode projections and the cap must be positive")
        self._tables = {"relay": rates, "openrouter": openrouter_rates}
        priced = all(r.endpoint == "vllm" or self._rate(r) for r in refs)
        self.factor = RUNAWAY_FACTOR if priced else UNPRICED_FACTOR
        self.limit_micro_usd = cap_micro_usd
        self.limit_tokens = self.factor * projected_tokens
        self.limit_unpriced_calls = self.factor * projected_calls
        self._by_role: dict[str, int] = {}
        self._unpriced_by_role: dict[str, int] = {}  # calls, per role
        self.unpriced_calls = self.gpu_time_calls = self.tokens = 0

    def _rate(self, ref: ModelRef) -> Rate | None:
        table = self._tables.get(ref.endpoint or "")
        return None if table is None else table.get(ref.model_id)

    def price(self, record: LLMCallRecord) -> Charge:
        ref, usage = record.model_ref, record.usage
        rate = self._rate(ref)
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
            role = charge.role
            self._unpriced_by_role[role] = self._unpriced_by_role.get(role, 0) + 1
        elif charge.basis == "gpu_time":
            self.gpu_time_calls += 1
        if charge.basis != "gpu_time" and (usage := record.usage) is not None:
            self.tokens += usage.prompt_tokens + usage.completion_tokens
        if charge.micro_usd:
            role = charge.role
            self._by_role[role] = self._by_role.get(role, 0) + charge.micro_usd
        total, unpriced = self.spend.micro_usd, self.unpriced_calls
        if total > self.limit_micro_usd:
            limit = self.limit_micro_usd
            raise RunawaySpend(f"runaway spend: {total} > {limit} micro-USD", charge)
        if self.tokens > self.limit_tokens:
            limit = self.limit_tokens
            raise RunawaySpend(f"runaway tokens: {self.tokens} > {limit}", charge)
        if unpriced > self.limit_unpriced_calls:
            limit = self.limit_unpriced_calls
            raise RunawaySpend(f"runaway calls: {unpriced} > {limit} unpriced", charge)
        return charge

    @property
    def spend(self) -> Spend:
        return Spend(micro_usd=sum(self._by_role.values()), by_role=dict(self._by_role))

    def totals(self) -> dict[str, object]:
        """Every charge so far, the unpriced and GPU-time calls beside the priced
        subtotal (the manifest's ``Spend`` holds only the latter until S1-CON-03)."""
        return {
            "priced_micro_usd": self.spend.micro_usd,
            "priced_by_role": dict(self._by_role),
            "unpriced_calls": self.unpriced_calls,
            "unpriced_by_role": dict(self._unpriced_by_role),
            "gpu_time_calls": self.gpu_time_calls,
            "tokens": self.tokens,
        }
