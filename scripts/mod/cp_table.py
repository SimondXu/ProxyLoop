"""The cp decision table's checks (ADR-0029): the classes ``profile_check`` leaves
unscored. Offline: no key, no model call. ``profile_check`` stays as pinned
(ADR-0026); this module reuses its row check and adds:

- S1: after a commit (COMMITTED, EVIDENCE_PENDING, VERIFIED_COMPLETE) no ``@hold``,
  no read-back request, no "can't accept" (lexical);
- H4: a standing hold, the representative speaking or waiting: the same ``@hold``;
- H5: a standing hold, new guidance that is not a hold move: no ``@hold``;
- H7: stalling speech and a ``@hold`` go together, where no hold stands (lexical).

    python -m scripts.mod.cp_table --evidence runs \
        (--views-manifest <json> | --views-file <json>) --report <probe json>... \
        --out <json>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from proxyloop.contract import protocol as fp
from proxyloop.contract.state import CaseStatus
from proxyloop.kernel.lanes import load_tokenizer
from scripts.mod import probe_same_state as pss
from scripts.mod import profile_check as pc
from scripts.mod import profile_sets as ps
from scripts.mod import teacher_select as ts

Json = dict[str, Any]
RULES = ("S1", "H4", "H5")
DONE = frozenset(
    {CaseStatus.COMMITTED, CaseStatus.EVIDENCE_PENDING, CaseStatus.VERIFIED_COMPLETE}
)
STALL = re.compile(
    r"\b(?:check(?:ing)? with (?:my|the|our) (?:customer|client|account holder)"
    r"|please hold|hold on|hold (?:for )?a moment|one moment|bear with me)\b",
    re.I,
)
S1_LEXICON = {
    "readback": re.compile(r"\bread (?:\w+ )?back\b", re.I),
    "cant_accept": re.compile(
        r"\b(?:can(?:no|')t|cannot|not able to|unable to|not authori[sz]ed to)"
        r" (?:accept|agree|commit)",
        re.I,
    ),
}


def rule(v: pss.View) -> str | None:
    """The table rule this module scores for a row (ADR-0029); None: another rule
    (``profile_check.hold_label`` scores H1-H3 and H6) or the user lane."""
    fv = v.view
    if v.lane != "cp":
        return None
    if fv.status in DONE:
        return "S1"
    if fv.hold is not None and fv.trigger.kind in ("rep_spoke", "hold_wait"):
        return "H4"
    if fv.hold is not None and fv.trigger.kind == "guidance":
        return None if ps.move(v) in ts.HOLD_MOVES else "H5"
    return None


def check(row: Json, v: pss.View, tok: ts.Tok) -> Json:
    """One row against its rule; an error row fails it (``profile_check`` NOTES)."""
    base, r = pc.check_row(row, v, None, tok), rule(v)
    out: Json = {"rule": r, "error": base["error"], "held": base["held"]}
    if base["error"]:
        none: Json = {"incoherent": False, "h7_scored": False, "s1_hits": []}
        return out | none | {"ok": False if r else None}
    items = fp.parse_turn(row["raw"], v.lane, pc.rendered(row, v))
    speech = " ".join(i.text for i in items if isinstance(i, fp.Speech))
    held = base["held"] is not None
    scored = v.lane == "cp" and v.view.hold is None
    out["h7_scored"] = scored
    out["incoherent"] = scored and bool(STALL.search(speech)) != held
    hits = (["hold"] if held else []) + [
        k for k, rx in S1_LEXICON.items() if rx.search(speech)
    ]
    out["s1_hits"] = hits if r == "S1" else []
    hold = v.view.hold
    ok = {"S1": not hits, "H4": hold is not None and base["held"] == hold.reason}
    out["ok"] = (ok | {"H5": not held}).get(r) if r else None
    return out


def tally(cs: Sequence[Json]) -> Json:
    """[k, n] per rule (k = rows that follow it), the S1 hits by kind and H7's
    incoherent rows over the cp rows without a standing hold."""
    out: Json = {
        r: [
            sum(bool(c["ok"]) for c in cs if c["rule"] == r),
            sum(c["rule"] == r for c in cs),
        ]
        for r in RULES
    }
    out["s1_hits"] = {
        k: sum(k in c["s1_hits"] for c in cs) for k in ("hold", *S1_LEXICON)
    }
    scored = [c for c in cs if c["h7_scored"]]
    out["incoherent"] = [sum(c["incoherent"] for c in scored), len(scored)]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.mod.cp_table")
    parser.add_argument("--evidence", type=Path, required=True)
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--views-manifest", type=Path)
    src.add_argument("--views-file", type=Path, help="constructed views (cp_sets)")
    parser.add_argument("--max-views", type=int, default=pss.HUGE)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    a = parser.parse_args(argv)
    a.no_reference = a.views_file is not None  # a views file has no reference
    views, funnel = ts.views_of(a)
    at = {(v.run_id, v.turn): v for v in views}
    tok, doc = cast(ts.Tok, load_tokenizer()), {"funnel": funnel, "arms": {}}
    for path in a.report:
        arms, _, _ = ts.load([path], views, a.no_reference)
        for arm, rows in arms.items():
            cs = [check(r, at[k], tok) for k, r in rows.items()]
            doc["arms"].setdefault(arm, tally(cs))
    a.out.write_text(json.dumps(doc, indent=1) + "\n", "utf-8")
    print(json.dumps(doc["arms"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
