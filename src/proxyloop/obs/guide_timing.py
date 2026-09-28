"""GUIDE timing: from each GUIDE to the first line heard of a generation that
voiced it, through cancelled generations' re-runs.

ADVISORY ONLY: triage signals, never a metric, a claim or a merge gate (and
never imported by ``proxyloop.eval``). It registers in ``DETECTORS``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from proxyloop.obs.detectors import Inputs, Value, detector
from proxyloop.obs.guides import superseded as unvoiced_superseded


@detector("guide_to_heard_ms")
def _guide_to_heard(x: Inputs) -> Value:
    """From each GUIDE s2f.msg to the first utt.delivered of a generation that
    voiced it (s2f.voiced msg_id → gen_id; fast.sentence utt_id → gen_id). A
    voicing generation that was cancelled (``fast.cancelled``; S1-SYS-59's
    ``verbatim`` comes after its s2f.voiced) is replaced by its re-run
    (``_reruns``), followed through further cancellations; ``cancelled``:
    guides with such a generation. On bundles before #230, or when the GUIDE
    is no longer its lane's newest, the re-run voices no s2f.voiced for it (the
    fold dropped it from ``s2f_pending``): its view shows only the newest GUIDE
    (``guidance_cp``), so a guide another GUIDE on its lane followed before the
    re-run's fast.request is ``superseded``, never credited with the re-run's
    lines. After #230 a re-run that acts voices the lane's newest GUIDE again
    (a second s2f.voiced): both voicings lead to the re-run, counted once.
    ``superseded`` counts both paths: that voiced guide, and (#242, S1-SYS-67:
    a turn voices only the GUIDE its view rendered) a guide never voiced that
    a later GUIDE replaced with no generation requested between the two still
    open (``guides.superseded``, slow.heard's ``Fate.superseded`` rule).
    ``unheard``: guides never voiced or delivered; ``unknown``: those the log
    ends on within the relay window (as in ``relay_gap``), or whose cancelled
    generation has no re-run."""
    gens: dict[str, list[str]] = {}
    for v in x.of("s2f.voiced"):
        gens.setdefault(str(v.payload["msg_id"]), []).append(str(v.payload["gen_id"]))
    gen_of = {
        str(s.payload["utt_id"]): str(s.payload["gen_id"])
        for s in x.of("fast.sentence")
    }
    first: dict[str, int] = {}
    for d in x.of("utt.delivered"):
        gen = gen_of.get(str(d.payload["utt_id"]))
        if gen is not None:
            first.setdefault(gen, d.t_ms)
    reruns, gone = _reruns(x), unvoiced_superseded(x.events)
    asked = {str(r.payload["gen_id"]): r.seq for r in x.of("fast.request")}
    guides = [g for g in x.of("s2f.msg") if g.payload.get("type") == "GUIDE"]
    ms: list[int] = []
    unheard = unknown = cancelled = superseded = 0
    end = x.events[-1].t_ms if x.events else 0
    for g in guides:
        voicing = gens.get(str(g.payload["msg_id"]), [])
        cancelled += any(n in reruns for n in voicing)
        speakers = [(n, _follow(n, reruns)) for n in voicing]
        lane = g.payload.get("lane")
        newer = [
            h.seq for h in guides if h.seq > g.seq and h.payload.get("lane") == lane
        ]
        replaced = [  # a re-run whose view held a newer GUIDE instead
            n
            for n, run in speakers
            if run not in (None, n) and any(s < asked[str(run)] for s in newer)
        ]
        heard = [
            first[run]
            for n, run in speakers
            if run is not None and run in first and n not in replaced
        ]
        if heard:
            ms.append(min(heard) - g.t_ms)
        elif any(run is None for _, run in speakers):
            unknown += 1
        elif replaced or g.payload["msg_id"] in gone:
            superseded += 1
        elif end < g.t_ms + x.relay_window_ms:
            unknown += 1
        else:
            unheard += 1
    ms.sort()
    return {
        "count": len(ms),
        "p50": _rank(ms, 0.5),
        "p90": _rank(ms, 0.9),
        "unheard": unheard,
        "unknown": unknown,
        "cancelled": cancelled,
        "superseded": superseded,
        "ms": ms,
    }


def _reruns(x: Inputs) -> dict[str, str | None]:
    """Each cancelled generation's re-run: the kernel re-queues a cancelled
    generation's trigger first (lanes.py ``_again``), so its re-run is the
    first later fast.request on the same ``lane`` with the same ``trigger``
    kind whose ``basis_seq`` is at or after the fast.cancelled (its board holds
    the cancellation). Causes are not compared: a newer trigger of the same
    kind absorbs the re-queued one. None: the cancelled generation has no
    fast.request, or no request matches."""
    asked = x.of("fast.request")
    by_gen = {str(r.payload["gen_id"]): r for r in asked}
    out: dict[str, str | None] = {}
    for c in x.of("fast.cancelled"):
        gen, run = str(c.payload["gen_id"]), None
        if (own := by_gen.get(gen)) is not None:
            same = [own.payload.get(k) for k in ("lane", "trigger")]
            run = next(
                (
                    str(r.payload["gen_id"])
                    for r in asked
                    if [r.payload.get(k) for k in ("lane", "trigger")] == same
                    and _at_or_after(r.payload.get("basis_seq"), c.seq)
                ),
                None,
            )
        out[gen] = run
    return out


def _at_or_after(basis: object, seq: int) -> bool:
    return isinstance(basis, int) and not isinstance(basis, bool) and basis >= seq


def _follow(gen: str, reruns: dict[str, str | None]) -> str | None:
    """The generation that finally ran for ``gen``; None: a re-run is missing,
    or the chain loops (only a malformed ``basis_seq`` can make one)."""
    seen = {gen}
    while gen in reruns:
        if (nxt := reruns[gen]) is None or nxt in seen:
            return None
        seen.add(gen := nxt)
    return gen


def _rank(xs: Sequence[int], q: float) -> int | None:
    """Nearest-rank percentile; None for no data."""
    return xs[max(math.ceil(q * len(xs)) - 1, 0)] if xs else None
