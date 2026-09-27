"""``pl_cp_v3``: ``pl_cp_v2`` plus one grammar flag (ADR-0017).

A pause ends the turn's speech: after the parser emits a ``Hold`` or a
``Wait``, every later non-directive line is a ``speech_after_pause`` issue,
never voiced. The rendering is ``pl_cp_v2``'s; ``pl_cp_v2`` stays frozen.
"""

from __future__ import annotations

from dataclasses import replace

from proxyloop.contract.profiles import pl_cp_v2

PROFILE = replace(
    pl_cp_v2.PROFILE,
    name="pl_cp_v3",
    pause_ends_speech=True,
    p2_ids_sha256="b9dfd61afe16ee5c170dc90d5572e5076bb5bd1b9ac17ce37dd26aec764c6986",
)
