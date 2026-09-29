"""Teacher selection instruments (S1-MOD-10, ADR-0025). Offline: no key, no model call.

    python -m scripts.mod.teacher_select export --reports <probe json>... \
        --evidence runs --max-views 127 --out-dir <dir> --key-out <json outside it> \
        --seed N [--views-per-batch 5]
    python -m scripts.mod.teacher_select score --reports <probe json>... \
        --evidence runs --max-views 127 --key <json> --labels-dir <dir> \
        [--costs <json>] --out <json> --md <md> [--seed 0] [--resamples 10000]

Inputs: same-state probe reports (``probe_same_state``); an arm is its label (the full
``<endpoint>:<model>@<effort>`` spec); views re-collected (``pss.collect``), matched
by (run_id, turn) and checked (``load``). ``checks``: every row, the reference's too.
``export``: blind judge batches; ``score``: the report. ``NOTES`` define the metrics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import statistics
import string
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from itertools import combinations
from pathlib import Path
from typing import Any, Protocol, cast

from proxyloop.contract import protocol as fp
from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.contract.state import CaseStatus
from proxyloop.kernel.lanes import load_tokenizer
from proxyloop.training import pull_through as pt
from scripts.mod import probe_same_state as pss

Json = dict[str, Any]
Key = tuple[str, str]  # (run_id, turn)
Arms = dict[str, dict[Key, Json]]
REPO = Path(__file__).resolve().parents[2]
RUBRIC = REPO / "docs/decisions/data/teacher-select-rubric.md"
RUBRIC_SHA = "eac7fbfe1ae6c0b8d6169bca560d86633fd87b4561d47ee49f0e476931dba536"
REF = pss.REFERENCE
LANES = ("all", *pss.LANES)
HARD = ("D1", "D2", "D4", "D6", "D7")
JUDGED = tuple(f"T{i}" for i in range(1, 7))
HOLD_MOVES = {"hold_for_decision": "decision", "hold_for_fact": "fact_request"}
# D6, frozen with the rubric (ADR-0025): phrases, word-boundaried, case-insensitive.
# CP_AUTHORITY: accepting, agreeing or committing for the customer. USER_COMPLETION:
# the task claimed done (CASE STATUS not VERIFIED_COMPLETE). GUARDS (negation and
# modality): a hit is not counted when one of these, or a word ending in n't or 'll,
# is among the GUARD_WINDOW words before it in its sentence.
# fmt: off
CP_AUTHORITY = (
    "we accept", "i accept", "we'll accept", "we will accept", "we'll take it",
    "we will take it", "go ahead and apply", "i agree to", "we agree to",
    "you can sign us up", "that works for us, let's do it",
)
USER_COMPLETION = (
    "is done", "has been applied", "has been accepted", "has been completed",
    "all set", "i've accepted", "i have accepted", "is confirmed",
)
GUARDS = frozenset((
    "not", "never", "nothing", "cannot", "unable", "without", "before", "once",
    "until", "after", "when", "if", "unless", "need", "needs", "will", "would",
    "could", "should", "might", "may",
))
# fmt: on
GUARD_WINDOW = 6
GUARD_PAIRS = frozenset({("no", "way"), ("no", "sign")})  # guards though "no" is not
FREE_PAIRS = frozenset({("once", "again"), ("after", "all")})  # "once", "after" are
LEAK_CHARS = 25  # a reference sentence this long, seen in another prompt, is a leak
PATTERNS = {
    p: re.compile(r"\b" + r"\s+".join(map(re.escape, p.split())) + r"\b")
    for p in (*CP_AUTHORITY, *USER_COMPLETION)
}
NOTE = (
    "Internal instrument choice, not a claim; open-loop, {views} states from {runs} "
    "train runs; the user decides (ADR-0025)."
)
NOTES = {
    "useful": "USEFUL = D1 & D2 & D4 & D6 & D7 & judged T1..T6. Primary ('all', and "
    "USEFUL itself): k / every view of the lane; an errored row and a view an aborted "
    "arm never called (`not_run`) are not useful. 'over_rows_run': k / the arm's rows; "
    "'answered' / 'judged': k / its non-error rows. Rates: Wilson 95 % CIs.",
    "timing": "TTFT/latency: the candidates' TeamRouter-relay-measured by the probe, "
    "the reference's recorded live via OpenRouter in a session: not comparable. "
    "Percentiles: nearest rank.",
    "hold": "hold_agreement: 'has a @hold' equals the reference's (cp lane, answered "
    "rows); the reference is the recorded Luna answer, not gold.",
    "numbers": f"Numbers (D3, D4, D5): {pss.NUMBER_RULE}; number words are not seen.",
    "D1": "No error, no parse issue, some speech or directive (first attempt).",
    "D2": "hold_for_decision needs @hold decision, hold_for_fact @hold fact_request, "
    "close_call @end_call; @end_call under any other guide or none fails; user lane: "
    "no @end_call or @hold (wrong_lane_directives).",
    "D3": "Informational: each guide slot value (read from the rendered line) in the "
    "speech, as digits or a case-insensitive substring; numbers said naturally (as the "
    "profile asks) read as not stated.",
    "D4": "Every number of the speech and of the relays' values and texts (not fact "
    "keys) is among the rendered user message's numbers (not the system text's).",
    "D5": "Informational: on rep_spoke / user_msg whose last partner line has a "
    "number, a relay value or text carries one of its numbers.",
    "D6": "Frozen phrase lists (CP_AUTHORITY; USER_COMPLETION unless "
    "VERIFIED_COMPLETE) in the speech, a negation/modality guard over the "
    f"{GUARD_WINDOW} words before it in its sentence (GUARDS: 'if', 'will', 'once', "
    "words ending in n't or 'll, 'no way', 'no sign', ...; not a bare 'no', 'once "
    "again' or 'after all'); lexical, not semantic (T3 is "
    "the backstop). Every hit is listed.",
    "D7": "The raw output's pinned-Qwen token count (no special tokens) <= the "
    "recorded sessions' Fast max_tokens (the student's cap). finish_reason 'length' is "
    "a runaway: the candidates' max_tokens is a guard, not the length control.",
    "paired": "Every candidate - the reference, the two arms of a model, the models at "
    "one level (none/minimal/low = low-end; medium); over every view (not run = not "
    "useful); run_id clusters resampled; few clusters, wide CI.",
    "judging": "Blind batches, one fresh judge each; a batch never holds two views of "
    "one run, nor a view whose prompt carries another's reference sentence "
    f"(>= {LEAK_CHARS} characters, whitespace and case normalised); errored outputs "
    "are not judged.",
    "cost": "usd: the arm's actual spend (--costs, per-arm balance deltas), else null, "
    "never 0; usd_per_useful = usd / useful rows (TRAINING §7 cpue sense).",
    "dash": "A '-' cell is null: no denominator, or not known.",
}


class Tok(Protocol):
    def encode(self, text: str, add_special_tokens: bool = ...) -> list[int]: ...


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def rubric_text(path: Path) -> str:
    if (sha := file_sha(path)) != RUBRIC_SHA:
        raise SystemExit(f"{path}: sha256 {sha}, not the rubric's {RUBRIC_SHA}")
    return path.read_text("utf-8")


def authority(speech: str, v: pss.View) -> list[Json]:
    """D6's hits: the phrases found in the speech outside the guard."""
    if v.lane == "user" and v.view.status is CaseStatus.VERIFIED_COMPLETE:
        return []
    text, hits = speech.lower().replace("\u2019", "'"), list[Json]()
    for p in CP_AUTHORITY if v.lane == "cp" else USER_COMPLETION:
        for m in PATTERNS[p].finditer(text):
            before = re.split(r"[.!?;]", text[: m.start()])[-1]
            words = re.findall(r"[a-z']+", before)[-GUARD_WINDOW:]
            pairs = zip(words, [*words[1:], ""], strict=False)
            if not any(guard(w, n) for w, n in pairs):
                hits.append({"phrase": p, "text": speech})
                break
    return hits


def guard(w: str, n: str) -> bool:
    """Word ``w``, followed by ``n``, is a D6 guard."""
    if (w, n) in GUARD_PAIRS:
        return True
    return (w in GUARDS or w.endswith(("n't", "'ll"))) and (w, n) not in FREE_PAIRS


def directive_ok(items: Sequence[fp.TurnItem], v: pss.View) -> tuple[bool, int]:
    """D2, and the user lane's @end_call / @hold count (wrong lane)."""
    ends = any(isinstance(i, fp.EndCall) for i in items)
    if v.lane == "user":
        wrong = sum(
            isinstance(i, fp.EndCall)
            or (isinstance(i, fp.ParseIssue) and i.text.startswith("@hold"))
            for i in items
        )
        return wrong == 0, wrong
    move = v.view.guidance[0].move.value if v.view.guidance else None
    want = HOLD_MOVES.get(str(move))
    held = want is None or any(
        isinstance(i, fp.Hold) and i.reason == want for i in items
    )
    return held and ends == (move == "close_call"), 0


def slots_stated(speech: str, v: pss.View) -> bool | None:
    """D3: each slot value, read back from the rendered guidance line, in the speech."""
    if not v.view.guidance or not v.view.guidance[0].slots:
        return None
    g = v.view.guidance[0]
    head = f"- {fp.PROFILES[v.profile].moves[g.move.value]} ("
    user = fp.render_messages(v.view, v.profile)[1].content
    body = next(x for x in user.splitlines() if x.startswith(head))[len(head) : -1]
    values: list[str] = []
    for n, slot in enumerate(g.slots):
        body = body.removeprefix(f"{slot} = ")
        nxt = f"; {g.slots[n + 1]} = " if n + 1 < len(g.slots) else None
        value, _, rest = body.partition(nxt) if nxt else (body, "", "")
        values.append(value)
        body = nxt.removeprefix("; ") + rest if nxt else ""
    said, nums = speech.lower(), set(pss.numbers(speech))
    return all(
        set(pss.numbers(x)) <= nums if pss.numbers(x) else x.lower() in said
        for x in values
    )


def checks(row: Json, v: pss.View, tok: Tok) -> Json:
    """The deterministic checks of one row at its view (``NOTES``)."""
    if len(v.view.guidance) > 1:
        raise SystemExit(f"{v.run_id} {v.turn}: more than one guide; D2 assumes one")
    if row["error"] is not None:
        return dict.fromkeys(HARD, False) | {"error": True, "authority_hits": []}
    raw: str = row["raw"]
    items = fp.parse_turn(raw, v.lane, v.profile)
    speech = " ".join(i.text for i in items if isinstance(i, fp.Speech))
    relays = [i for i in items if isinstance(i, fp.Relay)]
    relayed = " ".join(
        [r.text for r in relays] + [x for r in relays for _, x in r.facts]
    )
    known = set(pss.numbers(fp.render_messages(v.view, v.profile)[1].content))
    invented = [n for n in pss.numbers(speech) + pss.numbers(relayed) if n not in known]
    hits, (d2, wrong) = authority(speech, v), directive_ok(items, v)
    n_tok = len(tok.encode(raw, add_special_tokens=False))
    said = [x.text for x in v.view.transcript if x.speaker == "partner"]
    last = set(pss.numbers(said[-1])) if said else set[str]()
    applies = bool(last) and v.view.trigger.kind in ("rep_spoke", "user_msg")
    d5 = bool(last & set(pss.numbers(relayed))) if applies else None
    out: Json = {"error": False, "D2": d2, "D4": not invented, "D6": not hits}
    out["D1"] = bool(items) and not any(isinstance(i, fp.ParseIssue) for i in items)
    out |= {"D7": n_tok <= v.sampling.max_tokens, "qwen_tokens": n_tok}
    out |= {"D3": slots_stated(speech, v), "D5": d5, "invented": invented}
    out |= {"authority_hits": hits, "wrong_lane_directives": wrong}
    out["has_hold"] = any(isinstance(i, fp.Hold) for i in items)
    out["sentences"] = sum(isinstance(i, fp.Speech) for i in items)
    out["spoken_words"] = len(speech.split())
    out["length_stop"] = row["record"]["finish_reason"] == "length"
    return out | {"length_empty": out["length_stop"] and not speech}


def load(
    paths: Sequence[Path], views: Sequence[pss.View]
) -> tuple[Arms, dict[str, str], dict[str, str | None]]:
    """The arms' rows by view (refusals: the module docstring), the reports' sha256
    by file name, and each arm's report's ``aborted`` text."""
    at = {(v.run_id, v.turn): v for v in views}
    arms: Arms = {}
    shas: dict[str, str] = {}
    aborted: dict[str, str | None] = {REF: None}
    reference: str | None = None
    for p in paths:
        doc = cast(Json, read(p))
        shas[p.name], rows = file_sha(p), cast(list[Json], doc["rows"])
        for r in rows:
            if (k := (r["run_id"], r["turn"])) not in at:
                raise SystemExit(f"{p}: {r['model']} row {k} has no view (--evidence?)")
            if r["lane"] != at[k].lane:
                raise SystemExit(f"{p}: {r['model']} row {k}: not its view's lane")
        refs = [r for r in rows if r["model"] == REF]
        refs.sort(key=lambda r: (r["run_id"], r["turn"]))
        if reference is None:
            reference, arms[REF] = canonical_json(refs), by_view(REF, refs)
        elif canonical_json(refs) != reference:
            raise SystemExit(f"{p}: the reference rows differ between the reports")
        for m in cast(list[str], doc["models"]):
            if m in arms:
                raise SystemExit(f"{p}: arm {m} twice")
            arms[m] = by_view(m, [r for r in rows if r["model"] == m])
            aborted[m], override = doc.get("aborted"), doc.get("max_tokens_override")
            sent = {r.get("max_tokens_sent") for r in arms[m].values()}
            if None in sent or len(sent) != 1:
                raise SystemExit(f"{p}: {m}: max_tokens_sent missing or varying {sent}")
            for k, r in arms[m].items():
                want = override if override is not None else at[k].sampling.max_tokens
                if r["max_tokens_sent"] != want:
                    raise SystemExit(f"{p}: {m}: max_tokens_sent is not {want}")
    for m, rows in arms.items():
        if rows.keys() != at.keys() and not (aborted[m] and rows.keys() < at.keys()):
            raise SystemExit(f"arm {m}: rows for {len(rows)} of {len(at)} views")
        refs = {canonical_json(r["record"]["model_ref"]) for r in rows.values()}
        if len(refs) > 1:
            raise SystemExit(f"arm {m}: more than one model_ref")
        if m != REF and any('"reasoning_effort":null' in x for x in refs):
            raise SystemExit(f"arm {m}: no explicit reasoning_effort (ADR-0025 (3))")
    return arms, shas, aborted


def by_view(arm: str, rows: Sequence[Json]) -> dict[Key, Json]:
    out = {(r["run_id"], r["turn"]): r for r in rows}
    if len(out) != len(rows):
        raise SystemExit(f"arm {arm}: {len(rows) - len(out)} rows twice")
    return out


def export_id(seed: int, per_batch: int, shas: dict[str, str]) -> str:
    doc = {"seed": seed, "per_batch": per_batch, "reports": sorted(shas.values())}
    return sha256_text(canonical_json(doc | {"rubric": RUBRIC_SHA}))


def fenced(text: str) -> str:
    fence = "`" * max([3, *(len(x) + 1 for x in re.findall(r"`+", text))])
    return f"{fence}text\n{text}\n{fence}"


def said(v: pss.View) -> set[str]:
    """The reference's spoken sentences of at least LEAK_CHARS, normalised."""
    items = fp.parse_turn(v.raw, v.lane, v.profile)
    out = {" ".join(i.text.split()).lower() for i in items if isinstance(i, fp.Speech)}
    return {x for x in out if len(x) >= LEAK_CHARS}


def prompt(v: pss.View) -> str:
    return " ".join(pss.view_text(v).split()).lower()


def leaks(views: Sequence[pss.View]) -> Callable[[pss.View, pss.View], bool]:
    """(v, w) -> ``v``'s reference speech (``said``) is visible in ``w``'s prompt."""
    s, t = {id(v): said(v) for v in views}, {id(v): prompt(v) for v in views}
    return lambda v, w: any(x in t[id(w)] for x in s[id(v)])


def batches(
    views: Sequence[pss.View], per_batch: int, rng: random.Random
) -> list[list[pss.View]]:
    """Seeded greedy: each view, in a seeded order, joins the first batch with room,
    no view of its run, and no leak either way (``leaks``); else a new batch."""
    order, out, leak = list(views), list[list[pss.View]](), leaks(views)
    rng.shuffle(order)
    for v in order:
        for b in out:
            fits = len(b) < per_batch and all(w.run_id != v.run_id for w in b)
            if fits and not any(leak(v, w) or leak(w, v) for w in b):
                b.append(v)
                break
        else:
            out.append([v])
    return out


def visible(batch: Sequence[pss.View]) -> int:
    """Views whose reference speech (``said``) is in another prompt of the batch."""
    leak = leaks(batch)
    return sum(any(leak(v, w) for w in batch if w is not v) for v in batch)


def run_export(
    reports: Sequence[Path],
    views: Sequence[pss.View],
    out_dir: Path,
    key_out: Path,
    seed: int,
    per_batch: int = 5,
    rubric: Path = RUBRIC,
) -> Json:
    """Blind batches (one Markdown file = one judge prompt, the rubric on top): per
    view, the rendered prompt and every arm's non-error raw output under an opaque
    record id, shuffled by ``seed``; no arm, model, echo or timing. ``manifest.json``
    (batch -> ids) in ``out_dir``; the key (id -> arm, run_id, turn) outside it."""
    text = rubric_text(rubric)
    if key_out.resolve().is_relative_to(out_dir.resolve()):
        raise SystemExit(f"--key-out {key_out} is inside --out-dir {out_dir}")
    arms, shas, _ = load(reports, views)
    eid, rng = export_id(seed, per_batch, shas), random.Random(seed)
    chunks = batches(views, per_batch, rng)
    if leaks := sum(map(visible, chunks)):
        raise SystemExit(f"{leaks} views' reference speech is in a batch's prompt")
    key: Json = {"export_id": eid, "seed": seed, "views_per_batch": per_batch}
    key |= {"rubric_sha256": RUBRIC_SHA, "reports_sha256": shas}
    errs = {m: sum(r["error"] is not None for r in a.values()) for m, a in arms.items()}
    key |= {"not_exported_errors": errs, "batches": {}, "records": {}}
    key["not_run"] = {m: len(views) - len(a) for m, a in arms.items()}
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_shas: dict[str, str] = {}
    for b, chunk in enumerate(chunks, 1):
        name = f"ts-{eid[:8]}-{b:03d}"
        md, ids = [text, "---", f"# Batch {name}", ""], list[str]()
        for j, v in enumerate(chunk, 1):
            system, user = fp.render_messages(v.view, v.profile)
            md += [f"## View {j}", "", "### System message", "", fenced(system.content)]
            md += ["", "### User message", "", fenced(user.content), ""]
            k = (v.run_id, v.turn)
            outs = [(m, a[k]) for m, a in sorted(arms.items())
                    if k in a and a[k]["error"] is None]  # fmt: skip
            rng.shuffle(outs)
            md += ["### Outputs", ""]
            for letter, (m, r) in zip(string.ascii_lowercase, outs, strict=False):
                rid = f"{name}-{j:02d}{letter}"
                md += [f"#### Record {rid}", "", fenced(r["raw"]), ""]
                ids.append(rid)
                key["records"][rid] = {"arm": m, "run_id": v.run_id, "turn": v.turn}
        path = out_dir / f"{name}.md"
        path.write_text("\n".join(md), "utf-8")
        batch_shas[name], key["batches"][name] = file_sha(path), ids
    (out_dir / "manifest.json").write_text(json.dumps(key["batches"], indent=1) + "\n")
    key |= {"n_records": len(key["records"]), "reference_visible": leaks}
    key["export_sha256"] = sha256_text(canonical_json(batch_shas))
    key_out.parent.mkdir(parents=True, exist_ok=True)
    key_out.write_text(json.dumps(key, indent=1, sort_keys=True) + "\n", "utf-8")
    return key


def read_labels(root: Path, key: Json, arms: Arms) -> dict[tuple[str, Key], Json]:
    """(arm, view) -> T1..T6: every exported record labelled exactly once."""
    records = cast(dict[str, Json], key["records"])
    out: dict[tuple[str, Key], Json] = {}
    seen: set[str] = set()
    for f in sorted(root.glob("*.jsonl")):
        for line in filter(str.strip, f.read_text("utf-8").splitlines()):
            r = cast(Json, json.loads(line))
            if (rid := str(r.get("record"))) not in records:
                raise SystemExit(f"{f}: record {rid!r} unknown")
            if rid in seen:
                raise SystemExit(f"{f}: record {rid} labelled twice")
            if not all(isinstance(r.get(t), bool) for t in JUDGED):
                raise SystemExit(f"{f}: record {rid}: T1..T6 must be true or false")
            seen.add(rid)
            meta = records[rid]
            k = (meta["run_id"], meta["turn"])
            if (row := arms.get(meta["arm"], {}).get(k)) is None:
                raise SystemExit(f"{f}: record {rid} names no row")
            if row["error"] is not None:
                raise SystemExit(f"{f}: record {rid} labels an errored row")
            out[(meta["arm"], k)] = {t: r[t] for t in JUDGED}
    if missing := len(records.keys() - seen):
        raise SystemExit(f"{missing} of {len(records)} exported records unlabelled")
    return out


def round4(x: float) -> float:
    return round(x, 4)


def rate(k: int, n: int) -> Json:
    """k of n with a Wilson 95 % CI (rate and CI null when n is 0)."""
    if n == 0:
        return {"k": k, "n": 0, "rate": None, "ci95": None}
    z, p = 1.959963984540054, k / n
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    lo, hi = ((p + z * z / (2 * n) + s * half) / (1 + z * z / n) for s in (-1, 1))
    return {
        "k": k,
        "n": n,
        "rate": round4(p),
        "ci95": [round4(max(lo, 0)), round4(min(hi, 1))],
    }


def spread(xs: Sequence[float]) -> Json:
    """Nearest-rank p50 and p95."""
    s = sorted(xs)
    at = {q: s[math.ceil(q * len(s)) - 1] if s else None for q in (0.5, 0.95)}
    return {"p50": at[0.5], "p95": at[0.95], "n": len(s)}


def bootstrap(units: Sequence[tuple[str, float]], seed: int, resamples: int) -> Json:
    """Run clusters resampled with replacement: the mean difference and its 2.5 % and
    97.5 % percentiles (as ``world_select_score.bootstrap``)."""
    sums: dict[str, list[float]] = {}
    for c, d in units:
        t = sums.setdefault(c, [0.0, 0.0])
        t[0], t[1] = t[0] + d, t[1] + 1
    groups = [sums[c] for c in sorted(sums)]
    out: Json = {"units": len(units), "clusters": len(groups)}
    if not groups:
        return out | {"estimate": None, "ci95": None}
    est = sum(g[0] for g in groups) / sum(g[1] for g in groups)
    rng, stats = random.Random(seed), list[float]()
    for _ in range(resamples):
        pick = rng.choices(groups, k=len(groups))
        stats.append(sum(g[0] for g in pick) / sum(g[1] for g in pick))
    stats.sort()
    lo = stats[math.floor(0.025 * (resamples - 1))]
    hi = stats[math.ceil(0.975 * (resamples - 1))]
    return out | {"estimate": round4(est), "ci95": [round4(lo), round4(hi)]}


def summarise(es: Sequence[Json], reference: bool, views: int) -> Json:
    """One arm's rows of one lane (or all) of ``views`` views; ``es``: {row, c
    (checks), j (labels)}; ``NOTES['useful']`` names the denominators."""
    ok = [e for e in es if not e["c"]["error"]]
    out: Json = {"views": views, "n": len(es), "not_run": views - len(es)}
    out["errors"] = len(es) - len(ok)
    for d in HARD:
        k = sum(e["c"][d] for e in es)
        out[d] = {"answered": rate(k, len(ok)), "all": rate(k, views)}
        out[d]["over_rows_run"] = rate(k, len(es))
    judged = [cast(Json, e["j"]) for e in es if e["j"] is not None]
    out["judged"] = {t: rate(sum(j[t] for j in judged), len(judged)) for t in JUDGED}
    passed = sum(all(j.values()) for j in judged)
    out["judged_all_pass"] = {"judged": rate(passed, len(judged))}
    out["judged_all_pass"] |= {"all": rate(passed, views)}
    out["judged_all_pass"]["over_rows_run"] = rate(passed, len(es))
    useful = sum(e["useful"] for e in es)
    out["useful"] = rate(useful, views)
    out["useful_over_rows_run"] = rate(useful, len(es))
    out["failed_attempts"] = sum(len(e["row"].get("failed_attempts", [])) for e in es)
    echo = [e["row"]["record"]["served_model_echo"] for e in ok]
    out["missing_echoes"] = echo.count(None)
    for name, d in (("D3_slots_stated", "D3"), ("D5_relay_expected", "D5")):
        seen = [e["c"][d] for e in ok if e["c"][d] is not None]
        out[name] = rate(sum(seen), len(seen))
    cp = [e for e in ok if e["row"]["lane"] == "cp"]
    agree = sum(e["c"]["has_hold"] == e["ref_hold"] for e in cp)
    out["hold_agreement"] = None if reference else rate(agree, len(cp))
    out["wrong_lane_directives"] = sum(e["c"]["wrong_lane_directives"] for e in ok)
    for k in ("sentences", "spoken_words"):
        xs = [e["c"][k] for e in ok]
        out[f"{k}_mean"] = round4(statistics.fmean(xs)) if xs else None
    recs = [cast(Json, e["row"]["record"]) for e in ok]
    out["finish_reason"] = dict(Counter(str(r["finish_reason"]) for r in recs))
    out["length_stops"] = sum(e["c"]["length_stop"] for e in ok)
    out["length_empty_speech"] = sum(e["c"]["length_empty"] for e in ok)
    known = [u for e in ok if (u := e["row"]["record"]["usage"]) is not None]
    thought = [x for u in known if (x := u.get("reasoning_tokens")) is not None]
    out["reasoning_tokens"] = spread(thought) | {"unknown": len(ok) - len(thought)}
    q = [e["c"]["qwen_tokens"] for e in ok]
    out["qwen_tokens"] = spread(q) | {"max": max(q, default=None)}
    out["ttft_ms"] = spread([x for e in ok if (x := e["row"]["ttft_ms"]) is not None])
    out["latency_ms"] = spread([r["t_end"] - r["t_start"] for r in recs])
    out["usage_unknown"] = len(ok) - len(known)
    for k in ("prompt_tokens", "completion_tokens"):
        out[k] = sum(u[k] for u in known) if known else None
    return out


def entries(
    arms: Arms, views: Sequence[pss.View], labels: dict[tuple[str, Key], Json], tok: Tok
) -> dict[str, dict[Key, Json]]:
    """Per arm and view: the row, its checks, its labels, useful and all-pass."""
    at = {(v.run_id, v.turn): v for v in views}
    out: dict[str, dict[Key, Json]] = {}
    for m, rows in arms.items():
        out[m] = {}
        for k, row in rows.items():
            c, j = checks(row, at[k], tok), labels.get((m, k))
            passed = j is not None and all(j.values())
            useful = passed and all(c[d] for d in HARD)
            out[m][k] = {"row": row, "c": c, "j": j, "useful": useful, "pass": passed}
    for m in out:
        for k, e in out[m].items():
            e["ref_hold"] = out[REF][k]["c"]["has_hold"]
    return out


def level(effort: str) -> str:
    """ADR-0025 (3): the low-end arm (none, else minimal, else low) or medium."""
    return "low-end" if effort in ("none", "minimal", "low") else effort


def paired(
    es: dict[str, dict[Key, Json]],
    metric: str,
    seed: int,
    n: int,
    views: Sequence[pss.View],
) -> Json:
    """Every candidate - the reference; the arms of one model (the effort effect); the
    models at one level. Model and effort are read from the rows."""
    ref = {
        m: next(iter(e.values()))["row"]["record"]["model_ref"] for m, e in es.items()
    }
    model = {m: (r["endpoint"], r["model_id"]) for m, r in ref.items()}
    lvl = {m: level(r["reasoning_effort"]) for m, r in ref.items() if m != REF}
    cands = sorted(m for m in es if m != REF)
    pairs = [(a, b) for a, b in combinations(cands, 2)
             if (model[a] == model[b]) != (lvl[a] == lvl[b])]  # fmt: skip
    out: Json = {lane: {} for lane in LANES}
    for lane in LANES:
        for a, b in [*pairs, *((c, REF) for c in cands)]:
            units = [(v.run_id, got(es[a], v, metric) - got(es[b], v, metric))
                     for v in views if lane in ("all", v.lane)]  # fmt: skip
            out[lane][f"{a} - {b}"] = bootstrap(units, seed, n)
    return out


def got(arm: dict[Key, Json], v: pss.View, metric: str) -> float:
    """A view's metric for an arm; a view it never ran is not useful (0)."""
    e = arm.get((v.run_id, v.turn))
    return float(e[metric]) if e is not None else 0.0


def git(*argv: str) -> str:
    return subprocess.run(
        ["git", *argv], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()


def run_score(
    reports: Sequence[Path],
    views: Sequence[pss.View],
    key_path: Path,
    labels_dir: Path,
    costs_path: Path | None,
    tok: Tok,
    seed: int = 0,
    resamples: int = 10_000,
    rubric: Path = RUBRIC,
    funnel: Json | None = None,
) -> Json:
    """The report JSON: per arm and lane (``summarise``), paired differences of USEFUL
    and judged all-pass, the D6 hits, the inputs' sha256 and the git sha."""
    rubric_text(rubric)
    arms, shas, aborted = load(reports, views)
    key = cast(Json, read(key_path))
    if (eid := key["export_id"]) != export_id(
        key["seed"], key["views_per_batch"], shas
    ):
        raise SystemExit(f"{key_path}: an export of other reports or another rubric")
    labels = read_labels(labels_dir, key, arms)
    costs = cast(dict[str, float], read(costs_path)) if costs_path else {}
    if odd := sorted(costs.keys() - arms.keys()):
        raise SystemExit(f"--costs names no arm: {odd}")
    es, runs = entries(arms, views, labels, tok), len({v.run_id for v in views})
    doc: Json = {"note": NOTE.format(views=len(views), runs=runs)}
    over = {m: a[next(iter(a))]["max_tokens_sent"] for m, a in arms.items() if m != REF}
    session = sorted({v.sampling.max_tokens for v in views})
    doc["request_note"] = (
        "The exact kernel request (S1-MOD-08) except max_tokens: the candidates ran "
        f"with a max_tokens override {over}, read from the probe reports' "
        "max_tokens_override and every row's max_tokens_sent (they agree; refused "
        f"otherwise); the reference was recorded at the session's {session}."
    )
    doc |= {"notes": NOTES, "views": len(views), "runs": runs}
    doc["by_lane"] = dict(Counter(v.lane for v in views))
    doc |= {"session_max_tokens": session, "arms": {}}
    for m in (REF, *sorted(m for m in arms if m != REF)):
        rows = list(es[m].values())
        refs = {canonical_json(e["row"]["record"]["model_ref"]) for e in rows}
        arm: Json = {"model_refs": [json.loads(x) for x in sorted(refs)]}
        echoes = {e["row"]["record"]["served_model_echo"] for e in rows} - {None}
        arm["served_echoes"] = sorted(echoes)
        effort = arm["model_refs"][0]["reasoning_effort"]
        arm["level"] = None if m == REF else level(effort)
        sent = [e["row"].get("max_tokens_sent") for e in rows]
        values = sorted({x for x in sent if x is not None})
        arm["max_tokens"] = {"values": values, "rows_without": sent.count(None)}
        arm |= {"rows": len(rows), "not_run": len(views) - len(rows)}
        useful, usd = sum(e["useful"] for e in rows), costs.get(m)
        arm |= {"aborted": aborted[m], "usd": usd}
        arm["usd_per_useful"] = (
            round4(usd / useful) if usd is not None and useful else None
        )
        for lane in LANES:
            mine = [e for e in rows if lane in ("all", e["row"]["lane"])]
            n = sum(lane in ("all", v.lane) for v in views)
            arm[lane] = summarise(mine, m == REF, n)
        doc["arms"][m] = arm
    doc["paired"] = {
        "useful": paired(es, "useful", seed, resamples, views),
        "judged_all_pass": paired(es, "pass", seed, resamples, views),
    }
    doc["authority_hits"] = [
        {"arm": m, "run_id": k[0], "turn": k[1], "lane": e["row"]["lane"]} | h
        for m in sorted(es)
        for k, e in es[m].items()
        for h in e["c"]["authority_hits"]
    ]
    doc["exclusions"] = {"errored_rows_not_judged": key["not_exported_errors"]}
    doc["bootstrap"] = {"seed": seed, "resamples": resamples}
    lab = {f.name: file_sha(f) for f in sorted(labels_dir.glob("*.jsonl"))}
    inputs: Json = {"reports": shas, "key": file_sha(key_path), "labels": lab}
    inputs["costs"] = file_sha(costs_path) if costs_path else None
    inputs["evidence_funnel"] = sha256_text(canonical_json(funnel)) if funnel else None
    doc |= {"inputs_sha256": inputs | {"rubric": RUBRIC_SHA}, "export_id": eid}
    doc["git_sha"], dirty = git("rev-parse", "HEAD"), git("status", "--porcelain")
    return doc | {"git_dirty": bool(dirty)}


def cell(v: object) -> str:
    if isinstance(v, dict) and "ci95" in v:
        r = cast(Json, v)
        rated = "rate" in r
        mid = r["rate"] if rated else r["estimate"]
        n = f"{r['k']}/{r['n']}" if rated else f"{r['clusters']} clusters"
        return "-" if mid is None else f"{mid} [{r['ci95'][0]}, {r['ci95'][1]}] ({n})"
    return "-" if v is None else json.dumps(v) if isinstance(v, list | dict) else str(v)


def flat(doc: Json, pre: str = "") -> Json:
    """Nested metrics as dotted keys; a rate, a comparison or a count map is a cell."""
    out: Json = {}
    for k, v in doc.items():
        if isinstance(v, dict) and "ci95" not in v and k != "finish_reason":
            out |= flat(cast(Json, v), f"{pre}{k}.")
        else:
            out[pre + k] = v
    return out


def table(title: str, cols: dict[str, Json]) -> list[str]:
    keys = list(dict.fromkeys(k for c in cols.values() for k in c))
    lines = [f"## {title}", "", "| metric | " + " | ".join(cols) + " |"]
    lines.append("|" + "---|" * (len(cols) + 1))
    row = [" | ".join([k, *(cell(c.get(k)) for c in cols.values())]) for k in keys]
    return [*lines, *(f"| {r} |" for r in row), ""]


def render(doc: Json) -> str:
    """The Markdown report, every number read from ``doc``."""
    out = ["# Teacher selection report (S1-MOD-10, ADR-0025)", "", doc["note"], ""]
    out += [doc["request_note"], "", *(f"- {k}: {v}" for k, v in doc["notes"].items())]
    heads = ("git_sha", "git_dirty", "export_id", "views", "runs", "by_lane")
    heads += ("bootstrap", "exclusions")
    facts = {k: doc[k] for k in heads} | flat(doc["inputs_sha256"], "sha256.")
    out += ["", *(f"- {k}: {cell(v)}" for k, v in facts.items())]
    arms = cast(dict[str, Json], doc["arms"])
    head = ("model_refs", "level", "served_echoes", "max_tokens", "rows", "not_run")
    head += ("aborted", "usd", "usd_per_useful")
    out += ["", *table("arms", {m: {k: a[k] for k in head} for m, a in arms.items()})]
    for lane in LANES:
        out += table(f"lane: {lane}", {m: flat(a[lane]) for m, a in arms.items()})
    for metric, lanes in doc["paired"].items():
        out += table(f"paired {metric}: difference, 95 % CI (no decision rule)", lanes)
    out += ["## D6 lexical hits", ""]
    for h in doc["authority_hits"]:
        where = f"{h['arm']} {h['run_id']} {h['turn']} ({h['lane']})"
        out.append(f"- {where}: '{h['phrase']}' in: {h['text']}")
    return "\n".join(out if doc["authority_hits"] else [*out, "- none"]) + "\n"


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.mod.teacher_select")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex, sc = sub.add_parser("export"), sub.add_parser("score")
    for p in (ex, sc):
        p.add_argument("--reports", type=Path, nargs="+", required=True)
        p.add_argument("--evidence", type=Path, required=True, help="train bundles")
        p.add_argument("--max-views", type=pss.at_least_1, required=True)
        p.add_argument("--rubric", type=Path, default=RUBRIC)
    ex.add_argument("--out-dir", type=Path, required=True)
    ex.add_argument("--key-out", type=Path, required=True, help="outside --out-dir")
    ex.add_argument("--seed", type=int, required=True)
    ex.add_argument("--views-per-batch", type=pss.at_least_1, default=5)
    for flag in ("--key", "--labels-dir", "--out", "--md"):
        sc.add_argument(flag, type=Path, required=True)
    sc.add_argument("--costs", type=Path, help="{arm label: USD actual}")
    sc.add_argument("--seed", type=int, default=0)
    sc.add_argument("--resamples", type=pss.at_least_1, default=10_000)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    a = parser().parse_args(argv)
    views, funnel = pss.collect(
        pt.load_bundles(a.evidence), pt.current_fingerprints(), a.max_views
    )
    if a.cmd == "export":
        key = run_export(
            a.reports, views, a.out_dir, a.key_out, a.seed, a.views_per_batch, a.rubric
        )
        shown = ("export_id", "export_sha256", "n_records", "reference_visible")
        print(json.dumps({k: key[k] for k in shown} | {"batches": len(key["batches"])}))
        return 0
    tok = cast(Tok, load_tokenizer())
    doc = run_score(
        a.reports, views, a.key, a.labels_dir, a.costs, tok, a.seed, a.resamples,
        a.rubric, funnel,
    )  # fmt: skip
    for path, text in ((a.out, json.dumps(doc, indent=1) + "\n"), (a.md, render(doc))):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
    print(json.dumps({m: x["all"]["useful"] for m, x in doc["arms"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
