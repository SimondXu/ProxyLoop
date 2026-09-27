"""The needs ledger (ADR-0012, reduced by ADR-0016): a pure fold of the log
over Slow's keyed asks. Per key:
- ``pending`` from a successful ``ask_user(…, keys)`` (its ``slow.tool``);
- ``replied`` once a ``user.msg`` is newer than the ask's voicing (the
  ``s2f.voiced`` of its ``s2f.msg``). An echo relay citing an older message is
  no reply: no new user message exists, and relays are not read here;
- ``answered`` once a ``fact.recorded`` for the key exists (either scope).
Asking a replied or answered key again makes it pending again. An ask whose
``s2f.voiced`` cites a turn with no speech (the fold reads the ``fast.turn``
item kinds) was never heard: its keys return to their state before the ask
and are ``unvoiced`` until asked again (review D1). Keyless asks are counted,
not tracked; ``holds`` counts the cp holds (``chan.hold``).

It holds key names, states, seqs, times and counts only, never text, so it
adds no transcript path to Slow (I5). The kernel holds it, as ``Authority``."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from proxyloop.contract.events import Event

State = Literal["pending", "replied", "answered"]


@dataclass(frozen=True, slots=True)
class Need:
    key: str
    state: State
    asks: int = 0  # successful keyed asks
    asked_seq: int | None = None  # the latest ask's slow.tool
    asked_ms: int | None = None
    voiced_seq: int | None = None  # its s2f.voiced
    replied_seq: int | None = None  # the user.msg after it
    answered_seq: int | None = None  # the fact.recorded


_Ask = tuple[int, tuple[tuple[str, Need | None], ...]]  # seq, (key, need before)


@dataclass(frozen=True, slots=True)
class Ledger:
    needs: Mapping[str, Need] = field(default_factory=dict[str, Need])
    keyless: int = 0
    holds: int = 0
    unvoiced: frozenset[str] = frozenset()  # asked, but the ask was not heard
    asking: Mapping[str, _Ask] = field(  # ask event id -> the ask
        default_factory=dict[str, _Ask]
    )
    voicing: Mapping[str, _Ask] = field(  # s2f msg id -> the ask
        default_factory=dict[str, _Ask]
    )
    turn: tuple[str, bool] | None = None  # the last fast.turn: id, it spoke

    def state(self, key: str) -> State | None:
        need = self.needs.get(key)
        return None if need is None else need.state

    def states(self) -> dict[str, State]:
        return {k: n.state for k, n in sorted(self.needs.items())}


def _set(ledger: Ledger, keys: Iterable[str], **change: Any) -> Ledger:
    needs = dict(ledger.needs)
    for k in keys:
        now = needs.get(k) or Need(key=k, state="pending")
        needs[k] = dataclasses.replace(now, **change)
    return dataclasses.replace(ledger, needs=needs)


def step(ledger: Ledger, e: Event) -> Ledger:
    """The ledger after ``e``."""
    p, n = e.payload, ledger.needs
    if e.type == "slow.tool" and p["name"] == "ask_user" and p["ok"]:
        args = cast(Mapping[str, object], p["args"])
        keys = tuple(dict.fromkeys(cast(Sequence[str], args.get("keys") or ())))
        if not keys:
            return dataclasses.replace(ledger, keyless=ledger.keyless + 1)
        before = tuple((k, n.get(k)) for k in keys)
        asking = {**ledger.asking, e.event_id: (e.seq, before)}
        unvoiced = ledger.unvoiced - set(keys)
        ledger = dataclasses.replace(ledger, asking=asking, unvoiced=unvoiced)
        asks = {k: (n[k].asks if k in n else 0) + 1 for k in keys}
        for k in keys:  # a new ask: pending again, its voicing still to come
            ledger = _set(
                ledger, (k,), state="pending", asks=asks[k], asked_seq=e.seq,
                asked_ms=e.t_ms, voiced_seq=None, replied_seq=None,
            )  # fmt: skip
        return ledger
    if e.type == "s2f.msg" and e.cause_ids and e.cause_ids[0] in ledger.asking:
        asking = dict(ledger.asking)
        ask = asking.pop(e.cause_ids[0])
        voicing = {**ledger.voicing, str(p["msg_id"]): ask}
        return dataclasses.replace(ledger, asking=asking, voicing=voicing)
    if e.type == "fast.turn":
        items = cast(Sequence[Mapping[str, object]], p["items"])
        spoke = any(i.get("kind") == "speech" for i in items)
        return dataclasses.replace(ledger, turn=(e.event_id, spoke))
    if e.type == "s2f.voiced" and p["msg_id"] in ledger.voicing:
        voicing = dict(ledger.voicing)
        seq, before = voicing.pop(str(p["msg_id"]))
        ledger = dataclasses.replace(ledger, voicing=voicing)
        mine = [(k, b) for k, b in before if k in n and n[k].asked_seq == seq]
        heard = ledger.turn is not None and ledger.turn == (e.cause_ids[0], True)
        if heard:
            asked = [k for k, _ in mine if n[k].voiced_seq is None]
            return _set(ledger, asked, voiced_seq=e.seq)
        needs = dict(n)  # never heard: as before the ask (fail closed)
        for k, b in mine:
            if b is None:
                del needs[k]
            else:
                needs[k] = b
        unvoiced = ledger.unvoiced | {k for k, _ in mine}
        return dataclasses.replace(ledger, needs=needs, unvoiced=unvoiced)
    if e.type == "user.msg":
        heard = [k for k, x in n.items() if x.state == "pending" and x.voiced_seq]
        return _set(ledger, heard, state="replied", replied_seq=e.seq)
    if e.type == "fact.recorded":
        return _set(ledger, (str(p["key"]),), state="answered", answered_seq=e.seq)
    if e.type == "chan.hold" and p.get("reason") is not None:
        return dataclasses.replace(ledger, holds=ledger.holds + 1)
    return ledger


def fold(events: Iterable[Event]) -> Ledger:
    ledger = Ledger()
    for e in events:
        ledger = step(ledger, e)
    return ledger


def ask_denial(ledger: Ledger, keys: Sequence[str]) -> str | None:
    """A1: at most one successful ask per key while it is pending. A keyless
    ask is never refused here."""
    waiting = [k for k in keys if ledger.state(k) == "pending"]
    if not waiting:
        return None
    return (
        f"already asked, waiting for the user: {', '.join(waiting)}; "
        "ask again once the status bar shows it replied, or ask only for other keys"
    )


def start_denial(ledger: Ledger, missing: Sequence[str]) -> str | None:
    """``start_call`` (ADR-0012 R1): every missing readiness key was asked and
    the user has replied since (or it is answered)."""
    unasked = [k for k in missing if ledger.state(k) is None]
    if unasked:
        return f"not asked yet: {', '.join(unasked)}; ask_user for them with keys first"
    waiting = [k for k in missing if ledger.state(k) == "pending"]
    if waiting:
        return f"no reply from the user yet for {', '.join(waiting)}; wait for it"
    return None
