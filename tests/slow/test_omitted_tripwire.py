"""The omission tripwire (main root, S1-SYS-34 round 2): fence coverage stays
"a completed step with basis >= the line's seq", so a rep line dropped from
every Slow render before an accept's release is reported offline from the log.
Reporting only: nothing is suppressed and the kernel never calls it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from proxyloop.contract.events import Event
from proxyloop.slow.transcript import omitted_before_release

RUN = "r1"
LONG = "x" * 470  # a full row: about eight fill the cp lane's cap


class Log:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def add(
        self, type_: str, actor: str, payload: dict[str, Any], *causes: str,
        stream: str = "agent",
    ) -> str:  # fmt: skip
        seq = len(self.events)
        e = Event.model_validate(
            {"run_id": RUN, "seq": seq, "event_id": f"{RUN}:{seq}", "t_ms": seq,
             "wall": datetime(2026, 9, 27, tzinfo=UTC), "type": type_,
             "actor": actor, "stream": stream, "cause_ids": causes or (),
             "epoch": 0, "payload": payload}
        )  # fmt: skip
        self.events.append(e)
        return e.event_id

    def rep(self, n: int) -> str:
        said = {"lane": "cp", "speaker": "partner", "utt_id": f"cp-{n}"}
        return self.add("utt.final", "kernel", said | {"text": f"{n} {LONG}"})

    def step(self) -> None:
        basis = len(self.events) - 1
        self.add("slow.step.started", "slow", {"basis_seq": basis, "wake_reasons": []})

    def release(self) -> str:
        line = {"lane": "cp", "kind": "accept", "text": "Yes, I accept.",
                "cap_id": "cap-1"}  # fmt: skip
        said = self.add("speak.verbatim", "guard", line, f"{RUN}:0")
        return self.add("speak.released", "kernel", {"cap_id": "cap-1"}, said)


def test_a_burst_over_the_cap_before_an_accept_is_flagged() -> None:
    log = Log()
    for n in range(12):  # twelve long rep lines, then one step reads them
        log.rep(n)
    log.step()
    released = log.release()
    flagged = omitted_before_release(log.events)
    assert flagged and {r for r, _ in flagged} == {released}
    assert [u for _, u in flagged] == [f"cp-{n}" for n in range(len(flagged))]
    assert 0 < len(flagged) < 12


def test_a_line_shown_once_before_the_release_is_not_flagged() -> None:
    """Lines only grow older, so a line one render omitted is never shown by
    a later one (the kept rows are the newest that fit); a line shown once,
    then dropped as old by a later burst, is not flagged."""
    log = Log()
    for n in range(6):
        log.rep(n)
    log.step()  # all six shown
    for n in range(6, 12):
        log.rep(n)
    log.step()  # the first six drop out as old lines
    log.release()
    assert omitted_before_release(log.events) == []


def test_no_omission_is_empty() -> None:
    log = Log()
    for n in range(3):
        log.rep(n)
    log.step()
    log.release()
    assert omitted_before_release(log.events) == []


def test_a_relay_only_run_is_not_checked() -> None:
    """#183 review N-b: a ``relay_only`` run renders no conversations, so no
    line was ever "omitted" from one; the tripwire reports nothing for it."""
    log = Log()
    head = dict.fromkeys(("cfg_hash", "task_ref", "instance_hash", "git_sha"), "x")
    head |= {"split": "train", "models": {}, "renderer_fp": {}, "attest": None}
    head |= {"contract_version": "x", "parity": "pass", "slow_view": "relay_only"}
    log.add("session.started", "kernel", head, stream="ops")
    for n in range(12):
        log.rep(n)
    log.step()
    log.release()
    assert omitted_before_release(log.events) == []
