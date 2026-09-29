"""Small synthetic bundles for the Ear-audit tests: built from a script of
lines, valid to ``read_bundle``, never a claim."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from tests.contract.samples import GEMINI, QWEN, SONNET

from proxyloop.contract import CONTRACT_VERSION
from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS, Manifest, RoleModel
from proxyloop.contract.config import (
    Sampling,
    SessionConfig,
    WorldModels,
    config_hash,
)
from proxyloop.contract.state import Spend


@dataclass(frozen=True)
class Line:
    lane: str  # "cp" or "user"
    text: str
    act: str | None = None  # the rep.ear act (cp lane only)
    facts: tuple[tuple[str, str], ...] = ()
    verbatim: bool = False  # a Guard-released line, not a Fast sentence
    rep: str = "Which plan is it?"  # the rep line just before (cp lane)


@dataclass
class Script:
    lines: list[Line] = field(default_factory=list[Line])
    offer: bool = False


def write_bundle(
    run_dir: Path, run_id: str, script: Script, model: str = "Qwen3.5-9B"
) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    ref = QWEN.model_copy(update={"model_id": model})
    cfg = SessionConfig(
        fast_user=ref,
        fast_cp=ref,
        slow=SONNET,
        world=WorldModels(ear=GEMINI, mouth=GEMINI, simuser=GEMINI),
        fast_sampling=Sampling(temperature=0.3, top_p=0.9, max_tokens=160),
        seed=7,
        live=True,
    )
    events: list[dict[str, object]] = []

    def emit(
        type_: str, actor: str, stream: str, payload: dict[str, object], *cause: int
    ) -> int:
        seq = len(events)
        events.append(
            {
                "run_id": run_id,
                "seq": seq,
                "event_id": f"{run_id}:{seq}",
                "t_ms": seq,
                "wall": "2026-09-30T00:00:00Z",
                "type": type_,
                "actor": actor,
                "stream": stream,
                "cause_ids": [f"{run_id}:{c}" for c in cause],
                "epoch": 0,
                "payload": payload,
            }
        )
        return seq

    start = emit(
        "session.started",
        "kernel",
        "ops",
        {
            "cfg_hash": config_hash(cfg),
            "task_ref": "t@1",
            "instance_hash": "i",
            "split": "train",
            "models": {},
            "renderer_fp": {},
            "attest": None,
            "contract_version": CONTRACT_VERSION,
            "git_sha": "x",
            "parity": "not_applicable",
        },
    )
    if script.offer:
        emit(
            "offer.recorded",
            "guard",
            "agent",
            {
                "offer_ref": "o1",
                "revision": 1,
                "terms_hash": "h",
                "slots": [
                    {
                        "field": "monthly",
                        "value": "5000",
                        "unit": "usd_minor",
                        "role": "recurring",
                        "source_utt": f"{run_id}-secret",
                        "span": [0, 3],
                        "status": "heard",
                    }
                ],
            },
            start,
        )
    for n, ln in enumerate(script.lines):
        utt = f"{ln.lane}-{n}"
        if ln.lane == "cp":
            emit(
                "utt.final",
                "kernel",
                "agent",
                {
                    "lane": "cp",
                    "speaker": "partner",
                    "utt_id": f"rep-{n}",
                    "text": ln.rep,
                },
                start,
            )
        if ln.verbatim:
            src = emit("speak.released", "kernel", "agent", {"lane": ln.lane}, start)
        else:
            src = emit(
                "fast.sentence",
                f"fast.{ln.lane}",
                "agent",
                {"lane": ln.lane, "gen_id": f"g{n}", "utt_id": utt, "text": ln.text},
                start,
            )
        heard = emit(
            "utt.delivered",
            "kernel",
            "agent",
            {
                "lane": ln.lane,
                "utt_id": utt,
                "text_generated": ln.text,
                "text_heard": ln.text,
                "interrupted": False,
            },
            src,
        )
        if ln.act is not None:
            args: dict[str, object] = {}
            if ln.facts:
                args["facts"] = [{"key": k, "value": v} for k, v in ln.facts]
            emit(
                "rep.ear",
                "world.ear",
                "world",
                {"utt_id": utt, "act": ln.act, "args": args, "call_id": f"c{n}"},
                heard,
            )
    emit("session.ended", "kernel", "ops", {"reason": "info_only"})
    (run_dir / EVENTS).write_text(
        "".join(json.dumps(e) + "\n" for e in events), "utf-8"
    )
    (run_dir / PROMPTS).write_text("", "utf-8")
    manifest = Manifest(
        run_id=run_id,
        git_sha="x",
        contract_version=CONTRACT_VERSION,
        cfg=cfg,
        cfg_hash=config_hash(cfg),
        task_ref="t@1",
        instance_hash="i",
        split="train",
        fingerprints={},
        models={"fast_cp": RoleModel(ref=ref)},
        p3="not_applicable",
        reality={"fast_cp": ref.kind},
        spend=Spend(),
    )
    (run_dir / MANIFEST).write_text(manifest.model_dump_json(), "utf-8")
    return run_dir
