"""S1-SYS-02 evidence rules: M7 (an accept release carries its capability) and
E1 (a teacher-substituted call keeps its ``fast_*`` role, with the teacher's
model, only under the matching ``teacher_repair_*`` ablation)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from tests.contract.samples import QWEN, SONNET, call_record, session_config

from proxyloop.contract import CONTRACT_VERSION
from proxyloop.contract.bundle import Bundle, Manifest, RoleModel
from proxyloop.contract.config import SessionConfig, config_hash
from proxyloop.contract.events import Event
from proxyloop.contract.llm import AdapterKind, LLMRole, ModelRef
from proxyloop.contract.state import Spend
from proxyloop.evidence.chain import chain_failures
from proxyloop.evidence.check import evidence_check
from proxyloop.evidence.reality import claim_failures, consistency_failures

RUN = "r1"
TEXT = "Yes, we accept these terms."


def _log(*rows: tuple[str, str, Mapping[str, object]]) -> list[Event]:
    """Each event cites the one before it."""
    out: list[Event] = []
    for seq, (type_, actor, payload) in enumerate(rows):
        out.append(
            Event(
                run_id=RUN,
                seq=seq,
                event_id=f"{RUN}:{seq}",
                t_ms=seq,
                wall=datetime(2026, 9, 26, tzinfo=UTC),
                type=type_,
                actor=actor,
                stream="agent",
                cause_ids=(f"{RUN}:{seq - 1}",) if seq else (),
                epoch=0,
                payload=dict(payload),
            )
        )
    return out


def _accept(
    verbatim: Mapping[str, object], released: Mapping[str, object]
) -> list[str]:
    heard: dict[str, object] = {"lane": "cp", "utt_id": "accept-1"}
    heard |= {"text_generated": TEXT}
    heard |= {"text_heard": TEXT, "interrupted": False}
    events = _log(
        ("user.msg", "kernel", {"text": "go"}),
        ("speak.verbatim", "guard", {"lane": "cp", "text": TEXT, **verbatim}),
        ("speak.released", "kernel", {"lane": "cp", **released}),
        ("utt.delivered", "kernel", heard),
    )
    return chain_failures(events, {}, real_only=False)


def test_an_accept_release_must_carry_the_lines_capability() -> None:  # M7
    line = {"kind": "accept", "cap_id": "cap-1"}
    assert _accept(line, {"cap_id": "cap-1"}) == []
    (bare,) = _accept(line, {})
    assert bare.endswith("an accept release must carry its line's cap_id cap-1")
    (other,) = _accept(line, {"cap_id": "cap-2"})
    assert other.endswith("an accept release must carry its line's cap_id cap-1")
    (uncapped,) = _accept({"kind": "accept"}, {})
    assert uncapped.endswith("its speak.verbatim{accept} carries no cap_id")
    (stray,) = _accept({"kind": "disclosure"}, {"cap_id": "cap-1"})
    assert stray.endswith("a cap_id release must cite a speak.verbatim{accept}")


TEACHER = ModelRef(kind=AdapterKind.REAL_HTTP, endpoint="relay", model_id="teacher-5")


def _manifest(cfg: SessionConfig) -> Manifest:
    refs: dict[LLMRole, ModelRef] = {"fast_cp": cfg.fast_cp, "slow": cfg.slow}
    if cfg.teacher is not None:
        refs["teacher"] = cfg.teacher
    return Manifest(
        run_id=RUN,
        git_sha="test",
        contract_version=CONTRACT_VERSION,
        cfg=cfg,
        cfg_hash=config_hash(cfg),
        task_ref="x@1",
        instance_hash="i1",
        split="train",
        fingerprints={},
        models={r: RoleModel(ref=ref) for r, ref in refs.items()},
        p3="pass",
        reality={r: ref.kind for r, ref in refs.items()},
        spend=Spend(),
    )


def _failures(
    cfg: SessionConfig, roles: Sequence[LLMRole], student: bool = True
) -> list[str]:
    m = _manifest(cfg)
    calls = [
        *([call_record(QWEN, call_id="s1")] if student else []),
        call_record(TEACHER, call_id="t1", request_id="req_2"),  # role fast_cp
        call_record(SONNET, call_id="w1", role="slow", request_id="req_3"),
    ]
    return consistency_failures(m, calls) + claim_failures(m, calls, roles, ())


def test_a_teacher_substituted_call_keeps_its_fast_role() -> None:  # E1
    repair = session_config(ablations=["teacher_repair_cp"], teacher=TEACHER)
    assert _failures(repair, ["fast_cp", "slow", "teacher"]) == []


def test_the_teacher_is_accepted_only_on_its_ablations_lane() -> None:  # E1
    other = session_config(ablations=["teacher_repair_user"], teacher=TEACHER)
    failures = _failures(other, ["fast_cp"])
    assert "call t1: model_ref is not the cfg's fast_cp model" in failures
    plain = session_config()
    assert "call t1: model_ref is not the cfg's fast_cp model" in _failures(
        plain, ["fast_cp"]
    )


def test_teacher_calls_alone_never_prove_a_fast_role_ran() -> None:  # E1
    repair = session_config(ablations=["teacher_repair_cp"], teacher=TEACHER)
    failures = _failures(repair, ["fast_cp", "slow"], student=False)
    assert "claimed role fast_cp has no successful real_http call" in failures


def test_the_default_claim_includes_the_teacher_whenever_it_is_set() -> None:
    """``roles=None`` claims every role the manifest ran: under condition R the
    teacher too, so a teacher that never answered fails the claim (E1)."""
    repair = session_config(ablations=["teacher_repair_cp"], teacher=TEACHER)
    m = _manifest(repair)
    assert "teacher" in m.reality
    report = evidence_check(Bundle(m, (), {}), "claim")
    assert "claimed role teacher has no successful real_http call" in report.failures
    assert "claimed role teacher has no successful real_http call" not in (
        evidence_check(Bundle(m, (), {}), "claim", ["fast_cp"]).failures
    )
