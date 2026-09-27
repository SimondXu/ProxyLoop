"""``pl_cp_v2``: ``pl_cp_v1`` plus the ``hold_for_fact`` move (ADR-0011).

``pl_cp_v1`` stays byte-for-byte frozen so its fingerprint, and the bundles
that record it, still verify.
"""

from __future__ import annotations

from dataclasses import replace

from proxyloop.contract.profiles import pl_cp_v1

PROFILE = replace(
    pl_cp_v1.PROFILE,
    name="pl_cp_v2",
    moves={
        **pl_cp_v1.PROFILE.moves,
        "hold_for_fact": "Say you are getting that detail from your customer and "
        "ask them to hold a moment (@hold fact_request).",
    },
    p2_ids_sha256="f3c330dcae4331fe249f2f095a4ce00d656825a331fd307d07c205bed3a0e539",
)
