"""The kernel's wiring of the simulated principal (N6) and of condition R's
teacher (E1), on virtual time."""

from __future__ import annotations

from pathlib import Path

from tests.concurrency.harness import Sim, settle
from tests.concurrency.test_cases import arun
from tests.support.sessions import fake, fake_config, reply

from proxyloop.contract.config import SessionConfig
from proxyloop.contract.llm import LLMCallRecord
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.tasks.schema import Task
from proxyloop.evidence.check import check_path

STOP = "Stop, do not accept anything. I will keep my current plan for now."
SILENT = "@slow: note the user wants a lower price"  # FastU says nothing


def _mind_change() -> Task:
    """The family with its delays pinned: the user's replies take 20 s, the
    approver its 3 s floor (above a triggered stop's 0.5-2.5 s)."""
    data = load_task("x-user-mind-change").model_dump(mode="json")
    data["user"]["reply_delay_s"]["range"] = [20, 20]
    data["principal"]["approver_delay_s"]["range"] = [3, 3]
    return Task.model_validate(data)


def test_n6_the_stop_is_delivered_before_the_cards_grant(tmp_path: Path) -> None:
    async def case() -> None:
        scripts = {
            "simuser": [
                reply("Please get my cable bill down."),
                reply("Thanks, keep me posted."),  # due 20 s after "Okay."
                reply(STOP),
            ],
            "fast_user": ["Okay.", SILENT],  # silent from the card on
        }
        sim = Sim(tmp_path, scripts, _mind_change(), "sim")
        await sim.start()
        await sim.offer(dollars=76)  # above the stated 70, within the card limit
        sim.card()  # the stop queues behind the user's pending reply
        await sim.vt.run_for(30_000)
        (asked,) = sim.of("approval.requested")
        (stop,) = [e for e in sim.of("user.sim") if e.payload.get("stop") == "stop"]
        assert stop.cause_ids[0] == asked.event_id  # after_card, unprompted
        (said,) = [e for e in sim.of("user.msg") if stop.event_id in e.cause_ids]
        heard = [e.t_ms for e in sim.of("utt.delivered", lane="user")]
        assert heard and max(heard) < asked.t_ms  # the agent silent after the card
        (post,) = sim.of("approval.post")
        (decided,) = sim.of("approval.decided")
        assert post.actor == "sim_approver" and decided.payload["by"] == "sim_approver"
        assert post.payload["decision"] == "granted"  # decided before the stop
        assert said.t_ms - asked.t_ms > 3_000  # the stop landed after the 3 s delay
        assert said.seq < post.seq  # N6: yet the grant waited for it
        (fence,) = sim.of("authority.fence", op="raised", utt_id=said.event_id)
        assert fence.seq == said.seq + 1  # raised at once
        await sim.stop()
        assert check_path(sim.k.path, "offline").ok

    arun(case())


def _repair() -> SessionConfig:
    cfg = fake_config().model_dump()
    cfg |= {"ablations": ["teacher_repair_cp"], "teacher": fake("teacher")}
    return SessionConfig.model_validate(cfg)


def test_r_a_decision_point_goes_to_the_teacher_as_a_fast_call(
    tmp_path: Path,
) -> None:
    async def case() -> None:
        scripts = {"fast_cp": ["Okay."], "teacher": ["Could you read that back?"]}
        sim = Sim(tmp_path, scripts, cfg=_repair())
        await sim.start()
        sim.rep_says("How are you today?")  # no decision point: the student
        await sim.vt.run_for(3_000)
        sim.rep_says("I can offer you $60 a month for 12 months. Deal?")
        await sim.vt.run_for(5_000)
        await settle()
        student, teacher = sim.of("fast.turn", lane="cp")
        calls = {str(e.payload["call_id"]): e for e in sim.of("llm.call")}
        of = {
            t.event_id: LLMCallRecord.model_validate(
                calls[str(t.payload["call_id"])].payload
            )
            for t in (student, teacher)
        }
        assert of[student.event_id].model_ref.model_id == "fast_cp-fake"
        taught = of[teacher.event_id]
        assert (taught.role, taught.model_ref.model_id) == ("fast_cp", "teacher-fake")
        # E1: its fast_* role, the teacher's model
        assert teacher.payload["resamples"] == 0 and "resamples" not in student.payload
        await sim.stop()
        report = check_path(sim.k.path, "offline")
        assert report.ok, report.failures

    arun(case())
