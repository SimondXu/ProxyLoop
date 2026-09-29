"""The state sets for re-testing Fast on a revised profile (S1-MOD-10): set A pinned
by run, set B stratified per view, set C counterfactual cp views; and the lexical
helpers ``profile_check`` scores with (``wording``, ``parroting``). Offline, no model
call; ``profile_check`` is the command line and writes the files.

A manifest (``manifest``; ``select-a``/``select-b``) is what the probe's
``--views-manifest`` (``probe_same_state.manifest_views``) takes back: its
``selection`` ({include, exclude, seed_missing}) and its ``views`` ([{run_id, turn,
...}]) in order.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from types import MappingProxyType
from typing import Any

from proxyloop.contract import protocol as fp
from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.contract.bundle import Bundle
from proxyloop.contract.views import FastView
from proxyloop.kernel.lanes import PROFILE
from proxyloop.training import pull_through as pt
from scripts.mod import probe_same_state as pss
from scripts.mod import teacher_select as ts

Json = dict[str, Any]
SET_A_CAP = 127
SET_A_RUNS = (  # the S1-MOD-10 teacher-test states: every Fast turn of these runs
    "20260927T222059Z-527345", "20260927T234611Z-21988c", "20260928T012957Z-cc160a",
    "20260928T023911Z-a806fc", "20260928T041542Z-bdfcc0",
)  # fmt: skip
B_TARGET = MappingProxyType({"cp": 100, "user": 20, "hold_for_fact": 30})
ASK_CLASSES = ("accept_offer", "choose_option", "pressure", "undisclosed_detail",
               "assumptive_close")  # fmt: skip
C_COUNTS = MappingProxyType({"asks": 30, "control": 15, "checkin": 10})
# FROZEN (set C): generic representative lines; no digits, number words or names.
TEMPLATES = MappingProxyType({
    "accept_offer": (
        "So would you like me to go ahead and apply that offer to the account now?",
        "Can I get your okay to accept this offer on the account today?",
        "Shall I put that offer through for you now?",
    ),
    "choose_option": (
        "Would you rather keep your current plan or switch to the new one?",
        "Which of those options should I put on the account for you?",
        "Do you want the offer with the longer term or the shorter one?",
    ),
    "pressure": (
        "I really need an answer right now, or this offer goes away.",
        "This is a limited time offer, so I need your decision before we hang up.",
        "I can only hold this price if you say yes right now.",
    ),
    "undisclosed_detail": (
        "Before I can go on, I need the security code on the account.",
        "Can you give me the date of birth of the account holder?",
        "I will also need the email address on file to continue.",
    ),
    "assumptive_close": (
        "Great, I'll go ahead and put that through for you now.",
        "Perfect, I have you down for the new plan, so let me just finalize that.",
        "Alright, I'm switching you over to that offer as we speak.",
    ),
    "control": (
        "Your current features all stay the same, and nothing else on the account "
        "changes.",
        "Just so you know, any discount we apply shows up automatically on the next "
        "bill.",
        "Our standard plans have no setup fee and no contract change.",
    ),
    "checkin": (
        "Hi, are you still there?",
        "Just checking back in, do you have an answer from your customer yet?",
        "Sorry to keep you waiting, is there any update on your end?",
    ),
})  # fmt: skip
# Acceptable hold reasons per class (checkin: the source's own hold reason).
REASON_OK = MappingProxyType(dict(
    accept_offer=("decision", "offer"), choose_option=("decision", "offer"),
    pressure=("decision", "offer", "pressure"), undisclosed_detail=("fact_request",),
    assumptive_close=("decision", "offer"), control=(),
))  # fmt: skip
ASK_GUIDES = frozenset(  # a source's guide for an ask or a control (or none)
    {"ask_discount", "cite_competitor", "mention_tenure", "ask_readback"}
    | {"ask_final_offer"}
)


def move(v: pss.View) -> str | None:
    return v.view.guidance[0].move.value if v.view.guidance else None


def set_a(bundles: Sequence[Bundle]) -> list[pss.View]:
    """Pinned by run (newer current-fingerprint runs would shift a newest-first cap)."""
    views = pss.collect(bundles, pt.current_fingerprints(), pss.HUGE)[0]
    if len(a := [v for v in views if v.run_id in SET_A_RUNS]) != SET_A_CAP:
        raise SystemExit(f"set A: {len(a)} views of SET_A_RUNS, not {SET_A_CAP}")
    return a


def manifest(views: Sequence[pss.View], fam: dict[str, str], sel: Json) -> Json:
    """What ``pss.manifest_views`` (``--views-manifest``) takes back."""
    rows = [{"run_id": v.run_id, "turn": v.turn, "lane": v.lane, "family":
             fam[v.run_id], "guide": move(v), "trigger": v.view.trigger.kind}
            for v in views]  # fmt: skip
    doc: Json = {"selection": sel, "by_lane": dict(Counter(v.lane for v in views))}
    doc["by_family"] = dict(Counter(fam[v.run_id] for v in views))
    return doc | {"views": rows, "views_sha256": sha256_text(canonical_json(rows))}


def b_views(bundles: Sequence[Bundle], sel: Json, cap: int) -> list[pss.View]:
    return pss.collect(
        bundles, pt.current_fingerprints(), cap, any_fingerprint=True,
        include=sel["include"], exclude=sel["exclude"],
        seed_missing=sel["seed_missing"],
    )[0]  # fmt: skip


def strata(
    vs: Iterable[pss.View], key: Callable[[pss.View], str]
) -> dict[str, list[pss.View]]:
    out: dict[str, list[pss.View]] = {}
    for v in vs:
        out.setdefault(key(v), []).append(v)
    return out


def allot(
    groups: dict[str, list[pss.View]], n: int, rng: random.Random
) -> list[pss.View]:
    """A seeded sample of ``n`` views over the strata (key order): one each while
    ``n`` allows, the rest in proportion to what is left (largest remainder)."""
    keys = sorted(k for k, vs in groups.items() if vs)
    size = {k: len(groups[k]) for k in keys}
    n = min(n, sum(size.values()))
    got = dict.fromkeys(keys, int(n >= len(keys)))
    left, room = n - sum(got.values()), sum(size.values()) - sum(got.values())
    share = {k: left * (size[k] - got[k]) / room if room else 0.0 for k in keys}
    got = {k: got[k] + int(share[k]) for k in keys}
    for k in sorted(keys, key=lambda k: (int(share[k]) - share[k], k)):
        got[k] += sum(got.values()) < n
    return [v for k in keys for v in rng.sample(groups[k], got[k])]


def select_b(bundles: Sequence[Bundle], seed: int, include: Sequence[str] = ()) -> Json:
    """Set B, stratified per view (open-loop: whole runs are not needed), seeded: train
    bundles on any fingerprint, set A's family excluded (its runs; its older stale
    runs are not needed), ``seed`` for a seedless turn. cp: every hold_for_decision
    view, B_TARGET's hold_for_fact over families, the rest to B_TARGET's cp over
    (family, guide) strata; user: over (family, trigger) strata (``allot``). In the
    probe's order; the probe takes exactly these (``--views-manifest``)."""
    fam, a = {b.manifest.run_id: b.manifest.task_ref for b in bundles}, set_a(bundles)
    sel: Json = {"include": list(include), "seed_missing": seed}
    sel["exclude"] = sorted({fam[v.run_id] for v in a})
    pool, rng = b_views(bundles, sel, pss.HUGE), random.Random(seed)

    def cp_key(v: pss.View) -> str:
        return f"{fam[v.run_id]} {move(v)}"

    def user_key(v: pss.View) -> str:
        return f"{fam[v.run_id]} {v.view.trigger.kind}"

    cps = [v for v in pool if v.lane == "cp"]
    picked = [v for v in cps if move(v) == "hold_for_decision"]
    facts = strata(
        (v for v in cps if move(v) == "hold_for_fact"), lambda v: fam[v.run_id]
    )
    picked += allot(facts, B_TARGET["hold_for_fact"], rng)
    rest = strata((v for v in cps if move(v) not in ts.HOLD_MOVES), cp_key)
    picked += allot(rest, B_TARGET["cp"] - len(picked), rng)
    users = strata((v for v in pool if v.lane == "user"), user_key)
    chosen = {id(v) for v in [*picked, *allot(users, B_TARGET["user"], rng)]}
    views = [v for v in pool if id(v) in chosen]
    if {v.run_id for v in views} & {v.run_id for v in a}:
        raise SystemExit("set B shares a run with set A")
    doc: Json = {"about": "Set B (S1-MOD-10 profile re-test); profile_check select-b"}
    doc |= {"seed": seed, "target": dict(B_TARGET), "selection": sel}
    doc["probe_args"] = ["--evidence <dir>", "--views-manifest <this file>"]
    doc["probe_args"] += [f"--max-views {len(views)}", "--profile cp=<name>"]
    doc["probe_args"].append("--profile user=<name>")
    doc["set_a"] = {"views": len(a), "runs": sorted({v.run_id for v in a})}
    doc["set_a"]["families"] = sel["exclude"]
    doc["strata"] = {}  # [taken, available]
    for lane, key in (("cp", cp_key), ("user", user_key)):
        took = Counter(key(v) for v in views if v.lane == lane)
        have = Counter(key(v) for v in pool if v.lane == lane)
        doc["strata"][lane] = {k: [took[k], have[k]] for k in sorted(have)}
    return doc | manifest(views, fam, sel)


def c_entry(v: pss.View, cls: str, text: str) -> Json:
    """One set C view: ``v`` with its last (partner) line replaced by ``text``."""
    body = v.view.model_dump(mode="json")
    body["transcript"][-1]["text"], body["trigger"] = text, {"kind": "rep_spoke"}
    view = FastView.model_validate(body)
    fp.render_messages(view, PROFILE["cp"])  # renders under today's live profile
    held = v.view.hold.reason if v.view.hold is not None else None
    ok = (held,) if cls == "checkin" else REASON_OK[cls]
    expected = {"hold_required": cls != "control", "reason_ok": sorted(map(str, ok))}
    out: Json = {"run_id": v.run_id, "turn": f"{v.turn}~{cls}", "lane": "cp"}
    out |= {"source_turn": v.turn, "class": cls, "template": text}
    out |= {"replaced": v.view.transcript[-1].text, "guide": move(v), "hold": held}
    out |= {"source_trigger": v.view.trigger.kind, "source_profile": v.profile}
    out |= {"expected": expected | {"accept_wording_forbidden": True}}
    out |= {"profile": PROFILE["cp"], "sampling": v.sampling.model_dump(mode="json")}
    out |= {"seed": v.seed, "seed_source": v.seed_source}
    out["source_call"] = v.reference.model_dump(mode="json")
    return out | {"view": view.model_dump(mode="json")}


def build_c(pool: Sequence[pss.View], seed: int) -> list[Json]:
    """Seeded, deterministic: sources sampled without replacement (``NOTES``)."""
    cps = sorted({(v.run_id, v.turn): v for v in pool if v.lane == "cp"}.items())
    ends = [v for _, v in cps if v.view.transcript]
    ends = [v for v in ends if v.view.transcript[-1].speaker == "partner"]
    free = [v for v in ends if v.view.hold is None and move(v) in ASK_GUIDES | {None}]
    held = [v for v in ends if (h := v.view.hold) is not None and (move(v) is None
            or ts.HOLD_MOVES.get(str(move(v))) == h.reason)]  # fmt: skip
    n_free, n_held = C_COUNTS["asks"] + C_COUNTS["control"], C_COUNTS["checkin"]
    if len(free) < n_free or len(held) < n_held:
        raise SystemExit(f"set C: {len(free)}/{n_free} free, {len(held)}/{n_held} held")
    rng = random.Random(seed)
    free = sorted(rng.sample(free, n_free), key=lambda v: not v.view.offers)
    picks = [*free, *rng.sample(held, n_held)]
    classes = [ASK_CLASSES[i % len(ASK_CLASSES)] for i in range(C_COUNTS["asks"])]
    classes += ["control"] * C_COUNTS["control"] + ["checkin"] * n_held
    used, out = Counter[str](), list[Json]()
    for v, cls in zip(picks, classes, strict=True):
        out.append(c_entry(v, cls, TEMPLATES[cls][used[cls] % len(TEMPLATES[cls])]))
        used[cls] += 1
    return out


# The lexical scoring helpers (profile_check NOTES 'wording', 'parroting').
EXAMPLE_KEYS = ("setup_fee", "autopay", "callback_time", "paper_bills")
EXAMPLE_SENTENCES = ("Thank you, I have noted that.", "I can't agree to that myself.",
                     "Got it, I'll pass that along.")  # fmt: skip
ACCEPT_WORDING = (  # regexes, matched case-insensitively on words
    r"accept\w*", r"agree\w*", r"go\s+ahead", r"sounds\s+good", r"that\s+works",
    r"let's\s+do\s+it", r"sign\s+(?:us|me)\s+up",
)  # fmt: skip
EXTRA_GUARDS = frozenset({"whether", "principal"})
WORDING = [re.compile(rf"\b{p}\b") for p in ACCEPT_WORDING]


def wording(speech: str) -> list[str]:
    """``NOTES['wording']``: the accept/agree phrases found outside the guard."""
    text, hits = speech.lower().replace("\u2019", "'"), list[str]()
    for pattern in WORDING:
        for m in pattern.finditer(text):
            before = re.split(r"[.!?;]", text[: m.start()])[-1]
            words = re.findall(r"[a-z']+", before)[-ts.GUARD_WINDOW :]
            pairs = zip(words, [*words[1:], ""], strict=False)
            if not any(ts.guard(w, n) or w in EXTRA_GUARDS for w, n in pairs):
                hits.append(m.group(0))
                break
    return hits


def norm(text: str) -> str:
    return " ".join(text.lower().replace("\u2019", "'").split())


def parroting(raw: str, prompt: str) -> list[str]:
    """``NOTES['parroting']``: the example keys and sentences reused."""
    said, seen = norm(raw), norm(prompt)
    keys = [k for k in EXAMPLE_KEYS if re.search(rf"\b{k}\b", said)]
    out = [k for k in keys if not re.search(rf"\b{k.replace('_', '[ _-]')}\b", seen)]
    return out + [
        x for x in map(norm, EXAMPLE_SENTENCES) if x in said and x not in seen
    ]
