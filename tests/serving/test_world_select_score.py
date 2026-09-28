"""World-model selection, PR2b-1 (S1-MOD-09): the Ear gold file, on hand-built items,
keys, labels and review sheet (no real annotation data)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from proxyloop.contract.base import sha256_text
from scripts.mod import world_select as ws
from scripts.mod import world_select_score as wss

Json = dict[str, Any]
A, B, C, D, E = ("a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64)
B_SAID = ["One moment please.", "Please read back every term of save-1."]
C_SAID = ["We'll take it at 60."]
OFFER = [{"open": True, "ref": "save-1", "terms": [["monthly_price", "78.00"]]}]


def items() -> Json:
    ear: list[Json] = [
        {"item_id": A, "kind": "single", "count": 2, "offers": [],
         "utterances": ["Can you do better on the price?"]},
        {"item_id": B, "kind": "block", "count": 1, "offers": OFFER,
         "utterances": B_SAID},
        {"item_id": E, "kind": "single", "count": 1, "offers": [],
         "utterances": ["Is there anything else?"]},
    ]  # fmt: skip
    made: list[Json] = [
        {"item_id": C, "constructed": True, "block": C_SAID, "offers": {},
         "gold": [{"act": "accept", "offer_ref": "save-1", "price_usd": 60,
                   "alternates": [{"act": "other"}]}]},
        {"item_id": D, "constructed": True, "block": ["Brightwave is sixty a month."],
         "offers": {}, "gold": [{"act": "excluded"}]},
    ]  # fmt: skip
    root = sha256_text("\n".join(sorted([A, B, C, D, E])))
    empty: dict[str, list[Json]] = {"mouth": [], "simuser": []}
    return {"root_hash": root, "items": {"ear": ear, **empty},
            "constructed": {"ear": made, **empty}}  # fmt: skip


def lab(batch: str, pos: int, idx: int, act: str, **kw: Any) -> Json:
    return {"batch": batch, "pos": pos, "idx": idx, "act": act, "confidence": 4} | kw


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Items, codebook, keys, labels (batch-001: v1.0; batch-007: v1.1) and sheet."""
    doc = items()
    monkeypatch.setattr(wss, "ITEMS_ROOT", doc["root_hash"])
    book = tmp_path / "codebook.md"
    book.write_text("# Ear labelling codebook v1.2 (world-model selection)\n")
    monkeypatch.setattr(
        wss, "CODEBOOK_SHA", hashlib.sha256(book.read_bytes()).hexdigest()
    )
    batches = {"batch-001": [A], "batch-007": [B, E], "check-001": [D, C]}
    files: dict[str, Any] = {
        "items.json": doc,
        "key.json": {"root_hash": doc["root_hash"], "batches": batches},
        "adj-key.json": {"adj-001": [["batch-007", 0]]},
        "labels/batch-001.json": [
            lab("batch-001", 0, 1, "ask_discount", alternates=[{"act": "other"}])
        ],
        "labels/batch-007.json": [
            lab("batch-007", 0, 1, "hold_request"),
            lab("batch-007", 0, 2, "other"),
            lab("batch-007", 1, 1, "other"),
        ],
        "labels/adj-001.json": [
            lab("adj-001", 0, 1, "hold_request"),
            lab(
                "adj-001",
                0,
                2,
                "ask_readback",
                offer_ref="save-1",
                alternates=[{"act": "cite_competitor", "price_usd": 70}],
            ),
        ],
        "labels/check-001.json": [lab("check-001", 1, 1, "other")],  # never read
        "sheet.json": [
            {
                "id": 1,
                "adj": "adj-001",
                "pos": 0,
                "idx": 2,
                "orig": ["batch-007", 0],
                "text": B_SAID[1],
                "alternates": ["other", "cite_competitor"],
            },
            {
                "id": 2,
                "check": ["check-001", 1, 1],
                "text": C_SAID[0],
                "alternates": ["other"],
            },
        ],
    }
    for name, body in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(json.dumps(body))
    return tmp_path


def build(t: Path, decisions: list[Json] | None = None) -> Json:
    read = wss.read
    user = (decisions, read(t / "sheet.json")) if decisions is not None else ((), ())
    doc = wss.load_items(t / "items.json")
    keys = read(t / "key.json"), read(t / "adj-key.json")
    return wss.gold(doc, t / "labels", *keys, t / "codebook.md", *user)


def by_key(doc: Json) -> dict[tuple[str, int], Json]:
    return {(x["item_id"], x["idx"]): x for x in doc["labels"]}


def test_precedence_annotator_adjudicated_constructed(tree: Path) -> None:
    doc = build(tree)
    got = by_key(doc)
    assert (got[(A, 1)]["act"], got[(A, 1)]["source"]) == ("ask_discount", "annotator")
    assert got[(A, 1)]["codebook_version"] == "v1.0"  # batch-001
    assert (got[(E, 1)]["source"], got[(E, 1)]["codebook_version"]) == (
        "annotator",
        "v1.1",  # batch-007
    )
    assert (got[(B, 1)]["act"], got[(B, 1)]["source"]) == (
        "hold_request",
        "adjudicated",
    )
    adjudicated = got[(B, 2)]
    assert (adjudicated["act"], adjudicated["offer_ref"]) == ("ask_readback", "save-1")
    assert (adjudicated["source"], adjudicated["codebook_version"]) == (
        "adjudicated",
        "v1.2",
    )
    made = got[(C, 1)]
    assert (made["act"], made["price_usd"], made["source"]) == (
        "accept",
        60,
        "constructed",
    )
    assert made["codebook_version"] is None
    assert (got[(D, 1)]["act"], got[(D, 1)]["excluded"]) == ("excluded", True)
    assert not any(x["excluded"] for k, x in got.items() if k != (D, 1))
    assert doc["counts"] == {
        "by_source": {"constructed": 2, "annotator": 2, "adjudicated": 2},
        "excluded": 1,
        "items": 5,
        "labels": 6,
    }
    assert (doc["version"], doc["codebook_version"]) == (1, "v1.2")


def test_user_beats_adjudicated_and_constructed(tree: Path) -> None:
    decisions = [{"review_id": 1, "act": "other"}, {"review_id": 2, "act": "other"}]
    got = by_key(build(tree, decisions))
    for k in ((B, 2), (C, 1)):
        assert (got[k]["act"], got[k]["source"]) == ("other", "user")
        assert got[k]["codebook_version"] == "v1.2"
        assert (got[k]["offer_ref"], got[k]["price_usd"], got[k]["facts"]) == (
            None,
            None,
            [],
        )  # another act takes no argument of the label it replaces
    assert got[(A, 1)]["source"] == "annotator"


def one(t: Path, d: Json) -> Json:
    """The label review 1 decides, review 2 decided ``other``."""
    return by_key(build(t, [d, {"review_id": 2, "act": "other"}]))[(B, 2)]


def test_user_arguments(tree: Path) -> None:
    same = one(tree, {"review_id": 1, "act": "ask_readback"})
    assert (same["offer_ref"], same["source"]) == ("save-1", "user")  # kept
    alt = one(tree, {"review_id": 1, "act": "cite_competitor"})
    assert alt["price_usd"] == 70  # from the replaced label's alternate
    given = {"review_id": 1, "act": "cite_competitor", "price_usd": 65}
    assert one(tree, given)["price_usd"] == 65
    with pytest.raises(SystemExit, match=r"review_id 1 .*facts; review_id 2 .*price"):
        build(
            tree,
            [
                {"review_id": 1, "act": "provide_fact"},
                {"review_id": 2, "act": "cite_competitor"},
            ],
        )


def test_hash_refusals(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wss, "ITEMS_ROOT", "0" * 64)
    with pytest.raises(SystemExit, match="the items hash to"):
        build(tree)
    monkeypatch.setattr(wss, "ITEMS_ROOT", items()["root_hash"])
    book = tree / "codebook.md"
    book.write_text(book.read_text() + "edited\n")
    with pytest.raises(SystemExit, match="not the frozen"):
        build(tree)
    monkeypatch.setattr(
        wss, "CODEBOOK_SHA", hashlib.sha256(book.read_bytes()).hexdigest()
    )
    key = json.loads((tree / "key.json").read_text()) | {"root_hash": "1" * 64}
    (tree / "key.json").write_text(json.dumps(key))
    with pytest.raises(SystemExit, match="--batch-key is for the items"):
        build(tree)


BOTH = [{"review_id": 1, "act": "other"}, {"review_id": 2, "act": "other"}]


def test_mapping_refusals(tree: Path) -> None:
    sheet = get(tree, "sheet.json")
    put(tree, "sheet.json", [sheet[0], sheet[1] | {"check": ["batch-007", 0, 2]}])
    with pytest.raises(SystemExit, match="not its text, or twice"):  # one utterance
        build(tree, BOTH)
    put(tree, "sheet.json", [sheet[0] | {"text": "Something else."}, sheet[1]])
    with pytest.raises(SystemExit, match="not its text"):
        build(tree, BOTH)
    put(tree, "labels/batch-007.json", [lab("batch-007", 0, 1, "hold_request")])
    with pytest.raises(SystemExit, match="adjudicates no first-pass label"):
        build(tree)
    bad = [lab("batch-007", 0, 1, "haggle"), lab("batch-007", 0, 2, "other")]
    put(tree, "labels/batch-007.json", bad)
    with pytest.raises(SystemExit, match="unknown act 'haggle'"):
        build(tree)


def test_adjudication_covers_every_utterance(tree: Path) -> None:
    """A missing adj file refuses; it never falls back to the first pass."""
    (tree / "labels/adj-001.json").unlink()
    with pytest.raises(SystemExit, match="2 --adj-key utterances unadjudicated"):
        build(tree)
    put(tree, "labels/adj-001.json", [lab("adj-001", 0, 2, "other")])
    with pytest.raises(
        SystemExit, match="1 --adj-key utterances unadjudicated: adj-001"
    ):
        build(tree)


def test_every_review_id_decided_once(tree: Path) -> None:
    with pytest.raises(SystemExit, match="1 review ids not decided exactly once: 2"):
        build(tree, BOTH[:1])
    with pytest.raises(SystemExit, match="not decided exactly once: 1"):
        build(tree, [*BOTH, BOTH[0]])
    with pytest.raises(SystemExit, match="review_id 9 is not on the sheet"):
        build(tree, [*BOTH, {"review_id": 9, "act": "other"}])
    sheet = get(tree, "sheet.json")
    put(tree, "sheet.json", [*sheet, sheet[0]])
    with pytest.raises(SystemExit, match="lists an id twice"):
        build(tree, BOTH)


def cli(t: Path, out: Path | None, *more: str) -> list[str]:
    argv = ["gold", "--items", str(t / "items.json")]
    argv += ["--codebook", str(t / "codebook.md")]
    argv += ["--labels-dir", str(t / "labels")]
    argv += ["--batch-key", str(t / "key.json")]
    argv += ["--adj-key", str(t / "adj-key.json")]
    return argv + (["--out", str(out)] if out else []) + list(more)


def test_cli_deterministic(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def run(out: Path) -> Json:
        user = ["--user", str(tree / "user.json"), "--review", str(tree / "sheet.json")]
        ws.main(cli(tree, out, *user))
        return json.loads(capsys.readouterr().out)

    put(tree, "user.json", [BOTH[0] | {"act": "ask_readback"}, BOTH[1]])
    first, second = run(tree / "g1.json"), run(tree / "g2.json")
    text = (tree / "g1.json").read_bytes()
    assert text == (tree / "g2.json").read_bytes()
    assert first == second and first["sha256"] == hashlib.sha256(text).hexdigest()
    assert first["by_source"]["user"] == 2
    doc = json.loads(text)
    assert text.decode() == json.dumps(doc, indent=1, sort_keys=True) + "\n"
    assert doc["draft"] is False
    with pytest.raises(SystemExit, match="go together"):
        ws.main(["gold", "--labels-dir", "x", "--batch-key", "y", "--adj-key", "z",
                 "--user", "u"])  # fmt: skip


def put(t: Path, name: str, body: object) -> None:
    (t / name).write_text(json.dumps(body))


def get(t: Path, name: str) -> Any:
    return json.loads((t / name).read_text())


@pytest.mark.parametrize(
    ("pos", "idx", "bad"),
    [(-1, 1, "pos -1"), (True, 1, "pos True"), (0, 0, "idx 0"), (0, True, "idx True")],
)
def test_label_positions_refused(tree: Path, pos: Any, idx: Any, bad: str) -> None:
    """A pos of -1 would index batch-001's last item: another item's label."""
    put(tree, "labels/batch-001.json", [lab("batch-001", pos, idx, "other")])
    with pytest.raises(SystemExit, match=f"{bad}: not an int"):
        build(tree)


def test_sheet_positions_refused(tree: Path) -> None:
    sheet = get(tree, "sheet.json")
    put(tree, "sheet.json", [sheet[0], sheet[1] | {"check": ["check-001", -1, 1]}])
    with pytest.raises(SystemExit, match="check-001 pos -1: not an int"):
        build(tree, BOTH)
    put(tree, "sheet.json", [sheet[0], sheet[1] | {"check": ["check-001", 1, True]}])
    with pytest.raises(SystemExit, match="check idx True: not an int"):
        build(tree, BOTH)
    put(tree, "sheet.json", [sheet[0] | {"pos": -1}, sheet[1]])
    with pytest.raises(SystemExit, match="adj-001 pos -1: not an int"):
        build(tree, BOTH)
    put(tree, "sheet.json", [sheet[0] | {"idx": 0}, sheet[1]])
    with pytest.raises(SystemExit, match="review_id 1: idx 0: not an int"):
        build(tree, BOTH)


def test_batch_key_ids_unique(tree: Path) -> None:
    key = get(tree, "key.json")
    key["batches"]["batch-007"].append(A)
    put(tree, "key.json", key)
    with pytest.raises(SystemExit, match="lists 1 items twice"):
        build(tree)


def test_first_pass_label_twice_refused(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defence in depth behind the unique-id and position checks: two first-pass
    labels that land on one (item_id, idx) refuse, whatever produced them."""
    real = wss.read_labels

    class Twice(dict[tuple[str, int, int], Json]):
        def items(self) -> Any:
            return [*super().items(), *super().items()]

    def doubled(root: Path, prefix: str) -> dict[tuple[str, int, int], Json]:
        got = real(root, prefix)
        return Twice(got) if prefix == "batch" else got

    monkeypatch.setattr(wss, "read_labels", doubled)
    with pytest.raises(SystemExit, match="a second first-pass label for"):
        build(tree)


def test_cli_draft_only(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Without the user's decisions only a --draft writes, and never to GOLD."""
    with pytest.raises(SystemExit, match="needs --user and --review"):
        ws.main(cli(tree, tree / "g.json"))
    with pytest.raises(SystemExit, match="--draft never writes"):
        ws.main(cli(tree, None, "--draft"))
    with pytest.raises(SystemExit, match="--draft never writes"):
        ws.main(cli(tree, wss.GOLD, "--draft"))
    assert not (tree / "g.json").exists()
    ws.main(cli(tree, tree / "g.json", "--draft"))
    assert "user" not in json.loads(capsys.readouterr().out)["by_source"]
    assert get(tree, "g.json")["draft"] is True
