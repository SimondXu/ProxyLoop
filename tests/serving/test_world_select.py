"""World-model selection data, PR1 (S1-MOD-09): offline, no model call. Bundles come
from whole fake sessions (tests/support/sessions, a scripted world) and from hand-built
rep logs whose clock is set by the test (a constructed backlog, as in
tests/env/test_backlog.py)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from tests.kernel.test_session import SCRIPTS, UNTIL
from tests.support.sessions import run

from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS
from proxyloop.contract.events import Event
from scripts.mod import world_select as ws

Json = dict[str, Any]
OFFER = [["monthly_price", "75.00"], ["term_months", "12"]]
FINAL = [["monthly_price", "68.00"], ["term_months", "24"]]
MADE: dict[str, tuple[str | None, list[list[str]]]] = {
    "offer": ("loyal-1", OFFER),
    "final_offer": ("loyal-2", FINAL),
}


@pytest.fixture(scope="module")
def sessions(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two fake sessions with the same scripts: the same heard lines twice. Their
    manifests say real_http for every role, as freeze requires (the only way a
    test bundle reaches the item set)."""
    root = tmp_path_factory.mktemp("runs")
    for name in ("a", "b"):
        run(root / name, SCRIPTS, until=UNTIL)
        d = run_dir(root, name)
        roles = {*manifest(d)["reality"], *ws.REAL_ROLES}
        rewrite(d, reality=dict.fromkeys(sorted(roles), "real_http"))
    return root


def run_dir(root: Path, name: str) -> Path:
    (d,) = (root / name).iterdir()
    return d


def manifest(d: Path) -> Json:
    return json.loads((d / MANIFEST).read_text("utf-8"))


def rewrite(d: Path, **update: object) -> None:
    (d / MANIFEST).write_text(json.dumps(manifest(d) | update), "utf-8")


class Log:
    """A hand-built rep log on a test-set clock (the events SimRep and the kernel
    emit, ADR-0021)."""

    def __init__(self, run_id: str) -> None:
        self.run_id, self.events = run_id, list[Event]()
        self.root = self.emit("user.msg", "kernel", {"text": "start"}, [], 0)

    def emit(
        self, type_: str, actor: str, payload: Json, causes: Sequence[str], t: int
    ) -> str:
        seq = len(self.events)
        stream = "world" if actor.startswith("world.") else "agent"
        e = Event.model_validate(
            {
                "run_id": self.run_id,
                "seq": seq,
                "event_id": f"{self.run_id}:{seq}",
                "t_ms": t,
                "wall": datetime(2026, 9, 28, tzinfo=UTC),
                "type": type_,
                "actor": actor,
                "stream": stream,
                "cause_ids": list(causes),
                "epoch": 0,
                "payload": payload,
            }
        )
        self.events.append(e)
        return e.event_id

    def say(self, text: str, t: int, heard: str | None = None) -> str:
        said = text if heard is None else heard
        payload: Json = {"lane": "cp", "utt_id": f"u{len(self.events)}"}
        payload |= {"text_generated": text, "text_heard": said}
        payload["interrupted"] = said != text
        return self.emit("utt.delivered", "kernel", payload, [self.root], t)

    def call(self, role: str, cause: str, t_start: int, t_end: int) -> str:
        ref = {"kind": "test_fake", "endpoint": None, "model_id": f"{role}-fake"}
        record = {
            "call_id": f"{role}:{cause}:0",
            "role": role,
            "model_ref": ref,
            "adapter_kind": "test_fake",
            "requested_model": f"{role}-fake",
            "served_model_echo": None,
            "request_id": None,
            "prompt_sha": hashlib.sha256(f"{role}{cause}".encode()).hexdigest(),
            "response_sha": None,
            "usage": None,
            "t_start": t_start,
            "t_first_token": None,
            "t_end": t_end,
            "finish_reason": "stop",
            "attempt": 0,
        }
        return self.emit("llm.call", f"world.{role}", record, [cause], t_end)

    def turn(self, heard: Sequence[str], start: int, end: int, *kinds: str) -> None:
        """One rep turn over a heard block: one Ear call, a rep.ear per utterance,
        then a decision per kind (an offer makes loyal-1, a final offer loyal-2)
        and its line."""
        call = self.call("ear", heard[-1], start, start + 10)
        ears = [
            self.emit(
                "rep.ear",
                "world.ear",
                {"utt_id": h, "act": "other", "args": {}, "call_id": f"ear:{call}"},
                [h, call],
                start + 10,
            )
            for h in heard
        ]
        for kind in kinds:
            ref, say = MADE.get(kind, (None, []))
            intent = {"kind": kind, "offer_ref": ref, "say": say, "ask": []}
            policy = self.emit(
                "rep.policy",
                "world.policy",
                {"from": "OFFER", "to": "OFFER", "rung": None, "intent": intent},
                [ears[-1]],
                start + 20,
            )
            mouth = self.call("mouth", policy, start + 20, end)
            line = {"intent": intent, "text": kind, "fidelity_ok": True, "attempts": 1}
            self.emit("rep.mouth", "world.mouth", line, [policy, mouth], end)

    def expire(self, t: int) -> None:
        intent: Json = {"kind": "offer_expired", "offer_ref": "loyal-1"}
        intent |= {"say": [], "ask": []}
        payload: Json = {"from": "OFFER", "to": "OFFER", "rung": 0, "intent": intent}
        self.emit("rep.policy", "world.policy", payload, [], t)

    def write(self, root: Path, like: Path) -> Path:
        d = root / self.run_id
        d.mkdir(parents=True)
        (d / MANIFEST).write_text(json.dumps(manifest(like) | {"run_id": self.run_id}))
        (d / EVENTS).write_text(
            "".join(e.model_dump_json() + "\n" for e in self.events)
        )
        (d / PROMPTS).write_text("")
        return d


def backlog(run_id: str = "r-backlog") -> Log:
    """Recorded one turn at a time (pre-ADR-0021): U2 and U3 are heard while U1's
    turn is in flight, U4 long after; U1's turn makes loyal-1, which lapses, and
    U2's turn makes loyal-2."""
    log = Log(run_id)
    u1 = log.say("Can you lower the price?", 0)
    u2 = log.say("Could you read back", 300)
    u2b = log.say("every term of it?", 350)  # the same delivery: joined
    u3 = log.say("And is that final?", 600)
    log.turn([u1], 10, 1000, "offer")
    log.turn([u2b], 1000, 2000, "final_offer")
    log.turn([u3], 2000, 2500, "no_better")
    log.expire(4000)
    u4 = log.say("We", 5000, heard="")  # cut before a word: nothing heard
    u4b = log.say("Can  you LOWER the price?", 5000)
    log.turn([u4b], 5000, 5500, "no_better")
    assert u2 and u4
    return log


def ear_items(doc: Json, kind: str) -> list[Json]:
    return [i for i in doc["items"]["ear"] if i["kind"] == kind]


def test_freeze_is_deterministic_to_the_byte(sessions: Path, tmp_path: Path) -> None:
    one, two = tmp_path / "one.json", tmp_path / "two.json"
    ws.main(["freeze", "--runs", str(sessions), "--out", str(one)])
    ws.main(["freeze", "--runs", str(sessions), "--out", str(two)])
    assert one.read_bytes() == two.read_bytes()
    doc = json.loads(one.read_text("utf-8"))
    ids = sorted(i["item_id"] for role in ws.ROLES for i in doc["items"][role])
    assert doc["root_hash"] == hashlib.sha256("\n".join(ids).encode()).hexdigest()
    for b in doc["bundles"]:
        (d,) = [p for p in sessions.glob(f"*/{b['run_id']}")]
        assert (
            b["events_sha256"] == hashlib.sha256((d / EVENTS).read_bytes()).hexdigest()
        )
    assert all(
        i["item_id"] == ws.item_id(_ear_content(i)) for i in ear_items(doc, "single")
    )


def _ear_content(item: Json) -> Json:
    keys = ("company", "identity_keys", "offers")
    return {k: item[k] for k in keys} | {
        "utterances": list(map(ws.norm, item["utterances"]))
    }


def test_the_same_heard_line_is_one_item_with_every_occurrence(
    sessions: Path, tmp_path: Path
) -> None:
    both = ws.freeze(sessions)
    shutil.copytree(run_dir(sessions, "a"), tmp_path / "a")
    alone = ws.freeze(tmp_path)
    singles = ear_items(both, "single")
    assert singles and len(singles) == len(ear_items(alone, "single"))
    for item in singles:  # the disclosure and the ask, heard in both runs
        runs = {o["run_id"] for o in item["occurrences"]}
        assert item["count"] == len(item["occurrences"]) == 2 == len(runs)
    assert both["counts"]["recorded"]["ear_single"] == {
        "unique": len(singles),
        "occurrences": 2 * len(singles),
    }
    log = backlog()  # "Can you lower the price?" twice, once shouted and spaced
    log.write(tmp_path / "hand", run_dir(sessions, "a"))
    doc = ws.freeze(tmp_path / "hand")
    lower = [
        i for i in ear_items(doc, "single") if "lower" in i["utterances"][0].lower()
    ]
    assert len(lower) == 2  # the same text, but loyal-1 open vs lapsed: two contexts
    assert {len(i["offers"]) for i in lower} == {0, 2}
    same = Log("r-same")  # the same text in the same context: one item
    u1 = same.say("Can you lower the price?", 0)
    same.turn([u1], 10, 100, "clarify")
    u2 = same.say(" can  you LOWER\nthe price?", 200)
    same.turn([u2], 210, 300, "clarify")
    same.write(tmp_path / "same", run_dir(sessions, "a"))
    (item,) = ws.freeze(tmp_path / "same")["items"]["ear"]
    assert item["count"] == 2 and [o["heard"] for o in item["occurrences"]] == [
        [u1],
        [u2],
    ]
    assert item["utterances"] == [" can  you LOWER\nthe price?"]  # the least raw text


def test_blocks_are_rebuilt_as_adr_0021_d1_groups_them(
    sessions: Path, tmp_path: Path
) -> None:
    log = backlog()
    log.write(tmp_path, run_dir(sessions, "a"))
    doc = ws.freeze(tmp_path)
    singles = {tuple(i["utterances"]): i for i in ear_items(doc, "single")}
    assert set(singles) == {
        ("Can you lower the price?",),
        ("Could you read back every term of it?",),  # one delivery, joined
        ("And is that final?",),
        ("Can  you LOWER the price?",),  # the cut line added nothing
    }
    (block,) = ear_items(doc, "block")  # U2, U3: heard while U1's turn ran
    assert block["utterances"] == [
        "Could you read back every term of it?",
        "And is that final?",
    ]
    # ADR-0021 D2: the offers made before its FIRST utterance, not loyal-2, which
    # U2's own turn made (a block never lists what it unlocked)
    assert block["offers"] == [{"ref": "loyal-1", "terms": OFFER, "open": True}]
    u3 = singles[("And is that final?",)]["offers"]  # heard alone: after loyal-2
    assert [o["ref"] for o in u3] == ["loyal-1", "loyal-2"]
    lapsed = singles[("Can  you LOWER the price?",)]["offers"]
    assert lapsed == [
        {"ref": "loyal-1", "terms": OFFER, "open": False},
        {"ref": "loyal-2", "terms": FINAL, "open": True},
    ]
    assert singles[("Can you lower the price?",)]["offers"] == []  # made after it
    assert doc["counts"]["recorded"]["ear_block"] == {"unique": 1, "occurrences": 1}


def test_a_recorded_block_replays_to_itself(sessions: Path, tmp_path: Path) -> None:
    """Post-ADR-0021 logs: one Ear call for U2 and U3; the replay keeps the block."""
    log = Log("r-block")
    u1 = log.say("Can you lower the price?", 0)
    u2 = log.say("Could you read back every term?", 300)
    u3 = log.say("And is that final?", 600)
    log.turn([u1], 10, 1000, "offer")
    log.turn([u2, u3], 1000, 2000, "readback", "no_better")
    b = ws.load(log.write(tmp_path, run_dir(sessions, "a")).parent)[0][0]
    walk = ws.walk(b, ws.task_of(b.manifest.task_ref))
    assert [len(t.heard) for t in walk.turns] == [1, 2]
    blocks = [[h.event_id for h in hs] for hs, _ in ws.d1_blocks(walk.turns)]
    assert blocks == [[u1], [u2, u3]]
    heard = [m["heard"] for m, _ in walk.mouth]  # each line answers its utterance
    assert heard == [
        "Can you lower the price?",
        "And is that final?",
        "And is that final?",
    ]


def test_a_sealed_test_path_is_refused_and_non_train_bundles_are_skipped(
    sessions: Path, tmp_path: Path
) -> None:
    sealed = tmp_path / "s4" / "test"
    shutil.copytree(run_dir(sessions, "a"), sealed / "run")
    with pytest.raises(SystemExit):
        ws.freeze(sealed)
    dev = tmp_path / "s4" / "dev"
    shutil.copytree(run_dir(sessions, "b"), dev)
    rewrite(dev, split="dev")
    doc = ws.freeze(tmp_path)  # the sealed run inside is never opened either
    assert doc["skipped"]["bundles_not_train"] == 1
    assert doc["bundles"] == [] and doc["items"] == {
        "ear": [],
        "mouth": [],
        "simuser": [],
    }


def test_a_bundle_not_real_http_for_a_fast_or_world_role_is_skipped(
    sessions: Path, tmp_path: Path
) -> None:
    for role in ws.REAL_ROLES:
        d = tmp_path / role
        shutil.copytree(run_dir(sessions, "a"), d)
        rewrite(d, reality=manifest(d)["reality"] | {role: "test_fake"})
    shutil.copytree(run_dir(sessions, "b"), tmp_path / "missing")
    reality = manifest(tmp_path / "missing")["reality"]
    rewrite(
        tmp_path / "missing", reality={k: v for k, v in reality.items() if k != "ear"}
    )
    doc = ws.freeze(tmp_path)
    assert doc["skipped"]["bundles_not_real_http"] == len(ws.REAL_ROLES) + 1
    assert doc["bundles"] == [] and all(not doc["items"][r] for r in ws.ROLES)
    kept = ws.freeze(sessions)["bundles"]  # all real_http: kept, reality recorded
    assert [b["reality"]["ear"] for b in kept] == ["real_http", "real_http"]


def test_the_offline_evidence_check_is_disclosed_not_a_filter(
    sessions: Path, tmp_path: Path
) -> None:
    backlog().write(tmp_path, run_dir(sessions, "a"))  # no session.started: fails
    shutil.copytree(run_dir(sessions, "a"), tmp_path / "a")
    doc = ws.freeze(tmp_path)
    status = {b["run_id"]: b["evidence_check"] for b in doc["bundles"]}
    assert not status["r-backlog"]["ok"]
    assert (
        "the log does not open with session.started" in status["r-backlog"]["failures"]
    )
    summary = doc["evidence_check"]
    assert "r-backlog" in summary["failing_bundles"] and summary["mode"] == "offline"
    from_backlog = [  # still items: disclosed, never dropped
        i
        for i in doc["items"]["ear"]
        if {o["run_id"] for o in i["occurrences"]} == {"r-backlog"}
    ]
    assert len(from_backlog) == 5
    failing = summary["items_only_from_failing_bundles"]
    assert failing["ear_single"] + failing["ear_block"] >= 5


def test_simuser_items_only_from_runs_after_9e4e796(
    sessions: Path, tmp_path: Path
) -> None:
    doc = ws.freeze(sessions)
    assert doc["items"]["simuser"] and all(
        b["simuser_eligible"] for b in doc["bundles"]
    )
    old = tmp_path / "old"
    shutil.copytree(run_dir(sessions, "a"), old)
    parent = subprocess.run(
        ["git", "rev-parse", f"{ws.SIMUSER_SINCE}^"],
        cwd=ws.REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    rewrite(old, git_sha=parent)
    doc = ws.freeze(tmp_path)
    assert doc["items"]["simuser"] == [] and doc["items"]["mouth"]
    assert not doc["bundles"][0]["simuser_eligible"]


def test_trivial_mouth_intents_are_capped_by_a_seeded_draw() -> None:
    items = [{"item_id": f"{n:04d}", "intent": {"kind": "ok_hold"}} for n in range(20)]
    items += [{"item_id": "x", "intent": {"kind": "offer"}}]
    kept, uncapped = ws._cap(items)  # pyright: ignore[reportPrivateUsage]
    assert len(kept) == ws.TRIVIAL_CAP + 1 and uncapped["ok_hold"] == 20
    assert kept == ws._cap(items)[0]  # pyright: ignore[reportPrivateUsage]


BLIND_KEYS = {
    "pos",
    "company",
    "identity_keys",
    "offers",
    "utterances",
    "accept_available",
    "acts",
    "labels",
}


def strings(value: Any) -> Iterator[str]:
    """Every key and string value in a JSON document."""
    if isinstance(value, dict):
        for k, v in cast(Json, value).items():
            yield k
            yield from strings(v)
    elif isinstance(value, list):
        for v in cast(list[Any], value):
            yield from strings(v)
    elif isinstance(value, str):
        yield value


def test_the_export_carries_what_the_ear_sees_and_nothing_else(
    sessions: Path, tmp_path: Path
) -> None:
    log = backlog()
    log.write(tmp_path / "runs", run_dir(sessions, "a"))
    doc = ws.freeze(tmp_path / "runs")
    key = ws.export(doc, tmp_path / "out", 25, seed=3)
    (body,) = [
        json.loads((tmp_path / "out" / f"{name}.json").read_text("utf-8"))
        for name in key["batches"]
    ]
    assert set(body) == {"batch", "items"}
    run_ids = {b["run_id"] for b in doc["bundles"]}
    for item in body["items"]:
        assert set(item) == BLIND_KEYS
        assert (
            set(item["offers"][0]) == {"ref", "terms", "open"}
            if item["offers"]
            else True
        )
        assert (
            item["accept_available"]
            == ("accept" in item["acts"])
            == bool(item["offers"])
        )
        texts = set(strings(item))
        assert not texts & run_ids and not any("fake" in s or ":" in s for s in texts)
    by_pos = {tuple(u["text"] for u in i["utterances"]): i for i in body["items"]}
    block = by_pos[("Could you read back every term of it?", "And is that final?")]
    assert block["offers"] == [{"ref": "loyal-1", "terms": dict(OFFER), "open": True}]


ACCEPT: Json = {
    "item_id": "c-ear-001",
    "tag": "accept",
    "family": "cp-direct-discount",
    "offers": {"loyal-1": dict(OFFER)},
    "open_offers": ["loyal-1"],
    "block": ["Okay, we'll go ahead with loyal-1.", "Dana Reyes, 4821."],
    "gold": [{"act": "accept", "offer_ref": "loyal-1"}, {"act": "provide_fact"}],
    "why": "accept by ref",
}
HELLO: Json = {  # no gold: exported apart from the check batches
    "item_id": "c-ear-002",
    "tag": "smalltalk",
    "family": "x-out-of-envelope-approval",
    "offers": {},
    "open_offers": [],
    "block": ["Hello?"],
    "why": "an opener",
}
MOUTH: Json = {
    "item_id": "c-mouth-001",
    "family": "cp-direct-discount",
    "intent": "offer",
    "offer_ref": "loyal-1",
    "ask": [],
    "say": dict(OFFER),
    "heard": "Brightwave's got it for 60.",
    "template": "I can offer you this: monthly price: 75.00; term: 12 months.",
    "note": "must not say the ref",
}


def test_constructed_items_are_flagged_and_kept_apart(
    sessions: Path, tmp_path: Path
) -> None:
    made: Json = {"conventions": {"offers": "said terms only"}, "findings": ["F1"]}
    made |= {"ear": [ACCEPT, HELLO], "mouth": [MOUTH]}
    (tmp_path / "made.json").write_text(json.dumps(made), "utf-8")
    shutil.copytree(run_dir(sessions, "a"), tmp_path / "runs" / "a")
    doc = ws.freeze(tmp_path / "runs", tmp_path / "made.json")
    assert doc["counts"]["constructed"] == {
        "ear": 2,
        "mouth": 1,
        "simuser": 0,
        "ear_off_distribution": 1,
    }
    assert doc["constructed_meta"] == {k: made[k] for k in ("conventions", "findings")}
    assert all(i["constructed"] for r in ws.ROLES for i in doc["constructed"][r])
    assert not any(i.get("constructed") for r in ws.ROLES for i in doc["items"][r])
    by_name = {i["name"]: i for r in ws.ROLES for i in doc["constructed"][r]}
    for given in (ACCEPT, HELLO, MOUTH):  # every given field, as given
        item = by_name[given["item_id"]]
        assert {k: item[k] for k in given if k != "item_id"} == {
            k: v for k, v in given.items() if k != "item_id"
        }
    assert by_name["c-ear-001"]["off_distribution"]  # it names loyal-1
    assert not by_name["c-ear-002"]["off_distribution"]
    assert by_name["c-ear-002"]["company"] == "Crestline Wireless"
    key = ws.export(doc, tmp_path / "out", 25, seed=0)
    assert set(key["batches"]) == {"batch-001", "check-001", "constructed-001"}
    check = json.loads((tmp_path / "out" / "check-001.json").read_text("utf-8"))
    (item,) = check["items"]
    assert set(item) == BLIND_KEYS and item["labels"] == [None, None]  # gold withheld
    assert item["company"] == "Northwind Mobile" and item["accept_available"]
    assert item["offers"] == [{"ref": "loyal-1", "terms": dict(OFFER), "open": True}]
    assert "accept by ref" not in set(strings(item))  # nor its tag, why or gold
    recorded = {i["item_id"] for i in doc["items"]["ear"]}
    assert set(key["batches"]["batch-001"]) == recorded


def test_batches_and_their_order_are_seeded(sessions: Path, tmp_path: Path) -> None:
    backlog().write(tmp_path / "runs", run_dir(sessions, "a"))
    doc = ws.freeze(tmp_path / "runs")
    ears = {i["item_id"] for i in doc["items"]["ear"]}
    assert len(ears) == 5

    def order(seed: int, out: str) -> list[str]:
        key = ws.export(doc, tmp_path / out, 1, seed)
        assert all(len(ids) <= 1 for ids in key["batches"].values())
        return [i for ids in key["batches"].values() for i in ids]

    assert sorted(order(5, "x")) == sorted(ears)
    assert order(5, "x") == order(5, "y")
    x, y = sorted((tmp_path / "x").iterdir()), sorted((tmp_path / "y").iterdir())
    assert [p.read_bytes() for p in x] == [p.read_bytes() for p in y]
    seeds = {tuple(order(s, f"s{s}")) for s in range(8)}
    assert len(seeds) > 1  # the seed moves the order
    with pytest.raises(SystemExit):
        ws.export(doc, tmp_path / "z", ws.MAX_BATCH + 1, 0)
