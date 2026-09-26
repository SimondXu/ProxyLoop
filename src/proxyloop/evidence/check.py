"""``evidence_check(bundle, mode)`` (ARCHITECTURE §14).

``offline``, whatever adapters ran: the log (one run, dense ``seq``, monotone
``t_ms``, causes, a replayed fold, envelope epochs, one closing
``session.ended``), every sha against ``prompts.jsonl``, the chain of every
delivered line, and manifest/cfg/call agreement. ``claim`` adds, per claimed
role (default: all): ``real_http`` only, a successful call, request ids,
usage, echoed model; attestation, fingerprints, contract version, P3, and an
ending in ``ENDED_OK``. Neither mode touches the network.

Passing ``claim`` proves internal consistency and chain completeness, not
authenticity: a bundle can be forged consistently. Authenticity comes from
root-run provenance, a bundle produced by ``run_session`` under the root
with live keys.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Literal

from proxyloop.contract.base import sha256_text
from proxyloop.contract.bundle import Bundle, Manifest, PromptRecord, read_bundle
from proxyloop.contract.events import Event, check_causes
from proxyloop.contract.llm import LLMCallRecord, LLMRole
from proxyloop.contract.state import Blackboard
from proxyloop.core.fold import apply
from proxyloop.evidence.chain import chain_failures
from proxyloop.evidence.reality import (
    claim_failures,
    consistency_failures,
    reality_report,
)

Mode = Literal["offline", "claim"]
# Slow's finish() outcomes (§8) and the cp hang-up (§9.5 ABANDONED). Anything
# else (llm_unavailable, a budget or timeout stop, an error) is not claimable.
ENDED_OK = frozenset({"completed", "no_deal", "info_only", "escalate", "abandoned"})


@dataclass(frozen=True, slots=True)
class Report:
    mode: Mode
    failures: tuple[str, ...]
    reality: Mapping[str, str]  # role -> vllm | hosted | baseline_fsm | ...

    @property
    def ok(self) -> bool:
        return not self.failures


def _log_failures(m: Manifest, events: Sequence[Event]) -> list[str]:
    out: list[str] = []
    if not events or events[0].type != "session.started":
        out.append("the log does not open with session.started")
    else:
        started = events[0].payload
        for key in ("cfg_hash", "split", "contract_version"):
            if started[key] != getattr(m, key):
                out.append(f"session.started {key} is not the manifest's")
    ends = [i for i, e in enumerate(events) if e.type == "session.ended"]
    if ends != [len(events) - 1]:
        out.append("the log does not end with its one session.ended")
    if runs := {e.run_id for e in events} - {m.run_id}:
        out.append(f"events of runs {sorted(runs)} in bundle {m.run_id}")
    if gaps := [(i, e.seq) for i, e in enumerate(events) if e.seq != i]:
        out.append(f"seq is not dense: position {gaps[0][0]} holds seq {gaps[0][1]}")
    if any(b.t_ms < a.t_ms for a, b in pairwise(events)):
        out.append("t_ms is not monotone")
    try:
        check_causes(events)
    except ValueError as err:
        out.append(f"causes: {err}")
    return out + _fold_failures(events)


def _fold_failures(events: Sequence[Event]) -> list[str]:
    """Replay the fold: it must accept every event, and each envelope epoch
    must be the folded epoch just before that event."""
    bb = Blackboard()
    for e in events:
        if e.epoch != bb.epoch:
            return [f"{e.event_id}: epoch {e.epoch}, but the fold is at {bb.epoch}"]
        try:
            bb = apply(bb, e)
        except ValueError as err:
            return [f"fold rejects {e.event_id}: {err}"]
    return []


def _sha_failures(
    events: Sequence[Event], prompts: Mapping[str, PromptRecord]
) -> list[str]:
    out = [
        f"prompts.jsonl {r.kind} {sha[:12]} does not hash to its sha"
        for sha, r in prompts.items()
        if sha256_text(r.content) != sha
    ]

    def need(e: Event, sha: object, kinds: tuple[str, ...]) -> None:
        record = prompts.get(str(sha))
        if record is None or record.kind not in kinds:
            out.append(f"{e.type} {e.event_id}: no {'/'.join(kinds)} {str(sha)[:12]}")

    for e in events:
        if e.type == "llm.call":
            call = LLMCallRecord.model_validate(e.payload)
            need(e, call.prompt_sha, ("prompt", "messages"))
            if call.response_sha is not None:
                need(e, call.response_sha, ("response",))
        elif e.type == "fast.request":
            need(e, e.payload["view_sha"], ("view",))
            need(e, e.payload["prompt_sha"], ("prompt", "messages"))
    return out


def evidence_check(
    bundle: Bundle, mode: Mode = "offline", roles: Collection[LLMRole] | None = None
) -> Report:
    m, events = bundle.manifest, bundle.events
    calls = [
        LLMCallRecord.model_validate(e.payload) for e in events if e.type == "llm.call"
    ]
    failures = _log_failures(m, events) + _sha_failures(events, bundle.prompts)
    failures += consistency_failures(m, calls)
    failures += chain_failures(events, bundle.prompts, real_only=mode == "claim")
    if mode == "claim":
        claimed = set(m.reality) if roles is None else set(roles)
        profiles = {
            str(e.payload["profile"]) for e in events if e.type == "fast.request"
        }
        failures += claim_failures(m, calls, claimed, profiles)
        last = events[-1] if events else None
        reason = (
            last.payload["reason"] if last and last.type == "session.ended" else None
        )
        if reason not in ENDED_OK:
            failures.append(
                f"session ended with {reason!r}, not one of {sorted(ENDED_OK)}"
            )
    return Report(mode, tuple(failures), reality_report(m))


def check_path(
    path: Path, mode: Mode = "offline", roles: Collection[LLMRole] | None = None
) -> Report:
    """Read and check ``runs/<run_id>/``; an unreadable bundle fails the check."""
    try:
        bundle = read_bundle(path)
    except (OSError, ValueError) as err:
        return Report(mode, (f"unreadable bundle: {err}",), {})
    return evidence_check(bundle, mode, roles)
