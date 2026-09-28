"""World-model selection, PR2a (S1-MOD-09): the frozen items through the production
world code, one JSONL of rows per arm. Root-run (L); ``--plan``: no call, no key.

    python -m scripts.mod.world_select run --items <items json> --runs runs \
        --out-dir <dir> --arm teamrouter:gemini-3.8-flash@low [--arm ...] \
        [--roles ear,mouth,simuser] [--limit N] [--repeat-subset N --seed S] \
        [--concurrency K] [--resume] [--plan]

An arm is ``<endpoint>:<model_id>[@effort]`` (``cli.world_spec``), its client
``make_client``'s (live; keys and URLs only from ``PL_<ENDPOINT>_*``, never written).
Every arm calls, the recorded incumbent too. The production builders make the requests;
``world.bounded`` runs the attempts with the production checks; no other retry: a dead
endpoint (``LLMUnavailable``) writes its row and aborts (AGENTS rule 6). Ear:
``Ear.request``, ``check_act`` (``Heard`` ids from the item id). Mouth:
``Mouth.request``, ``fidelity_ok`` (exhausted: the template, ``fallback: true``, as
live). SimUser: ``simuser_replay`` (the recorded request rebuilt with
``SimUser.request`` and ``check_reply``; else the recorded content and ``fact_free``:
``check: partial``); a constructed item (its chat only prose) makes no call and its row
is ``not_replayable``, left out of the scoring (decision (c)).

Row (one JSON line, ``pl.world-select-row/1``; PR2b's scorer takes the last final row
per (item_id, role, repeat)): ``arm``, ``model_ref``, ``items_root_hash``, ``role``,
``item_id``, ``constructed``, ``repeat`` (2: ``--repeat-subset``), ``seed`` and
``repeat_subset`` (``--resume`` refuses others), ``status`` (final: ``ok``,
``exhausted``, ``timeout``, ``not_replayable``; ``unavailable`` is re-run on resume),
``recorded_ref`` (per occurrence, ``{run_id, response_shas}`` of the recorded
incumbent's calls: informational, never a result), ``request_sha`` (attempt 0's prompt
sha), ``elapsed_ms`` (wall), ``attempts`` (per model attempt ``{n, raw, valid, reason,
records}``: ``raw`` the tool calls ``[{name, arguments}]`` or the streamed text;
``valid``/``reason`` the check's verdict; ``records`` per HTTP attempt ``{http_attempt,
echo, usage, latency_ms, ttft_ms, finish_reason, error, prompt_sha, response_sha,
sampling_sent}``), ``result`` (null unless ok; ear ``{acts}``, mouth ``{text,
fidelity_ok, fallback, attempts}``, simuser ``{reply}``, the ``SimOut``). Mouth rows add
``prompt_sha_match`` (null when constructed); simuser rows ``request_source``,
``check``, ``check_reason``; an aborted row ``error``.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, cast

import httpx
from pydantic import ValidationError

from proxyloop.cli import world_spec
from proxyloop.contract import llm
from proxyloop.contract.base import sha256_text
from proxyloop.contract.bundle import Bundle
from proxyloop.contract.events import Event
from proxyloop.contract.llm import LLMCallRecord, ModelRef, ToolCall, ToolRequest
from proxyloop.core.clock import WallClock
from proxyloop.env import world
from proxyloop.env.counterparty.ear import Ear, EarAct, Heard, check_act
from proxyloop.env.counterparty.mouth import Mouth, fidelity_ok, template
from proxyloop.env.counterparty.policy import IntentKind, PublicIntent
from proxyloop.env.tasks.loader import load_task
from proxyloop.env.tasks.schema import CounterpartySpec, Stop
from proxyloop.env.user.simuser import SimOut, SimUser, check_reply
from proxyloop.llm.factory import make_client
from proxyloop.llm.http import HTTPAdapter
from scripts.mod import world_select as ws

Json = dict[str, Any]
Key = tuple[str, str, int]  # (item_id, role, repeat)
ROW_SCHEMA = "pl.world-select-row/1"
ITEMS = ws.REPO / "docs/decisions/data/world-select-items.json"
FINAL = frozenset({"ok", "exhausted", "timeout", "not_replayable"})
ROLES = ws.ROLES
TRIES = world.MAX_REGENERATIONS + 1
UNUSED = cast(Any, None)  # the builders are pure: their client and writer stay unused
Check = Callable[[tuple[ToolCall, ...]], SimOut]  # a SimUser reply's check
Sink = defaultdict[str, list[LLMCallRecord]]  # the arm client's records, by call id
Seam = httpx.AsyncBaseTransport | None  # the test seam into make_client
PLAIN = ("finish_reason", "error", "prompt_sha", "response_sha", "sampling_sent")
EST_RULE = "per role, the mean first recorded usage per item called, times its items"


@dataclass(frozen=True)
class Arm:
    label: str
    ref: ModelRef
    file: str  # its JSONL under --out-dir


def parse_arm(spec: str) -> Arm:
    endpoint, model_id, effort = world_spec(spec)
    ref = {"kind": "real_http", "endpoint": endpoint, "model_id": model_id}
    label = f"{endpoint}:{model_id}" + (f"@{effort}" if effort else "")
    file = re.sub(r"[^A-Za-z0-9._@-]", "_", label) + ".jsonl"
    return Arm(label, ModelRef.model_validate(ref | {"reasoning_effort": effort}), file)


@dataclass(frozen=True)
class Work:
    role: str
    item: Json
    repeat: int

    @property
    def key(self) -> Key:
        return (self.item["item_id"], self.role, self.repeat)

    @property
    def replayable(self) -> bool:  # a constructed SimUser item holds only prose
        return self.role != "simuser" or not self.item.get("constructed")

    @property
    def tag(self) -> str:  # the synthetic event id stem, unique per item and repeat
        return f"ws-{self.item['item_id'][:16]}-{self.repeat}"


class Recorded:
    """The items file and the bundles it was frozen from (read-only): the items must
    hash to their root hash, each bundle's events.jsonl to its frozen sha."""

    def __init__(self, doc: Json, runs: Path | None) -> None:
        ids = [i["item_id"] for k in ("items", "constructed") for r in ROLES
               for i in doc[k][r]]  # fmt: skip
        if sha256_text("\n".join(sorted(ids))) != doc["root_hash"]:
            raise SystemExit("the items do not hash to their root_hash")
        self.doc = doc
        self.task_ref = {b["run_id"]: b["task_ref"] for b in doc["bundles"]}
        frozen = {b["run_id"]: b["events_sha256"] for b in doc["bundles"]}
        self.bundles: dict[str, Bundle] = {}
        self._events: dict[str, dict[str, Event]] = {}
        for b, sha in ws.load(runs) if runs is not None else ():
            if (run_id := b.manifest.run_id) not in frozen:
                continue
            if sha != frozen[run_id]:
                raise SystemExit(f"{run_id}: events.jsonl differs from the frozen one")
            self.bundles[run_id] = b
            self._events[run_id] = {e.event_id: e for e in b.events}

    def calls(self, role: str, occ: Json) -> list[LLMCallRecord]:
        """The occurrence's recorded ``llm.call`` records ([] without its bundle,
        and for an Ear block, which no call classified)."""
        if (events := self._events.get(occ["run_id"])) is None:
            return []
        ids: list[str] = list(occ.get("llm_calls", []))
        if (ev := occ.get("rep_ear" if role == "ear" else "event_id")) in events:
            ids = list(events[ev].cause_ids[1:])
        return [LLMCallRecord.model_validate(events[i].payload) for i in ids]

    def recorded_ref(self, w: Work) -> list[Json]:
        """The recorded incumbent's response shas per occurrence (informational)."""
        occs: list[Json] = w.item.get("occurrences", [])
        return [{"run_id": o["run_id"], "response_shas": [c.response_sha for c in
                 self.calls(w.role, o)]} for o in occs]  # fmt: skip


def counterparty(rec: Recorded, item: Json) -> CounterpartySpec:
    if item.get("constructed"):
        return load_task(item["family"]).counterparty
    run_id = item["occurrences"][0]["run_id"]
    spec = ws.task_of(rec.task_ref[run_id]).counterparty
    if sha256_text(spec.persona.strip()) != item["persona_sha"]:
        raise SystemExit(f"mouth {item['item_id']}: the persona moved since the freeze")
    return spec


def ear_inputs(
    item: Json, tag: str
) -> tuple[list[Heard], dict[str, dict[str, str]], list[str]]:
    """The block as ``Heard`` records, every offer made (in order) with its terms,
    and the open ones."""
    if item.get("constructed"):
        offers = {r: dict(t) for r, t in item["offers"].items()}
        opened, said = list(item["open_offers"]), list(item["block"])
    else:
        offers = {o["ref"]: dict(o["terms"]) for o in item["offers"]}
        opened = [o["ref"] for o in item["offers"] if o["open"]]
        said = list(item["utterances"])
    block = [
        Heard(utt_id=f"{tag}-u{i}", text=t, event_id=f"{tag}:{i}", t_ms=0)
        for i, t in enumerate(said, 1)
    ]
    return block, offers, opened


def mouth_intent(item: Json, company: str) -> PublicIntent:
    """As recorded; a constructed one's ``say`` (stored key-sorted) in the order its
    frozen ``template`` shows each term as rendered today (the line may be older)."""
    if not item.get("constructed"):
        return PublicIntent.model_validate(item["intent"])
    kind, ref = cast(IntentKind, item["intent"]), item["offer_ref"]
    bare = len(template(PublicIntent(kind=kind), company)) + 1  # the line and a space
    at = {kv: item["template"].find(template(PublicIntent(kind=kind, say=(kv,)),
                                             company)[bare:-1])
          for kv in item["say"].items()}  # fmt: skip
    if min(at.values(), default=0) < 0 or len(set(at.values())) != len(at):
        raise SystemExit(f"mouth {item['name']}: its template shows no say order")
    say = tuple(sorted(at, key=at.__getitem__))
    return PublicIntent(kind=kind, offer_ref=ref, say=say, ask=tuple(item["ask"]))


def mouth_requests(
    rec: Recorded, item: Json, tag: str
) -> tuple[PublicIntent, str, list[llm.TextRequest]]:
    """The intent, the template line and ``Mouth.request`` for every attempt."""
    spec = counterparty(rec, item)
    intent, mouth = mouth_intent(item, spec.company), Mouth(UNUSED, UNUSED, spec)
    requests = [mouth.request(intent, item["heard"], tag, n) for n in range(TRIES)]
    return intent, template(intent, spec.company), requests


def simuser_replay(
    rec: Recorded, item: Json, tag: str
) -> tuple[list[ToolRequest], str, Check, str | None]:
    """The requests per attempt, their source, the check and why it is partial. The
    recorded request (by its prompt sha) is rebuilt with ``SimUser.request`` from its
    task: the facts as the user holds them (the profile's, or with the mind change),
    the stop (if the request says the task's), the chat (the recorded lines as one
    block; none: the opening). When that reproduces the sha, the check is
    ``check_reply`` with those inputs; else the recorded content and ``fact_free``."""
    sha = item["prompt_sha"]
    held = [(o, b.prompts[sha]) for o in item["occurrences"]
            if (b := rec.bundles.get(o["run_id"])) and sha in b.prompts]  # fmt: skip
    if not held:
        raise SystemExit(f"simuser {item['item_id']}: no bundle holds prompt {sha}")
    task = ws.task_of(rec.task_ref[held[0][0]["run_id"]])
    sim, body = SimUser(task, UNUSED, UNUSED, 0), json.loads(held[0][1].content)
    user, stop = body["messages"][-1]["content"], task.stop
    profile = dict(task.profile.facts)
    changed = [profile | stop.change] if stop and stop.change else []
    stops: list[Stop | None] = [stop, None] if stop else [None]
    for facts, now in itertools.product([profile, *changed], stops):
        marked = sim.request(["\0"], facts, now, tag, 0).messages[-1].content
        head, tail = marked.split("\0")
        opening = sim.request([], facts, now, tag, 0).messages[-1].content == user
        chat = [] if opening else [user[len(head) : len(user) - len(tail)]]
        requests = [sim.request(chat, facts, now, tag, n) for n in range(TRIES)]
        if user.startswith(head) and user.endswith(tail) and sha_of(requests[0]) == sha:
            check = partial(check_reply, facts=facts, opening=opening, stop=now)
            return requests, "rebuilt", check, None
    base = sim.request([], profile, None, tag, 0)  # the builder's sampling
    tools = tuple(llm.ToolSpec.model_validate(t) for t in body["tools"])
    messages = tuple(llm.ChatMessage.model_validate(m) for m in body["messages"])
    fields = {"messages": messages, "tools": tools, "tool_choice": body["tool_choice"]}
    ids = [f"simuser:{tag}:{n}" for n in range(TRIES)]
    requests = [base.model_copy(update=fields | {"call_id": i}) for i in ids]
    if sha_of(requests[0]) != sha:
        raise SystemExit(f"simuser {item['item_id']}: the replayed request differs")
    why = "the request does not rebuild from its task's facts and stop"
    return requests, "recorded", fact_free(user == base.messages[-1].content), why


def fact_free(opening: bool) -> Check:
    """``check_reply``'s checks that need no facts or stop: one ``reply`` call, the
    ``SimOut`` schema, no silent opening."""

    def check(calls: tuple[ToolCall, ...]) -> SimOut:
        if len(calls) != 1 or calls[0].name != "reply":
            raise world.Invalid("expected exactly one reply call")
        try:
            out = SimOut.model_validate_json(calls[0].arguments)
        except ValidationError as err:
            raise world.Invalid(f"schema: {err.errors()[0]['msg']}") from err
        if out.silent and opening:
            raise world.Invalid("the opening request cannot be silent")
        return out

    return check


def sha_of(request: llm.TextRequest | ToolRequest) -> str:
    return sha256_text(llm.request_content(request))


def work(doc: Json, args: argparse.Namespace) -> list[Work]:
    """Recorded then constructed items per role (the first ``--limit``), then
    ``--repeat-subset`` Ear items drawn with ``--seed``, again, as repeat 2."""
    out: list[Work] = []
    for role in args.roles:
        made: list[Json] = doc["constructed"][role]
        out += [Work(role, i, 1) for i in [*doc["items"][role], *made][: args.limit]]
    ears = sorted((w.item for w in out if w.role == "ear"), key=lambda i: i["item_id"])
    if (n := args.repeat_subset or 0) > len(ears):
        raise SystemExit(f"--repeat-subset {n} > {len(ears)} Ear items")
    return out + [Work("ear", i, 2) for i in random.Random(args.seed).sample(ears, n)]


def summary(r: LLMCallRecord) -> Json:
    first, out = r.t_first_token, {k: getattr(r, k) for k in PLAIN}
    out |= {"http_attempt": r.attempt, "echo": r.served_model_echo}
    out["usage"] = r.usage.model_dump(mode="json") if r.usage else None
    out["latency_ms"] = r.t_end - r.t_start
    return out | {"ttft_ms": None if first is None else first - r.t_start}


class Replay:
    """One arm's calls through its production client, each item written into its
    ``row`` as it goes (so an aborted item's row still carries its attempts)."""

    def __init__(self, arm: Arm, rec: Recorded, timeout_s: float, seam: Seam) -> None:
        self.arm, self.rec, self.timeout_s, self.sink = arm, rec, timeout_s, Sink(list)
        self.client = make_client(
            arm.ref, live=True, clock=WallClock().monotonic_ms, on_record=self.record,
            transport=seam,
        )  # fmt: skip

    def record(self, record: LLMCallRecord) -> None:  # the client's on_record
        self.sink[record.call_id].append(record)

    async def bounded[Q: (llm.TextRequest, ToolRequest), R, T](
        self,
        row: Json,
        requests: Sequence[Q],
        call: Callable[[Q], Awaitable[tuple[object, R]]],
        check: Callable[[R], T],
        exhausted: Callable[[], T] | None = None,
    ) -> tuple[T, int, bool] | None:
        """``world.bounded`` over ``requests``, each attempt and its check recorded;
        None when it ends in a ``WorldError`` (``status``: exhausted or timeout)."""
        tries: list[Json] = row["attempts"]

        async def attempt(n: int) -> R:
            tries.append({"n": n, "raw": None, "valid": None, "reason": None})
            try:
                tries[-1]["raw"], value = await call(requests[n])
                return value
            finally:  # a cancelled or dead attempt's records too
                records = self.sink.pop(requests[n].call_id, [])
                tries[-1]["records"] = [summary(r) for r in records]

        def checked(value: R) -> T:
            try:
                out = check(value)
            except world.Invalid as err:
                tries[-1] |= {"valid": False, "reason": str(err)}
                raise
            tries[-1]["valid"] = True
            return out

        row["request_sha"] = sha256_text(llm.request_content(requests[0]))
        what, timeout_s = row["role"], self.timeout_s
        try:
            return await world.bounded(
                attempt, checked, what=what, timeout_s=timeout_s, exhausted=exhausted
            )
        except world.WorldError as err:
            timeout = isinstance(err.__cause__, TimeoutError)
            row["status"] = "timeout" if timeout else "exhausted"
            return None

    async def tools(self, request: ToolRequest) -> tuple[object, tuple[ToolCall, ...]]:
        resp = await self.client.chat_tools(request)
        calls = [{"name": c.name, "arguments": c.arguments} for c in resp.tool_calls]
        return calls, resp.tool_calls

    async def text(self, request: llm.TextRequest) -> tuple[object, str]:
        """As ``World.text`` (deltas joined, the stream closed), stripped as
        ``Mouth.say`` strips it."""
        parts: list[str] = []
        stream = self.client.stream_text(request)
        try:
            async for item in stream:
                if isinstance(item, str):
                    parts.append(item)
        finally:
            if (close := getattr(stream, "aclose", None)) is not None:
                await close()
        return "".join(parts), "".join(parts).strip()

    async def ear(self, w: Work, row: Json, arm: Arm) -> None:
        block, offers, opened = ear_inputs(w.item, w.tag)
        keys = list(w.item["identity_keys"])
        ear = Ear(UNUSED, UNUSED, w.item["company"], keys)
        requests = [ear.request(block, offers, opened, n) for n in range(TRIES)]
        heard = [h.text for h in block]

        def check(calls: tuple[ToolCall, ...]) -> tuple[EarAct, ...]:
            return check_act(calls, heard, offers.keys(), keys)  # as Ear.classify

        if done := await self.bounded(row, requests, self.tools, check):
            acts = [a.model_dump(mode="json", exclude_defaults=True) for a in done[0]]
            row |= {"status": "ok", "result": {"acts": acts}}

    async def mouth(self, w: Work, row: Json, arm: Arm) -> None:
        intent, line, requests = mouth_requests(self.rec, w.item, w.tag)
        sha = sha256_text(llm.request_content(requests[0]))
        made, occs = w.item.get("constructed"), w.item.get("occurrences", [])
        row["prompt_sha_match"] = (
            None if made else sha in {o["prompt_sha"] for o in occs}
        )

        def check(text: str) -> str:  # Mouth.say's check
            if not text or not fidelity_ok(text, intent):
                raise world.Invalid("number fidelity")
            return text

        if done := await self.bounded(row, requests, self.text, check, lambda: line):
            text, attempts, ok = done
            result = {"text": text, "fidelity_ok": ok, "fallback": not ok}
            row |= {"status": "ok", "result": result | {"attempts": attempts}}

    async def simuser(self, w: Work, row: Json, arm: Arm) -> None:
        if not w.replayable:
            return row.update(status="not_replayable")
        requests, source, check, why = simuser_replay(self.rec, w.item, w.tag)
        row |= {"request_source": source, "check": "partial" if why else "full"}
        row |= {"check_reason": why} if why else {}
        if done := await self.bounded(row, requests, self.tools, check):
            row |= {"status": "ok", "result": {"reply": done[0].model_dump()}}


def resume(path: Path, args: argparse.Namespace) -> tuple[set[Key], int]:
    """The final rows' keys, and the torn lines (unparsable: skipped, their items
    re-run; a torn tail gets its newline, so the next row starts clean). The rows
    must have run with this ``--seed`` and ``--repeat-subset``."""
    text = path.read_text("utf-8") if path.exists() else ""
    rows, torn = list[Json](), 0
    for line in text.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            torn += 1
    if (ran := {(r.get("seed"), r.get("repeat_subset")) for r in rows}) - {draw(args)}:
        raise SystemExit(f"{path}: (seed, repeat_subset) {ran}, not {draw(args)}")
    if text and not text.endswith("\n"):
        with path.open("a", encoding="utf-8") as f:
            f.write("\n")
    return {(r["item_id"], r["role"], r["repeat"]) for r in rows
            if r["status"] in FINAL}, torn  # fmt: skip


def draw(args: argparse.Namespace) -> tuple[int | None, int]:
    return args.seed, args.repeat_subset or 0


async def run_arm(
    replay: Replay, todo: Sequence[Work], out: Path, args: argparse.Namespace
) -> Counter[str]:
    """``todo`` through the arm, ``--concurrency`` at a time, each row appended as it
    ends. ``LLMUnavailable`` writes its row, cancels the rest (their rows are not
    written: resume re-runs them) and propagates."""
    arm, rec, tally = replay.arm, replay.rec, Counter[str]()
    gate = asyncio.Semaphore(args.concurrency)
    base: Json = {"schema": ROW_SCHEMA, "arm": arm.label}
    base |= dict(zip(("seed", "repeat_subset"), draw(args), strict=True))
    base |= {"model_ref": arm.ref.model_dump(mode="json")}
    base |= {"items_root_hash": rec.doc["root_hash"], "status": None, "result": None}
    roles = {"ear": replay.ear, "mouth": replay.mouth, "simuser": replay.simuser}

    with out.open("a", encoding="utf-8") as f:

        async def one(w: Work) -> None:
            async with gate:
                row = base | {"role": w.role, "item_id": w.item["item_id"]}
                constructed = bool(w.item.get("constructed"))
                row |= {"constructed": constructed, "repeat": w.repeat, "attempts": []}
                row["recorded_ref"] = rec.recorded_ref(w)
                start = time.monotonic()
                try:
                    await roles[w.role](w, row, arm)
                except llm.LLMUnavailable as dead:
                    row |= {"status": "unavailable", "error": str(dead)}
                    raise
                finally:
                    if row["status"] is not None:  # None: cancelled by an abort
                        row["elapsed_ms"] = round((time.monotonic() - start) * 1000)
                        f.write(json.dumps(row, sort_keys=True, ensure_ascii=False))
                        f.write("\n")
                        f.flush()
                        tally[f"{w.role}:{row['status']}"] += 1

        try:
            async with asyncio.TaskGroup() as tg:
                for w in todo:
                    tg.create_task(one(w))
        except* llm.LLMUnavailable as group:
            raise group.exceptions[0] from None
        finally:
            await cast(HTTPAdapter, replay.client).aclose()
    return tally


def estimate(found: Sequence[Json | None]) -> Json:
    """The role's mean recorded tokens per item, times its items (null-safe)."""
    known = [u for u in found if u is not None]
    out: Json = {"items": len(found), "with_usage": len(known)}
    for key in ("prompt_tokens", "completion_tokens", "reasoning_tokens"):
        vals = [cast(int, u[key]) for u in known if u.get(key) is not None]
        out[key] = round(sum(vals) / len(vals) * len(found)) if vals else None
    return out


def plan(rec: Recorded, todo: Sequence[Work], arms: Sequence[Arm]) -> Json:
    """Calls per arm and role (one per item; up to ``TRIES`` with regenerations) and a
    token estimate from the recorded usage. No call."""
    usage: dict[Key, Json | None] = {}
    mismatch = 0
    for w in todo:
        recs = [c for o in w.item.get("occurrences", []) for c in rec.calls(w.role, o)]
        use = next((c.usage for c in recs if c.usage is not None), None)
        usage[w.key] = use.model_dump(mode="json") if use is not None else None
        if w.role == "mouth" and not w.item.get("constructed"):
            request = mouth_requests(rec, w.item, w.tag)[2][0]
            shas = {o["prompt_sha"] for o in w.item["occurrences"]}
            mismatch += sha256_text(llm.request_content(request)) not in shas
    called = [w for w in todo if w.replayable]
    calls = Counter(w.role for w in called)
    per_arm: Json = {"calls": dict(calls)}
    per_arm["max_calls"] = {r: n * TRIES for r, n in calls.items()}
    per_arm["tokens"] = {
        r: estimate([usage[w.key] for w in called if w.role == r]) for r in calls
    }
    out: Json = {"items_root_hash": rec.doc["root_hash"], "bundles": len(rec.bundles)}
    out["simuser_not_replayable"] = sum(not w.replayable for w in todo)
    out |= {"mouth_prompt_sha_mismatch": mismatch, "est_rule": EST_RULE}
    return out | {"arms": {arm.label: per_arm for arm in arms}}


def roles_arg(text: str) -> list[str]:
    if bad := set(text.split(",")) - set(ROLES):
        raise argparse.ArgumentTypeError(f"unknown roles {bad}; pick from {ROLES}")
    return text.split(",")


def positive(text: str) -> int:
    if (n := int(text)) < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, not {n}")
    return n


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.mod.world_select run")
    ap.add_argument("--items", type=Path, default=ITEMS)
    ap.add_argument("--runs", type=Path, default=Path("runs"), help="read-only")
    ap.add_argument("--out-dir", type=Path, help="one JSONL per arm")
    ap.add_argument("--arm", type=parse_arm, action="append", required=True)
    ap.add_argument("--roles", type=roles_arg, default=list(ROLES))
    ap.add_argument("--limit", type=positive, help="the first N items per role")
    ap.add_argument("--repeat-subset", type=positive, help="N seeded Ear items again")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--concurrency", type=positive, default=4)
    ap.add_argument("--resume", action="store_true", help="skip final rows")
    ap.add_argument("--plan", action="store_true", help="counts only; no call, no key")
    return ap


def run(
    args: argparse.Namespace,
    timeout_s: float = world.TIMEOUT_S,
    transports: Mapping[str, httpx.AsyncBaseTransport] | None = None,
) -> Json:
    """``transports``: per endpoint, the test seam into ``make_client``."""
    if args.repeat_subset and args.seed is None:
        raise SystemExit("--repeat-subset needs --seed")
    if len({a.label for a in args.arm}) != len(args.arm):
        raise SystemExit("an arm is given twice")
    runs = args.runs if args.runs.is_dir() else None
    if runs is None and not args.plan and {"mouth", "simuser"} & set(args.roles):
        raise SystemExit(f"--runs {args.runs}: the Mouth and SimUser need its bundles")
    rec = Recorded(json.loads(args.items.read_text("utf-8")), runs)
    todo = work(rec.doc, args)
    sources = Counter[str]()  # SimUser requests rebuilt or recorded
    for w in todo if runs is not None else ():  # a data defect aborts before a call
        if w.role == "mouth":
            mouth_requests(rec, w.item, "")
        elif w.role == "simuser" and w.replayable:
            sources[simuser_replay(rec, w.item, "")[1]] += 1
    if args.plan:
        return plan(rec, todo, args.arm) | {"simuser_request_source": dict(sources)}
    if args.out_dir is None:
        raise SystemExit("--out-dir is required without --plan")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report: Json = {}
    for arm in args.arm:
        out = args.out_dir / arm.file
        if out.exists() and out.stat().st_size and not args.resume:
            raise SystemExit(f"{out} exists: pass --resume to continue it")
        done, torn = resume(out, args)
        left = [w for w in todo if w.key not in done]
        seam = (transports or {}).get(str(arm.ref.endpoint))
        replay = Replay(arm, rec, timeout_s, seam)
        tally = asyncio.run(run_arm(replay, left, out, args))
        report[arm.label] = {"skipped_final": len(todo) - len(left), **tally}
        report[arm.label] |= {"torn_lines": torn} if torn else {}
    return report


def main(argv: Sequence[str]) -> None:
    json.dump(run(parser().parse_args(argv)), sys.stdout, indent=1, sort_keys=True)
    print()
