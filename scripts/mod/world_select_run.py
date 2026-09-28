"""World-model selection, PR2a (S1-MOD-09): the frozen items through the production
world code, one JSONL of rows per arm. Root-run (L); ``--plan``: no call, no key.

    python -m scripts.mod.world_select run --items <items json> --runs runs \
        --out-dir <dir> --arm teamrouter:gemini-3.8-flash@low [--arm ...] \
        [--roles ear,mouth,simuser] [--limit N] [--repeat-subset N --seed S] \
        [--concurrency K] [--resume] [--plan]

An arm is ``<endpoint>:<model_id>[@effort]`` (``cli.world_spec``); its client is
``make_client``'s, live, keys and URLs only from ``PL_<ENDPOINT>_*``, never written.
The production builders make the requests; ``world.bounded`` itself runs the attempts
with the production checks. No other retry: a dead endpoint (``LLMUnavailable``)
writes its row and aborts the run (AGENTS rule 6).

- **ear**: every item (``Ear.request``, ``check_act``; ids from the item id), called.
- **mouth**: every Mouth item (``Mouth.request``, ``fidelity_ok``; exhausted, the
  template, ``fallback: true``, as live). An arm whose ref is the recorded run's mouth
  ref reuses a recorded output, no call, when the rebuilt prompt sha equals an
  occurrence's and its ``fidelity_ok`` is true (``world_select.MOUTH_REUSE``).
- **simuser**: a recorded item replays its request by reference (``prompts.jsonl``,
  sha-checked; no chat state to rebuild it from: ``request_source: recorded``), one
  call, no check (no facts, opening or stop in the item); the recorded arm reuses its
  first attempt. A constructed item (its chat only prose) makes no call: its row is
  ``not_replayable``, left out of the scoring (the root's decision (c)).

Row (one JSON line, ``pl.world-select-row/1``; PR2b's scorer takes the last final row
per (item_id, role, repeat)): ``arm``, ``model_ref``, ``items_root_hash``, ``role``,
``item_id``, ``constructed``, ``repeat`` (2: ``--repeat-subset``), ``status`` (final:
``ok``, ``exhausted``, ``timeout``, ``reused``, ``not_replayable``; ``unavailable`` is
re-run on resume),
``reused``, ``request_sha`` (attempt 0's prompt sha), ``elapsed_ms`` (wall),
``attempts`` (per model attempt ``{n, raw, valid, reason, records}``: ``raw`` the tool
calls ``[{name, arguments}]`` or the streamed text; ``valid``/``reason`` the check's
verdict; ``records`` per HTTP attempt ``{http_attempt, echo, usage, latency_ms,
ttft_ms, finish_reason, error, prompt_sha, response_sha, sampling_sent}``), ``result``
(null unless ok/reused; ear ``{acts}``, mouth ``{text, fidelity_ok, fallback,
attempts}``, simuser ``{calls, recorded_output}``). Mouth rows add
``prompt_sha_match`` (null when constructed); simuser rows ``request_source``; reused
rows ``source {run_id, event_id}`` and ``recorded_records``; an aborted row ``error``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

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
from proxyloop.env.tasks.schema import CounterpartySpec
from proxyloop.env.user.simuser import TEMPERATURE
from proxyloop.llm.factory import make_client
from proxyloop.llm.http import HTTPAdapter
from scripts.mod import world_select as ws

Json = dict[str, Any]
ROW_SCHEMA = "pl.world-select-row/1"
ITEMS = ws.REPO / "docs/decisions/data/world-select-items.json"
FINAL = frozenset({"ok", "exhausted", "timeout", "reused", "not_replayable"})
ROLES = ws.ROLES
TRIES = world.MAX_REGENERATIONS + 1
UNUSED = cast(Any, None)  # the builders are pure: their client and writer stay unused
Sink = defaultdict[str, list[LLMCallRecord]]  # the arm client's records, by call id
PLAIN = ("finish_reason", "error", "prompt_sha", "response_sha", "sampling_sent")
EST_RULE = "per role, the mean first recorded usage per item called, times its items"


@dataclass(frozen=True)
class Arm:
    label: str
    ref: ModelRef
    file: str  # its JSONL under --out-dir


def parse_arm(spec: str) -> Arm:
    endpoint, model_id, effort = world_spec(spec)
    ref = {
        "kind": llm.AdapterKind.REAL_HTTP,
        "endpoint": endpoint,
        "model_id": model_id,
    }
    label = f"{endpoint}:{model_id}" + (f"@{effort}" if effort else "")
    file = re.sub(r"[^A-Za-z0-9._@-]", "_", label) + ".jsonl"
    return Arm(label, ModelRef.model_validate(ref | {"reasoning_effort": effort}), file)


@dataclass(frozen=True)
class Work:
    role: str
    item: Json
    repeat: int

    @property
    def key(self) -> tuple[str, str, int]:
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

    def ref(self, role: str, run_id: str) -> ModelRef | None:
        b = self.bundles.get(run_id)
        return None if b is None else b.manifest.models[cast(Any, role)].ref


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
        i = item["intent"]
        say, ask = tuple((k, v) for k, v in i["say"]), tuple(i["ask"])
        return PublicIntent(
            kind=i["kind"], offer_ref=i.get("offer_ref"), say=say, ask=ask
        )
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


def reuse_of(rec: Recorded, w: Work, arm: Arm, sha: str = "") -> Json | None:
    """The occurrence the arm reuses: one recorded by the arm's own ref and, for the
    Mouth, with this prompt sha and ``fidelity_ok`` true (``MOUTH_REUSE``)."""
    occs: list[Json] = [] if w.item.get("constructed") else w.item["occurrences"]
    for occ in occs:
        mouth_ok = occ.get("prompt_sha") == sha and occ.get("fidelity_ok") is True
        own = rec.ref(w.role, occ["run_id"]) == arm.ref
        if own and (w.role == "simuser" or mouth_ok):
            return occ
    return None


def simuser_request(rec: Recorded, item: Json, tag: str) -> ToolRequest:
    """The recorded request by its prompt sha, with SimUser's pinned max_tokens and
    temperature; its content must hash to the recorded sha."""
    sha = item["prompt_sha"]
    held = [b.prompts[sha] for o in item["occurrences"]
            if (b := rec.bundles.get(o["run_id"])) and sha in b.prompts]  # fmt: skip
    if not held:
        raise SystemExit(f"simuser {item['item_id']}: no bundle holds prompt {sha}")
    body = json.loads(held[0].content)
    request = ToolRequest(
        call_id=f"simuser:{tag}:0",
        role="simuser",
        messages=tuple(llm.ChatMessage.model_validate(m) for m in body["messages"]),
        tools=tuple(llm.ToolSpec.model_validate(t) for t in body["tools"]),
        tool_choice=body["tool_choice"],
        max_tokens=world.MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    if sha256_text(llm.request_content(request)) != sha:
        raise SystemExit(f"simuser {item['item_id']}: the replayed request differs")
    return request


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


def tool_calls(calls: Sequence[ToolCall]) -> list[Json]:
    return [{"name": c.name, "arguments": c.arguments} for c in calls]


class Replay:
    """One arm's calls, each item written into its ``row`` as it goes (so an
    aborted item's row still carries its attempts and records)."""

    def __init__(
        self, client: llm.LLMClient, sink: Sink, rec: Recorded, timeout_s: float
    ) -> None:
        self.client, self.sink, self.rec, self.timeout_s = client, sink, rec, timeout_s

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
        return tool_calls(resp.tool_calls), resp.tool_calls

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
        if (occ := reuse_of(self.rec, w, arm, sha)) is not None:
            result = {"text": occ["output"], "fidelity_ok": True, "fallback": False}
            result["attempts"] = occ["attempts"]
            return self.reuse(row, occ, occ["event_id"], result)

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
        request = simuser_request(self.rec, w.item, w.tag)
        row["request_source"] = "recorded"  # the items hold no chat state to rebuild
        if (occ := reuse_of(self.rec, w, arm)) is not None:
            prompts = self.rec.bundles[occ["run_id"]].prompts
            first = json.loads(prompts[occ["response_shas"][0]].content)  # attempt 0
            calls = [ToolCall.model_validate(c) for c in first["tool_calls"]]
            result = {"calls": tool_calls(calls), "recorded_output": occ["output"]}
            return self.reuse(row, occ, occ["llm_calls"][0], result)

        def check(calls: tuple[ToolCall, ...]) -> tuple[ToolCall, ...]:
            return calls  # none: the item holds no facts, opening or stop

        if done := await self.bounded(row, [request], self.tools, check):
            result = {"calls": tool_calls(done[0]), "recorded_output": None}
            row |= {"status": "ok", "result": result}

    def reuse(self, row: Json, occ: Json, event_id: str, result: Json) -> None:
        records = self.rec.calls(row["role"], occ)
        if row["role"] == "simuser":
            records = records[:1]  # the first attempt, as a candidate's one call
        row |= {"status": "reused", "reused": True, "result": result}
        row["source"] = {"run_id": occ["run_id"], "event_id": event_id}
        row["recorded_records"] = [summary(r) for r in records]


def done_keys(path: Path) -> set[tuple[str, str, int]]:
    lines = path.read_text("utf-8").splitlines() if path.exists() else []
    return {(r["item_id"], r["role"], r["repeat"]) for r in map(json.loads, lines)
            if r["status"] in FINAL}  # fmt: skip


async def run_arm(
    arm: Arm,
    todo: Sequence[Work],
    rec: Recorded,
    out: Path,
    args: argparse.Namespace,
    timeout_s: float,
    transport: httpx.AsyncBaseTransport | None,
) -> Counter[str]:
    """``todo`` through the arm, ``--concurrency`` at a time, each row appended as it
    ends. ``LLMUnavailable`` writes its row, cancels the rest (their rows are not
    written: resume re-runs them) and propagates."""
    sink, tally, ms = Sink(list), Counter[str](), WallClock().monotonic_ms
    client = make_client(
        arm.ref,
        live=True,
        clock=ms,
        on_record=lambda r: sink[r.call_id].append(r),  # every record, by call id
        transport=transport,
    )
    replay = Replay(client, sink, rec, timeout_s)
    gate = asyncio.Semaphore(args.concurrency)
    base: Json = {"schema": ROW_SCHEMA, "arm": arm.label, "reused": False}
    base |= {"model_ref": arm.ref.model_dump(mode="json")}
    base |= {"items_root_hash": rec.doc["root_hash"], "status": None, "result": None}
    roles = {"ear": replay.ear, "mouth": replay.mouth, "simuser": replay.simuser}

    with out.open("a", encoding="utf-8") as f:

        async def one(w: Work) -> None:
            async with gate:
                row = base | {"role": w.role, "item_id": w.item["item_id"]}
                constructed = bool(w.item.get("constructed"))
                row |= {"constructed": constructed, "repeat": w.repeat, "attempts": []}
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
            await cast(HTTPAdapter, client).aclose()
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
    """Calls per arm and role (one per item; up to ``TRIES`` for the Ear and the
    Mouth), reuses, and a token estimate from the recorded usage. No call."""
    usage: dict[tuple[str, str, int], Json | None] = {}
    sha: dict[tuple[str, str, int], str] = {}
    for w in todo:
        recs = [c for o in w.item.get("occurrences", []) for c in rec.calls(w.role, o)]
        use = next((c.usage for c in recs if c.usage is not None), None)
        usage[w.key] = use.model_dump(mode="json") if use is not None else None
        if w.role == "mouth":
            request = mouth_requests(rec, w.item, w.tag)[2][0]
            sha[w.key] = sha256_text(llm.request_content(request))
    mismatch = sum(
        sha[w.key] not in {o["prompt_sha"] for o in w.item["occurrences"]}
        for w in todo
        if w.role == "mouth" and not w.item.get("constructed")
    )
    out: Json = {"items_root_hash": rec.doc["root_hash"], "bundles": len(rec.bundles)}
    out["simuser_not_replayable"] = sum(not w.replayable for w in todo)
    out |= {"mouth_prompt_sha_mismatch": mismatch, "est_rule": EST_RULE, "arms": {}}
    for arm in arms:
        called = [
            w for w in todo if w.replayable
            and (w.role == "ear" or reuse_of(rec, w, arm, sha.get(w.key, "")) is None)
        ]  # fmt: skip
        calls = Counter(w.role for w in called)
        out["arms"][arm.label] = {
            "calls": dict(calls),
            "max_calls": {
                r: n * (1 if r == "simuser" else TRIES) for r, n in calls.items()
            },
            "reused": dict(Counter(w.role for w in todo if w.replayable) - calls),
            "tokens": {
                r: estimate([usage[w.key] for w in called if w.role == r])
                for r in calls
            },
        }
    return out


def roles_arg(text: str) -> list[str]:
    roles = [r for r in text.split(",") if r]
    if bad := [r for r in roles if r not in ROLES]:
        raise argparse.ArgumentTypeError(f"unknown roles {bad}; pick from {ROLES}")
    return roles


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
    for w in todo if runs is not None else ():  # a data defect aborts before a call
        if w.role != "ear" and w.replayable:
            (mouth_requests if w.role == "mouth" else simuser_request)(rec, w.item, "")
    if args.plan:
        return plan(rec, todo, args.arm)
    if args.out_dir is None:
        raise SystemExit("--out-dir is required without --plan")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report: Json = {}
    for arm in args.arm:
        out = args.out_dir / arm.file
        if out.exists() and out.stat().st_size and not args.resume:
            raise SystemExit(f"{out} exists: pass --resume to continue it")
        done = done_keys(out)
        left = [w for w in todo if w.key not in done]
        seam = (transports or {}).get(str(arm.ref.endpoint))
        tally = asyncio.run(run_arm(arm, left, rec, out, args, timeout_s, seam))
        report[arm.label] = {"skipped_final": len(todo) - len(left), **tally}
    return report


def main(argv: Sequence[str]) -> None:
    json.dump(run(parser().parse_args(argv)), sys.stdout, indent=1, sort_keys=True)
    print()
