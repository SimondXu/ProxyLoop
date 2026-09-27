"""Synthetic event streams built from contract types (data, not fakes).

``Stream`` stamps seq, t_ms and epoch like the bus, validates each event
through ``Event`` and ``check_causes``, and returns a ``Bundle``. It runs no
fold and no model: it only writes the events a metric reads.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from tests.contract.samples import QWEN, SONNET, call_record, session_config

from proxyloop.contract import CONTRACT_VERSION
from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.contract.bundle import (
    EVENTS,
    MANIFEST,
    PROMPTS,
    Bundle,
    Manifest,
    PromptRecord,
    RoleModel,
)
from proxyloop.contract.config import SessionConfig, config_hash
from proxyloop.contract.events import Event, check_causes, event_id
from proxyloop.contract.llm import ModelRef
from proxyloop.contract.protocol import fingerprint
from proxyloop.contract.state import CaseStatus, OfferPublic, PublicFact, Spend
from proxyloop.contract.views import FastView, Trigger
from proxyloop.env.tasks.loader import instance_hash, load_task

RUN = "run-s"
TASK_REF = "cp-direct-discount@1"
INSTANCE = instance_hash(load_task("cp-direct-discount"))  # a piloted train family
WALL = datetime(2026, 9, 26, tzinfo=UTC)
_WORLD = {
    "user.sim": "world.simuser",
    "rep.mouth": "world.mouth",
    "rep.commit_heard": "world.policy",
    "ledger.write": "world.ledger",
}
_OPS = {"session.started", "session.ended", "spend.charged"}
_ACTOR = {
    "speak.verbatim": "guard",
    "approval.requested": "guard",
    "offer.recorded": "guard",
    "approval.post": "sim_approver",
    "action.authorized": "guard",
}


class Stream:
    def __init__(
        self,
        cfg: SessionConfig | None = None,
        split: Literal["train", "dev", "test"] = "train",
        task_ref: str = TASK_REF,
        instance: str = INSTANCE,
    ) -> None:
        self.cfg = cfg or session_config()
        self.task_ref, self.instance = task_ref, instance
        self.split: Literal["train", "dev", "test"] = split
        self.events: list[Event] = []
        self.prompts: dict[str, PromptRecord] = {}
        self.t, self.epoch, self._calls = 0, 0, 0
        self.emit("session.started", {"cfg_hash": config_hash(self.cfg)})

    def emit(
        self,
        type_: str,
        payload: Mapping[str, object] | None = None,
        causes: Sequence[str] = (),
        actor: str | None = None,
        dt: int = 10,
    ) -> str:
        self.t += dt
        seq = len(self.events)
        stream = "world" if type_ in _WORLD else "ops" if type_ in _OPS else "agent"
        body = dict(payload or {})
        if type_ == "session.started":
            body |= {"task_ref": self.task_ref, "instance_hash": self.instance}
            body |= {
                "split": self.split,
                "models": {},
                "renderer_fp": {},
                "attest": None,
            }
            body |= {"contract_version": CONTRACT_VERSION, "git_sha": "t"}
            body |= {"parity": "not_applicable"}
        event = Event(
            run_id=RUN,
            seq=seq,
            event_id=event_id(RUN, seq),
            t_ms=self.t,
            wall=WALL,
            type=type_,
            actor=actor or _WORLD.get(type_) or _ACTOR.get(type_, "kernel"),
            stream=stream,
            cause_ids=tuple(causes),
            epoch=self.epoch,
            payload=body,
        )
        self.events.append(event)
        return event.event_id

    def store(self, kind: str, content: str) -> str:
        sha = sha256_text(content)
        self.prompts[sha] = PromptRecord.model_validate(
            {"sha": sha, "kind": kind, "content": content}
        )
        return sha

    # --- composite steps -------------------------------------------------------
    def fast(
        self,
        lane: str,
        trigger: str | None,
        response_items: Sequence[Mapping[str, object]] = (),
        view: FastView | None = None,
        ref: ModelRef = QWEN,
        first_token_ms: int = 50,
        ttfs_ms: int | None = 80,
        wait_ms: int = 10,
        heard_start: int | None = None,
    ) -> str:
        """One Fast generation answering ``trigger``: request (with its stored
        view), call, turn, sentences, delivered lines. ``heard_start`` sets
        ``t_start_ms`` that many ms before each delivery. Returns its gen_id."""

        self._calls += 1
        gen_id = f"{lane}-g{self._calls}"
        actor = f"fast.{lane}"
        view = view or fast_view(lane)
        shown = self.store("view", canonical_json(view.model_dump(mode="json")))
        req = {"lane": lane, "gen_id": gen_id, "trigger": "t", "view_sha": shown}
        req |= {"prompt_sha": self.store("messages", f"p{self._calls}")}
        req |= {"profile": f"pl_{lane}_v1", "basis_seq": len(self.events) - 1}
        req |= {"model_ref": ref.model_dump(mode="json")}
        causes = [trigger] if trigger else []  # None: a timer trigger
        asked = self.emit("fast.request", req, causes, actor, dt=wait_ms)
        start = self.t
        record = call_record(
            ref,
            call_id=f"c{self._calls}",
            role=f"fast_{lane}",
            t_start=start,
            t_first_token=start + first_token_ms,
            t_end=start + first_token_ms + 100,
        )
        call = self.emit(
            "llm.call", record.model_dump(mode="json"), [asked], actor, dt=150
        )
        turn = {"lane": lane, "gen_id": gen_id, "call_id": record.call_id}
        turn |= {"items": list(response_items), "ttft_ms": 0, "ttfs_ms": ttfs_ms}
        turned = self.emit("fast.turn", turn, [asked, call], actor)
        for n, item in enumerate(i for i in response_items if i["kind"] == "speech"):
            utt = {"lane": lane, "gen_id": gen_id, "utt_id": f"{gen_id}-u{n}"}
            said = self.emit("fast.sentence", utt | {"text": item["text"]}, [turned])
            heard = {"text_generated": item["text"], "text_heard": item["text"]}
            out: dict[str, object] = {"lane": lane, "utt_id": utt["utt_id"]}
            out["interrupted"] = False
            if heard_start is not None:
                out["t_start_ms"] = self.t + 10 - heard_start
            self.emit("utt.delivered", out | heard, [said])
        for item in response_items:
            if item["kind"] == "relay":
                self.f2s(lane, gen_id, turned, item)
        return gen_id

    def f2s(
        self, lane: str, gen_id: str, turn: str, item: Mapping[str, object]
    ) -> None:
        own = "USER_UPDATE" if lane == "user" else "CP_UPDATE"
        kind = item.get("type", "fact")
        type_ = {"note": "NOTE", "revoke": "REVOKE", "request": "REQUEST"}
        msg = {"msg_id": event_id(RUN, len(self.events)), "lane": lane}
        msg |= {"gen_id": gen_id, "utt_ref": None}
        msg |= {"type": type_.get(str(kind), own), "text": item.get("text", "")}
        msg |= {"facts": item.get("facts", [])}
        self.emit("f2s.msg", msg, [turn], f"fast.{lane}")

    def user_says(self, text: str, **revealed: str) -> str:
        """SimUser replies (``user.sim``), then the kernel's ``user.msg``."""

        sim = {"text": text, "revealed": revealed, "delay_s": 1.0}
        sim_ev = self.emit("user.sim", sim, [self.events[0].event_id])
        return self.emit("user.msg", {"text": text}, [sim_ev])

    def rep_says(self, intent: Mapping[str, object], text: str, utt_id: str) -> str:
        mouth = {"intent": dict(intent), "text": text, "fidelity_ok": True}
        said = self.emit(
            "rep.mouth", mouth | {"attempts": 1}, [self.events[0].event_id]
        )
        line = {"lane": "cp", "speaker": "partner", "utt_id": utt_id, "text": text}
        return self.emit("utt.final", line, [said])

    def charge(self, role: str, basis: str, micro: int | None, endpoint: str) -> None:
        charge = {"call_id": "x", "role": role, "attempt": 0, "endpoint": endpoint}
        charge |= {"model_id": "m", "basis": basis, "micro_usd": micro}
        self.emit("spend.charged", charge, [self.events[-1].event_id])

    def end(self, reason: str = "info_only") -> Bundle:
        self.emit("session.ended", {"reason": reason})
        check_causes(self.events)
        return Bundle(self.manifest(), tuple(self.events), dict(self.prompts))

    def manifest(self) -> Manifest:
        return Manifest(
            run_id=RUN,
            git_sha="t",
            contract_version=CONTRACT_VERSION,
            cfg=self.cfg,
            cfg_hash=config_hash(self.cfg),
            task_ref=self.task_ref,
            instance_hash=self.instance,
            split=self.split,
            fingerprints={"pl_cp_v1": fingerprint("pl_cp_v1")},
            models={"fast_cp": RoleModel(ref=QWEN), "slow": RoleModel(ref=SONNET)},
            p3="not_applicable",
            reality={"fast_cp": QWEN.kind, "slow": SONNET.kind},
            spend=Spend(),
        )

    def write(self, run_dir: Path, reason: str = "info_only") -> Path:
        bundle = self.end(reason)
        run_dir.mkdir(parents=True)
        (run_dir / MANIFEST).write_text(bundle.manifest.model_dump_json(), "utf-8")
        lines = [e.model_dump_json() for e in bundle.events]
        (run_dir / EVENTS).write_text("\n".join(lines) + "\n", "utf-8")
        prompts = [p.model_dump_json() for p in bundle.prompts.values()]
        (run_dir / PROMPTS).write_text("".join(f"{p}\n" for p in prompts), "utf-8")
        return run_dir


def speech(text: str) -> dict[str, object]:
    return {"kind": "speech", "text": text}


def fact(*pairs: tuple[str, str]) -> dict[str, object]:
    return {"kind": "relay", "type": "fact", "facts": [list(p) for p in pairs]}


def note(text: str) -> dict[str, object]:
    return {"kind": "relay", "type": "note", "text": text}


def issue(reason: str = "unknown_directive") -> dict[str, object]:
    return {"kind": "issue", "reason": reason, "text": "@x"}


def offer_slot(
    field: str, value: str, unit: str, role: str, utt: str
) -> dict[str, str]:
    return {
        "field": field,
        "value": value,
        "unit": unit,
        "role": role,
        "source_utt": utt,
    }


def fast_view(
    lane: str,
    partner: Sequence[str] = (),
    agent: Sequence[str] = (),
    offers: Sequence[OfferPublic] = (),
    facts: Sequence[PublicFact] = (),
    summary: str = "",
    brief: str = "",
) -> FastView:
    """A stored FastView: partner lines, then the agent's own lines."""
    lines = [
        {"utt_id": f"p{n}", "speaker": "partner", "text": t}
        for n, t in enumerate(partner)
    ]
    lines += [
        {"utt_id": f"a{n}", "speaker": "agent", "text": t} for n, t in enumerate(agent)
    ]
    trigger = Trigger(kind="user_msg" if lane == "user" else "rep_spoke")
    return FastView.model_validate(
        {
            "lane": lane,
            "brief": brief,
            "public_summary": summary,
            "action_log": (),
            "offers": offers,
            "public_facts": facts,
            "status": CaseStatus.IN_CALL,
            "transcript": lines,
            "trigger": trigger,
        }
    )
