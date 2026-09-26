"""The event envelope ``pl.event/2`` and the event registry (ARCHITECTURE §4).

A registry entry fixes the type's streams, whether it needs ``cause_ids``, and
its required payload keys (§4.2). Extra payload keys are allowed; types §4.2
lists without fields require none yet. Additions need an ADR.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from proxyloop.contract.base import Frozen
from proxyloop.contract.llm import LLMCallRecord
from proxyloop.contract.messages import FastToSlow, SlowToFast
from proxyloop.contract.state import ApprovalCard

EVENT_SCHEMA = "pl.event/2"
Stream = Literal["agent", "world", "ops"]
_STREAMS: tuple[Stream, ...] = ("agent", "world", "ops")


@dataclass(frozen=True, slots=True)
class EventSpec:
    streams: tuple[Stream, ...]
    cause_required: bool
    payload_keys: tuple[str, ...]


# type | streams | cause_ids required (+) or exogenous (-) | required payload keys.
# Exogenous (§4.1): ingress (session.started, user.msg, utt.final, approval.post)
# and what a timer can emit (session.ended, parity.checked, attest.recorded,
# chan.strike, fast.request, slow.step.started, rep.policy). "*" = a model's fields.
_TABLE: str = """
session.started      ops          -  cfg_hash task_ref instance_hash split models
                                     renderer_fp contract_version git_sha attest parity
session.ended        ops          -  reason
spend.charged        ops          +
parity.checked       ops          -
attest.recorded      ops          -
llm.call             agent,world  +  *
user.msg             agent        -  text
utt.final            agent        -  lane speaker utt_id text
utt.delivered        agent        +  lane utt_id text_generated text_heard interrupted
chan.opened          agent        +
chan.closed          agent        +
chan.hold            agent        +
chan.strike          agent        -
chan.barge_in        agent        +
fast.request         agent        -  lane gen_id trigger view_sha prompt_sha profile
                                     model_ref basis_seq
fast.turn            agent        +  lane gen_id call_id items ttft_ms ttfs_ms
fast.sentence        agent        +  lane gen_id utt_id text
fast.cancelled       agent        +  gen_id reason
f2s.msg              agent        +  *
s2f.msg              agent        +  *
s2f.voiced           agent        +  msg_id gen_id
slow.step.started    agent        -  basis_seq wake_reasons
slow.step.completed  agent        +  basis_seq
slow.tool            agent        +  name args result_text ok
summary.updated      agent        +  scope text
declass.denied       agent        +  violations
fact.recorded        agent        +
offer.recorded       agent        +  offer_ref revision slots terms_hash
readback.updated     agent        +  offer_ref slot_statuses
approval.post        agent        -  approval_id decision terms_hash authority_epoch
authority.fence      agent        +  op fence_id utt_id
authority.epoch      agent        +  new reason
mandate.proposed     agent        +
mandate.decided      agent        +
approval.requested   agent        +  *
approval.decided     agent        +  approval_id decision by
action.authorized    agent        +  intent capability
action.denied        agent        +  intent reason
speak.verbatim       agent        +  lane kind text
speak.released       agent        +
speak.revoked        agent        +  reason
screen.redacted      agent        +
evidence.recorded    agent        +
status.changed       agent        +
completion.decided   agent        +  verdict reasons
rep.ear              world        +  utt_id act args call_id
rep.policy           world        -  from to intent rung
rep.mouth            world        +  intent text fidelity_ok attempts
rep.commit_heard     world        +  utt_id offer_ref
ledger.write         world        +  confirmation_id binding
user.sim             world        +  text revealed delay_s
"""
_MODELS: dict[str, type[Frozen]] = {
    "llm.call": LLMCallRecord,
    "f2s.msg": FastToSlow,
    "s2f.msg": SlowToFast,
    "approval.requested": ApprovalCard,
}


def _registry() -> dict[str, EventSpec]:
    rows: list[list[str]] = []
    for line in _TABLE.strip().splitlines():
        if line.startswith(" "):  # continues the previous type's keys
            rows[-1] += line.split()
        else:
            rows.append(line.split())
    specs: dict[str, EventSpec] = {}
    for name, streams, cause, *keys in rows:
        model = _MODELS.get(name)
        specs[name] = EventSpec(
            streams=tuple(s for s in _STREAMS if s in streams.split(",")),
            cause_required=cause == "+",
            payload_keys=tuple(model.model_fields) if model else tuple(keys),
        )
    return specs


EVENT_TYPES: MappingProxyType[str, EventSpec] = MappingProxyType(_registry())


def event_id(run_id: str, seq: int) -> str:
    return f"{run_id}:{seq}"


class Event(Frozen):
    """One line of ``events.jsonl``. ``t_ms`` is monotonic ms since start."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", validate_by_name=True, serialize_by_alias=True
    )

    schema_: Literal["pl.event/2"] = Field(default="pl.event/2", alias="schema")
    run_id: str = Field(min_length=1)
    seq: int = Field(ge=0)
    event_id: str
    t_ms: int = Field(ge=0)
    wall: datetime
    type: str
    actor: str
    stream: Stream
    cause_ids: tuple[str, ...] = ()
    epoch: int = Field(ge=0)
    payload: dict[str, object] = Field(default_factory=dict[str, object])

    @model_validator(mode="after")
    def _envelope(self) -> Self:
        if self.event_id != event_id(self.run_id, self.seq):
            raise ValueError("event_id must be f'{run_id}:{seq}'")
        if self.wall.utcoffset() is None:
            raise ValueError("wall must be timezone-aware")
        spec = EVENT_TYPES.get(self.type)
        if spec is None:
            raise ValueError(f"unregistered event type {self.type!r}")
        if self.stream not in spec.streams:
            raise ValueError(f"{self.type} is not a {self.stream} event")
        if spec.cause_required and not self.cause_ids:
            raise ValueError(f"{self.type} is derived and needs cause_ids")
        for cause in self.cause_ids:
            run, _, seq = cause.rpartition(":")
            if run != self.run_id or not seq.isdigit() or int(seq) >= self.seq:
                raise ValueError(f"cause {cause!r} is not an earlier event of this run")
        missing = [key for key in spec.payload_keys if key not in self.payload]
        if missing:
            raise ValueError(f"{self.type} payload lacks {missing}")
        return self
