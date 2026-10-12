"""State sets for the cp decision-table rounds (ADR-0029): a tuning and a hold-out
set split by run, and constructed post-commit (S1) states, which real runs barely
reach. Offline: no key, no model call.

    python -m scripts.mod.cp_sets --evidence runs --seed N --out-dir <dir>

Writes ``tune.json`` and ``holdout.json`` (manifests for ``probe_same_state
--views-manifest``) and ``tune-s1.json`` and ``holdout-s1.json`` (views files for
``--views-file``). Set B and the pinned set C (S1-MOD-10) are hold-out as they are.
An S1 state is a real cp view at AWAITING_APPROVAL or COMMIT_AUTHORIZED in which
the representative has spoken, with an offer on the table, plus two lines: the
Guard's verbatim accept (in the kernel's wording, fc41ec 237.8 s) and one
representative template; CASE STATUS becomes COMMITTED, no hold stands (the kernel
fix of PLAN Now/Next item 2), and the trigger is ``rep_spoke``.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from proxyloop.contract import protocol as fp
from proxyloop.contract.state import CaseStatus, OfferPublic
from proxyloop.contract.views import FastView
from proxyloop.training import pull_through as pt
from scripts.mod import probe_same_state as pss
from scripts.mod import profile_sets as ps

Json = dict[str, Any]
SET_A = ps.SET_A_RUNS  # x-out-of-envelope-approval, before any approval
TUNE = (  # post-M1 runs whose states reach the card, a hold or a commit
    *SET_A,
    "20261011T232856Z-4b9901", "20261011T233912Z-afa368", "20261012T043721Z-99c310",
    "20261012T051522Z-aebf80", "20261012T032545Z-6ebdc0", "20261012T054553Z-9a7dd3",
    "20261012T062213Z-66518e", "20261012T063019Z-af5744",
)  # fmt: skip
HOLDOUT = (  # read as aggregates only (ADR-0029)
    "20261012T060408Z-fc41ec", "20261012T063803Z-0b2df4", "20261012T064250Z-618fc8",
    "20261012T063402Z-9a1849",
)  # fmt: skip
S1_CAP = {"tune": 20, "holdout": 12}
SOURCES = frozenset({CaseStatus.AWAITING_APPROVAL, CaseStatus.COMMIT_AUTHORIZED})
REP_AFTER = (
    "Done, the offer is accepted. Your confirmation number is {n}.",
    "Perfect, that's applied to the account and starts on your next bill.",
    "You're all set with the new plan. Is there anything else I can help you with?",
    "Great, it's done. You'll get an email with the details shortly.",
)
SELECTION: Json = {"include": [], "exclude": [], "seed_missing": None}


def said(o: OfferPublic) -> str:
    """The verbatim accept in the kernel's wording (fc41ec 237.8 s)."""
    parts: list[str] = []
    for s in o.slots:
        value = s.value
        if s.unit == "usd_minor":
            value = f"${int(s.value) / 100:.2f}"
        elif s.unit == "months":
            value = f"{s.value} months"
        parts.append(f"{s.field.replace('_', ' ')} {value}")
    return "Yes, we accept these terms: " + "; ".join(parts) + "."


def s1_entry(v: pss.View, i: int, rng: random.Random) -> Json:
    body = v.view.model_dump(mode="json")
    offer = v.view.offers[-1]
    template = REP_AFTER[i % len(REP_AFTER)].format(n=rng.randrange(100000, 1000000))
    body["transcript"] += [
        {"utt_id": f"s1-accept-{i}", "speaker": "agent", "text": said(offer)},
        {"utt_id": f"s1-rep-{i}", "speaker": "partner", "text": template},
    ]
    body |= {"status": CaseStatus.COMMITTED.value, "hold": None}
    body["trigger"] = {"kind": "rep_spoke"}
    view = FastView.model_validate(body)
    fp.render_messages(view, v.profile)  # renders
    out: Json = {"run_id": v.run_id, "turn": f"{v.turn}~s1-{i}", "lane": "cp"}
    out |= {"source_turn": v.turn, "class": "s1", "template": template}
    out |= {"source_status": v.view.status.value, "profile": v.profile}
    out |= {"sampling": v.sampling.model_dump(mode="json"), "seed": v.seed}
    out |= {"seed_source": v.seed_source}
    out["source_call"] = v.reference.model_dump(mode="json")
    return out | {"view": view.model_dump(mode="json")}


def s1_states(
    views: Sequence[pss.View], runs: Sequence[str], cap: int, seed: int
) -> list[Json]:
    """Seeded: up to ``cap`` states from the sources of ``runs``; when sources are
    fewer than ``cap``, a source is reused with the next template (correlated rows,
    disclosed in ``split.json``)."""
    pool = [
        v for v in views
        if v.run_id in runs and v.lane == "cp" and v.view.status in SOURCES
        and v.view.offers
        and any(x.speaker == "partner" for x in v.view.transcript)
    ]  # fmt: skip
    rng = random.Random(seed)
    pool = rng.sample(sorted(pool, key=lambda v: (v.run_id, v.turn)), len(pool))
    n = min(cap, len(pool) * len(REP_AFTER))
    return [s1_entry(pool[i % len(pool)], i, rng) for i in range(n)]


def manifest(views: Sequence[pss.View], runs: Sequence[str]) -> Json:
    listed = [{"run_id": v.run_id, "turn": v.turn} for v in views if v.run_id in runs]
    return {"about": "cp_sets (ADR-0029)", "selection": SELECTION, "views": listed}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.mod.cp_sets")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    a = parser.parse_args(argv)
    bundles = pt.load_bundles(a.evidence)
    views, _ = pss.collect(
        bundles, pt.current_fingerprints(), pss.HUGE, any_fingerprint=True
    )
    found = {v.run_id for v in views}
    if lost := [r for r in (*TUNE, *HOLDOUT) if r not in found]:
        raise SystemExit(f"runs without views: {lost}")
    a.out_dir.mkdir(parents=True, exist_ok=True)
    counts: Json = {}
    for name, runs in (("tune", TUNE), ("holdout", HOLDOUT)):
        m = manifest(views, runs)
        s1 = s1_states(views, runs, S1_CAP[name], a.seed)
        (a.out_dir / f"{name}.json").write_text(json.dumps(m, indent=1) + "\n")
        doc = {"about": "cp_sets S1 (ADR-0029)", "seed": a.seed, "views": s1}
        (a.out_dir / f"{name}-s1.json").write_text(json.dumps(doc, indent=1) + "\n")
        sources = len({x["source_turn"] for x in s1})
        counts[name] = {"views": len(m["views"]), "s1": len(s1), "s1_sources": sources}
        counts[name]["runs"] = list(runs)
    (a.out_dir / "split.json").write_text(json.dumps(counts, indent=1) + "\n")
    print(
        json.dumps({k: {"views": c["views"], "s1": c["s1"]} for k, c in counts.items()})
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
