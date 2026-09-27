"""The shape of Slow's ``act`` and its refusal texts (S1-SYS-45, runs f828f1 and
aeab91): a malformed act or call gets one short refusal that says the shape it
needs. Nothing is reinterpreted or repaired (rule 12); refusals are counted as
every refused tool is (a ``slow.tool`` with ``ok`` false)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from pydantic import ValidationError

ACT_KEYS = ("private_summary", "public_summary", "calls")
ITEM = '{"tool": <tool name>, ...its arguments}'


def act_problem(args: Mapping[str, Any]) -> str | None:
    """Why the act's top level is not {private_summary, public_summary, calls}
    with ``calls`` a list; else None. The whole act is refused: no call runs."""
    if extra := sorted(set(args) - set(ACT_KEYS)):
        return (
            f"act takes only {', '.join(ACT_KEYS)}, not {', '.join(extra)}: nothing "
            f"ran; put each action in calls as {ITEM}"
        )
    if not isinstance(args.get("calls", []), list):
        return f"calls is a list of {ITEM}: nothing ran"
    return None


def item_problem(n: int, item: object) -> str | None:
    """Why ``calls[n]`` names no tool; else None."""
    if not isinstance(item, Mapping):
        return f"calls[{n}] is not an object {ITEM}"
    if "tool" not in item:
        keys = ", ".join(sorted(map(str, cast(Mapping[object, object], item))))
        return f"calls[{n}] has no tool (keys: {keys or 'none'}); each is {ITEM}"
    return None


def invalid(err: Exception) -> str:
    """``<field>: <short reason>`` of the first error, on one line."""
    if isinstance(err, ValidationError):
        first = err.errors()[0]
        field = ".".join(str(p) for p in first["loc"]) or "value"
        return f"{field}: {first['msg']}"
    if isinstance(err, KeyError):
        return f"{err.args[0]}: required"
    return str(err).splitlines()[0] if str(err) else type(err).__name__
