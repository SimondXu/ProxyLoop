"""ADR-0012: the readiness table. A cp call needs the identity keys the task
may share public before it opens; later task kinds add rows, not a redesign."""

from __future__ import annotations

from proxyloop.contract.state import Blackboard, PublicFact
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.tasks.schema import Task
from proxyloop.guard.readiness import IDENTITY, REQUIRED, kind, missing, required

TASK = load_task("cp-direct-discount")


def _task(channels: tuple[str, ...], shareable: tuple[str, ...]) -> Task:
    data = TASK.model_dump(mode="json")
    data["channels"], data["disclosure"]["shareable"] = channels, shareable
    return Task.model_validate(data)


def test_a_cp_task_needs_the_shareable_identity_keys() -> None:
    assert kind(TASK) == "cp_call"
    assert REQUIRED["cp_call"] == IDENTITY
    assert required(TASK) == ("account.holder_name", "account.last4")


def test_only_shareable_keys_are_required() -> None:
    only_last4 = _task(("user", "cp"), ("account.last4", "tenure_years"))
    assert required(only_last4) == ("account.last4",)
    assert required(_task(("user", "cp"), ())) == ()


def test_a_task_without_a_call_needs_nothing() -> None:
    chat = _task(("user",), ("account.last4",))
    assert kind(chat) is None
    assert required(chat) == ()


def test_learned_rows_arrive_as_data_and_stay_shareable_only() -> None:
    got = required(TASK, learned=frozenset({"tenure_years", "account.pin"}))
    assert got == ("account.holder_name", "account.last4", "tenure_years")


def test_missing_is_the_required_keys_not_public() -> None:
    need = required(TASK)
    assert missing(Blackboard(), need) == need
    fact = PublicFact(
        key="account.last4", value="4821", source="shareable", source_ref="u1"
    )
    bb = Blackboard()
    public = bb.public.model_copy(update={"facts": {fact.key: fact}})
    assert missing(bb.model_copy(update={"public": public}), need) == (
        "account.holder_name",
    )
