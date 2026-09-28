"""World health (S1-SYS-89): the world's own calls, apart from the agent's behaviour.

DIAGNOSTIC — not a claim or metric: reported, never a gate, never imported by
``proxyloop.eval``, and no number of it goes into a doc (rule 13). Events
only; values are codes, counts, seqs and milliseconds, never text.

``roles``: per world role (``ear``, ``mouth``, ``simuser``: the llm.call
record's ``role``, which ``env/world.py`` ``World.record`` also writes as the
actor ``world.<role>``), over the whole run:

- ``calls``: every llm.call, one per HTTP attempt (regenerations are calls of
  their own, retries records of their own).
- ``finish_length``, ``errors`` (an error other than ``cancelled``) and
  ``cancelled`` (never a failure): ``detectors``' per-role counts.
  ``length_empty``: the ``finish_length`` calls with no visible output, told
  by ``response_sha`` alone (a substitute: the record has no output-length
  field): the hash of an empty streamed text or of a tool response with no
  text and no tool call (``_EMPTY``, pinned to the real ChatClient); a
  whitespace-only output counts as visible. Not ``detectors``'
  ``empty_length``, which reads Fast turns' parsed speech.
- ``reasoning_tokens_p50`` over the calls whose usage carries
  ``reasoning_tokens`` (``reasoning_n``; 0 counts); ``latency_p50_ms`` and
  ``latency_p95_ms`` (``t_end - t_start``) over the calls with no error
  (``latency_n``); nearest rank, None with no data.
- ``attempts_gt1``: result events whose ``attempts`` (the world's
  regenerations, not the record's HTTP ``attempt``) is over 1: rep.ear once
  per call (its ``call_id``: one call classifies a block, one rep.ear per
  line; None: a rep.ear without one), rep.mouth, user.sim (a silent SimUser
  reply emits none: unseen).
- ``exhausted``: the Mouth's ``fidelity_fallback`` count (rep.mouth
  ``fidelity_ok: false``, a substitute: no event names the fallback; a
  rep.mouth without the key is none); for the Ear and the SimUser, whether
  the session.ended ``world_error`` head names the role and ``invalid after N
  regenerations`` (0 or 1; None: a world_error end without a head, a bundle
  from before S1-SYS-43). Documented exception (root ruling R1, rev-273): the
  kernel-authored message is read without ``--content``, only as a whole
  (``fullmatch``) against the heads ``kernel/session.py`` ``_AUTHORED`` lets
  through, ``<role>: invalid after N regenerations`` or ``<role>: no answer
  within S s``; anything after a head (``Invalid``'s reason may quote model
  output) matches nothing. Role and detail codes only are emitted.

``window`` (root ruling on S1-SYS-89, ADR-0023 unchanged: no tier moves): on
tiers F, F-infra, E and X only, else None. The failure event is the first
status.changed to a terminal status (``guard.status.TERMINAL``) when the case
got there before the session.ended, else the session.ended; ``after_seq`` is
the last event Slow or Fast wrote before it (actor ``slow``, ``fast.user``,
``fast.cp``) that is no cancellation (``_cancelled``: an llm.call
``error: cancelled``, which the TaskGroup's teardown writes for every call in
flight, or a fast.cancelled); None: none, the window opens at the log's
start. The window ``(after_seq, failure_seq]`` lists the world artefacts in
it: ``length_empty`` (a world llm.call), ``fidelity_fallback`` (a rep.mouth),
``world_error`` (the session.ended; ``detail`` ``exhausted`` or ``timeout``
from its head, else None) and ``llm_unavailable`` (root ruling R2: an
``llm_unavailable`` end whose failing call, the first llm.call whose last
record for its call_id failed, a world actor made; that llm.call). ``self``:
the artefact is the failure event itself. A co-occurring artefact does not
prove the world caused the failure: it is shown for a human to judge.
``nearest_before``: the last artefact at or before ``after_seq`` with
``agent_turns``, the agent turns begun after it and before the failure event
(fast.request, slow.step.started), or None. ``count`` None: an X run with no
failure event yet.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import cast

from proxyloop.contract.base import sha256_text
from proxyloop.contract.events import Event
from proxyloop.contract.llm import LLMCallRecord, tool_response_content
from proxyloop.guard.status import TERMINAL
from proxyloop.obs import guide_timing
from proxyloop.obs.detectors import DETECTORS, Inputs, as_dict
from proxyloop.obs.progress import LABEL, family

ROLES = ("ear", "mouth", "simuser")
FLAGGED = frozenset({"F", "F-infra", "E", "X"})
AGENT = frozenset({"slow", "fast.user", "fast.cp"})
TURNS = ("fast.request", "slow.step.started")
_RESULTS = {"rep.ear": "ear", "rep.mouth": "mouth", "user.sim": "simuser"}
# ``llm/http.py`` hashes the delivered text: "" for a text stream with none,
# ``tool_response_content`` for a tool call (``llm/relay.py``).
_EMPTY = frozenset({sha256_text(""), sha256_text(tool_response_content("", ()))})
_HEAD = re.compile(
    r"(ear|mouth|simuser): (?:(invalid after \d+ regenerations)"
    r"|no answer within [\d.]+ s)"
)
LEGEND = (
    "length_empty = a finish_reason length call whose response_sha is that of "
    "an empty response (pinned to the real ChatClient); Mouth fallback = "
    "rep.mouth fidelity_ok false"
)
_SUMMED = ("calls", "finish_length", "length_empty", "errors", "cancelled",
           "attempts_gt1", "exhausted")  # fmt: skip
_rank = guide_timing._rank  # pyright: ignore[reportPrivateUsage]


def _head(end: Event) -> tuple[str | None, str | None]:
    """The world_error end's role and detail from its kernel-authored head."""
    message = as_dict(end.payload.get("world_error")).get("message")
    m = _HEAD.fullmatch(message) if isinstance(message, str) else None
    if m is None:
        return None, None
    return m.group(1), "exhausted" if m.group(2) else "timeout"


def _empty(r: LLMCallRecord) -> bool:
    """Cut at the cap with no visible output (module doc)."""
    return r.finish_reason == "length" and r.response_sha in _EMPTY


def _world_errors(x: Inputs) -> list[Event]:
    return [
        e for e in x.of("session.ended") if e.payload.get("reason") == "world_error"
    ]


def _attempts(x: Inputs) -> dict[str, int | None]:
    seen, out = set[object](), dict[str, int | None]()
    out.update(dict.fromkeys(ROLES, 0))
    for e in x.of(*_RESULTS):
        key = e.payload.get("call_id") if e.type == "rep.ear" else e.event_id
        attempts, role = e.payload.get("attempts"), _RESULTS[e.type]
        if key is None:  # a rep.ear with no call_id: its call cannot be told
            out[role] = None
        if (e.type, key) in seen or not isinstance(attempts, int):
            continue
        seen.add((e.type, key))
        if (n := out[role]) is not None:
            out[role] = n + (attempts > 1)
    return out


def _fallbacks(x: Inputs) -> list[int]:
    return [e.seq for e in x.of("rep.mouth") if e.payload.get("fidelity_ok") is False]


def roles(x: Inputs) -> dict[str, dict[str, object]]:
    """The whole run's per-role counts (module doc)."""
    reused = {k: as_dict(DETECTORS[k](x)) for k in
              ("finish_length", "llm_errors", "llm_cancelled")}  # fmt: skip
    attempts, fallbacks, ends = _attempts(x), _fallbacks(x), _world_errors(x)
    heads = [_head(e) for e in ends]
    out: dict[str, dict[str, object]] = {}
    for role in ROLES:
        mine = [r for _, r in x.calls if r.role == role]
        reasoning = sorted(
            r.usage.reasoning_tokens for r in mine
            if r.usage is not None and r.usage.reasoning_tokens is not None
        )  # fmt: skip
        ms = sorted(r.t_end - r.t_start for r in mine if r.error is None)
        empty = [r for r in mine if _empty(r)]
        if role == "mouth":
            exhausted: int | None = len(fallbacks)
        elif any(h[0] is None for h in heads):
            exhausted = None  # a world_error end whose role cannot be told
        else:
            exhausted = sum(h == (role, "exhausted") for h in heads)
        counts: dict[str, object] = {
            "calls": len(mine),
            "finish_length": reused["finish_length"].get(role, 0),
            "length_empty": len(empty),
            "errors": reused["llm_errors"].get(role, 0),
            "cancelled": reused["llm_cancelled"].get(role, 0),
            "reasoning_tokens_p50": _rank(reasoning, 0.5),
            "reasoning_n": len(reasoning),
            "latency_p50_ms": _rank(ms, 0.5),
            "latency_p95_ms": _rank(ms, 0.95),
            "latency_n": len(ms),
            "attempts_gt1": attempts[role],
            "exhausted": exhausted,
        }
        if role == "mouth":
            counts["fidelity_fallback"] = {"count": len(fallbacks), "seqs": fallbacks}
        out[role] = counts
    return out


def _artefact(
    seq: int, kind: str, role: str | None, detail: str | None = None
) -> dict[str, object]:
    return {"seq": seq, "kind": kind, "role": role, "detail": detail}


def artefacts(x: Inputs) -> list[dict[str, object]]:
    """Every world artefact in the run, in log order (module doc)."""
    found = [
        _artefact(seq, "length_empty", r.role)
        for seq, r in x.calls
        if r.role in ROLES and _empty(r)
    ]
    found += [_artefact(s, "fidelity_fallback", "mouth") for s in _fallbacks(x)]
    found += [_artefact(e.seq, "world_error", *_head(e)) for e in _world_errors(x)]
    found += _unavailable(x)
    return sorted(found, key=lambda a: cast(int, a["seq"]))


def _unavailable(x: Inputs) -> list[dict[str, object]]:
    """R2: an llm_unavailable end's failing call, when a world actor made it."""
    ends = x.of("session.ended")
    if not ends or ends[0].payload.get("reason") != "llm_unavailable":
        return []
    calls = [e for e in x.of("llm.call") if e.seq < ends[0].seq]
    last = {e.payload.get("call_id"): e for e in calls}  # a retry replaces it
    failed = [
        e for e in calls
        if last[e.payload.get("call_id")] is e
        and e.payload.get("error") not in (None, "cancelled")
    ]  # fmt: skip
    if not failed or not failed[0].actor.startswith("world."):
        return []
    role = str(failed[0].payload.get("role"))
    return [_artefact(failed[0].seq, "llm_unavailable", role)]


def _cancelled(e: Event) -> bool:
    """A cancellation, never the window's edge: the teardown's llm.calls."""
    cancelled = e.type == "llm.call" and e.payload.get("error") == "cancelled"
    return cancelled or e.type == "fast.cancelled"


def _failure(x: Inputs) -> Event | None:
    ends = x.of("session.ended")
    closed = [e for e in x.of("status.changed") if e.payload.get("status") in TERMINAL]
    if closed and (not ends or closed[0].seq < ends[0].seq):
        return closed[0]
    return ends[0] if ends else None


def window(x: Inputs, tier: object) -> dict[str, object] | None:
    """The flag shown next to the tier (module doc); None off F/F-infra/E/X."""
    if tier not in FLAGGED:
        return None
    out: dict[str, object] = {"tier": tier}
    if (fail := _failure(x)) is None:
        return out | {"failure": None, "failure_seq": None, "after_seq": None,
                      "count": None, "seqs": list[int](), "artefacts": list[object](),
                      "nearest_before": None}  # fmt: skip
    agent = [
        e.seq for e in x.events
        if e.actor in AGENT and e.seq < fail.seq and not _cancelled(e)
    ]  # fmt: skip
    after = agent[-1] if agent else None
    found = [(cast(int, a["seq"]), a) for a in artefacts(x)]
    inside = [
        a | {"self": s == fail.seq}
        for s, a in found if (after is None or s > after) and s <= fail.seq
    ]  # fmt: skip
    nearest: dict[str, object] | None = None
    if before := [a for s, a in found if after is not None and s <= after]:
        since = cast(int, before[-1]["seq"])
        turns = sum(since < e.seq < fail.seq for e in x.of(*TURNS))
        nearest = before[-1] | {"agent_turns": turns}
    return out | {
        "failure": fail.type, "failure_seq": fail.seq, "after_seq": after,
        "count": len(inside), "seqs": [a["seq"] for a in inside],
        "artefacts": inside, "nearest_before": nearest,
    }  # fmt: skip


def run(x: Inputs) -> dict[str, object]:
    tier = as_dict(DETECTORS["tier"](x)).get("tier")
    return {"label": LABEL, "roles": roles(x), "window": window(x, tier)}


def summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Per family over one diagnose group's rows: the runs, the per-role sums
    (``exhausted`` None in a run is counted in ``exhausted_unknown``), the
    runs the flag ran on (``flagged``); by run id, those with an artefact in
    the window other than the failure itself (``in_window``, its seqs), those
    whose failure event is one (``world_failure``) and those with one before
    the window."""
    fams: dict[str, dict[str, object]] = {}
    for r in rows:
        w = as_dict(r.get("world"))
        if not w:
            continue
        fam = fams.setdefault(family(r), {
            "runs": 0, "flagged": 0, "in_window": {}, "world_failure": [],
            "nearest_before": {},
            "roles": {role: {k: 0 for k in _SUMMED} for role in ROLES},
        })  # fmt: skip
        fam["runs"] = cast(int, fam["runs"]) + 1
        for role, counts in as_dict(w.get("roles")).items():
            got = cast(dict[str, int], as_dict(fam["roles"])[role])
            for k in _SUMMED:
                if isinstance(n := as_dict(counts).get(k), int):
                    got[k] += n
                else:
                    got[f"{k}_unknown"] = got.get(f"{k}_unknown", 0) + 1
        if flag := as_dict(w.get("window")):
            fam["flagged"] = cast(int, fam["flagged"]) + 1
            run_id = str(r.get("run_id"))
            found = [as_dict(a) for a in cast(list[object], flag["artefacts"])]
            if seqs := [a["seq"] for a in found if not a["self"]]:
                as_dict(fam["in_window"])[run_id] = seqs
            if any(a["self"] for a in found):
                cast(list[str], fam["world_failure"]).append(run_id)
            if near := as_dict(flag.get("nearest_before")):
                as_dict(fam["nearest_before"])[run_id] = {
                    k: near[k] for k in ("seq", "kind", "agent_turns")
                }
    return {"label": LABEL, "legend": LEGEND, "families": dict(sorted(fams.items()))}


def cells(value: object) -> list[str]:
    """The table cells beside the tier: the window's seqs (``:self``: the
    failure event itself; ``?``: unknown) and the nearest artefact before it
    (``seq:kind:turns``); none when empty."""
    flag, out = as_dict(as_dict(value).get("window")), list[str]()
    if flag and flag.get("count") != 0:
        found = [as_dict(a) for a in cast(list[object], flag.get("artefacts"))]
        seqs = ",".join(f"{a['seq']}{':self' * bool(a['self'])}" for a in found)
        out.append(f"artefact_window={'?' if flag.get('count') is None else seqs}")
    if near := as_dict(flag.get("nearest_before")):
        out.append(f"artefact_before={_near(near)}")
    return out


def _near(value: object) -> str:
    near = as_dict(value)
    return f"{near['seq']}:{near['kind']}:{near['agent_turns']}t"


def block(s: Mapping[str, object], group: str) -> str:
    """The human block diagnose prints per group, after the watch block."""
    kind, _, value = group.partition(":")
    out = [f"== world {kind} {value[:12]} ({LABEL})", f"  legend: {LEGEND}"]
    for fam, c in as_dict(s["families"]).items():
        d = as_dict(c)
        win, near = as_dict(d["in_window"]), as_dict(d["nearest_before"])
        failed = cast(list[str], d["world_failure"])
        out.append(f"  {fam} runs={d['runs']} flagged={d['flagged']} "
                   f"in_window={len(win)} world_failure={len(failed)} "
                   f"nearest_before={len(near)}")  # fmt: skip
        for role, counts in as_dict(d["roles"]).items():
            items = (f"{k}={n}" for k, n in as_dict(counts).items())
            out.append(" ".join([f"    {role}", *items]))
        out += [f"    window {rid} seqs={seqs}" for rid, seqs in win.items()]
        out += [f"    world_failure {rid}" for rid in failed]
        out += [f"    before {rid} {_near(n)}" for rid, n in near.items()]
    return "\n".join(out)
