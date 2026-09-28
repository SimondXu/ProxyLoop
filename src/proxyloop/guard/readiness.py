"""Readiness (ADR-0012): the facts a task kind needs public before its call
opens. An agent-side table, not task data (a task field would change the
piloted instance hashes); later task kinds add rows, not a redesign. Pure."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from types import MappingProxyType
from typing import Protocol

from proxyloop.contract.state import Blackboard

IDENTITY = ("account.holder_name", "account.last4")  # the rep verifies these
REQUIRED: Mapping[str, tuple[str, ...]] = MappingProxyType({"cp_call": IDENTITY})


class _Disclosure(Protocol):
    @property
    def shareable(self) -> Sequence[str]: ...


class TaskLike(Protocol):  # env's Task (guard never imports env)
    @property
    def channels(self) -> Sequence[str]: ...

    @property
    def disclosure(self) -> _Disclosure: ...


def kind(task: TaskLike) -> str | None:
    return "cp_call" if "cp" in task.channels else None


def required(task: TaskLike, learned: Collection[str] = frozenset()) -> tuple[str, ...]:
    """The kind's row, then any ``learned`` rows (data), each only if the task
    may share it: a key the agent can never make public is never required."""
    row = REQUIRED.get(kind(task) or "", ())
    rows = (*row, *sorted(learned)) if row else ()
    shareable = set(task.disclosure.shareable)
    return tuple(dict.fromkeys(k for k in rows if k in shareable))


def missing(bb: Blackboard, need: Sequence[str]) -> tuple[str, ...]:
    return tuple(k for k in need if k not in bb.public.facts)
