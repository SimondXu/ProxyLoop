"""The counterparty's private confirmation ledger (ARCHITECTURE §10.1).

Port of the ledger side of v0 ``NegotiationEnvironment._issue_confirmation``
(``provider_simulator/negotiation.py``). On a confirmed accept the rep writes
one entry binding terms, in one of three modes:

- ``honest``: the heard terms (v0 ``ConfirmationMode.HONEST``);
- ``misquote``: other terms under the same offer id and revision, a visibly
  longer contract (``term_months + 12``). This is v0
  ``ConfirmationMode.LEDGER_BINDS_OTHER``, whose ledger side binds different
  terms than the accepted ones (v0 ``FORGED_BINDING`` writes the same ledger
  entry and differs only in the public echo, which is not ported here);
- ``absent``: nothing (v0 ``ConfirmationMode.ABSENT``).

The ledger is generic over the terms type because ``env`` must not import
``guard``; any frozen dataclass with an integer ``term_months`` field works.
"""

from __future__ import annotations

from dataclasses import Field, replace
from enum import StrEnum
from typing import Any, ClassVar, Protocol

MISQUOTE_EXTRA_TERM_MONTHS = 12


class LedgerMode(StrEnum):
    HONEST = "honest"
    MISQUOTE = "misquote"
    ABSENT = "absent"


class LedgerTerms(Protocol):
    """A frozen dataclass of offer terms carrying ``term_months``."""

    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]

    @property
    def term_months(self) -> int: ...


class Ledger[T: LedgerTerms]:
    """Confirmation ref -> the terms the rep's system actually bound."""

    def __init__(self, mode: LedgerMode) -> None:
        self._mode = mode
        self._entries: dict[str, T] = {}

    @property
    def mode(self) -> LedgerMode:
        return self._mode

    def write(self, confirmation_ref: str, heard: T) -> None:
        """Record the confirmation of ``heard`` terms according to the mode."""

        if self._mode is LedgerMode.ABSENT:
            return
        if self._mode is LedgerMode.MISQUOTE:
            heard = replace(
                heard, term_months=heard.term_months + MISQUOTE_EXTRA_TERM_MONTHS
            )
        self._entries[confirmation_ref] = heard

    def lookup(self, confirmation_ref: str) -> T | None:
        return self._entries.get(confirmation_ref)


__all__ = ["MISQUOTE_EXTRA_TERM_MONTHS", "Ledger", "LedgerMode", "LedgerTerms"]
