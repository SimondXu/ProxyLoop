"""World-model selection, PR2b-2 (S1-MOD-09): the scores, the blind Mouth judge batches
and the report, on hand-built items, gold and rows; every expected number is computed
by hand in the comments."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, cast

import pytest

from proxyloop.contract.base import sha256_text
from scripts.mod import world_select as ws
from scripts.mod import world_select_report as wr
from scripts.mod import world_select_run as wsr
from scripts.mod import world_select_score as sc

Json = dict[str, Any]
INC, CAND = "teamrouter:gemini-3.8-flash@low", "teamrouter:deepseek-flash@low"
ECHO = {INC: "gemini-3.8-flash", CAND: "deepseek-v4-1-flash-260910"}
E1, E2, E3, E4, E5, E6 = (f"e{n}" * 32 for n in range(1, 7))
M1, M2, M3, S1, S2 = ("m1" * 32, "m2" * 32, "m3" * 32, "s1" * 32, "s2" * 32)
# RUBRIC_TEXT: a fixture copy of docs/decisions/data/world-select-mouth-rubric.md
# (committed on #257's branch); its sha256 is checked against wr.RUBRIC_SHA below.
RUBRIC_TEXT = (
    "# Mouth judge rubric v1 (world-model selection, S1-MOD-09, ADR-0"
    '024)\n\nThe judge sees one simulated customer-service rep line ("t'
    'he output"), together with what the rep was asked to say:\n- `int'
    "ent`: the policy's speech act for this turn (e.g. offer, readbac"
    "k, ask_identity, ok_hold, no_better, confirmed, hang_up);\n- `say"
    "`: the terms the rep must state, with their values (absence term"
    's such as "no fee" or "no change" included);\n- `ask`: the one th'
    "ing the rep may ask the caller for, if any;\n- `heard`: what the "
    "caller said this turn (context only).\n\nThe judge never sees whic"
    "h model wrote the output. Judge each criterion independently and"
    " answer true (satisfied) or false (violated). If the criterion d"
    "oes not apply (e.g. `say` is empty for M2), answer true.\n\n- **M1"
    " (speech act):** the output performs the same speech act as `int"
    "ent` (an offer is an offer, a read-back reads back, a hold ackno"
    "wledgement acknowledges the hold, a hang-up ends the call).\n- **"
    "M2 (terms stated):** every `say` term is stated with its value, "
    'including absence terms ("no activation fee", "no service change'
    's"). A value may be phrased naturally (e.g. "seventy-five dollar'
    's a month" for monthly_price 75.00) but must be the same value.\n'
    "- **M3 (nothing invented):** the output states no term, price, f"
    "ee, perk, date or commitment that is not in `say`, and contradic"
    "ts none that is.\n- **M4 (no extra request):** the output asks th"
    "e caller for nothing beyond `ask` (no extra questions, no reques"
    "ts for other information).\n- **M5 (form):** at most two spoken s"
    'entences, and no meta-text (no "As a rep…", stage directions, qu'
    "otation marks around the whole line, or explanations of the task"
    ').\n\nOutput per record: {"record": <id>, "M1": bool, "M2": bool, '
    '"M3": bool, "M4": bool, "M5": bool, "note": "≤ 20 words, only wh'
    'en any is false"}.\nA line is "no-violation" when all five are tr'
    "ue.\n"
)


def items() -> Json:
    def occ(run: str) -> list[Json]:
        return [{"run_id": run}]

    ear: list[Json] = [
        {"item_id": E1, "count": 3, "occurrences": occ("r1"),
         "utterances": ["Can you do better?"]},
        {"item_id": E2, "count": 1, "occurrences": occ("r1"),
         "utterances": ["We accept save-1 at 60."]},
        {"item_id": E3, "count": 1, "occurrences": occ("r2"),
         "utterances": ["One moment.", "Hmm."]},
    ]  # fmt: skip
    made_ear: list[Json] = [
        {"item_id": E4, "constructed": True, "block": ["Hi there."]},
        {"item_id": E5, "constructed": True, "block": ["Orbit quoted 62."],
         "off_distribution": True},
        {"item_id": E6, "constructed": True, "block": ["Orbit is sixty."]},
    ]  # fmt: skip
    offer: Json = {"kind": "offer", "offer_ref": "save-1", "ask": []}
    mouth: list[Json] = [
        {"item_id": M1, "occurrences": occ("r1"), "heard": "Any deal?",
         "intent": offer | {"say": [["monthly_price", "75.00"]]}},
        {"item_id": M2, "occurrences": occ("r2"), "heard": "Anything else?",
         "intent": offer | {"say": [["term_months", "12"]]}},
    ]  # fmt: skip
    made_mouth: list[Json] = [
        {"item_id": M3, "constructed": True, "intent": "confirm_accept",
         "offer_ref": "keep-1", "ask": [], "heard": "Okay.",
         "say": {"term_months": "12", "monthly_price": "76.00"}},
    ]  # fmt: skip
    ids = [E1, E2, E3, E4, E5, E6, M1, M2, M3, S1, S2]
    return {
        "root_hash": sha256_text("\n".join(sorted(ids))),
        "items": {"ear": ear, "mouth": mouth, "simuser": [{"item_id": S1}]},
        "constructed": {
            "ear": made_ear,
            "mouth": made_mouth,
            "simuser": [{"item_id": S2, "constructed": True}],
        },
    }


def gold_label(item_id: str, idx: int, act: str, **kw: Any) -> Json:
    base: Json = {"offer_ref": None, "price_usd": None, "facts": []}
    base["source"] = "annotator"
    base |= {"codebook_version": "v1.1", "excluded": act == "excluded"}
    return {"item_id": item_id, "idx": idx, "act": act} | base | kw


GOLD = [
    gold_label(E1, 1, "ask_discount"),
    gold_label(E2, 1, "accept", offer_ref="save-1", price_usd=60),
    gold_label(E3, 1, "hold_request"),
    gold_label(E3, 2, "other"),
    gold_label(E4, 1, "smalltalk", source="constructed", codebook_version=None),
    gold_label(E5, 1, "cite_competitor", price_usd=62, source="constructed"),
    gold_label(E6, 1, "excluded", source="constructed", codebook_version=None),
]


def attempt(acts: list[Json] | None, valid: bool, ms: int, arm: str) -> Json:
    raw = [{"name": "classify", "arguments": json.dumps({"acts": acts or []})}]
    use = {"prompt_tokens": 100, "completion_tokens": 10, "reasoning_tokens": 0}
    rec = {"latency_ms": ms, "echo": ECHO[arm], "usage": use, "error": None}
    return {"n": 0, "raw": raw, "valid": valid, "records": [rec]}


def a(*names: str, **kw: Any) -> list[Json]:
    return [{"act": n} | kw for n in names]


def row(arm: str, role: str, iid: str, status: str, result: Any, **kw: Any) -> Json:
    out = {
        "schema": wsr.ROW_SCHEMA,
        "arm": arm,
        "items_root_hash": items()["root_hash"],
    }
    out |= {"model_ref": {"model_id": arm.split(":")[1].split("@")[0]}}
    out |= {"role": role, "item_id": iid, "status": status, "result": result}
    return out | {"repeat": 1, "attempts": list[Json]()} | kw


def ear(arm: str, iid: str, acts: list[Json] | None, ms: int, **kw: Any) -> Json:
    """An ok row (valid first attempt) with ``acts``; None: exhausted, all invalid."""
    if acts is None:
        tries = [attempt(None, False, ms, arm) for _ in range(3)]
        return row(arm, "ear", iid, "exhausted", None, attempts=tries, **kw)
    tries = [attempt(acts, True, ms, arm)]
    return row(arm, "ear", iid, "ok", {"acts": acts}, attempts=tries, **kw)


def mouth(arm: str, iid: str, status: str, ok: bool = True) -> Json:
    result = {"text": f"Line {iid[:2]}.", "fidelity_ok": ok, "fallback": not ok}
    return row(arm, "mouth", iid, status, result if status == "ok" else None)


def rows() -> dict[str, list[Json]]:
    return {
        INC: [
            ear(INC, E1, a("ask_discount"), 100),
            ear(INC, E2, a("accept", offer_ref="save-1", price_usd=60.0), 200),
            ear(INC, E3, a("hold_request", "smalltalk"), 300),
            ear(INC, E3, a("hold_request", "other"), 400, repeat=2),
            ear(INC, E4, a("other"), 500),
            ear(INC, E5, a("cite_competitor", price_usd=62), 600),
            ear(INC, E6, a("other"), 700),
            mouth(INC, M1, "ok"),
            mouth(INC, M2, "ok"),
            mouth(INC, M3, "ok", ok=False),  # exhausted: the template
            row(INC, "simuser", S1, "ok", {"reply": {"text": "Hi"}}, check="full"),
            row(INC, "simuser", S2, "not_replayable", None),
        ],
        CAND: [
            ear(CAND, E1, None, 100),
            ear(CAND, E2, a("other"), 200),
            ear(CAND, E3, a("hold_request", "other"), 300),
            ear(CAND, E4, a("accept"), 400),
            row(CAND, "ear", E5, "timeout", None),
            ear(CAND, E6, a("other"), 600),
            mouth(CAND, M1, "ok"),
            mouth(CAND, M2, "timeout"),
            mouth(CAND, M3, "ok"),
            row(CAND, "simuser", S1, "exhausted", None, check="full"),
            row(CAND, "simuser", S2, "not_replayable", None),
        ],
    }


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    doc = items()
    (tmp_path / "items.json").write_text(json.dumps(doc))
    book = tmp_path / "codebook.md"
    book.write_text("# Ear labelling codebook v1.2\n")
    gold = {"version": 1, "items_root_hash": doc["root_hash"], "labels": GOLD}
    gold["codebook_sha256"] = hashlib.sha256(book.read_bytes()).hexdigest()
    (tmp_path / "gold.json").write_text(json.dumps(gold))
    for arm, lines in rows().items():
        text = "".join(json.dumps(r) + "\n" for r in lines)
        (tmp_path / f"{arm.split(':')[1]}.jsonl").write_text(text)
    (tmp_path / "rubric.md").write_text(RUBRIC_TEXT, "utf-8")
    return tmp_path


def args(t: Path, cmd: str = "score", *extra: str) -> list[str]:
    out = [cmd, "--items", str(t / "items.json"), "--rows"]
    out += [str(p) for p in sorted(t.glob("*.jsonl"))]
    if cmd == "judge-export":
        return [*out, "--rubric", str(t / "rubric.md"), *extra]
    sha = hashlib.sha256((t / "gold.json").read_bytes()).hexdigest()
    out += ["--gold", str(t / "gold.json"), "--gold-sha", sha, "--resamples", "2000"]
    return [*out, "--codebook", str(t / "codebook.md"), *extra]


def scores(t: Path, *extra: str) -> Json:
    ns = wr.parser().parse_args(args(t, "score", *extra))
    judged = wr.judged_labels(ns.judge_key, ns.judge_dir) if ns.judge_dir else None
    return wr.score(ns, judged)


def rate(k: int, n: int, lo: float, hi: float) -> Json:
    return {"k": k, "n": n, "rate": round(k / n, 4), "ci95": [lo, hi]}


def test_ear_accuracy_harm_weights_errors(tree: Path) -> None:
    doc = scores(tree)
    inc, cand = doc["arms"][INC]["ear"], doc["arms"][CAND]["ear"]
    # Recorded, 4 utterances. Incumbent: E3's 2nd says smalltalk for other (one class).
    assert inc["recorded"]["cc_accuracy"] == rate(4, 4, 0.5101, 1.0)
    assert inc["recorded"]["exact_accuracy"] == rate(3, 4, 0.3006, 0.9544)
    # Weights 3, 1, 1, 1 (E1 occurs 3 times): exact misses 1 of 6 -> 5/6.
    assert inc["recorded"]["weighted"] == {"cc_accuracy": 1.0, "exact": 0.8333}
    # Candidate: E1 exhausted (wrong), E2 other for accept (wrong), E3 right.
    assert cand["recorded"]["cc_accuracy"] == rate(2, 4, 0.15, 0.85)
    assert cand["recorded"]["weighted"]["cc_accuracy"] == 0.3333  # 2 of 6
    assert (cand["recorded"]["exhausted"], cand["recorded"]["timeout"]) == (1, 0)
    assert cand["recorded"]["harm"]["accept"] == {"fp": 0, "fn": 1}
    assert inc["recorded"]["harm"]["accept"] == {"fp": 0, "fn": 0}  # a true positive
    assert cand["recorded"]["first_attempt_valid"] == rate(2, 3, 0.2077, 0.9385)
    assert cand["recorded"]["block_size_first_attempt"] == rate(1, 1, 0.2065, 1.0)
    per = inc["recorded"]["per_class"]
    assert per["other"]["recall"] == rate(0, 1, 0.0, 0.7935)
    assert per["other"]["precision"] == {"k": 0, "n": 0, "rate": None, "ci95": None}
    assert per["hold_request"]["recall"] == rate(1, 1, 0.2065, 1.0)
    args_ = inc["recorded"]["arguments"]  # 60.0 is 60
    assert (args_["offer_ref"]["k"], args_["price_usd"]["k"]) == (1, 1)
    assert cand["recorded"]["arguments"]["offer_ref"]["n"] == 0  # its act was wrong
    assert inc["recorded"]["stability"] == rate(1, 2, 0.0945, 0.9055)  # E3 again
    # Constructed: E4 smalltalk; E6 excluded is left out.
    assert inc["constructed"]["cc_accuracy"]["k"] == 1
    assert inc["constructed"]["exact_accuracy"]["k"] == 0
    assert (inc["constructed"]["utterances"], inc["constructed"]["excluded"]) == (1, 1)
    assert cand["constructed"]["harm"]["accept"] == {"fp": 1, "fn": 0}
    # Off-distribution: E5; the candidate timed out, a harm-class negative.
    assert cand["off_distribution"]["cc_accuracy"]["k"] == 0
    assert cand["off_distribution"]["timeout"] == 1
    assert cand["off_distribution"]["harm"]["cite_competitor"] == {"fp": 0, "fn": 1}
    assert inc["off_distribution"]["arguments"]["price_usd"]["k"] == 1


def test_paired_bootstrap(tree: Path) -> None:
    pair = scores(tree)["paired"][CAND]
    # Recorded clusters: r1 = E1 + E2 (-2 over 2), r2 = E3 (0 over 2): -2/4. A
    # resample is r1r1 (-1), r2r2 (0) or mixed (-0.5): the CI is [-1, 0].
    assert pair["ear_cc_accuracy"]["recorded"] == {
        "units": 3, "clusters": 2, "estimate": -0.5, "ci95": [-1.0, 0.0]
    }  # fmt: skip
    # Constructed: E4 (-1 over 1); E6 has no scored utterance.
    assert pair["ear_cc_accuracy"]["constructed"]["ci95"] == [-1.0, -1.0]
    assert pair["mouth_fidelity_ok"]["recorded"]["estimate"] == -0.5  # M2 timed out
    assert pair["mouth_fidelity_ok"]["constructed"]["ci95"] == [1.0, 1.0]
    one = sc.bootstrap([("a", 1, 2), ("b", 3, 2)], seed=5, resamples=50)
    assert one == sc.bootstrap([("a", 1, 2), ("b", 3, 2)], seed=5, resamples=50)
    assert one["estimate"] == 1.0 and one["ci95"] == [0.5, 1.5]  # 1/2 and 3/2


def test_mouth_simuser_calls(tree: Path) -> None:
    arms = scores(tree)["arms"]
    inc, cand = arms[INC], arms[CAND]
    assert inc["mouth"]["recorded"]["fidelity_ok"] == rate(2, 2, 0.3424, 1.0)
    assert inc["mouth"]["constructed"]["fallback"] == rate(1, 1, 0.2065, 1.0)
    assert cand["mouth"]["recorded"]["timeout"] == 1
    assert inc["simuser"]["recorded"]["valid_full_check"]["k"] == 1
    assert cand["simuser"]["recorded"]["exhausted"] == 1
    assert cand["simuser"]["constructed"]["not_replayable"] == 1
    assert inc["simuser"]["recorded"]["invented_numbers"] is None  # no --runs
    # Ear latencies 100..700 ms: p50 the 4th, p95 the 7th.
    assert inc["latency_ms"]["ear"] == {"n": 7, "p50": 400, "p95": 700}
    assert inc["tokens"]["ear"]["prompt_tokens"] == 700
    assert (inc["echoes"], cand["echoes"]) == ([ECHO[INC]], [ECHO[CAND]])
    assert inc["cost_usd"] is None
    item = {"item_id": S1}
    reply = {"reply": {"text": "I pay 70, maybe 65."}}
    one = row(INC, "simuser", S1, "ok", reply, check="full")
    arm = sc.Arm(INC, {}, {(S1, "simuser", 1): one})
    got = wr.simuser_metrics([item], arm, {S1: "limit: 70"})["invented_numbers"]
    assert (got["k"], got["n"], got["numbers"]) == (1, 1, 1)  # 65


def test_refusals(tree: Path) -> None:
    with pytest.raises(SystemExit, match="not --gold-sha"):
        wr.score(wr.parser().parse_args([*args(tree)[:-2], "--gold-sha", "0" * 64]))
    lines = (tree / "deepseek-flash@low.jsonl").read_text().splitlines()
    kept = [x for x in lines if M2 not in x]
    (tree / "deepseek-flash@low.jsonl").write_text("\n".join(kept) + "\n")
    with pytest.raises(SystemExit, match="1 mouth items have no row"):
        scores(tree)
    (tree / "codebook.md").write_text("edited\n")
    with pytest.raises(SystemExit, match="not the gold's"):
        scores(tree)
    doc = items()
    doc["items"]["ear"][0]["item_id"] = "f" * 64
    (tree / "items.json").write_text(json.dumps(doc))
    with pytest.raises(SystemExit, match="the items hash to"):
        scores(tree)


def test_judge_export_is_blind(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert hashlib.sha256(RUBRIC_TEXT.encode()).hexdigest() == wr.RUBRIC_SHA
    out, key = tree / "batches", tree / "key" / "key.json"
    with pytest.raises(SystemExit, match="inside --out-dir"):
        ws.main(args(tree, "judge-export", "--out-dir", str(out), "--key-out",
                      str(out / "k.json"), "--seed", "1"))  # fmt: skip
    ws.main(args(tree, "judge-export", "--out-dir", str(out), "--key-out", str(key),
                  "--seed", "1", "--batch", "3"))  # fmt: skip
    summary = json.loads(capsys.readouterr().out)
    # Exported: the incumbent's M1, M2 and the candidate's M1, M3.
    assert summary == {"batches": 2, "records": 4,
                       "not_exported": {"fallback": 1, "timeout": 1}}  # fmt: skip
    records: list[Json] = []
    for f in sorted(out.glob("*.json")):
        text, body = f.read_text(), json.loads(f.read_text())
        assert set(body) == {"batch", "rubric", "rubric_sha256", "records"}
        assert body["rubric"] == RUBRIC_TEXT
        for leak in ("gemini", "deepseek", "teamrouter", M1, M2, M3, "offer_ref"):
            assert leak not in text
        records += body["records"]
    assert all(set(r) == set(wr.SHOWN) for r in records)
    made = next(r for r in records if r["intent"] == "confirm_accept")
    assert made["say"] == [["monthly_price", "76.00"], ["term_months", "12"]]
    meta = json.loads(key.read_text())["records"]
    assert {m["arm"] for m in meta.values()} == {INC, CAND}
    labels = [{"record": r["record"], "note": ""} for r in records]
    for lab in labels:  # every candidate record breaks M5
        lab |= {m: meta[lab["record"]]["arm"] == INC or m != "M5" for m in sc.JUDGED}
    (tree / "judged").mkdir()
    (tree / "judged" / "out.json").write_text(json.dumps(labels))
    got = scores(tree, "--judge-dir", str(tree / "judged"), "--judge-key", str(key))
    cand = got["arms"][CAND]["mouth"]["recorded"]["judged"]
    assert (cand["M5"]["n"], cand["M5"]["k"], cand["no_violation"]["k"]) == (1, 0, 0)
    inc = got["arms"][INC]["mouth"]["recorded"]["judged"]
    assert inc["M1"] == rate(2, 2, 0.3424, 1.0)
    (tree / "rubric.md").write_text(RUBRIC_TEXT + "x", "utf-8")
    with pytest.raises(SystemExit, match="not the rubric's"):
        ws.main(args(tree, "judge-export", "--out-dir", str(out), "--key-out",
                      str(key), "--seed", "1"))  # fmt: skip


def numbers(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {n for v in cast(Json, value).values() for n in numbers(v)}
    if isinstance(value, list):
        return {n for v in cast(list[Any], value) for n in numbers(v)}
    ok = isinstance(value, int | float) and not isinstance(value, bool)
    return {str(value)} if ok else set()


def test_report_md_numbers_are_the_json(tree: Path) -> None:
    out, md = tree / "report.json", tree / "report.md"
    ws.main(args(tree, "report", "--out", str(out), "--out-md", str(md)))
    doc, text = json.loads(out.read_text()), md.read_text()
    assert "not a claim; the user decides" in text
    assert re.fullmatch(r"[0-9a-f]{40}", doc["git_sha"])
    assert md.read_text() == wr.render(doc) + "\n"
    known = numbers(doc)
    rows_ = [
        r for r in text.splitlines() if r.startswith("| ") and "| metric |" not in r
    ]
    assert len(rows_) > 50
    for r in rows_:
        cells = [c.strip() for c in r.strip("|").split("|")]
        if cells[0] == "echoes":
            continue
        for c in cells[1:]:
            assert set(re.findall(r"-?\d+(?:\.\d+)?", c)) <= known, (r, c)
    ear = next(r for r in rows_ if r.startswith("| cc_accuracy |"))  # recorded first
    assert "| 1.0 [0.5101, 1.0] (4/4) |" in ear and "0.5 [0.15, 0.85] (2/4)" in ear
