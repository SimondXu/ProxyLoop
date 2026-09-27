"""Fixture bundles for the run index and the spend report, built with the real
contract models so the tests break when the contract changes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.contract.samples import GEMINI, QWEN, SONNET, session_config

from proxyloop.contract import CONTRACT_VERSION
from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS, Manifest, RoleModel
from proxyloop.contract.config import SessionConfig, config_hash
from proxyloop.contract.events import Event, event_id
from proxyloop.contract.llm import AdapterKind, LLMCallRecord, LLMRole, ModelRef, Usage
from proxyloop.contract.state import Spend
from proxyloop.llm.spend import Charge

WALL = datetime(2026, 9, 27, 1, 0, tzinfo=UTC)
_AGENT = {"fast_user": "fast.user", "fast_cp": "fast.cp", "slow": "slow"}
LIVE_REFS: dict[LLMRole, ModelRef] = {
    "fast_user": QWEN,
    "fast_cp": QWEN,
    "slow": SONNET,
    "ear": GEMINI,
    "mouth": GEMINI,
    "simuser": GEMINI,
}


class Log:
    """One run's events, appended in order with valid causes."""

    def __init__(self, run_id: str, split: str = "train") -> None:
        self.run_id, self.events = run_id, list[Event]()
        self.start = self.add(
            "session.started",
            "kernel",
            "ops",
            {
                "cfg_hash": "c",
                "task_ref": "cp-direct-discount@1",
                "instance_hash": "i",
                "split": split,
                "models": {},
                "renderer_fp": {},
                "contract_version": CONTRACT_VERSION,
                "git_sha": "g",
                "attest": None,
                "parity": None,
            },
        )

    def add(
        self,
        type_: str,
        actor: str,
        stream: str,
        payload: dict[str, object],
        causes: tuple[str, ...] = (),
    ) -> str:
        seq = len(self.events)
        self.events.append(
            Event.model_validate(
                {
                    "run_id": self.run_id,
                    "seq": seq,
                    "event_id": event_id(self.run_id, seq),
                    "t_ms": seq * 100,
                    "wall": WALL + timedelta(milliseconds=seq * 100),
                    "type": type_,
                    "actor": actor,
                    "stream": stream,
                    "cause_ids": causes,
                    "epoch": 0,
                    "payload": payload,
                }
            )
        )
        return event_id(self.run_id, seq)

    def call(
        self,
        role: LLMRole,
        ref: ModelRef,
        usage: Usage | None,
        basis: str | None,  # None: an llm.call with no spend.charged
        micro_usd: int | None = None,
    ) -> None:
        call_id = f"{role}:{self.run_id}:{len(self.events)}"
        record = LLMCallRecord(
            call_id=call_id,
            role=role,
            model_ref=ref,
            adapter_kind=ref.kind,
            requested_model=ref.model_id,
            served_model_echo=ref.model_id,
            request_id=None,
            prompt_sha="p",
            response_sha="r",
            usage=usage,
            t_start=0,
            t_first_token=1,
            t_end=2,
            finish_reason="stop",
            attempt=0,
        )
        world = role not in _AGENT
        actor, stream = (f"world.{role}", "world") if world else (_AGENT[role], "agent")
        payload = record.model_dump(mode="json")
        cause = self.add("llm.call", actor, stream, payload, (self.start,))
        if basis is not None:
            self.charge(call_id, role, ref, basis, micro_usd, cause)

    def charge(
        self,
        call_id: str,
        role: LLMRole,
        ref: ModelRef,
        basis: str,
        micro_usd: int | None,
        cause: str | None = None,
    ) -> None:
        payload = Charge.model_validate(
            {
                "call_id": call_id,
                "role": role,
                "attempt": 0,
                "endpoint": ref.endpoint,
                "model_id": ref.model_id,
                "basis": basis,
                "micro_usd": micro_usd,
            }
        ).model_dump(mode="json")
        self.add("spend.charged", "kernel", "ops", payload, (cause or self.start,))

    def end(self, reason: str) -> None:
        self.add("session.ended", "kernel", "ops", {"reason": reason})


def manifest(
    run_id: str,
    refs: dict[LLMRole, ModelRef] = LIVE_REFS,
    split: str = "train",
) -> Manifest:
    world = {r: refs[r].model_dump() for r in ("ear", "mouth", "simuser")}
    cfg = session_config(
        fast_user=refs["fast_user"].model_dump(),
        fast_cp=refs["fast_cp"].model_dump(),
        slow=refs["slow"].model_dump(),
        world=world,
        live=all(ref.kind is AdapterKind.REAL_HTTP for ref in refs.values()),
    )
    return Manifest.model_validate(
        {
            "run_id": run_id,
            "git_sha": "g",
            "contract_version": CONTRACT_VERSION,
            "cfg": cfg,
            "cfg_hash": config_hash(SessionConfig.model_validate(cfg)),
            "task_ref": "cp-direct-discount@1",
            "instance_hash": "i",
            "split": split,
            "fingerprints": {},
            "models": {r: RoleModel(ref=ref) for r, ref in refs.items()},
            "p3": "not_applicable",
            "reality": {r: ref.kind for r, ref in refs.items()},
            "spend": Spend(),
        }
    )


def write(path: Path, log: Log | None, man: Manifest | None) -> Path:
    path.mkdir(parents=True)
    if man is not None:
        (path / MANIFEST).write_text(man.model_dump_json(), "utf-8")
    if log is not None:
        lines = [e.model_dump_json() for e in log.events]
        (path / EVENTS).write_text("\n".join(lines) + "\n", "utf-8")
    (path / PROMPTS).write_text("", "utf-8")
    return path
