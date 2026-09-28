"""World-model selection data (S1-MOD-09, PR1): offline, no keys, no model call.

    python -m scripts.mod.world_select freeze --runs runs \
        --out docs/decisions/data/world-select-items.json [--constructed <json>]
    python -m scripts.mod.world_select export --items <json> --out-dir <dir> \
        --key-out <json outside the out dir> --batch 25 --seed N
    python -m scripts.mod.world_select run ...  (PR2a, root-run: world_select_run)

``freeze`` reads every ``train`` bundle under ``--runs`` (``load_bundles``: a sealed
``test`` path is refused) and freezes three item sets from the events:

- **ear**: one item per unique (utterance text as heard, whitespace and case
  normalised; the offers made before it, with their terms and open status; the
  family's company and identity keys). The text is the cp-lane agent speech of the
  ``utt.delivered`` lines one delivery joined (what ``SimRep`` heard); offers come
  from the ``rep.policy`` intents (``offer``/``final_offer`` make one, ``offer_expired``
  and ``confirmed`` close it). Recorded Ear requests are never read (their schema
  predates ADR-0021). Items of kind ``block`` are the ADR-0021 D1 blocks, rebuilt by
  replaying the heard utterances on the recorded clock: a rep turn takes every
  utterance heard by the time it starts, and lasts as long as the recorded turn of
  its first utterance; its offers are those made before that first utterance.
- **mouth**: each recorded ``rep.mouth``'s semantic inputs (intent, the heard text it
  answers, company, persona sha) with the recorded prompt sha and incumbent output;
  whether an item may reuse that output is decided in PR2 by re-rendering the prompt
  sha. Trivial intents are capped by a seeded draw.
- **simuser**: the recorded SimUser requests (by prompt sha, in the bundle's
  ``prompts.jsonl``) and outputs, from bundles whose git sha descends from 9e4e796.

``--constructed`` items are copied in with every given field, flagged
``constructed: true`` and kept apart; the file's other top-level keys go to
``constructed_meta``. An Ear item whose text names an offer ref is flagged
``off_distribution`` (the rep never voices a ref, so live callers hear none).
``item_id`` is the sha256 of an item's canonical semantic content; the root hash is
the sha256 of the sorted item ids. The same inputs give byte-identical JSON.

``export`` writes blind Ear annotation batches (what the Ear sees, in structured form;
no world output, model, run or condition) in a seeded order, and to ``--key-out``,
which must lie outside ``--out-dir``, the key mapping each batch position to its
item id (never given to the annotator with the batches). Constructed Ear
items with gold go to separate check batches, their gold withheld.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, cast, get_args

from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.contract.bundle import EVENTS, Bundle
from proxyloop.contract.events import Event
from proxyloop.contract.llm import AdapterKind
from proxyloop.env.counterparty.ear import Act
from proxyloop.env.tasks.loader import instance_hash, load_task, resolve
from proxyloop.env.tasks.schema import Task
from proxyloop.evidence.check import evidence_check
from proxyloop.training.pull_through import load_bundles

Json = dict[str, Any]
SCHEMA = "pl.world-select-items/1"
REPO = Path(__file__).resolve().parents[2]
SIMUSER_SINCE = "9e4e796"  # S1-SYS-04: the SimUser of the slice (reply tool, stop)
TRIVIAL = ("ask_identity", "ok_hold", "greet", "check_in")
TRIVIAL_CAP, CAP_SEED = 15, 0
MAX_BATCH = 25
REAL_ROLES = ("fast_user", "fast_cp", "ear", "mouth", "simuser")  # Fast and world
ROLES = ("ear", "mouth", "simuser")
ELIGIBILITY = (
    "Bundles under --runs read by training.pull_through.load_bundles (a path with a "
    "'test' part is refused or skipped), manifest split == 'train' only, with "
    f"real_http for every Fast and world role ({', '.join(REAL_ROLES)}) in the "
    "manifest's reality, and a task instance (company, identity keys, ladder) "
    "whose hash is still the manifest's instance_hash; each bundle's offline "
    "evidence-check status is recorded and disclosed, never a filter. Ear: every "
    "cp-lane utterance a rep.ear classified (its utt.delivered lines of one delivery, "
    "text_heard joined), deduplicated on (whitespace/case-normalised text, offers "
    "made before it with terms and open status, company, identity keys); blocks: the "
    "ADR-0021 D1 replay on the recorded clock, 2+ utterances. Mouth: every rep.mouth, "
    f"deduplicated on its semantic inputs; intents {', '.join(TRIVIAL)} capped at "
    f"{TRIVIAL_CAP} unique items each by a seeded draw (seed {CAP_SEED}). SimUser: "
    f"every SimUser request of a bundle whose git_sha descends from {SIMUSER_SINCE}. "
    "Constructed items are flagged and never pooled with recorded ones. An Ear item "
    "whose text names an offer ref (the family ladder's or its own) is "
    "off_distribution: true and scored apart."
)
MOUTH_REUSE = (
    "Decided in PR2: a Mouth occurrence's recorded output stands for the incumbent "
    "only if the prompt sha the production Mouth re-renders from the item equals the "
    "occurrence's prompt_sha, and fidelity_ok is true (false: the output is the "
    "template line, not the model's)."
)


def item_id(content: object) -> str:
    return sha256_text(canonical_json(content))


def norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _s(payload: dict[str, object], key: str) -> str:
    return str(payload[key])


# ---------------------------------------------------------------- bundles


def load(root: Path) -> list[tuple[Bundle, str]]:
    """The bundles ``load_bundles`` reads, each with its events.jsonl sha256."""
    bundles = load_bundles(root)  # refuses a sealed root before anything is read
    dirs = sorted(m.parent.resolve() for m in root.rglob("manifest.json"))
    dirs = [d for d in dirs if "test" not in d.parts]
    shas = [hashlib.sha256((d / EVENTS).read_bytes()).hexdigest() for d in dirs]
    return list(zip(bundles, shas, strict=True))


@cache
def descends(git_sha: str, since: str = SIMUSER_SINCE) -> bool:
    """``since`` is an ancestor of ``git_sha`` (unknown shas are not)."""
    cmd = ["git", "merge-base", "--is-ancestor", since, git_sha]
    return subprocess.run(cmd, cwd=REPO, capture_output=True).returncode == 0


@cache
def task_of(task_ref: str) -> Task:
    return resolve(task_ref)


# ---------------------------------------------------------------- the walk


@dataclass
class Heard:
    event_id: str  # the delivery's last utt.delivered, as the Ear cites it
    text: str
    sent_ms: int


@dataclass
class Turn:
    """One recorded Ear call (one heard block) and the rep turn it started."""

    offers: list[Json]  # made before the turn, with terms and open status
    start_ms: int
    end_ms: int
    heard: list[tuple[Heard, str]] = field(default_factory=list[tuple[Heard, str]])


@dataclass
class Walk:
    turns: list[Turn]
    mouth: list[tuple[Json, Json]]  # (semantic content, occurrence)
    not_delivered: int  # rep.ear events whose utterance is not a cp utt.delivered


def walk(b: Bundle, task: Task) -> Walk:
    """The Ear's heard utterances and turns, and the Mouth's calls, from the events."""
    by_id = {e.event_id: e for e in b.events}
    offers: dict[str, list[list[str]]] = {}  # made, in order: ref -> terms as said
    closed: set[str] = set()
    deliveries: list[Event] = []  # cp-lane utt.delivered, in order
    taken = 0  # deliveries already joined into an earlier heard utterance
    turns: dict[str, Turn] = {}  # by the Ear's call_id
    ear_turn: dict[str, Turn] = {}  # rep.ear id -> its turn
    policy_turn: dict[str, Turn] = {}  # rep.policy id -> the turn it reacted in
    ear_text: dict[str, str] = {}  # rep.ear id -> the heard text
    mouth: list[tuple[Json, Json]] = []
    skipped = 0
    persona = sha256_text(task.counterparty.persona.strip())
    for e in b.events:
        p = e.payload
        if e.type == "utt.delivered" and p["lane"] == "cp":
            deliveries.append(e)
        elif e.type == "rep.ear":
            utt = by_id[e.cause_ids[0]]
            if utt.type != "utt.delivered" or utt.payload["lane"] != "cp":
                skipped += 1
                continue
            end = next(i for i, d in enumerate(deliveries) if d is utt) + 1
            lines = [_s(d.payload, "text_heard") for d in deliveries[taken:end]]
            taken = end
            heard = Heard(utt.event_id, " ".join(t for t in lines if t), utt.t_ms)
            turn = turns.get(call := _s(p, "call_id"))
            if turn is None:
                calls = [by_id[c].payload for c in e.cause_ids[1:]]
                start = min(cast(int, c["t_start"]) for c in calls)
                made = [
                    {"ref": r, "terms": t, "open": r not in closed}
                    for r, t in offers.items()
                ]
                turn = turns[call] = Turn(made, start, e.t_ms)
            turn.heard.append((heard, e.event_id))
            ear_turn[e.event_id], ear_text[e.event_id] = turn, heard.text
        elif e.type == "rep.policy":
            intent = cast(dict[str, object], p["intent"])
            kind, ref = intent["kind"], intent.get("offer_ref")
            if kind in ("offer", "final_offer") and isinstance(ref, str):
                offers[ref] = [list(kv) for kv in cast(list[list[str]], intent["say"])]
            elif kind in ("offer_expired", "confirmed") and isinstance(ref, str):
                closed.add(ref)
            if e.cause_ids and (turn := ear_turn.get(e.cause_ids[0])) is not None:
                turn.end_ms = max(turn.end_ms, e.t_ms)
                policy_turn[e.event_id] = turn
        elif e.type == "rep.mouth":
            policy = by_id[e.cause_ids[0]]
            if (turn := policy_turn.get(policy.event_id)) is not None:
                turn.end_ms = max(turn.end_ms, e.t_ms)
            ear = policy.cause_ids[0] if policy.cause_ids else ""
            calls = [by_id[c].payload for c in e.cause_ids[1:]]
            content = {
                "company": task.counterparty.company,
                "persona_sha": persona,
                "intent": p["intent"],
                "heard": ear_text.get(ear, ""),
            }
            occurrence = {
                "run_id": b.manifest.run_id,
                "event_id": e.event_id,
                "prompt_sha": calls[0]["prompt_sha"] if calls else None,
                "model": calls[-1]["requested_model"] if calls else None,
                "output": p["text"],
                "fidelity_ok": p.get("fidelity_ok"),
                "attempts": p.get("attempts"),
            }
            mouth.append((content, occurrence))
    return Walk(list(turns.values()), mouth, skipped)


def d1_blocks(turns: Sequence[Turn]) -> list[tuple[list[Heard], list[Json]]]:
    """ADR-0021 D1 on the recorded clock: a rep turn starts once the rep is free and
    an utterance is heard, takes every utterance heard by then (in delivery order),
    and lasts as long as the recorded turn of its first utterance. Each block keeps
    the offers made before its first utterance."""
    heard = [(h, t) for t in turns for h, _ in t.heard]
    blocks: list[tuple[list[Heard], list[Json]]] = []
    free, i = -1, 0
    while i < len(heard):
        first, turn = heard[i]
        start = max(first.sent_ms, free)
        j = i + 1
        while j < len(heard) and heard[j][0].sent_ms <= start:
            j += 1
        blocks.append(([h for h, _ in heard[i:j]], turn.offers))
        free, i = start + (turn.end_ms - turn.start_ms), j
    return blocks


# ---------------------------------------------------------------- items


class Pool:
    """Items deduplicated on a key, each with its occurrences."""

    def __init__(self) -> None:
        self.items: dict[str, Json] = {}

    def add(self, content: Json, shown: Json, occurrence: Json) -> None:
        iid = item_id(content)
        item = self.items.setdefault(iid, {"item_id": iid, **shown, "occurrences": []})
        item["occurrences"].append(occurrence)

    def done(self) -> list[Json]:
        out: list[Json] = []
        for iid in sorted(self.items):
            item = self.items[iid]
            item["occurrences"].sort(key=canonical_json)
            item["count"] = len(item["occurrences"])
            out.append(item)
        return out


def names_a_ref(texts: Iterable[str], task: Task, refs: Iterable[str] = ()) -> bool:
    """An utterance says an offer ref (the family's ladder, or one the item lists).
    The rep never voices a ref (``mouth.fidelity_ok``), so live callers hear none:
    such items are off-distribution and scored apart."""
    known = {o.offer_ref.casefold() for o in task.counterparty.ladder}
    known |= {r.casefold() for r in refs}
    return any(r in t.casefold() for t in texts for r in known)


def _ear_item(
    pool: Pool, task: Task, offers: list[Json], block: list[Heard], source: Json
) -> None:
    company, keys = task.counterparty.company, list(task.counterparty.identity)
    context: Json = {"company": company, "identity_keys": keys, "offers": offers}
    said = [norm(h.text) for h in block]
    content = context | {"utterances": said}
    shown = {"kind": "single" if len(block) == 1 else "block", **context}
    shown["off_distribution"] = names_a_ref(said, task)
    pool.add(content, shown, source | {"heard": [h.event_id for h in block]})


def _representative(items: list[Json]) -> None:
    """Show each Ear item with the smallest raw text among its occurrences."""
    for item in items:
        item["utterances"] = min(o.pop("text") for o in item["occurrences"])


def _simuser(b: Bundle) -> Iterator[tuple[Json, Json]]:
    groups: dict[str, list[Event]] = {}
    for e in b.events:
        if e.type == "llm.call" and e.payload["role"] == "simuser":
            groups.setdefault(_s(e.payload, "call_id").rsplit(":", 1)[0], []).append(e)
    replies = {c: e for e in b.events if e.type == "user.sim" for c in e.cause_ids}
    for calls in groups.values():
        prompt = _s(calls[0].payload, "prompt_sha")
        sim = next((replies[c.event_id] for c in calls if c.event_id in replies), None)
        output: Json = {"silent": True}
        if sim is not None:
            keys = ("text", "revealed", "stop")
            output = {k: sim.payload[k] for k in keys if k in sim.payload}
        yield (
            {"prompt_sha": prompt},
            {
                "run_id": b.manifest.run_id,
                "llm_calls": [c.event_id for c in calls],
                "response_shas": [c.payload["response_sha"] for c in calls],
                "model": calls[-1].payload["requested_model"],
                "output": output,
            },
        )


def _cap(items: list[Json]) -> tuple[list[Json], dict[str, int]]:
    """At most TRIVIAL_CAP unique items per trivial intent, by a seeded draw."""
    uncapped: dict[str, int] = {}
    for kind in TRIVIAL:
        mine = sorted(i["item_id"] for i in items if i["intent"]["kind"] == kind)
        uncapped[kind] = len(mine)
        if len(mine) > TRIVIAL_CAP:
            keep = random.Random(f"{CAP_SEED}:{kind}").sample(mine, TRIVIAL_CAP)
            drop = set(mine) - set(keep)
            items = [i for i in items if i["item_id"] not in drop]
    return items, uncapped


ADDED = frozenset(
    {"item_id", "name", "constructed", "kind", "company", "identity_keys"}
    | {"off_distribution"}
)


def constructed(path: Path) -> tuple[Json, Json]:
    """Constructed items, their fields as given, flagged ``constructed``; the id is
    the sha of the item as given without its own id, which is kept as ``name``. Ear
    items (``family``, ``offers`` {ref: terms}, ``open_offers``, ``block``, ``gold``)
    also get the family's company and identity keys. The file's other top-level
    keys are returned as its meta."""
    raw = cast(Json, json.loads(path.read_text("utf-8")))
    out: Json = {r: [] for r in ROLES}
    for role in ROLES:
        for c in cast(list[Json], raw.get(role, [])):
            if clash := (set(c) - {"item_id"}) & ADDED:
                raise SystemExit(f"constructed {c.get('item_id')}: reserved {clash}")
            given = {k: v for k, v in c.items() if k != "item_id"}
            iid = item_id(given | {"constructed": True})
            item = {"item_id": iid, "name": c.get("item_id"), "constructed": True}
            if role == "ear":
                task = load_task(c["family"])
                item["kind"] = "single" if len(c["block"]) == 1 else "block"
                item["company"] = task.counterparty.company
                item["identity_keys"] = list(task.counterparty.identity)
                named = names_a_ref(c["block"], task, c["offers"])
                item["off_distribution"] = named
            out[role].append(item | given)
    made = {k: sorted(v, key=lambda i: i["item_id"]) for k, v in out.items()}
    return made, {k: v for k, v in raw.items() if k not in ROLES}


def freeze(runs: Path, extra: Path | None = None) -> Json:
    ear, mouth, sim = Pool(), Pool(), Pool()
    bundles: list[Json] = []
    skipped = {"bundles_not_train": 0, "bundles_not_real_http": 0}
    skipped["bundles_task_instance_differs"] = 0
    skipped["ear_not_cp_delivered"] = 0
    skipped_runs: dict[str, list[str]] = {}
    for b, events_sha in sorted(load(runs), key=lambda x: x[0].manifest.run_id):
        m = b.manifest
        reality = {role: kind.value for role, kind in sorted(m.reality.items())}
        why = ""
        if m.split != "train":
            why = "bundles_not_train"
        elif any(m.reality.get(r) is not AdapterKind.REAL_HTTP for r in REAL_ROLES):
            why = "bundles_not_real_http"
        elif instance_hash(task_of(m.task_ref)) != m.instance_hash:
            why = "bundles_task_instance_differs"  # the YAML moved since the run
        if why:
            skipped[why] += 1
            skipped_runs.setdefault(why, []).append(m.run_id)
            continue
        task, eligible = task_of(m.task_ref), descends(m.git_sha)
        report = evidence_check(b, "offline")
        bundles.append(
            {
                "run_id": m.run_id,
                "events_sha256": events_sha,
                "task_ref": m.task_ref,
                "git_sha": m.git_sha,
                "task_instance_matches": True,  # else skipped above
                "simuser_eligible": eligible,
                "reality": reality,
                "evidence_check": {"ok": report.ok, "failures": list(report.failures)},
            }
        )
        w = walk(b, task)
        skipped["ear_not_cp_delivered"] += w.not_delivered
        for turn in w.turns:
            for h, ear_ev in turn.heard:
                source = {"run_id": m.run_id, "rep_ear": ear_ev, "text": [h.text]}
                _ear_item(ear, task, turn.offers, [h], source)
        for block, offers in d1_blocks(w.turns):
            if len(block) > 1:
                source = {"run_id": m.run_id, "text": [h.text for h in block]}
                _ear_item(ear, task, offers, block, source)
        for content, occurrence in w.mouth:
            mouth.add(content, content, occurrence)
        for content, occurrence in _simuser(b) if eligible else ():
            sim.add(content, content, occurrence)
    ears = ear.done()
    _representative(ears)
    mouths, uncapped = _cap(mouth.done())
    sims = sim.done()
    made, meta = constructed(extra) if extra else (dict[str, Any](), dict[str, Any]())
    made = {role: cast(list[Json], made.get(role, [])) for role in ROLES}
    ids = [i["item_id"] for i in (*ears, *mouths, *sims)]
    ids += [i["item_id"] for role in ROLES for i in made[role]]

    def tally(items: Iterable[Json]) -> Json:
        items = list(items)
        return {"unique": len(items), "occurrences": sum(i["count"] for i in items)}

    def off(items: Iterable[Json]) -> int:
        return sum(1 for i in items if i["off_distribution"])

    failing = [b["run_id"] for b in bundles if not b["evidence_check"]["ok"]]

    def only_failing(items: Iterable[Json]) -> int:
        """Items every occurrence of which is in a bundle that fails the check."""
        runs = [{o["run_id"] for o in i["occurrences"]} for i in items]
        return sum(1 for r in runs if r <= set(failing))

    counts = {
        "recorded": {
            "ear_single": tally(i for i in ears if i["kind"] == "single"),
            "ear_block": tally(i for i in ears if i["kind"] == "block"),
            "ear_off_distribution": off(ears),
            "mouth": tally(mouths) | {"trivial_uncapped": uncapped},
            "simuser": tally(sims),
        },
        "constructed": {role: len(made[role]) for role in ROLES}
        | {"ear_off_distribution": off(made["ear"])},
    }
    return {
        "schema": SCHEMA,
        "eligibility": ELIGIBILITY,
        "mouth_reuse": MOUTH_REUSE,
        "bundles": bundles,
        "skipped": skipped,
        "skipped_runs": skipped_runs,
        "counts": counts,
        "evidence_check": {
            "mode": "offline",
            "rule": "disclosed, not a filter",
            "failing_bundles": failing,
            "items_only_from_failing_bundles": {
                "ear_single": only_failing(i for i in ears if i["kind"] == "single"),
                "ear_block": only_failing(i for i in ears if i["kind"] == "block"),
                "mouth": only_failing(mouths),
                "simuser": only_failing(sims),
            },
        },
        "root_hash": sha256_text("\n".join(sorted(ids))),
        "items": {"ear": ears, "mouth": mouths, "simuser": sims},
        "constructed": made,
        "constructed_meta": meta,
    }


# ---------------------------------------------------------------- export

ACTS: tuple[str, ...] = get_args(Act)


def blind(item: Json, pos: int) -> Json:
    """Exactly what the Ear sees, structured; nothing else (an allow-list)."""
    if item.get("constructed"):  # offers {ref: terms} + open_offers, and a block
        opened = set(item["open_offers"])
        offers = [
            {"ref": r, "terms": dict(t), "open": r in opened}
            for r, t in cast(dict[str, dict[str, str]], item["offers"]).items()
        ]
        said = cast(list[str], item["block"])
    else:
        offers = [
            {"ref": o["ref"], "terms": dict(o["terms"]), "open": o["open"]}
            for o in item["offers"]
        ]
        said = cast(list[str], item["utterances"])
    utterances = [{"n": n, "text": t} for n, t in enumerate(said, 1)]
    return {
        "pos": pos,
        "company": item["company"],
        "identity_keys": list(item["identity_keys"]),
        "offers": offers,
        "utterances": utterances,
        "accept_available": bool(offers),
        "acts": [a for a in ACTS if offers or a != "accept"],
        "labels": [None] * len(utterances),
    }


def export(doc: Json, out_dir: Path, key_out: Path, batch: int, seed: int) -> Json:
    if not 1 <= batch <= MAX_BATCH:
        raise SystemExit(f"--batch must be 1..{MAX_BATCH}, got {batch}")
    if key_out.resolve().is_relative_to(out_dir.resolve()):
        raise SystemExit(f"--key-out {key_out} is inside --out-dir {out_dir}")
    made = cast(list[Json], doc["constructed"]["ear"])
    streams = {
        "batch": list(doc["items"]["ear"]),
        "check": [i for i in made if i.get("gold")],
        "constructed": [i for i in made if not i.get("gold")],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    key: Json = {"seed": seed, "batch_size": batch, "root_hash": doc["root_hash"]}
    key["batches"] = {}
    for prefix, items in streams.items():
        order = sorted(items, key=lambda i: i["item_id"])
        random.Random(f"{seed}:{prefix}").shuffle(order)
        for k, at in enumerate(range(0, len(order), batch), 1):
            name, chunk = f"{prefix}-{k:03d}", order[at : at + batch]
            body = {"batch": name, "items": [blind(i, p) for p, i in enumerate(chunk)]}
            _write(out_dir / f"{name}.json", body)
            key["batches"][name] = [i["item_id"] for i in chunk]
    key_out.parent.mkdir(parents=True, exist_ok=True)
    _write(key_out, key)
    return key


def _write(path: Path, doc: object) -> None:
    text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, "utf-8")


# ---------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["run"]:  # PR2a, in its own module (which imports this one)
        from scripts.mod import world_select_run

        return world_select_run.main(argv[1:])
    if argv[:1] == ["gold"]:  # PR2b, in its own module (which imports this one)
        from scripts.mod import world_select_score

        return world_select_score.main(argv[1:])
    ap = argparse.ArgumentParser(prog="python -m scripts.mod.world_select")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze", help="freeze the items from the train bundles")
    f.add_argument("--runs", type=Path, default=Path("runs"))
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--constructed", type=Path)
    x = sub.add_parser("export", help="write blind Ear annotation batches")
    x.add_argument("--items", type=Path, required=True)
    x.add_argument("--out-dir", type=Path, required=True)
    x.add_argument("--key-out", type=Path, required=True, help="outside --out-dir")
    x.add_argument("--batch", type=int, default=MAX_BATCH)
    x.add_argument("--seed", type=int, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "freeze":
        doc = freeze(args.runs, args.constructed)
        _write(args.out, doc)
        summary = {"counts": doc["counts"], "root_hash": doc["root_hash"]}
    else:
        doc = cast(Json, json.loads(args.items.read_text("utf-8")))
        key = export(doc, args.out_dir, args.key_out, args.batch, args.seed)
        summary = {"batches": len(key["batches"]), "root_hash": key["root_hash"]}
    json.dump(summary | {"skipped": doc.get("skipped")}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
