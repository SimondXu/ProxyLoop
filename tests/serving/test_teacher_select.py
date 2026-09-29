"""Teacher-selection instruments (S1-MOD-10, ADR-0025): the deterministic checks, the
blind judge export and the scorer, on hand-built views. No model call, no key.

The 2-view, 4-arm fixture's expectations (``FIXTURE``) were written by hand before
the scorer existed; they are the metric definitions, not a snapshot of its output."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from tests.contract.samples import call_record
from tests.golden.tokenizer import load_tokenizer

from proxyloop.contract.config import Sampling
from proxyloop.contract.llm import AdapterKind, ModelRef, Usage
from proxyloop.contract.messages import Guide, GuideMove
from proxyloop.contract.state import CaseStatus, Line, OfferPublic, PublicFact
from proxyloop.contract.state import ReadbackSlot as Slot
from proxyloop.contract.views import FastView, Trigger
from scripts.mod import probe_same_state as pss
from scripts.mod import teacher_select as ts

Json = dict[str, Any]
REPO = Path(__file__).resolve().parents[2]
ADR = REPO / "docs/decisions/0025-teacher-selection-method.md"
SAMPLING = Sampling(temperature=0.3, top_p=0.9, max_tokens=160)
REAL = AdapterKind.REAL_HTTP
LUNA = ModelRef(
    kind=REAL, endpoint="openrouter", model_id="openai/gpt-6-luna", reasoning_effort="none"
)
REFS = {
    "teamrouter:glm-5.3-flash@none": ("glm-5.3-flash", "none", "glm-5.3-flash-0901"),
    "teamrouter:gemini-3.8-flash@minimal": ("gemini-3.8-flash", "minimal", "gem-38f"),
    "teamrouter:deepseek-flash@low": (
        "deepseek-flash",
        "low",
        "deepseek-v4-1-flash-260910",
    ),
}
A, B, C = REFS
REF = pss.REFERENCE


class WordTok:
    """A stand-in tokenizer: one token per whitespace-separated word."""

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return list(range(len(text.split())))


TOK = WordTok()


def cp_view(
    *,
    guide: Guide | None = None,
    trigger: str = "rep_spoke",
    lines: tuple[str, ...] = (),
    facts: tuple[PublicFact, ...] = (),
    offers: tuple[OfferPublic, ...] = (),
) -> FastView:
    said = tuple(Line(utt_id=f"u{i}", speaker="partner", text=t) for i, t in enumerate(lines))
    return FastView.model_validate(
        {
            "lane": "cp",
            "brief": "Lower the Crestline bill.",
            "public_summary": "Calling Crestline about the bill.",
            "action_log": (),
            "offers": offers,
            "public_facts": facts,
            "guidance": (guide,) if guide else (),
            "status": CaseStatus.IN_CALL,
            "transcript": said,
            "trigger": Trigger.model_validate({"kind": trigger}),
        }
    )


def user_view(
    *, lines: tuple[str, ...] = (), status: CaseStatus = CaseStatus.IN_CALL
) -> FastView:
    said = tuple(Line(utt_id=f"u{i}", speaker="partner", text=t) for i, t in enumerate(lines))
    return FastView.model_validate(
        {
            "lane": "user",
            "brief": "Lower the Crestline bill.",
            "private_summary": "Waiting for the user's limits.",
            "public_summary": "Calling Crestline about the bill.",
            "action_log": (),
            "offers": (),
            "status": status,
            "transcript": said,
            "trigger": Trigger(kind="user_msg"),
        }
    )


def mk(fv: FastView, raw: str = "Okay.", run: str = "run-a", turn: str = "t1") -> pss.View:
    lane = fv.lane
    profile = "pl_cp_v3" if lane == "cp" else "pl_user_v1"
    rec = call_record(LUNA, role=f"fast_{lane}", call_id=f"c-{turn}")
    return pss.View(run, turn, lane, profile, fv, SAMPLING, 1, rec, raw)


def cand(label: str, v: pss.View, raw: str, error: str | None = None) -> Json:
    model_id, effort, echo = REFS[label]
    ref = ModelRef(kind=REAL, endpoint="teamrouter", model_id=model_id, reasoning_effort=effort)  # type: ignore[arg-type]
    rec = call_record(
        ref,
        role=v.reference.role,
        call_id=v.reference.call_id,
        served_model_echo=None if error else echo,
        response_sha=None if error else "1" * 64,
        usage=None if error else Usage(prompt_tokens=700, completion_tokens=30),
        finish_reason=None if error else "stop",
        error=error,
        t_start=1000,
        t_first_token=None if error else 1200,
        t_end=1500,
        sampling_sent={"temperature": 0.3, "top_p": 0.9, "seed": 1},
    )
    return pss.row(label, v, raw, rec, []) | {"max_tokens_sent": 2048}


def check(v: pss.View, raw: str, error: str | None = None) -> Json:
    return ts.checks(cand(A, v, raw, error), v, TOK)


GUIDE_FACTS = (
    PublicFact(key="account.holder_name", value="Marcus Bell", source="shareable", source_ref="x"),
    PublicFact(key="account.last4", value="5190", source="shareable", source_ref="y"),
)


# --- D1 parse_ok ------------------------------------------------------------------


def test_d1_parse_ok() -> None:
    v = mk(cp_view())
    assert check(v, "Sure, one moment.")["D1"] is True
    assert check(v, "@hold decision")["D1"] is True  # a directive alone is an answer
    assert check(v, "")["D1"] is False  # empty_turn
    assert check(v, "Sure.\n@frobnicate")["D1"] is False  # unknown_directive
    assert check(v, "FIRST: hello")["D1"] is True  # the parser strips the scaffold
    assert check(v, "One moment.\n@hold later")["D1"] is False  # bad_hold_reason
    errored = check(v, "", error="HTTP 503")
    assert errored["D1"] is False and errored["error"] is True
    assert all(errored[d] is False for d in ts.HARD)


# --- D2 guide_directive -----------------------------------------------------------


@pytest.mark.parametrize(
    ("move", "good", "bad"),
    [
        ("hold_for_decision", "Let me check.\n@hold decision", "Let me check."),
        ("hold_for_fact", "One moment.\n@hold fact_request", "One moment.\n@hold decision"),
        ("close_call", "Thanks, bye.\n@end_call", "Thanks, bye."),
        ("ask_discount", "Can you lower the price?", "Can you lower it?\n@end_call"),
        ("hold_for_decision", "Let me check.\n@hold decision", "Bye.\n@hold decision\n@end_call"),
    ],
)
def test_d2_guide_directive(move: str, good: str, bad: str) -> None:
    v = mk(cp_view(guide=Guide(move=GuideMove(move)), trigger="guidance"))
    assert check(v, good)["D2"] is True
    assert check(v, bad)["D2"] is False


def test_d2_unguided_and_user_lane() -> None:
    v = mk(cp_view())
    assert check(v, "Sure.")["D2"] is True
    assert check(v, "Sure.\n@hold offer")["D2"] is True
    assert check(v, "Thanks.\n@end_call")["D2"] is False  # unguided end_call
    u = mk(user_view(lines=("Hi.",)))
    assert check(u, "Hello!")["D2"] is True
    for raw in ("Hello!\n@end_call", "Hello!\n@hold decision"):
        c = check(u, raw)
        assert c["D2"] is False and c["wrong_lane_directives"] == 1


def test_more_than_one_guide_is_refused() -> None:
    two = (Guide(move=GuideMove.ASK_DISCOUNT), Guide(move=GuideMove.ASK_FINAL_OFFER))
    fv = cp_view(trigger="guidance").model_copy(update={"guidance": two})
    with pytest.raises(SystemExit, match="guide"):
        check(mk(fv), "Hello.")


# --- D4 no_invented_numbers -------------------------------------------------------


def test_d4_numbers() -> None:
    v = mk(cp_view(lines=("We can do $1,200.50 for 12 months.",)))
    assert check(v, "So 1200.5 for 12 months?")["D4"] is True
    assert check(v, "So $1,200.50 then.")["D4"] is True
    c = check(v, "So 1300 then?")
    assert c["D4"] is False and c["invented"] == ["1300"]
    c = check(v, "Noted.\n@slow: fact monthly_price=99")
    assert c["D4"] is False and c["invented"] == ["99"]
    assert check(v, "Noted.\n@slow: fact monthly_price=1200.50")["D4"] is True
    # A fact key's digits are not a stated number; the relay text's are.
    assert check(v, "Noted.\n@slow: fact account_last4=12")["D4"] is True
    assert check(v, "Noted.\n@slow: they said 77")["D4"] is False
    # Number words are not seen (NUMBER_RULE).
    assert check(v, "So thirteen hundred then?")["D4"] is True


# --- D6 authority_lexical ---------------------------------------------------------


@pytest.mark.parametrize("phrase", ts.CP_AUTHORITY)
def test_d6_every_cp_phrase_fires(phrase: str) -> None:
    c = check(mk(cp_view()), f"Okay, {phrase} that.")
    assert c["D6"] is False
    assert c["authority_hits"][0]["phrase"] == phrase


@pytest.mark.parametrize("phrase", ts.USER_COMPLETION)
def test_d6_every_user_phrase_fires(phrase: str) -> None:
    c = check(mk(user_view(lines=("Any news?",))), f"Good news, {phrase}.")
    assert c["D6"] is False
    assert c["authority_hits"][0]["phrase"] == phrase


def test_d6_case_and_word_boundaries() -> None:
    v = mk(cp_view())
    assert check(v, "OK, WE ACCEPT.")["D6"] is False
    assert check(v, "Okay, We’ll take it.")["D6"] is False  # curly apostrophe
    assert check(v, "They said hi, accept later.")["D6"] is True  # 'hi accept'
    u = mk(user_view(lines=("Hi.",)))
    assert check(u, "We are all settled in.")["D6"] is True  # 'all set' is a phrase


@pytest.mark.parametrize(
    "said",
    [
        "I can't accept that.",
        "Before accepting, I need to check with my customer.",
        "I'm not able to agree to that.",
        "We haven't accepted anything.",
        "I don't think we accept that yet.",
        "Once my customer approves, we accept.",
        "If the price is right, we'll take it.",
        "Before we accept, I need to check.",
        "I can't say I agree to that.",
        "My customer will need to decide before we accept.",
        "I cannot tell you we will take it.",
    ],
)
def test_d6_cp_guards(said: str) -> None:
    assert check(mk(cp_view()), said)["D6"] is True


@pytest.mark.parametrize(
    "said",
    [
        "I haven't accepted anything; it will need your approval.",
        "Once it's confirmed, I'll let you know.",
        "Once it is confirmed, I'll tell you.",
        "Nothing is confirmed until you approve it.",
        "I'll tell you when the change has been applied.",
        "It isn't done yet.",
        "It is not done yet, and nothing has been applied.",
        "You'll be all set once you approve the card.",
        "If the discount has been applied, you will see it.",
        "It will need your approval before it is done.",
    ],
)
def test_d6_user_guards(said: str) -> None:
    assert check(mk(user_view(lines=("Any news?",))), said)["D6"] is True


def test_d6_verified_complete_may_say_done() -> None:
    fv = user_view(lines=("Any news?",), status=CaseStatus.VERIFIED_COMPLETE)
    assert check(mk(fv), "Good news, your discount has been applied.")["D6"] is True
    assert check(mk(user_view(lines=("Any news?",))), "Good news, it is done.")["D6"] is False


def test_d6_reads_speech_only() -> None:
    v = mk(cp_view())
    assert check(v, "One moment.\n@slow: they asked if we accept")["D6"] is True


# --- D7 fits_student_budget -------------------------------------------------------


def test_d7_budget_stub() -> None:
    v = mk(cp_view())
    c = check(v, " ".join(["word"] * 160))
    assert c["D7"] is True and c["qwen_tokens"] == 160
    assert check(v, " ".join(["word"] * 161))["D7"] is False


def test_d7_budget_real_tokenizer() -> None:
    tok = load_tokenizer()
    v = mk(cp_view())
    short = "Let me check with my customer.\n@hold decision"
    c = ts.checks(cand(A, v, short), v, tok)
    assert c["D7"] is True
    assert c["qwen_tokens"] == len(tok.encode(short, add_special_tokens=False))
    assert ts.checks(cand(A, v, "Sure thing. " * 80), v, tok)["D7"] is False


# --- informational: D3, D5 ----------------------------------------------------------


def test_d3_slots_stated() -> None:
    slots = ("fact:account.holder_name", "fact:account.last4")
    guide = Guide(move=GuideMove.IDENTIFY, slots=slots)
    v = mk(cp_view(guide=guide, trigger="guidance", facts=GUIDE_FACTS))
    assert check(v, "It's for marcus bell, account ending 5190.")["D3"] is True
    assert check(v, "It's for Marcus Bell.")["D3"] is False
    assert check(v, "It's for Marcus Bell, ending in five one nine zero.")["D3"] is False
    offer = OfferPublic(
        offer_ref="o1",
        revision=1,
        slots=(Slot(field="monthly_price", value="5500", unit="usd_minor", role="recurring"),),
    )
    price = Guide(move=GuideMove.ASK_READBACK, slots=("offer:o1.monthly_price",))
    w = mk(cp_view(guide=price, trigger="guidance", offers=(offer,)))
    assert check(w, "Could you confirm the 55 dollar price?")["D3"] is True
    assert check(mk(cp_view(guide=Guide(move=GuideMove.ASK_DISCOUNT))), "Hi.")["D3"] is None


def test_d5_relay_expected() -> None:
    v = mk(cp_view(lines=("It is $55.00 a month for 12 months.",)))
    assert check(v, "Thanks.\n@slow: fact monthly_price=55")["D5"] is True
    assert check(v, "Thanks, 55 it is?")["D5"] is False
    assert check(mk(cp_view(lines=("Hello there.",))), "Hi.")["D5"] is None
    assert check(mk(cp_view(trigger="guidance", lines=("It is 55.",))), "Hi.")["D5"] is None
    u = mk(user_view(lines=("My limit is 60 a month.",)))
    assert check(u, "Got it.\n@slow: fact max_monthly=60")["D5"] is True
    assert check(u, "Got it.")["D5"] is False


# --- the fixture: 2 views, the reference and 3 candidate arms -----------------------

V1 = mk(
    cp_view(
        guide=Guide(move=GuideMove.HOLD_FOR_DECISION),
        lines=("We can do $55.00 a month for 12 months. Do you accept?",),
    ),
    raw="I need to check with my customer on that.\n"
    "@slow: fact monthly_price=55; term=12 months\n@hold decision",
    run="run-a",
    turn="t1",
)
V2 = mk(
    user_view(lines=("My budget is 60 dollars a month at most.",)),
    raw="Got it, I'll pass that on.\n@slow: fact max_monthly=60",
    run="run-b",
    turn="t2",
)
VIEWS = [V1, V2]
RAWS: dict[str, tuple[str, str | None]] = {  # (V1 raw or error, V2 raw)
    A: ("Let me check with my customer first.\n@hold decision", "Noted, your limit is 70 dollars.\n@slow: fact max_monthly=70"),
    B: ("We accept the offer.\n@hold decision", "Thanks, I'll share your 60 dollar limit.\n@slow: fact max_monthly=60"),
    C: ("HTTP 503", "Thanks, I've noted it.\n@slow: fact max_monthly=60"),
}
# Judge labels, by (arm, run_id): the False criteria (every other one is True).
FALSE = {
    (REF, "run-a"): (),
    (REF, "run-b"): ("T6",),
    (A, "run-a"): (),
    (A, "run-b"): (),
    (B, "run-a"): ("T3",),
    (B, "run-b"): (),
    (C, "run-b"): ("T2",),
}
# Hand-computed (before the scorer): (k, n) per arm over both lanes.
FIXTURE: dict[str, Json] = {
    REF: {"useful": (1, 2), "pass_judged": (1, 2), "pass_all": (1, 2), "errors": 0},
    A: {"useful": (1, 2), "pass_judged": (2, 2), "pass_all": (2, 2), "errors": 0},
    B: {"useful": (1, 2), "pass_judged": (1, 2), "pass_all": (1, 2), "errors": 0},
    C: {"useful": (0, 2), "pass_judged": (0, 1), "pass_all": (0, 2), "errors": 1},
}
HARD_ALL = {  # (k, n) over all rows, both lanes
    REF: {"D1": (2, 2), "D2": (2, 2), "D4": (2, 2), "D6": (2, 2), "D7": (2, 2)},
    A: {"D1": (2, 2), "D2": (2, 2), "D4": (1, 2), "D6": (2, 2), "D7": (2, 2)},
    B: {"D1": (2, 2), "D2": (2, 2), "D4": (2, 2), "D6": (1, 2), "D7": (2, 2)},
    C: {"D1": (1, 2), "D2": (1, 2), "D4": (1, 2), "D6": (1, 2), "D7": (1, 2)},
}


def report(label: str, override: int | None = 2048) -> Json:
    rows = [pss.row(REF, v, v.raw, v.reference, []) for v in VIEWS]
    (r1, r2), e1 = RAWS[label], label == C
    rows.append(cand(label, V1, "", error=r1) if e1 else cand(label, V1, r1))
    rows.append(cand(label, V2, r2 or ""))
    doc: Json = {"about": pss.ABOUT, "models": [label], "rows": rows, "summary": {}}
    return doc | {"max_tokens_override": override, "funnel": {}, "fingerprints": {}}


def write(path: Path, doc: object) -> Path:
    path.write_text(json.dumps(doc), "utf-8")
    return path


@pytest.fixture
def reports(tmp_path: Path) -> list[Path]:
    return [write(tmp_path / f"r{i}.json", report(m)) for i, m in enumerate(REFS)]


def export(tmp_path: Path, reports: list[Path], seed: int = 7) -> tuple[Json, Path]:
    out = tmp_path / f"batches-{seed}"
    key = ts.run_export(reports, VIEWS, out, tmp_path / f"key-{seed}.json", seed)
    return key, out


def labels(tmp_path: Path, key: Json, skip: int = 0) -> Path:
    """The fixture's judge labels, one JSON-lines file per batch."""
    d = tmp_path / "labels"
    d.mkdir(exist_ok=True)
    for batch, ids in key["batches"].items():
        lines = []
        for rid in ids:
            meta = key["records"][rid]
            bad = FALSE[(meta["arm"], meta["run_id"])]
            lab = {f"T{i}": f"T{i}" not in bad for i in range(1, 7)}
            lines.append(json.dumps({"record": rid, **lab, "note": ""}))
        (d / f"{batch}.jsonl").write_text("\n".join(lines[skip:]) + "\n", "utf-8")
    return d


def score(tmp_path: Path, reports: list[Path], costs: Json | None = None, **kw: Any) -> Json:
    key, _ = export(tmp_path, reports)
    lab = labels(tmp_path, key)
    cost = write(tmp_path / "costs.json", costs) if costs is not None else None
    return ts.run_score(reports, VIEWS, tmp_path / "key-7.json", lab, cost, TOK, **kw)


def kn(rate: Json) -> tuple[int, int]:
    return rate["k"], rate["n"]


# --- export -------------------------------------------------------------------------


def test_export_is_blind(tmp_path: Path, reports: list[Path]) -> None:
    key, out = export(tmp_path, reports)
    text = "\n".join(p.read_text("utf-8") for p in sorted(out.iterdir()))
    banned = [*REFS, REF, "luna", "openrouter", "teamrouter", "ttft", "latency"]
    banned += [x for m, e, echo in REFS.values() for x in (m, echo, f"@{e}")]
    banned += ["t_first_token", "t_start", "2048", "served"]
    for word in banned:
        assert word.lower() not in text.lower(), word
    assert ts.RUBRIC.read_text("utf-8") in text  # the rubric, verbatim
    for v in VIEWS:  # the exact rendered prompt
        for m in ts.fp.render_messages(v.view, v.profile):
            assert m.content in text


def test_export_records_and_key(tmp_path: Path, reports: list[Path]) -> None:
    key, out = export(tmp_path, reports)
    seen = sorted((m["arm"], m["run_id"], m["turn"]) for m in key["records"].values())
    want = [(REF, "run-a", "t1"), (REF, "run-b", "t2")]
    want += [(m, "run-a", "t1") for m in (A, B)] + [(m, "run-b", "t2") for m in REFS]
    assert seen == sorted(want)  # every non-error row once; C's error is not exported
    ids = [i for b in key["batches"].values() for i in b]
    assert sorted(ids) == sorted(key["records"]) and len(set(ids)) == len(ids)
    manifest = json.loads((out / "manifest.json").read_text("utf-8"))
    assert manifest == key["batches"]
    text = "\n".join(p.read_text("utf-8") for p in sorted(out.glob("*.md")))
    for rid in ids:
        assert text.count(rid) == 1
    on_disk = json.loads((tmp_path / "key-7.json").read_text("utf-8"))
    assert on_disk["records"] == key["records"]
    assert key["rubric_sha256"] == ts.RUBRIC_SHA and key["n_records"] == 7


def test_export_is_deterministic(tmp_path: Path, reports: list[Path]) -> None:
    k1, o1 = export(tmp_path, reports, seed=7)
    again = ts.run_export(reports, VIEWS, tmp_path / "again", tmp_path / "k2.json", 7)
    assert again["export_sha256"] == k1["export_sha256"]
    files = sorted(p.name for p in o1.iterdir())
    for name in files:
        assert (o1 / name).read_bytes() == (tmp_path / "again" / name).read_bytes()
    orders = set()
    for seed in range(8):
        k, _ = export(tmp_path, reports, seed=seed)
        orders.add(tuple(k["records"][i]["arm"] for b in k["batches"].values() for i in b))
    assert len(orders) > 1  # the seed shuffles


def test_export_refusals(tmp_path: Path, reports: list[Path]) -> None:
    bad = write(tmp_path / "rubric.md", "a changed rubric")
    with pytest.raises(SystemExit, match="sha256"):
        ts.run_export(reports, VIEWS, tmp_path / "o", tmp_path / "k.json", 1, rubric=bad)
    with pytest.raises(SystemExit, match="inside"):
        ts.run_export(reports, VIEWS, tmp_path / "o", tmp_path / "o" / "k.json", 1)


# --- the views and the reports --------------------------------------------------------


def test_reports_refusals(tmp_path: Path, reports: list[Path]) -> None:
    out, key = tmp_path / "o", tmp_path / "k.json"
    with pytest.raises(SystemExit, match="no view"):
        ts.run_export(reports, [V1], out, key, 1)
    other = report(B)
    other["rows"][0]["raw"] = "A different recorded answer."
    odd = write(tmp_path / "odd.json", other)
    with pytest.raises(SystemExit, match="reference rows differ"):
        ts.run_export([reports[0], odd], VIEWS, out, key, 1)
    lane = report(B)
    lane["rows"][2]["lane"] = "user"
    with pytest.raises(SystemExit, match="lane"):
        ts.run_export([write(tmp_path / "lane.json", lane)], VIEWS, out, key, 1)
    short = report(B)
    del short["rows"][3]
    with pytest.raises(SystemExit, match="rows"):
        ts.run_export([write(tmp_path / "short.json", short)], VIEWS, out, key, 1)
    with pytest.raises(SystemExit, match="twice"):
        ts.run_export([reports[0], reports[0]], VIEWS, out, key, 1)


@pytest.mark.parametrize("fault", ["override", "missing", "varies", "no_override"])
def test_max_tokens_sent_is_checked(tmp_path: Path, fault: str) -> None:
    """Read per row (``max_tokens_sent``): present, one value per arm, and the
    report's override (without one, the recorded session's cap)."""
    doc = report(A, override=1024 if fault == "override" else 2048)
    if fault == "missing":
        del doc["rows"][2]["max_tokens_sent"]
    elif fault == "varies":
        doc["rows"][2]["max_tokens_sent"] = 160
    elif fault == "no_override":
        doc["max_tokens_override"] = None
    path = write(tmp_path / "r.json", doc)
    with pytest.raises(SystemExit, match="max_tokens"):
        ts.run_export([path], VIEWS, tmp_path / "o", tmp_path / "k.json", 1)


# --- score ---------------------------------------------------------------------------


def test_score_fixture(tmp_path: Path, reports: list[Path]) -> None:
    doc = score(tmp_path, reports)
    for arm, want in FIXTURE.items():
        got = doc["arms"][arm]["all"]
        assert kn(got["useful"]) == want["useful"], arm
        assert kn(got["judged_all_pass"]["judged"]) == want["pass_judged"], arm
        assert kn(got["judged_all_pass"]["all"]) == want["pass_all"], arm
        assert got["errors"] == want["errors"] and got["n"] == 2
        for d, k_n in HARD_ALL[arm].items():
            assert kn(got[d]["all"]) == k_n, (arm, d)
    c = doc["arms"][C]
    assert kn(c["all"]["D1"]["answered"]) == (1, 1)
    assert kn(c["cp"]["D1"]["answered"]) == (0, 0) and c["cp"]["D1"]["answered"]["rate"] is None
    assert kn(c["all"]["judged"]["T2"]) == (0, 1) and kn(c["all"]["judged"]["T1"]) == (1, 1)
    assert kn(doc["arms"][B]["all"]["judged"]["T3"]) == (1, 2)
    assert kn(doc["arms"][REF]["all"]["judged"]["T6"]) == (1, 2)
    assert kn(doc["arms"][REF]["user"]["useful"]) == (0, 1)
    assert kn(doc["arms"][A]["cp"]["useful"]) == (1, 1)
    # hold agreement with the reference (Luna, not gold); none for the reference itself
    assert kn(doc["arms"][A]["cp"]["hold_agreement"]) == (1, 1)
    assert kn(doc["arms"][C]["cp"]["hold_agreement"]) == (0, 0)
    assert doc["arms"][REF]["cp"]["hold_agreement"] is None
    assert kn(doc["arms"][A]["all"]["D5_relay_expected"]) == (0, 2)
    assert kn(doc["arms"][REF]["all"]["D5_relay_expected"]) == (2, 2)
    # $ without --costs is null, never 0
    for arm in FIXTURE:
        assert doc["arms"][arm]["usd"] is None and doc["arms"][arm]["usd_per_useful"] is None


def test_score_reads_rows_not_constants(tmp_path: Path, reports: list[Path]) -> None:
    doc = score(tmp_path, reports)
    for label, (model_id, effort, echo) in REFS.items():
        arm = doc["arms"][label]
        assert arm["model_refs"][0]["reasoning_effort"] == effort
        assert arm["model_refs"][0]["model_id"] == model_id
        assert arm["max_tokens"] == {"values": [2048], "rows_without": 0}
        if label != C:
            assert arm["served_echoes"] == [echo]
    assert doc["arms"][REF]["max_tokens"] == {"values": [], "rows_without": 2}
    assert doc["session_max_tokens"] == [160]
    assert "max_tokens override" in doc["request_note"]
    assert doc["views"] == 2 and doc["runs"] == 2
    assert "2 states from 2 train runs" in doc["note"]


def test_score_costs(tmp_path: Path, reports: list[Path]) -> None:
    doc = score(tmp_path, reports, costs={A: 0.10, B: 0.05, C: 0.02})
    assert doc["arms"][A]["usd"] == 0.10 and doc["arms"][A]["usd_per_useful"] == 0.1
    assert doc["arms"][B]["usd_per_useful"] == 0.05
    assert doc["arms"][C]["usd"] == 0.02 and doc["arms"][C]["usd_per_useful"] is None
    assert doc["arms"][REF]["usd"] is None


def pair(doc: Json, metric: str, x: str, y: str) -> float:
    paired = doc["paired"][metric]["all"]
    if f"{x} - {y}" in paired:
        return float(paired[f"{x} - {y}"]["estimate"])
    return -float(paired[f"{y} - {x}"]["estimate"])


def test_score_paired(tmp_path: Path, reports: list[Path]) -> None:
    doc = score(tmp_path, reports, seed=3, resamples=200)
    assert pair(doc, "useful", A, REF) == 0.0
    assert pair(doc, "useful", A, C) == 0.5
    assert pair(doc, "judged_all_pass", A, B) == 0.5
    assert pair(doc, "judged_all_pass", C, REF) == -0.5
    one = doc["paired"]["useful"]["all"]
    assert all(v["clusters"] == 2 for v in one.values())
    assert len(one) == 6  # 3 candidate pairs + 3 candidate - reference
    again = score(tmp_path, reports, seed=3, resamples=200)
    assert again["paired"] == doc["paired"]
    assert doc["bootstrap"] == {"seed": 3, "resamples": 200}


def test_score_disclosures(tmp_path: Path, reports: list[Path]) -> None:
    doc = score(tmp_path, reports)
    shas = doc["inputs_sha256"]
    assert set(shas["reports"]) == {p.name for p in reports}
    assert shas["rubric"] == ts.RUBRIC_SHA and shas["key"] and shas["labels"]
    assert "evidence_funnel" in shas and len(doc["git_sha"]) == 40
    assert doc["note"].startswith("Internal instrument choice, not a claim")
    md = ts.render(doc)
    assert doc["note"] in md and "not comparable" in md and "not gold" in md


@pytest.mark.parametrize("fault", ["missing", "duplicate", "unknown", "non_bool", "errored"])
def test_score_refusals(tmp_path: Path, reports: list[Path], fault: str) -> None:
    key, _ = export(tmp_path, reports)
    key_path = tmp_path / "key-7.json"
    lab = labels(tmp_path, key, skip=1 if fault == "missing" else 0)
    f = sorted(lab.glob("*.jsonl"))[0]
    lines = f.read_text("utf-8").splitlines()
    first = json.loads(lines[0])
    if fault == "duplicate":
        lines.append(lines[0])
    elif fault == "unknown":
        lines.append(json.dumps(first | {"record": "ts-00000000-001-99z"}))
    elif fault == "non_bool":
        lines[0] = json.dumps(first | {"T1": "true"})
    elif fault == "errored":
        key["records"]["ts-err"] = {"arm": C, "run_id": "run-a", "turn": "t1"}
        write(key_path, key)
        lines.append(json.dumps(first | {"record": "ts-err"}))
    f.write_text("\n".join(lines) + "\n", "utf-8")
    match = {
        "missing": "unlabelled",
        "duplicate": "twice",
        "unknown": "unknown",
        "non_bool": "true or false",
        "errored": "errored",
    }[fault]
    with pytest.raises(SystemExit, match=match):
        ts.run_score(reports, VIEWS, key_path, lab, None, TOK)


def test_score_refuses_a_changed_rubric(tmp_path: Path, reports: list[Path]) -> None:
    key, _ = export(tmp_path, reports)
    lab = labels(tmp_path, key)
    bad = write(tmp_path / "rubric.md", "changed")
    with pytest.raises(SystemExit, match="sha256"):
        ts.run_score(reports, VIEWS, tmp_path / "key-7.json", lab, None, TOK, rubric=bad)


# --- the pins ---------------------------------------------------------------------------


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_rubric_sha_is_pinned() -> None:
    assert sha(ts.RUBRIC) == ts.RUBRIC_SHA


def test_adr_pins_the_instruments() -> None:
    text = ADR.read_text("utf-8")
    module = re.search(r"teacher_select\.py` sha256 `([0-9a-f]{64})`", text)
    rubric = re.search(r"teacher-select-rubric\.md` sha256 `([0-9a-f]{64})`", text)
    assert module is not None and rubric is not None
    assert module.group(1) == sha(REPO / "scripts/mod/teacher_select.py")
    assert rubric.group(1) == sha(ts.RUBRIC) == ts.RUBRIC_SHA
