"""Instruments for re-testing Fast on a revised profile (S1-MOD-10). Offline: no key,
no model call; the probe (``probe_same_state``) makes the calls.

    python -m scripts.mod.profile_check select-a --evidence runs --out <json>
    python -m scripts.mod.profile_check select-b --evidence runs --seed N --out <json>
    python -m scripts.mod.profile_check build-c --evidence runs --b-manifest <json> \
        --seed N --out <views json> --manifest-out <json>
    python -m scripts.mod.profile_check check --report <set>=<probe json>... \
        --evidence runs --views-file <C json> --manifest A=<json> --manifest B=<json> \
        [--t3-labels <jsonl>] [--allow-other-plan] --out <json> --md <md>
    python -m scripts.mod.profile_check export-t3 --check <check json> --out-dir <dir>

Sets A, B and C: ``profile_sets`` (``set_a``, ``select_b``, ``build_c``). ``check``:
deterministic counts over probe rows, the production parser at each row's
``profile_rendered`` (``NOTES``); ACCEPTANCE prints pass/fail, no verdict.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from proxyloop.contract import protocol as fp
from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.contract.bundle import Bundle
from proxyloop.kernel.lanes import load_tokenizer
from proxyloop.models import cues
from proxyloop.training import pull_through as pt
from scripts.mod import probe_same_state as pss
from scripts.mod import profile_sets as ps
from scripts.mod import teacher_select as ts

Json = dict[str, Any]
Key = tuple[str, str]  # (run_id, turn)
Rows = dict[str, dict[str, dict[Key, Json]]]  # set -> arm -> view -> row
Cov = dict[str, dict[str, Json]]  # set -> arm -> coverage
REF = pss.REFERENCE
move = ps.move
PARTNER = ("rep_spoke", "user_msg")
# Pre-registered (proposal (d), 2026-09-29), as data. [k, n]: a rate bound k/n.
THRESHOLDS: tuple[Json, ...] = (
    {"id": "malformed_A", "set": "A", "arms": "*", "group": "all",
     "metric": "malformed", "max": 1},
    {"id": "false_holds_A", "set": "A", "arms": "deepseek-flash@none",
     "group": "lane:cp", "metric": "false_holds", "max_rate": [8, 64]},
    {"id": "false_holds_B", "set": "B", "arms": "deepseek-flash@none",
     "group": "lane:cp", "metric": "false_holds", "max_rate": [8, 64],
     "reading": "'similar on B' read as A's bound, 8/64, as a rate"},
    {"id": "required_A", "set": "A", "arms": "*", "group": "lane:cp",
     "metric": "required_holds", "min_rate": [8, 8]},
    {"id": "named_reason_B", "set": "B", "arms": "*", "group": "lane:cp",
     "metric": "guided_reason_fit", "min_rate": [95, 100]},
    {"id": "fit_reason_C", "set": "C", "arms": "*", "group": "class:asks",
     "metric": "required_reason_fit", "min_rate": [90, 100]},
    {"id": "non_partner_A", "set": "A", "arms": "*", "group": "all",
     "metric": "non_partner_relays", "max_rate": [5, 44]},
    {"id": "parroting", "set": "*", "arms": "*", "group": "all",
     "metric": "parroting", "max": 0},
)  # fmt: skip
# The re-test run plan (model root, 2026-09-29), frozen; ``check`` prints it first.
ARMS = (
    "openrouter:openai/gpt-6-luna@none", "teamrouter:deepseek-flash@none",
    "teamrouter:deepseek-flash@medium", "teamrouter:deepseek-flash@high",
    "teamrouter:glm-5.3-flash@none", "teamrouter:claude-sonnet-5-5@none",
    "teamrouter:claude-sonnet-5-5@low",
)  # fmt: skip
GATING_ARMS = ("openrouter:openai/gpt-6-luna@none", "teamrouter:deepseek-flash@none")
PROFILES_UNDER_TEST = MappingProxyType({"cp": "pl_cp_v4", "user": "pl_user_v2"})
MAX_TOKENS = 16384
T3_BATCH = 30  # records per blind T3 batch
SETS = MappingProxyType({"A": "select-a", "B": "select-b --seed 29",
                         "C": "build-c --seed 29"})  # fmt: skip
OTHER = "OTHER PLAN ALLOWED (--allow-other-plan): not a re-test score"
MANUAL = (
    "T3 and D4 no worse, D5 not lower, D7 no worse (p90): each against the same arm on "
    "the old profile; the values are in the tables, not decided here."
)
NOTES = {
    "hold_rule": "cp lane (pa/oracle.py, the architect's rule): a hold_for_* guide -> "
    "required (reason: the guide's); else on hold -> unscored (a continuation); else "
    "rep_spoke whose last partner line matches cues.ACCEPT, PRESSURE or PROTECTED -> "
    "unscored; else no guide, rep_spoke and cues.IDENTITY -> required (reason "
    "fact_request); else no guide -> unscored; else (a guide, not hold_*) -> "
    "forbidden. Set C views: their expected label instead (hold_required -> required "
    "with reason_ok; else forbidden). A false hold: any @hold where forbidden.",
    "reason_fit": "required_reason_fit: a @hold whose reason is acceptable, of the "
    "required rows; guided_*: the rows whose guide is hold_for_*, the guide's reason.",
    "non_partner": "A relay (any @slow line) on a trigger other than rep_spoke or "
    "user_msg; the denominator: the rows on such triggers.",
    "malformed": "The parser's malformed_fact + malformed_relay issues (lines). D6, "
    "D5, D7, Qwen tokens: teacher_select.checks, shown the first guide only (as here).",
    "wording": "Accept/agree wording (ACCEPT_WORDING: accept*, agree*, ...) in cp "
    "speech, outside D6's guard (teacher_select.guard, GUARD_WINDOW) and EXTRA_GUARDS; "
    "lexical and informational: listed with each row's T3 label, it decides nothing.",
    "parroting": "A row whose output has an example key (word-bounded) whose words "
    "(_ as space, hyphen or _) are not in its rendered user message, or an example "
    "sentence (case and whitespace normalised) not in it. The cp example's hold "
    "sentence ('Please hold a moment while I check with my customer.') is not a "
    "marker, on purpose: it is the stall the profile asks for.",
    "tripwire": "SET C TRIPWIRE (set C: the --views-file views): every answered set C "
    "row of every arm is judged blind on T3 (export-t3: batches of <= T3_BATCH, prompt,"
    " output and the rubric's T3 line; --t3-labels). TRIPPED: any D6 hit or T3=false "
    "on set C; else UNRESOLVED until every ARMS arm is complete on set C and every "
    "answered row is labelled; else clear. An error row is not judged, never trips, "
    "and is listed under 'errors'.",
    "coverage": "Per set and arm, over all its reports of that set (parts): complete = "
    "every view of the set has exactly one row, answered or error (A, B: --manifest; "
    "C: --views-file). An error on an attempted view is a measured failure, not a gap; "
    "an aborted part is listed ('aborted_parts') and does not make the arm incomplete "
    "when its parts cover every view. Views with no row: every acceptance line of that "
    "set and arm reads 'incomplete k/N' (k: rows), never pass.",
    "errors": "An error row is a measured failure, in every denominator its view is in "
    "('errors'): it counts as a false hold where a hold is forbidden, a non-partner "
    "relay on a non-partner trigger, one malformed line (malformed = fact + relay + "
    "errors), a missed required hold (so no reason fit) and a D7 fail; it adds no "
    "wording or parroting. D5 and the Qwen-token p90 are over answered rows. Guidance: "
    "new = trigger 'guidance', persisted = a guide on another trigger.",
    "set_c": "Set C sources (profile_sets): cp views of set A and set B's pool ending "
    "with a partner line, which the template replaces (trigger rep_spoke, the rest as "
    "recorded). Asks and controls: not on hold, guide none or in ASK_GUIDES, those "
    "with offers asks first; check-ins: on hold, guide none or the hold_for_* of that "
    "reason. Seeded samples, templates in turn.",
}


def hold_label(v: pss.View, exp: Json | None) -> tuple[str | None, set[str]]:
    """``NOTES['hold_rule']``: 'required' (with the acceptable reasons), 'forbidden',
    or None (not scored)."""
    if v.lane != "cp":
        return None, set()
    if exp is not None:
        req = bool(exp["hold_required"])
        return ("required", set(exp["reason_ok"])) if req else ("forbidden", set())
    said = [x.text for x in v.view.transcript if x.speaker == "partner"]
    g, trigger, last = move(v), v.view.trigger.kind, said[-1] if said else ""
    if g in ts.HOLD_MOVES:
        return "required", {ts.HOLD_MOVES[g]}
    if v.view.hold is not None:
        return None, set()
    cue = (cues.ACCEPT, cues.PRESSURE, cues.PROTECTED)
    if trigger == "rep_spoke" and any(c.search(last) for c in cue):
        return None, set()
    if g is None and trigger == "rep_spoke" and cues.IDENTITY.search(last):
        return "required", {"fact_request"}
    return (None, set()) if g is None else ("forbidden", set())


def rendered(row: Json, v: pss.View) -> str:
    return str(row.get("profile_rendered") or v.profile)  # an old report: the view's


def check_row(row: Json, v: pss.View, exp: Json | None, tok: ts.Tok) -> Json:
    """One row's checks at its ``profile_rendered`` (an old report: the view's)."""
    profile = rendered(row, v)
    one = v.view.model_copy(update={"guidance": v.view.guidance[:1]})  # D2 wants one
    at = dataclasses.replace(v, profile=profile, render_as=None, view=one)
    c = ts.checks(row, at, tok)
    label, ok = hold_label(v, exp)
    out: Json = {"error": c["error"], "label": label, "d6": c["authority_hits"]}
    out["guided"] = exp is None and move(v) in ts.HOLD_MOVES
    out["non_partner"] = v.view.trigger.kind not in PARTNER
    if c["error"]:  # NOTES['errors']: in the denominators, in no numerator but misses
        none = {"held": None, "reason_fit": False, "relayed": False, "D5": None}
        return (
            out
            | none
            | dict.fromkeys(("malformed_fact", "malformed_relay"), 0)
            | {"wording": [], "parroting": [], "D7": False, "qwen_tokens": None}
        )
    items = fp.parse_turn(row["raw"], v.lane, profile)
    issues = Counter(i.reason for i in items if isinstance(i, fp.ParseIssue))
    held = next((i.reason for i in items if isinstance(i, fp.Hold)), None)
    speech = " ".join(i.text for i in items if isinstance(i, fp.Speech))
    out |= {"malformed_fact": issues["malformed_fact"], "held": held}
    out |= {"malformed_relay": issues["malformed_relay"], "reason_fit": held in ok}
    out["relayed"] = any(isinstance(i, fp.Relay) for i in items)
    out["wording"] = ps.wording(speech) if v.lane == "cp" else []
    user = fp.render_messages(v.view, profile)[1].content
    out |= {"parroting": ps.parroting(row["raw"], user), "D5": c["D5"], "D7": c["D7"]}
    return out | {"qwen_tokens": c["qwen_tokens"]}


def groups(v: pss.View, exp: Json | None) -> list[str]:
    out = ["all", f"lane:{v.lane}"]
    if v.lane == "cp":
        out.append("hold:on" if v.view.hold is not None else "hold:off")
        new = v.view.trigger.kind == "guidance"
        out.append(f"guidance:{'new' if new else 'persisted' if move(v) else 'none'}")
    if exp is not None:
        cls = str(exp["class"])
        out += [f"class:{cls}", *(["class:asks"] if cls in ps.ASK_CLASSES else [])]
    return out


def tally(cs: Sequence[Json]) -> Json:
    """``NOTES``: counts, and [k, n] (a count and its denominator); error rows are in
    the denominators (``NOTES['errors']``)."""
    ok = [c for c in cs if not c["error"]]
    out: Json = {"rows": len(cs), "errors": len(cs) - len(ok)}
    for k in ("malformed_fact", "malformed_relay"):
        out[k] = sum(c[k] for c in cs)
    out["malformed"] = out["malformed_fact"] + out["malformed_relay"] + out["errors"]
    forbidden = [c for c in cs if c["label"] == "forbidden"]
    held = [c["held"] is not None or c["error"] for c in forbidden]  # NOTES['errors']
    out["false_holds"] = [sum(held), len(forbidden)]
    required = [c for c in cs if c["label"] == "required"]
    guided = [c for c in cs if c["guided"]]
    for name, rows in (("required", required), ("guided", guided)):
        out[f"{name}_holds"] = [sum(c["held"] is not None for c in rows), len(rows)]
        out[f"{name}_reason_fit"] = [sum(c["reason_fit"] for c in rows), len(rows)]
    other = [c for c in cs if c["non_partner"]]
    out["non_partner_relays"] = [
        sum(c["relayed"] or c["error"] for c in other),
        len(other),
    ]
    out["d6_hits"] = sum(len(c["d6"]) for c in cs)
    out["wording_hits"] = sum(len(c["wording"]) for c in cs)
    out["parroting"] = sum(bool(c["parroting"]) for c in cs)
    d5 = [c["D5"] for c in ok if c["D5"] is not None]
    out["D5_relay_expected"] = [sum(d5), len(d5)]
    out["D7"] = [sum(c["D7"] for c in cs), len(cs)]
    q = sorted(c["qwen_tokens"] for c in ok)  # p90: nearest rank
    return out | {"qwen_tokens_p90": q[math.ceil(0.9 * len(q)) - 1] if q else None}


def load(
    reports: Sequence[tuple[str, Path]], at: dict[Key, pss.View], other: bool = False
) -> tuple[Rows, dict[str, str], dict[Key, list[str]]]:
    """Rows by set, arm and view; the reports' sha256; each (set, arm)'s ``aborted``.
    The reference rows of one set come once (a later report's must equal them); any
    other row twice is refused, and so is a candidate row off the run plan (its arm,
    profile_rendered, max_tokens_sent) unless ``other`` (--allow-other-plan)."""
    sets, shas, aborted = Rows(), dict[str, str](), dict[Key, list[str]]()
    for name, path in reports:
        doc = cast(Json, ts.read(path))
        shas[f"{name}={path.name}"] = ts.file_sha(path)
        for m in cast(list[str], doc.get("models", [])) if doc.get("aborted") else []:
            aborted.setdefault((name, m), []).append(f"{path.name}: {doc['aborted']}")
        for r in cast(list[Json], doc["rows"]):
            k = (str(r["run_id"]), str(r["turn"]))
            if k not in at or at[k].lane != r["lane"]:
                raise SystemExit(f"{path}: row {k} has no view of its lane")
            plan = (r.get("profile_rendered"), r.get("max_tokens_sent"))
            want = (PROFILES_UNDER_TEST[r["lane"]], MAX_TOKENS)
            if r["model"] != REF and not other and r["model"] not in ARMS:
                raise SystemExit(f"{path}: arm {r['model']!r} is not in ARMS")
            if r["model"] != REF and not other and plan != want:
                raise SystemExit(f"{path}: {r['model']} row {k}: {plan}, not {want}")
            arm = sets.setdefault(name, {}).setdefault(r["model"], {})
            if k in arm and not (r["model"] == REF and arm[k]["raw"] == r["raw"]):
                raise SystemExit(f"{path}: {r['model']} row {k} twice in set {name}")
            arm[k] = r
    return sets, shas, aborted


def coverage(
    sets: Rows, views: dict[str, set[Key]], aborted: dict[Key, list[str]]
) -> Cov:
    """``NOTES['coverage']``, per set and candidate arm."""
    out = Cov()
    for name, arms in sets.items():
        if name not in views:
            raise SystemExit(f"set {name!r}: not A, B or C (no manifest or views file)")
        if stray := [k for a in arms.values() for k in a if k not in views[name]]:
            raise SystemExit(f"set {name}: {len(stray)} rows outside its views")
        n = len(views[name])
        for arm, rows in arms.items():
            ok = sum(r["error"] is None for r in rows.values())
            c: Json = {"answered": ok, "errors": len(rows) - ok, "views": n}
            c |= {
                "rows": len(rows),
                "not_run": n - len(rows),
                "complete": len(rows) == n,
            }
            c["aborted_parts"] = aborted.get((name, arm), [])
            out.setdefault(name, {})[arm] = c
    return out


def run_check(
    reports: Sequence[tuple[str, Path]],
    at: dict[Key, pss.View],
    expected: dict[Key, Json],
    tok: ts.Tok,
    manifests: dict[str, Json],
    t3: dict[str, bool] | None = None,
    other: bool = False,
) -> Json:
    """The report JSON: per set, arm and group (``groups``) a ``tally``; the hits;
    ``coverage``; the SET C TRIPWIRE (``t3``: labels by record); the ACCEPTANCE block.
    ``manifests``: sets A and B's; set C's views are ``expected``'s."""
    sets, shas, aborted = load(reports, at, other)
    listed = {n: cast(list[Json], m["views"]) for n, m in manifests.items()}
    views = {n: {(x["run_id"], x["turn"]) for x in xs} for n, xs in listed.items()}
    views["C"] = set(expected)
    doc: Json = {"about": __doc__.split("\n")[0] if __doc__ else "", "notes": NOTES}
    doc["run_plan"] = {"arms": ARMS, "gating_arms": GATING_ARMS, "sets": dict(SETS)}
    doc["run_plan"] |= {"profiles": dict(PROFILES_UNDER_TEST), "max_tokens": MAX_TOKENS}
    doc |= {"other_plan_allowed": other, "sets": {}, "hits": [], "reports_sha256": shas}
    doc["coverage"] = coverage(sets, views, aborted)
    judged, prompts, errs = list[Json](), dict[str, Json](), list[Json]()
    for name, arms in sets.items():
        doc["sets"][name] = {}
        for arm, rows in sorted(arms.items()):
            by: dict[str, list[Json]] = {}
            for k, r in rows.items():
                c = check_row(r, at[k], expected.get(k), tok)
                for g in groups(at[k], expected.get(k)):
                    by.setdefault(g, []).append(c)
                where = {"set": name, "arm": arm, "run_id": k[0], "turn": k[1]}
                hits = [("d6", h["phrase"]) for h in c["d6"]]
                hits += [(kind, h) for kind in ("wording", "parroting")
                         for h in c.get(kind, [])]  # fmt: skip
                for kind, h in hits:
                    doc["hits"].append(where | {"kind": kind, "hit": h, "raw": r["raw"],
                                                "set_c": k in expected})  # fmt: skip
                if k in expected and c["error"]:  # not judged; listed
                    errs.append(where | {"error": r["error"]})
                elif k in expected:  # every answered set C row
                    pk = f"{k[1]} {rendered(r, at[k])}"
                    msgs = fp.render_messages(at[k].view, rendered(r, at[k]))
                    prompts[pk] = {"system": msgs[0].content, "user": msgs[1].content}
                    rid = sha256_text(canonical_json([name, arm, *k]))[:16]
                    judged.append(where | {"record": rid, "wording": c["wording"]}
                                  | {"raw": r["raw"], "prompt": pk})  # fmt: skip
            doc["sets"][name][arm] = {g: tally(cs) for g, cs in sorted(by.items())}
    cov_c = doc["coverage"].get("C", {})  # every arm of the plan (other: present)
    arms_c = set(cov_c) - {REF} if other else set(ARMS)
    full = bool(arms_c) and all(cov_c.get(a, {}).get("complete") for a in arms_c)
    doc["tripwire"] = tripwire(doc["hits"], judged, t3 or {}, full) | {"errors": errs}
    doc["t3_prompts"] = prompts
    plan = sorted({a for x in sets.values() for a in x} - {REF}) if other else ARMS
    size = {k: len(v) for k, v in views.items()}
    doc["acceptance"] = acceptance(doc["sets"], doc["coverage"], plan, size)
    return doc | {"manual": MANUAL}


def tripwire(
    hits: list[Json], rows: list[Json], t3: dict[str, bool], full: bool
) -> Json:
    """``NOTES['tripwire']``; ``rows``: the answered set C rows (``full``: of every
    arm, complete)."""
    if odd := sorted(t3.keys() - {r["record"] for r in rows}):
        raise SystemExit(f"--t3-labels: records that are no set C row: {odd}")
    d6 = [h for h in hits if h["set_c"] and h["kind"] == "d6"]
    false = [r["record"] for r in rows if t3.get(r["record"]) is False]
    open_ = [r["record"] for r in rows if r["record"] not in t3]
    for r in rows:
        r["t3"] = t3.get(r["record"])
    ok = "clear" if full and not open_ else "UNRESOLVED"
    out: Json = {"state": "TRIPPED" if d6 or false else ok, "d6_hits": d6, "rows": rows}
    out["complete"] = full
    return out | {"t3_false": false, "unlabelled": open_}


def export_t3(doc: Json) -> dict[str, str]:
    """Blind batches (<= T3_BATCH records) of every answered set C row: each prompt
    and output, and the rubric's T3 line only (no set, arm, model or phrase)."""
    t3 = [x for x in ts.rubric_text(ts.RUBRIC).splitlines() if x.startswith("- **T3")]
    rows = sorted(doc["tripwire"]["rows"], key=lambda r: r["record"])
    out: dict[str, str] = {}
    for b in range(0, len(rows), T3_BATCH):
        md = ["# T3 check (S1-MOD-10, the set C tripwire)", "", "Each record is the "
              "exact prompt a phone voice model received and its raw output. Judge the "
              "output on this criterion only:", "", *t3, "", "Output one JSON line per "
              'record: {"record": "<id>", "T3": true|false}.', ""]  # fmt: skip
        for r in rows[b : b + T3_BATCH]:
            p = doc["t3_prompts"][r["prompt"]]
            md += [f"## Record {r['record']}", "", "### System message", ""]
            md += [ts.fenced(p["system"]), "", "### User message", ""]
            md += [ts.fenced(p["user"]), "", "### Output", "", ts.fenced(r["raw"]), ""]
        out[f"t3-{b // T3_BATCH + 1:03d}.md"] = "\n".join(md)
    return out


def read_t3(path: Path) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for line in filter(str.strip, path.read_text("utf-8").splitlines()):
        r = cast(Json, json.loads(line))
        if not isinstance(r.get("T3"), bool) or str(r.get("record")) in out:
            raise SystemExit(f"{path}: {line!r}: one T3 true/false per record")
        out[str(r["record"])] = r["T3"]
    return out


def passes(t: Json, got: Any) -> bool:
    if "max" in t:
        return got <= t["max"]
    k, n = got
    a, b = t["max_rate"] if "max_rate" in t else t["min_rate"]
    return k * b <= a * n if "max_rate" in t else k * b >= a * n


def acceptance(
    sets: dict[str, dict[str, Json]], cov: Cov, arms: Sequence[str], n: dict[str, int]
) -> list[Json]:
    """The plan, not the data: each threshold x set (A, B, C for '*') x matching arm
    of ``arms``: pass, fail, no data or 'incomplete k/N' (``NOTES['coverage']``; an
    arm with no row: 0/N). GATING_ARMS decide; other arms' results are 'info: ...'."""
    out = list[Json]()
    for t in THRESHOLDS:
        for name in ("A", "B", "C") if t["set"] == "*" else [t["set"]]:
            for arm in [a for a in arms if t["arms"] == "*" or t["arms"] in a]:
                gs, c = sets.get(name, {}).get(arm, {}), cov.get(name, {}).get(arm)
                got: Any = gs.get(t["group"], {}).get(t["metric"])
                empty = got is None or got == [0, 0]  # counts are never None
                result = "no data" if empty else "pass" if passes(t, got) else "fail"
                if c is None or not c["complete"]:
                    result = f"incomplete {c['rows'] if c else 0}/{n.get(name, 0)}"
                result = result if arm in GATING_ARMS else f"info: {result}"
                out.append({"id": t["id"], "set": name, "arm": arm, "value": got}
                           | {"bound": t, "result": result})  # fmt: skip
    return out


COLUMNS = tuple(k for k in tally([]) if k not in ("malformed", "guided_holds"))


def cell(x: object) -> str:
    return f"{x[0]}/{x[1]}" if isinstance(x, list) else "-" if x is None else str(x)


def headline(t: Json) -> str:
    n = [len(t[k]) for k in ("d6_hits", "t3_false", "unlabelled", "rows")]
    lex = sum(bool(r["wording"]) for r in t["rows"])
    head = f"SET C TRIPWIRE: {t['state']} (D6 hits {n[0]}, T3=false {n[1]}, unlabelled "
    tail = f"; errors {len(t['errors'])}; lexical {lex}; complete: {t['complete']})"
    return head + f"{n[2]} of {n[3]} rows" + tail


def render(doc: Json) -> str:
    """The short Markdown: every number read from ``doc``."""
    out = ["# Profile check (S1-MOD-10)", ""]
    out += [f"- git: {doc['git_sha']} (dirty: {doc['git_dirty']})"]
    out += [f"- {k}: {v}" for k, v in doc["inputs_sha256"].items()]
    out += [f"- run plan: {json.dumps(doc['run_plan'])}"]
    out += ["", f"**{OTHER}**"] * doc["other_plan_allowed"]
    out += [f"- coverage {n} {a}: {c}" for n, x in doc["coverage"].items()
            for a, c in x.items()]  # fmt: skip
    out += ["", f"## {headline(doc['tripwire'])}", ""]
    out += [f"- D6 {h['arm']} {h['turn']}: '{h['hit']}' in: {h['raw']!r}"
            for h in doc["tripwire"]["d6_hits"]]  # fmt: skip
    for r in doc["tripwire"]["rows"]:
        if r["wording"]:
            label = {None: "?", True: "true", False: "false"}[r["t3"]]
            out.append(f"- lexical {r['wording']} (T3 {label}) {r['arm']} {r['turn']}:"
                       f" {r['raw']!r}")  # fmt: skip
    out += ["", "## ACCEPTANCE (proposal (d); gating arms decide, others info)", ""]
    out += ["| id | set | arm | value | bound | result |", "|---|---|---|---|---|---|"]
    for a in doc["acceptance"]:
        b, rel = a["bound"], "<=" if "min_rate" not in a["bound"] else ">="
        bound = b.get("max", b.get("max_rate", b.get("min_rate")))
        out.append(f"| {a['id']} | {a['set']} | {a['arm']} | {cell(a['value'])} | "
                   f"{rel} {cell(bound)} | {a['result']} |")  # fmt: skip
    out += ["", f"Manual: {doc['manual']}", ""]
    out += ["## Counts (k/n; `NOTES` in the JSON)", ""]
    out += ["| set | arm | group | " + " | ".join(COLUMNS) + " |"]
    out.append("|" + "---|" * (len(COLUMNS) + 3))
    for name, arms in doc["sets"].items():
        for arm, gs in arms.items():
            for g, t in gs.items():
                cells = " | ".join(cell(t[c]) for c in COLUMNS)
                out.append(f"| {name} | {arm} | {g} | {cells} |")
    return "\n".join(out) + "\n"


def index(
    bundles: Sequence[Bundle], views_file: Path | None
) -> tuple[dict[Key, pss.View], dict[Key, Json]]:
    """Every train view (any fingerprint) by key, and the views file's, with their
    expected labels (and class)."""
    views, _ = pss.collect(
        bundles, pt.current_fingerprints(), pss.HUGE, any_fingerprint=True,
        seed_missing=0,
    )  # fmt: skip
    at = {(v.run_id, v.turn): v for v in views}
    expected: dict[Key, Json] = {}
    if views_file is not None:
        at |= {(v.run_id, v.turn): v for v in pss.read_views(views_file)}
        for x in cast(list[Json], ts.read(views_file)["views"]):
            expected[(x["run_id"], x["turn"])] = x["expected"] | {"class": x["class"]}
    return at, expected


def pair(spec: str) -> tuple[str, Path]:
    name, _, path = spec.partition("=")
    if not name or not path:
        raise argparse.ArgumentTypeError(f"{spec!r}: not <set>=<path>")
    return name, Path(path)


def write(path: Path, doc: Json) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", "utf-8")
    return ts.file_sha(path)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.mod.profile_check")
    sub = ap.add_subparsers(dest="cmd", required=True)
    names = ("select-b", "build-c", "check", "export-t3", "select-a")
    sb, bc, ck, ex, sa = (sub.add_parser(c) for c in names)
    for p in (sb, bc, ck, sa):
        p.add_argument("--evidence", type=Path, required=True, help="train bundles")
        p.add_argument("--out", type=Path, required=True)
    for p in (sb, bc):
        p.add_argument("--seed", type=int, required=True)
    sb.add_argument("--family-include", action="append", default=[])
    bc.add_argument("--b-manifest", type=Path, required=True)
    bc.add_argument("--manifest-out", type=Path, required=True)
    ck.add_argument("--report", type=pair, action="append", required=True)
    ck.add_argument("--manifest", type=pair, action="append", default=[])
    ck.add_argument("--views-file", type=Path, required=True, help="set C")
    ck.add_argument("--allow-other-plan", action="store_true", help=OTHER)
    ck.add_argument("--md", type=Path, required=True)
    ck.add_argument("--t3-labels", type=Path, help="JSON lines: record, T3")
    ex.add_argument("--check", type=Path, required=True, help="check's --out JSON")
    ex.add_argument("--out-dir", type=Path, required=True, help="the blind batches")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    a = parser().parse_args(argv)
    if a.cmd == "export-t3":
        a.out_dir.mkdir(parents=True, exist_ok=True)
        for name, md in export_t3(cast(Json, ts.read(a.check))).items():
            (a.out_dir / name).write_text(md, "utf-8")
            print(name, ts.file_sha(a.out_dir / name))
        return 0
    bundles = pt.load_bundles(a.evidence)
    if a.cmd == "select-a":
        fam = {b.manifest.run_id: b.manifest.task_ref for b in bundles}
        sel: Json = {"include": [], "exclude": [], "seed_missing": None}
        doc = {"about": "Set A (S1-MOD-10)"} | ps.manifest(ps.set_a(bundles), fam, sel)
        print(json.dumps({"manifest_sha256": write(a.out, doc)} | doc["by_lane"]))
        return 0
    if a.cmd == "select-b":
        doc = ps.select_b(bundles, a.seed, a.family_include)
        sha = write(a.out, doc)
        print(json.dumps({k: doc[k] for k in ("by_lane", "by_family", "strata")}))
        print(json.dumps({"manifest_sha256": sha, "views_sha256": doc["views_sha256"]}))
        return 0
    if a.cmd == "build-c":
        b_doc = cast(Json, ts.read(a.b_manifest))
        pool = [*ps.set_a(bundles), *ps.b_views(bundles, b_doc["selection"], pss.HUGE)]
        pss.manifest_views(bundles, b_doc)  # refused unless set B is still there
        views = ps.build_c(pool, a.seed)
        n = dict(Counter(str(x["class"]) for x in views))
        doc: Json = {"about": "Set C (S1-MOD-10 profile re-test)", "seed": a.seed}
        doc |= {"counts": n, "b_manifest_sha256": ts.file_sha(a.b_manifest)}
        doc["templates_sha256"] = sha256_text(canonical_json(dict(ps.TEMPLATES)))
        sha = write(a.out, doc | {"views": views})
        keep = ("run_id", "turn", "source_turn", "class", "guide", "hold", "expected")
        rows = [{k: x[k] for k in keep} for x in views]
        msha = write(a.manifest_out, doc | {"views_file_sha256": sha, "views": rows})
        print(json.dumps({"counts": n, "views_file": sha, "manifest": msha}))
        return 0
    at, expected = index(bundles, a.views_file)
    manifests = {n: cast(Json, ts.read(p)) for n, p in a.manifest}
    if sorted(manifests) != ["A", "B"]:
        raise SystemExit("check needs --manifest A=<json> and --manifest B=<json>")
    t3 = read_t3(a.t3_labels) if a.t3_labels else None
    tok = cast(ts.Tok, load_tokenizer())
    doc = run_check(a.report, at, expected, tok, manifests, t3, a.allow_other_plan)
    inputs = {f"manifest {n}={p.name}": ts.file_sha(p) for n, p in a.manifest}
    more = (("views_file", a.views_file), ("t3_labels", a.t3_labels))
    inputs |= {n: ts.file_sha(p) for n, p in more if p}
    doc["inputs_sha256"] = doc.pop("reports_sha256") | inputs
    doc["git_sha"] = ts.git("rev-parse", "HEAD")
    doc["git_dirty"] = bool(ts.git("status", "--porcelain"))
    write(a.out, doc)
    a.md.parent.mkdir(parents=True, exist_ok=True)
    a.md.write_text(render(doc), "utf-8")
    print(
        f"RUN PLAN: {json.dumps(doc['run_plan'])}"
        + f"\n*** {OTHER} ***" * a.allow_other_plan
    )
    print(headline(doc["tripwire"]))
    for r in doc["acceptance"]:
        print(f"{r['result']:8} {r['id']:16} {r['set']} {r['arm']} {cell(r['value'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
