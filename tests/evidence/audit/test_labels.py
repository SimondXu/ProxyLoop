"""The label store is append-only, with rater and timestamp."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from proxyloop.evidence.audit.__main__ import main
from proxyloop.evidence.audit.labels import LabelStore


def _store(tmp_path: Path) -> LabelStore:
    ticks = iter(range(100))
    return LabelStore(
        tmp_path / "labels.jsonl",
        now=lambda: datetime(2026, 9, 30, 12, 0, next(ticks), tzinfo=UTC),
    )


def test_rows_carry_rater_and_timestamp_and_only_grow(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = tmp_path / "labels.jsonl"
    first = store.append("i1", "root", "accept")
    snapshot = path.read_bytes()
    store.append("i1", "user", "decline")
    assert path.read_bytes().startswith(snapshot)  # the old bytes are untouched
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    assert rows[0] == {
        "item_id": "i1", "rater": "root", "label": "accept", "ts": first.ts,
    }  # fmt: skip
    assert rows[0]["ts"] == "2026-09-30T12:00:00.000+00:00"
    assert rows[1]["ts"] > rows[0]["ts"] and rows[1]["rater"] == "user"


def test_a_relabel_is_a_new_row_and_the_latest_counts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append("i1", "root", "accept")
    store.append("i1", "root", "other")
    assert len(store.rows()) == 2
    assert store.latest()["i1"]["root"].label == "other"


def test_disagreements_are_items_where_both_latest_labels_differ(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    for item, rater, label in [
        ("i1", "root", "accept"), ("i1", "user", "accept"),
        ("i2", "root", "accept"), ("i2", "user", "decline"),
        ("i3", "root", "accept"),  # not yet labelled by the user
        ("i4", "root", "accept"), ("i4", "user", "decline"),
        ("i4", "root", "decline"),  # the root came round
        ("i5", "root", "accept"), ("i5", "user", "accept"),
        ("i5", "user", "other"),  # the user's newer label differs
    ]:  # fmt: skip
        store.append(item, rater, label)
    assert store.disagreements() == ["i2", "i5"]


def test_only_the_two_raters_and_known_labels(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="rater"):
        store.append("i1", "intern", "accept")
    with pytest.raises(ValueError, match="label"):
        store.append("i1", "user", "acept")
    assert store.rows() == []


def test_there_is_no_overwrite_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public = {n for n in dir(LabelStore) if not n.startswith("_")}
    assert public == {"append", "rows", "latest", "disagreements"}
    modes: list[str] = []
    real = Path.open

    def spy(self: Path, mode: str = "r", *a: Any, **k: Any) -> Any:
        modes.append(mode)
        return real(self, mode, *a, **k)

    monkeypatch.setattr(Path, "open", spy)
    store = _store(tmp_path)
    store.append("i1", "user", "accept")
    store.append("i1", "user", "decline")
    store.rows()
    assert modes.count("a") == 2 and set(modes) == {"a", "r"}  # append or read


def test_a_corrupt_row_is_an_error_not_skipped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append("i1", "user", "accept")
    with (tmp_path / "labels.jsonl").open("a") as f:
        f.write("not json\n")
    with pytest.raises(ValueError, match=r"labels\.jsonl:2"):
        store.rows()


def test_the_cli_appends_only_sampled_items(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    frame = tmp_path / "f.json"
    frame.write_text(
        json.dumps(
            {
                "schema": "pl.ear_audit_frame/1",
                "items": [
                    {"item_id": "s1", "sampled": True},
                    {"item_id": "n1", "sampled": False},
                ],
            }
        ),
        "utf-8",
    )
    store = str(tmp_path / "l.jsonl")
    base = ["label-append", store, "--frame", str(frame), "--rater", "user"]
    assert main([*base, "--item", "s1", "--label", "accept"]) == 0
    assert main([*base, "--item", "n1", "--label", "accept"]) == 2
    assert main(["label-append", store, "--frame", str(frame), "--rater", "root",
                 "--item", "s1", "--label", "decline"]) == 0  # fmt: skip
    capsys.readouterr()
    assert main(["disagreements", store]) == 0
    assert capsys.readouterr().out.split() == ["s1"]
