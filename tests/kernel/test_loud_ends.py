"""Every session end gates new work, loud ones too (S1-SYS-55 follow-up). A task
that dies of ``RunawaySpend``, ``Abort``, ``WorldError`` or ``LLMUnavailable``
ends the session, but the TaskGroup aborts only in its done callback: a FastU
or FastC woken in the same instant must start no paid ``fast.request`` first.
The session keeps today's reason, and the error is re-raised."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from tests.contract.samples import SONNET, call_record
from tests.kernel.test_session_end import NEW_WORK, Case
from tests.support.fakes import RepeatingLLM

from proxyloop.contract.llm import LLMUnavailable, ToolRequest, ToolResponse
from proxyloop.env import world
from proxyloop.env.world import MAX_REGENERATIONS, WorldError
from proxyloop.kernel import session
from proxyloop.kernel.session import Kernel
from proxyloop.kernel.watchdog import Abort
from proxyloop.llm.spend import RunawaySpend


class Held:
    """Slow's call waits here until ``fail`` lets it go and it ends the session
    loudly: ``how(k, inner)`` makes the failing answer."""

    def __init__(self, k: Kernel, how: Callable[[Kernel, RepeatingLLM], None]) -> None:
        loud = k.clients["slow"]
        assert isinstance(loud.inner, RepeatingLLM)
        self.inner, self.ref, self._k, self._how = loud.inner, loud.inner.ref, k, how
        loud.inner = self  # pyright: ignore[reportAttributeAccessIssue]
        self._go = asyncio.Event()

    def fail(self) -> None:
        self._go.set()

    async def chat_tools(self, request: ToolRequest) -> ToolResponse:
        await self._go.wait()
        self._how(self._k, self.inner)
        return await self.inner.chat_tools(request)


def _runaway(k: Kernel, inner: RepeatingLLM) -> None:  # this call's charge trips it
    k.ledger.limit_tokens = 0


def _dead(k: Kernel, inner: RepeatingLLM) -> None:  # the endpoint is gone
    inner._dead = True  # pyright: ignore[reportPrivateUsage]


def _step_cap(k: Kernel, inner: RepeatingLLM) -> None:
    raise Abort("slow_step_cap", "Slow reached 120 steps")


def _world(k: Kernel, inner: RepeatingLLM) -> None:
    raise WorldError("rep: no answer within 60 s")


LOUD = [
    pytest.param(_runaway, RunawaySpend, "budget", id="runaway_spend"),
    pytest.param(_step_cap, Abort, "slow_step_cap", id="abort"),
    pytest.param(_world, WorldError, "world_error", id="world_error"),
    pytest.param(_dead, LLMUnavailable, "llm_unavailable", id="llm_unavailable"),
]


@pytest.fixture(autouse=True)
def no_errors(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    caplog.set_level(logging.WARNING)
    yield
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def _loud(
    root: Path, how: Callable[[Kernel, RepeatingLLM], None], error: type[Exception]
) -> Case:
    """Slow's first call is held; in one instant the user and the rep speak
    (waking FastU and FastC), then the held call fails."""
    case = Case(root, "user", "cp")
    held = Held(case.k, how)

    def end(c: Case) -> None:
        c.says("user", "Any news?")
        c.says("cp", "One moment.")
        held.fail()

    with pytest.raises(error):
        asyncio.run(asyncio.wait_for(case.run(end), timeout=30))
    return case


def _ends_loudly(case: Case, reason: str, *landed: str) -> None:
    events = case.events
    (ended,) = [e for e in events if e.type == "session.ended"]
    assert events[-1] == ended and ended.payload["reason"] == reason
    at_end = [e for e in events if e.t_ms >= case.t_end]
    texts = [e.payload.get("text") for e in at_end]
    assert all(text in texts for text in landed), texts
    assert not [e for e in at_end if e.type in NEW_WORK], [e.type for e in at_end]
    assert case.k.bus.subscriber_errors == 0


@pytest.mark.parametrize(("how", "error", "reason"), LOUD)
def test_a_loud_end_starts_no_new_work(
    tmp_path: Path,
    how: Callable[[Kernel, RepeatingLLM], None],
    error: type[Exception],
    reason: str,
) -> None:
    case = _loud(tmp_path, how, error)
    _ends_loudly(case, reason, "Any news?", "One moment.")
    assert case.k._ending == reason  # pyright: ignore[reportPrivateUsage]


def test_a_runaway_charge_still_records(tmp_path: Path) -> None:
    """The call that trips the guard: its ``llm.call`` and ``spend.charged``
    are written, and the charge is the one the ledger refused."""
    case = _loud(tmp_path, _runaway, RunawaySpend)
    at_end = [e for e in case.events if e.t_ms >= case.t_end]
    kinds = [e.type for e in at_end if e.type in ("llm.call", "spend.charged")]
    assert kinds == ["llm.call", "spend.charged"], kinds
    call, charged = [e for e in at_end if e.type in kinds]
    assert call.payload["call_id"] == "slow:1" and call.payload["error"] is None
    assert charged.cause_ids == (call.event_id,)
    assert charged.payload["call_id"] == "slow:1"
    totals = case.events[-1].payload["spend"]
    assert isinstance(totals, dict) and totals


def test_a_dead_endpoint_still_records_its_call(tmp_path: Path) -> None:
    case = _loud(tmp_path, _dead, LLMUnavailable)
    calls = [e for e in case.events if e.type == "llm.call" and e.t_ms >= case.t_end]
    assert [c.payload["error"] for c in calls] == ["connection refused"]


# S1-SYS-43: session.ended names a world error (type, authored message: rule 15)
MARKER = "model said: SECRET provider: body"


def _bounded_error() -> WorldError:
    """The WorldError the real ``world.bounded`` raises for an Ear whose every
    attempt fails its check with an ``Invalid`` quoting model output."""

    async def attempt(n: int) -> str:
        return MARKER

    def check(raw: str) -> str:
        raise world.Invalid(raw)

    async def call() -> None:
        await world.bounded(attempt, check, what="ear", timeout_s=5)

    with pytest.raises(WorldError) as caught:
        asyncio.run(call())
    assert MARKER in str(caught.value)  # the world's message does quote it
    return caught.value


def _unknown_shape() -> WorldError:  # not one of the world's heads
    return WorldError(f"ear failed: {MARKER}")


INVALID = f"ear: invalid after {MAX_REGENERATIONS} regenerations"
TIMEOUT = "mouth: no answer within 60.0 s"


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        (_bounded_error, {"message": INVALID}),
        (lambda: WorldError(TIMEOUT), {"message": TIMEOUT}),
        (_unknown_shape, {}),
    ],
    ids=["invalid", "timeout", "unknown_shape"],
)
def test_a_world_error_end_records_its_type_and_authored_message(
    tmp_path: Path, make: Callable[[], WorldError], expected: dict[str, str]
) -> None:
    err = make()  # before the session's loop: bounded runs one of its own

    def fail(k: Kernel, inner: RepeatingLLM) -> None:
        raise err

    case = _loud(tmp_path, fail, WorldError)
    (ended,) = [e for e in case.events if e.type == "session.ended"]
    assert ended.payload["reason"] == "world_error"
    assert ended.payload["world_error"] == {"type": "WorldError"} | expected
    assert "SECRET" not in (case.k.path / "events.jsonl").read_text()


def test_no_other_end_has_a_world_error_key(tmp_path: Path) -> None:
    case = _loud(tmp_path, _runaway, RunawaySpend)
    (ended,) = [e for e in case.events if e.type == "session.ended"]
    assert "world_error" not in ended.payload


def test_a_dead_endpoint_outranks_a_world_error_and_names_none() -> None:
    """Both in the TaskGroup: ``run`` ends ``llm_unavailable``, and the error it
    hands ``_close`` makes no ``world_error`` key."""
    record = call_record(SONNET, usage=None, error="HTTP 503", response_sha=None)
    dead = LLMUnavailable("endpoint is dead", record)
    for leaves in ([_bounded_error(), dead], [dead, _bounded_error()]):
        reason, error = session._outcome(BaseExceptionGroup("both", leaves))  # pyright: ignore[reportPrivateUsage]
        assert (reason, error) == ("llm_unavailable", dead)
        assert session._world_error(error) is None  # pyright: ignore[reportPrivateUsage]
