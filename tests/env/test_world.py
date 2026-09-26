"""The world-call policy (ADR-0005 Decisions 5-6) and the number helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal

import pytest
from tests.support.fakes import ScriptedLLM, fake_ref

from proxyloop.contract.llm import LLMUnavailable, TextRequest
from proxyloop.env import world
from proxyloop.env.counterparty.mouth import fidelity_ok, template
from proxyloop.env.counterparty.policy import PublicIntent


def _check(raw: int) -> int:
    if raw < 0:
        raise world.Invalid("negative")
    return raw


def _run(
    outputs: list[int], exhausted: Callable[[], int] | None = None
) -> tuple[int, int, bool]:
    seen: list[int] = []

    async def attempt(n: int) -> int:
        seen.append(n)
        return outputs[n]

    result = asyncio.run(
        world.bounded(attempt, _check, what="t", timeout_s=1, exhausted=exhausted)
    )
    assert seen == list(range(result[1]))  # one attempt per regeneration
    return result


def test_a_valid_first_output_takes_one_attempt() -> None:
    assert _run([7]) == (7, 1, True)


def test_at_most_two_regenerations_are_counted() -> None:
    assert _run([-1, -1, 5]) == (5, 3, True)


def test_still_invalid_after_two_regenerations_is_an_episode_error() -> None:
    with pytest.raises(world.WorldError, match="invalid after 2 regenerations"):
        _run([-1, -1, -1, 9])


def test_only_a_named_fallback_replaces_an_exhausted_output() -> None:
    assert _run([-1, -1, -1], exhausted=lambda: 0) == (0, 3, False)


def test_a_wall_clock_timeout_is_an_episode_error() -> None:
    async def slow(n: int) -> int:
        await asyncio.sleep(5)
        return n

    with pytest.raises(world.WorldError, match="no answer within"):
        asyncio.run(world.bounded(slow, _check, what="t", timeout_s=0.01))


def test_llm_unavailable_propagates_untouched() -> None:
    dead = ScriptedLLM(fake_ref(), [], dead=True)
    request = TextRequest(
        call_id="c", role="mouth", prompt="hi", max_tokens=8, temperature=0
    )

    async def attempt(n: int) -> str:
        return "".join(
            [x async for x in dead.stream_text(request) if isinstance(x, str)]
        )

    with pytest.raises(LLMUnavailable):
        asyncio.run(world.bounded(attempt, str, what="t", timeout_s=1, exhausted=str))


def test_numbers_reads_digits_only() -> None:
    assert world.numbers("$1,250.50 for 12 months, code 048213") == {
        Decimal("1250.50"),
        Decimal(12),
        Decimal(48213),
    }
    assert world.numbers("seventy-five") == set()


def test_mouth_fidelity_needs_every_value_and_no_other_number() -> None:
    offer = PublicIntent(
        kind="offer", say=(("monthly_price", "75.00"), ("term_months", "12"))
    )
    assert fidelity_ok("I can do $75 a month on a 12-month term.", offer)
    assert not fidelity_ok("I can do $75 a month.", offer)  # a value is missing
    assert not fidelity_ok("$75 for 12 months, or $70 for 24.", offer)  # invented
    ask = PublicIntent(kind="greet", ask=("account.last4",))
    assert fidelity_ok("Could I get the last 4 digits?", ask)
    assert fidelity_ok(template(offer, "Northwind"), offer)
