"""Recorded replays (``AdapterKind.recorded_replay``) and a minimal Fast chain.

``replay_client(bundle_dir, role)`` serves a bundle's recorded responses for
one role, in call order: how implementers use ``evidence/`` bundles offline.

``write_fast_bundle`` builds the smallest bundle with a complete §4.3 chain
around one Fast response: the rep speaks, the cp view is rendered by the
contract renderer, the client streams the response through the contract's
``StreamParser``, and each spoken sentence is delivered. It goes through the
real ``Bus``/``EventLog``. There is no kernel yet (S0-SYS-06); this is test
scaffolding, not a runner.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from tests.contract.samples import session_config
from tests.support.fakes import ScriptedLLM
from tests.support.manual_clock import ManualClock

from proxyloop.contract import CONTRACT_VERSION
from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.contract.bundle import (
    EVENTS,
    MANIFEST,
    PROMPTS,
    Manifest,
    PromptRecord,
    RoleModel,
    read_bundle,
)
from proxyloop.contract.config import config_hash
from proxyloop.contract.llm import (
    AdapterKind,
    LLMCallRecord,
    LLMClient,
    LLMRole,
    ModelRef,
    TextRequest,
    request_content,
)
from proxyloop.contract.protocol import (
    Speech,
    StreamParser,
    TurnItem,
    fingerprint,
    render_messages,
)
from proxyloop.contract.state import Spend
from proxyloop.contract.views import Trigger, view_cp
from proxyloop.core.bus import Bus
from proxyloop.core.log import EventLog

RUN_ID = "run-test"
REP_LINE = "I can offer you 20 dollars off per month for 12 months."
RECORDED = ModelRef(
    kind=AdapterKind.RECORDED_REPLAY, endpoint="vllm", model_id="Qwen3.5-9B"
)


def recorded_responses(bundle_dir: Path, role: str) -> list[str]:
    bundle = read_bundle(bundle_dir)
    out: list[str] = []
    for e in bundle.events:
        if e.type == "llm.call" and e.payload["role"] == role:
            sha = LLMCallRecord.model_validate(e.payload).response_sha
            if sha is not None:
                out.append(bundle.prompts[sha].content)
    return out


def replay_client(bundle_dir: Path, role: str) -> ScriptedLLM:
    models = read_bundle(bundle_dir).manifest.models
    ref = next(model.ref for name, model in models.items() if name == role)
    replayed = ModelRef(
        kind=AdapterKind.RECORDED_REPLAY, endpoint=ref.endpoint, model_id=ref.model_id
    )
    return ScriptedLLM(replayed, recorded_responses(bundle_dir, role))


async def _run_chain(bus: Bus, client: LLMClient, prompts: list[PromptRecord]) -> None:
    def store(kind: str, content: str) -> str:
        sha = sha256_text(content)
        prompts.append(
            PromptRecord.model_validate({"sha": sha, "kind": kind, "content": content})
        )
        return sha

    rep = bus.emit(
        "utt.final",
        "kernel",
        "agent",
        {"lane": "cp", "speaker": "partner", "utt_id": "rep-1", "text": REP_LINE},
    )
    view = view_cp(bus.bb, Trigger(kind="rep_spoke"), "Ask for a discount.")
    request = TextRequest(
        call_id="call-1",
        role="fast_cp",
        messages=render_messages(view, "pl_cp_v1"),
        max_tokens=160,
        temperature=0.0,
    )
    prompt_sha = store("messages", request_content(request))
    fast = {"lane": "cp", "gen_id": "gen-1"}
    asked = bus.emit(
        "fast.request",
        "fast.cp",
        "agent",
        fast
        | {
            "trigger": "rep_spoke",
            "view_sha": store("view", canonical_json(view.model_dump(mode="json"))),
            "prompt_sha": prompt_sha,
            "profile": "pl_cp_v1",
            "model_ref": client.ref.model_dump(mode="json"),
            "basis_seq": rep.seq,
        },
        [rep.event_id],
    )
    parser, items, text = StreamParser("cp"), [], ""
    items: list[TurnItem]
    record: LLMCallRecord | None = None
    async for delta in client.stream_text(request):
        if isinstance(delta, LLMCallRecord):
            record = delta
        else:
            text += delta
            items += parser.feed(delta)
    items += parser.close()
    assert record is not None
    store("response", text)
    call = bus.emit(
        "llm.call", "fast.cp", "agent", record.model_dump(mode="json"), [asked.event_id]
    )
    turn = bus.emit(
        "fast.turn",
        "fast.cp",
        "agent",
        fast
        | {
            "call_id": record.call_id,
            "items": [i.model_dump(mode="json") for i in items],
            "ttft_ms": 0,
            "ttfs_ms": 0,
        },
        [asked.event_id, call.event_id],
    )
    spoken = [i.text for i in items if isinstance(i, Speech)]
    for n, sentence in enumerate(spoken):
        utt = {"lane": "cp", "utt_id": f"agent-{n}"}
        said = bus.emit(
            "fast.sentence",
            "fast.cp",
            "agent",
            fast | utt | {"text": sentence},
            [turn.event_id],
        )
        heard = {
            "text_generated": sentence,
            "text_heard": sentence,
            "interrupted": False,
        }
        bus.emit("utt.delivered", "kernel", "agent", utt | heard, [said.event_id])
    bus.emit("session.ended", "kernel", "ops", {"reason": "done"})


def write_fast_bundle(
    run_dir: Path, response: str, ref: ModelRef = RECORDED, live: bool = False
) -> Path:
    """One Fast cp turn answering the rep with ``response``, as a bundle."""

    run_dir.mkdir(parents=True, exist_ok=True)
    cfg = session_config(fast_cp=ref.model_dump(), live=live)
    models: dict[LLMRole, RoleModel] = {"fast_cp": RoleModel(ref=ref)}
    log = EventLog(run_dir / EVENTS, RUN_ID)
    clock = ManualClock()
    bus = Bus(log, clock)
    started = {
        "cfg_hash": config_hash(cfg),
        "task_ref": "cp-direct-discount@1",
        "instance_hash": "i1",
        "split": "train",
        "models": {r: m.model_dump(mode="json") for r, m in models.items()},
        "renderer_fp": {"pl_cp_v1": fingerprint("pl_cp_v1")},
        "contract_version": CONTRACT_VERSION,
        "git_sha": "test",
        "attest": None,
        "parity": "not_applicable",
    }
    bus.emit("session.started", "kernel", "ops", started)
    prompts: list[PromptRecord] = []
    asyncio.run(_run_chain(bus, ScriptedLLM(ref, [response], clock), prompts))
    log.close()
    lines = {p.sha: p.model_dump_json() for p in prompts}
    (run_dir / PROMPTS).write_text("".join(f"{v}\n" for v in lines.values()), "utf-8")
    manifest = Manifest(
        run_id=RUN_ID,
        git_sha="test",
        contract_version=CONTRACT_VERSION,
        cfg=cfg,
        cfg_hash=config_hash(cfg),
        task_ref="cp-direct-discount@1",
        instance_hash="i1",
        split="train",
        fingerprints={"pl_cp_v1": fingerprint("pl_cp_v1")},
        models=models,
        p3="not_applicable",
        reality={"fast_cp": ref.kind},
        spend=Spend(),
    )
    (run_dir / MANIFEST).write_text(manifest.model_dump_json(), "utf-8")
    return run_dir
