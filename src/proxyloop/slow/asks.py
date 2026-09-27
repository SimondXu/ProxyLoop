"""Plan before act (ADR-0012, S1-SYS-21): ``ask_user``'s ``keys`` and its dedupe
(A1), ``start_call()``, and the status bar's ``readiness`` and ``asks`` lines.
Guard decides (``guard.readiness``, ``guard.needs``); these are its words for
Slow. The needs ledger they read holds key names, states and times, never text
(I5). Bad arguments are refused, never repaired (rule 12)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from proxyloop.guard import needs
from proxyloop.slow.result import Result, no, refused

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

MAX_KEYS = 8


@dataclass(frozen=True, slots=True)
class Intake:
    """The call gate as Slow's status bar shows it."""

    missing: tuple[str, ...]  # readiness keys not public
    reason: str | None  # why the call opened; None: not open yet
    deadline_ms: int | None  # when the intake ends, while it runs
    ledger: needs.Ledger


def intake(k: Kernel) -> Intake:
    c = k.calls
    reason = None if c.opened is None else str(c.opened.payload["reason"])
    return Intake(c.missing(), reason, c.deadline_ms, c.needs)


def ask_problem(
    a: Mapping[str, Any], shareable: frozenset[str], ledger: needs.Ledger
) -> Result | None:
    """Why ``ask_user(text, keys)`` is refused, else None. ``keys`` (optional)
    names the SHAREABLE FACT KEYS the question asks for (A5: never text)."""
    keys = a.get("keys")
    if keys is None or keys == []:
        return None  # keyless: counted, not deduped
    if not isinstance(keys, list) or len(cast(list[object], keys)) > MAX_KEYS:
        return refused("invalid_args", f"invalid arguments: keys: ≤ {MAX_KEYS} keys")
    names = cast(list[object], keys)
    if bad := [k for k in names if not isinstance(k, str) or k not in shareable]:
        return refused(
            "invalid_args",
            f"invalid arguments: keys: {', '.join(map(str, bad))} is not one of "
            "the SHAREABLE FACT KEYS; ask for anything else without keys",
        )
    denied = needs.ask_denial(ledger, cast(list[str], names))
    return None if denied is None else no(denied)


def start_call(k: Kernel) -> Result:
    """``start_call()``: open the call before every readiness key is public,
    only once each missing one was asked and the user replied (R1)."""
    c = k.calls
    if c.opened is not None or c.deadline_ms is None:
        return no("the call is already open")
    if denial := needs.start_denial(c.needs, c.missing()):
        denied = {"intent": "start_call", "reason": "readiness_not_replied"}
        return no(f"refused: {denial}", ("action.denied", denied))
    return Result(True, "the call opens now; the phone voice discloses first")


def _key(key: str, ledger: needs.Ledger, now_ms: int) -> str:
    need = ledger.needs.get(key)
    if need is None:
        return f"{key} not asked"
    if need.asked_ms is None:
        return f"{key} {need.state}"
    return f"{key} {need.state} (asked {(now_ms - need.asked_ms) // 1000} s ago)"


def _missing(key: str, ledger: needs.Ledger, now_ms: int) -> str:
    said = _key(key, ledger, now_ms)
    if ledger.state(key) != "answered":
        return said
    return f"{said}, recorded private: re-record it citing the user's line"  # #140


def readiness_line(i: Intake, now_ms: int) -> str:
    what = ", ".join(_missing(k, i.ledger, now_ms) for k in i.missing)
    if i.reason is not None:
        still = f"; still missing: {what}" if what else ""
        return f"readiness: call open ({i.reason}){still}"
    if not i.missing:
        return "readiness: nothing missing; the call opens now"
    left = None if i.deadline_ms is None else max(0, i.deadline_ms - now_ms) // 1000
    return (
        f"readiness: call not open; missing: {what}. It opens when none is "
        "missing, or on start_call() once each missing key is replied"
    ) + ("" if left is None else f", or at the deadline in {left} s")


def asks_line(i: Intake, now_ms: int) -> str:
    keyed = [_key(k, i.ledger, now_ms) for k in sorted(i.ledger.needs)]
    keyless = [f"{i.ledger.keyless} without keys"] if i.ledger.keyless else []
    return f"asks: {'; '.join(keyed + keyless) or 'none'}"
