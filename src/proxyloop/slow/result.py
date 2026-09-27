"""A Slow tool's outcome: the text Slow reads and the ``guard`` effects to emit."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

Effect = tuple[str, Mapping[str, object]]
Code = Literal["invalid_args", "unknown_tool", "act_shape"]  # refusals (S1-SYS-21)


@dataclass(frozen=True)
class Result:
    ok: bool
    text: str
    effects: tuple[Effect, ...] = ()
    then: Callable[[], None] | None = None
    causes: tuple[str, ...] = ()  # cited by every effect, after the slow.tool
    code: Code | None = None  # a refusal's class (the slow.tool's ``code``)


def no(text: str, *effects: Effect) -> Result:
    return Result(False, text, effects)


def refused(code: Code, text: str) -> Result:
    return Result(False, text, code=code)
