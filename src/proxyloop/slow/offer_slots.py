"""The read-back slot table Slow records offers by (S1-SYS-28, run ed5063): each
field's role (Guard's ``ROLE_OF``), unit (the ledger's ``UNITS``) and value form.
A slot Guard's read-back or terms code could never confirm or hash is refused
when it is recorded, with this table; it is never repaired (rule 12)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from proxyloop.contract import base
from proxyloop.contract.state import READBACK_FIELD, ReadbackSlot
from proxyloop.guard.readback import ROLE_OF
from proxyloop.slow.authority import UNITS

_FORM = {  # the value form of each unit, as the read-back and terms code read it
    "usd_minor": "whole cents",
    "months": "whole months",
    "bool": "true|false",
    "iso": "ISO time with zone, ≤ 24 chars, prefer …Z (2026-10-01T00:00:00Z) or none",
}
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # the read-back matches its day
_WHOLE = re.compile(r"[0-9]+")  # usd_minor and months: plain ASCII integers
_NONE = {"fees_none": "fee", "changes_none": "applied_change"}  # flag: its list


def _unit(kind: str) -> str:
    return UNITS.get(kind, "bool")


def _field(kind: str) -> str:  # "fee" -> "fee:<code>"
    return kind if re.fullmatch(READBACK_FIELD, kind) else f"{kind}:<code>"


TABLE = "; ".join(
    f"{_field(kind)} → {role}, {_unit(kind)}, {_FORM[_unit(kind)]}"
    for kind, role in ROLE_OF.items()
)


CITE = (  # run 84f731: Slow cited the line after the offer
    "Each slot's utt_ref must cite the utt of the rep line that says it; "
    "money is usd_minor in cents (75.00 → 7500), a term is months"
)


def refused(problems: list[str]) -> str:
    return (
        f"record_offer refused, nothing recorded: {'; '.join(problems)}. "
        f"Slots (field → role, unit, value): {TABLE}"
    )


def shape(raw: object) -> str | None:
    """Why a raw slot's field, role, unit or value text is not the table's;
    else None. Before binding: "78.00" is refused here, not as a declass."""
    if not isinstance(raw, Mapping):
        return f"a slot is an object, not {raw!r}"
    m = cast(Mapping[str, Any], raw)
    field, role, unit, v = (m.get(k) for k in ("field", "role", "unit", "value"))
    if not isinstance(field, str) or not re.fullmatch(READBACK_FIELD, field):
        return f"unknown field {field!r}"
    if len(field) > base.MAX_SLOT_FIELD:
        return f"{field} is over {base.MAX_SLOT_FIELD} chars"
    kind = field.partition(":")[0]
    if role != ROLE_OF[kind]:
        return f"{field} has role {ROLE_OF[kind]}, not {role!r}"
    if unit != _unit(kind):
        return f"{field} has unit {_unit(kind)}, not {unit!r}"
    if not isinstance(v, str) or len(v) > base.MAX_SLOT_VALUE:
        return f"{field} value is text of ≤ {base.MAX_SLOT_VALUE} chars, not {v!r}"
    if unit in ("usd_minor", "months") and not _WHOLE.fullmatch(v):
        return f"{field} is {_FORM[unit]}, not {v!r}"
    return None


def conflicts(raw: Sequence[Mapping[str, Any]]) -> list[str]:
    """Slots that no terms hash could bind together (``shape`` passed):
    none, a repeated field, or a ``*_none=true`` beside a slot of its list."""
    fields = [str(s["field"]) for s in raw]
    out = [] if raw else ["no slots"]
    out += [f"{f} repeats" for f in sorted({f for f in fields if fields.count(f) > 1})]
    for s in raw:
        if (kind := _NONE.get(str(s["field"]))) and s["value"] == "true":
            listed = [f for f in fields if f.partition(":")[0] == kind]
            out += [f"{s['field']}=true with {f}" for f in listed]
    return out


def value(slot: ReadbackSlot) -> str | None:
    """Why a slot's value is not in its unit's form; else None. Money and
    months are bound to the rep's line (``record_offer``), not here."""
    v = slot.value
    if slot.unit == "bool" and v not in ("true", "false"):
        return f"{slot.field} is true or false, not {v!r}"
    if slot.unit == "iso" and v != "none" and not _zoned(v):
        return f"{slot.field} is an ISO time with zone or none, not {v!r}"
    return None


def _zoned(v: str) -> bool:
    try:
        at = datetime.fromisoformat(v)
    except ValueError:
        return False
    return at.utcoffset() is not None and _DAY.match(v) is not None
