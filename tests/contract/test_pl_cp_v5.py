"""ADR-0029: the candidate cp profile ``pl_cp_v5`` is ``pl_cp_v4`` with the decision
table in a new system text; its system sha256 and fingerprint are pinned in the ADR."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from proxyloop.contract.base import sha256_text
from proxyloop.contract.protocol import PROFILES, fingerprint

ADR = Path(__file__).parents[2] / "docs/decisions/0029-cp-decision-table.md"
SYSTEM_SHA256 = "56de846c3973894aaed17fdf91ad5805ce10606012b8268afa8be445f8d8920c"


def test_pl_cp_v5_is_pl_cp_v4_with_a_new_system_text() -> None:
    v4, v5 = PROFILES["pl_cp_v4"], PROFILES["pl_cp_v5"]
    same = {f.name for f in fields(v4)} - {"name", "system", "p2_ids_sha256"}
    assert all(getattr(v4, f) == getattr(v5, f) for f in same)
    assert v5.system != v4.system


def test_system_sha256_and_fingerprint_are_pinned_in_the_adr() -> None:
    assert sha256_text(PROFILES["pl_cp_v5"].system) == SYSTEM_SHA256
    adr = ADR.read_text("utf-8")
    assert SYSTEM_SHA256 in adr
    assert fingerprint("pl_cp_v5") in adr
