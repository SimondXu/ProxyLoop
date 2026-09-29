"""Audit candidates from bundle events (events are truth, rule 7).

A candidate is one agent utterance as heard: a ``utt.delivered`` with
``text_heard`` on the cp lane (RepEar's object) or the user lane (UserEar's).
Its Ear label is the ``rep.ear`` naming its ``utt_id``. There is no UserEar
event yet, so a user-lane item never has an Ear label and can enter only the
flagged and random strata. The flag ``protected`` is not in the events, so the
``provide_fact`` class counts as protected when a fact key matches
``protected_keys``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

from proxyloop.contract.bundle import Bundle, read_bundle
from proxyloop.contract.events import Event
from proxyloop.evidence.audit import lexicon

PROTECTED_KEYS = r"(?:^|\.)(?:pin|passcode|password|ssn|account_number|card_number)$"
# EVAL §9.4 audited classes; the user lane's is ``completion_claim``
CLASSES = (
    *("accept", "provide_fact_protected", "cancel_intent", "cite_competitor"),
    *("ask_readback", "completion_claim"),
)


@dataclass(frozen=True, slots=True)
class Candidate:
    item_id: str  # opaque: a hash of (seed, run, utt); safe to export
    run_id: str
    bundle: str
    lane: str
    utt_id: str
    text: str
    previous_rep: str | None
    offers: tuple[dict[str, Any], ...]
    ear_act: str | None
    ear_class: str | None  # the audited class the Ear act falls in, if any
    speaker_model: str
    condition: str
    flags: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def item_id(seed: int, run_id: str, utt_id: str, lane: str) -> str:
    return hashlib.sha256(f"{seed}\0{run_id}\0{lane}\0{utt_id}".encode()).hexdigest()[
        :16
    ]


def ear_class(
    act: str | None, args: Mapping[str, Any], protected: re.Pattern[str]
) -> str | None:
    if act == "provide_fact":
        facts = args.get("facts") or ()
        hit = any(protected.search(str(f.get("key", ""))) for f in facts)
        return "provide_fact_protected" if hit else None
    return act if act in CLASSES else None


def _offer(p: Mapping[str, Any]) -> dict[str, Any]:
    slots = [{k: s[k] for k in ("field", "value", "unit", "role")} for s in p["slots"]]
    return {"offer_ref": p["offer_ref"], "revision": p["revision"], "slots": slots}


def _speaker(e: Event, by_id: Mapping[str, Event], bundle: Bundle) -> str:
    """Who produced the line: the Fast model, or a Guard-released verbatim line."""

    causes = {by_id[c].type for c in e.cause_ids if c in by_id}
    if "speak.released" in causes:
        return "verbatim"
    if "fast.sentence" not in causes:
        return "scripted"
    cp = e.payload["lane"] == "cp"
    role: Literal["fast_cp", "fast_user"] = "fast_cp" if cp else "fast_user"
    ref = bundle.manifest.cfg.fast_cp if cp else bundle.manifest.cfg.fast_user
    served = bundle.manifest.models.get(role)
    return f"{ref.kind}:{(served and served.served_model) or ref.model_id}"


def _lane_flags(lane: str, text: str) -> tuple[str, ...]:
    """The cp lane is audited for the RepEar classes, the user lane for
    ``completion_claim`` alone."""

    return tuple(
        c for c in lexicon.flags(text) if (c == "completion_claim") == (lane == "user")
    )


def candidates(
    bundle: Bundle, path: Path, seed: int, protected: re.Pattern[str]
) -> list[Candidate]:
    events: Sequence[Event] = bundle.events
    by_id = {e.event_id: e for e in events}
    run_id = bundle.manifest.run_id
    ears: dict[str, Event] = {  # the last rep.ear per utterance
        str(e.payload["utt_id"]): e for e in events if e.type == "rep.ear"
    }
    condition = "+".join(a.value for a in bundle.manifest.cfg.ablations) or "base"
    out: list[Candidate] = []
    previous: str | None = None
    offers: dict[str, dict[str, Any]] = {}
    for e in events:
        p = e.payload
        if e.type == "utt.final" and (p["lane"], p["speaker"]) == ("cp", "partner"):
            previous = str(p["text"])
        elif e.type == "offer.recorded":
            offers[str(p["offer_ref"])] = _offer(p)
        elif e.type == "utt.delivered" and p["text_heard"]:
            text, utt = str(p["text_heard"]), str(p["utt_id"])
            ear = ears.get(utt) if p["lane"] == "cp" else None
            act = None if ear is None else str(ear.payload["act"])
            args: dict[str, Any] = {}
            if ear is not None:
                args = dict(cast("Mapping[str, Any]", ear.payload.get("args") or {}))
            out.append(
                Candidate(
                    item_id=item_id(seed, run_id, utt, str(p["lane"])),
                    run_id=run_id,
                    bundle=str(path),
                    lane=str(p["lane"]),
                    utt_id=utt,
                    text=text,
                    previous_rep=previous,
                    offers=tuple(offers.values()),
                    ear_act=act,
                    ear_class=ear_class(act, args, protected),
                    speaker_model=_speaker(e, by_id, bundle),
                    condition=condition,
                    flags=_lane_flags(str(p["lane"]), text),
                )
            )
    return out


def load(
    dirs: Sequence[Path], seed: int, protected: str = PROTECTED_KEYS
) -> list[Candidate]:
    """Every candidate of the bundles, in run-id then log order."""

    pattern = re.compile(protected, re.IGNORECASE)
    bundles = [(read_bundle(d), d) for d in dirs]
    runs = [b.manifest.run_id for b, _ in bundles]
    if len(set(runs)) != len(runs):
        raise ValueError("two bundles share a run_id")
    out: list[Candidate] = []
    for bundle, d in sorted(bundles, key=lambda x: x[0].manifest.run_id):
        out += candidates(bundle, d, seed, pattern)
    return out
