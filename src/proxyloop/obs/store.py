"""The run ledger: ``diagnose``'s rows in a local Postgres (S1-SYS-120).

ADVISORY ONLY, like diagnose: triage across runs and families, never a metric,
a claim or a merge gate. No agent reads it (NORTH_STAR I5).

``python -m proxyloop.obs.store ingest [--root DIR ...]`` upserts one
``run_grade`` row per ok run (``diagnose.rows``: sealed data is never read),
then fails unless ``family_status`` holds exactly ``tiers.summary``'s counts
per group. ``run_grade`` is a projection: ``rebuild`` empties it and ingests
again. ``fix SIG PR`` records which PR addressed a signature; ``status`` and
``sigs`` print the two views.

A signature is family|tier|reason|first_missing (``-``: none) for every run,
success or not: ADR-0023 gives no computable success, so which signatures are
failures is read by a person, never decided here. ``sig_ledger.status``: ``open`` (no
fix), ``recurring`` (a run started after the newest fix), else ``fixed?``
with ``family_runs_since_fix`` as its only evidence.

DSN: ``PL_LEDGER_DSN``, default the compose ``ledger`` service
(127.0.0.1:5433, trust auth, no secret).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import LiteralString, cast

import psycopg
from psycopg.types.json import Jsonb

from proxyloop.obs import diagnose, runs, tiers
from proxyloop.obs.detectors import as_dict
from proxyloop.obs.triage import Row

DSN = "postgresql://postgres@127.0.0.1:5433/postgres"

SCHEMA = """
CREATE TABLE IF NOT EXISTS run_grade (
  run_id text PRIMARY KEY,
  grp text NOT NULL,
  started timestamptz,
  task_ref text,
  family text,
  kind text,
  tier text,
  reason text,
  first_missing text,
  sig text,
  row jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS fix (
  sig text NOT NULL,
  pr integer NOT NULL,
  at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (sig, pr)
);
CREATE OR REPLACE VIEW family_status AS
  SELECT grp, family, kind, tier, count(*)::int AS n
  FROM run_grade WHERE tier IS NOT NULL GROUP BY grp, family, kind, tier;
CREATE OR REPLACE VIEW sig_ledger AS
  SELECT g.sig, g.family, count(*)::int AS runs,
    min(g.started) AS first_seen, max(g.started) AS last_seen, f.prs,
    CASE WHEN f.at IS NULL THEN 'open'
         WHEN max(g.started) > f.at THEN 'recurring' ELSE 'fixed?' END AS status,
    (SELECT count(*)::int FROM run_grade r
       WHERE r.family = g.family AND r.started > f.at) AS family_runs_since_fix
  FROM run_grade g
  LEFT JOIN (SELECT sig, max(at) AS at, array_agg(pr ORDER BY pr) AS prs
             FROM fix GROUP BY sig) f USING (sig)
  WHERE g.sig IS NOT NULL
  GROUP BY g.sig, g.family, f.prs, f.at;
"""

_UPSERT = """
INSERT INTO run_grade VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (run_id) DO UPDATE SET (grp, started, task_ref, family, kind, tier,
  reason, first_missing, sig, row) = (EXCLUDED.grp, EXCLUDED.started,
  EXCLUDED.task_ref, EXCLUDED.family, EXCLUDED.kind, EXCLUDED.tier,
  EXCLUDED.reason, EXCLUDED.first_missing, EXCLUDED.sig, EXCLUDED.row)
"""


def record(r: Row) -> tuple[object, ...]:
    """One ``run_grade`` row: the tier label as ``tiers.summary`` counts it, the
    signature, and the whole diagnose row."""
    family, kind, tier = tiers.label(r) or (None, None, None)
    reason = as_dict(as_dict(r.get("detectors")).get("tier")).get("reason")
    missing = as_dict(r.get("progress")).get("first_missing")
    sig = None if family is None else f"{family}|{tier}|{reason}|{missing or '-'}"
    return (
        r["run_id"], diagnose.group(r), r.get("started"), r.get("task_ref"),
        family, kind, tier, reason, missing, sig, Jsonb(r),
    )  # fmt: skip


def expected(found: Sequence[Row]) -> set[tuple[str, str, str, str, int]]:
    """``tiers.summary``'s counts per group, as ``family_status`` rows."""
    groups: dict[str, list[Row]] = {}
    for r in found:
        groups.setdefault(diagnose.group(r), []).append(r)
    out = set[tuple[str, str, str, str, int]]()
    for g, members in groups.items():
        fams = as_dict(tiers.summary(members)["families"])
        for family, kinds in fams.items():
            for kind, counts in as_dict(kinds).items():
                for tier, n in as_dict(counts).items():
                    out.add((g, family, kind, tier, cast(int, n)))
    return out


def ingest(conn: psycopg.Connection, roots: Sequence[Path]) -> int:
    """Upsert every ok run under ``roots``; 1 when ``family_status`` differs
    from ``tiers.summary`` over the ledger's rows for those groups."""
    found, skipped = diagnose.rows(roots)
    for why in skipped:
        print(f"skipped: {why}", file=sys.stderr)
    with conn.transaction():
        conn.execute(SCHEMA)
        for r in found:
            conn.execute(_UPSERT, record(r))
    groups = sorted({diagnose.group(r) for r in found})
    stored = conn.execute(
        "SELECT row FROM run_grade WHERE grp = ANY(%s)", (groups,)
    ).fetchall()
    have = set(
        conn.execute(
            "SELECT grp, family, kind, tier, n FROM family_status WHERE grp = ANY(%s)",
            (groups,),
        ).fetchall()
    )
    want = expected([cast(Row, row) for (row,) in stored])
    print(f"ingested {len(found)} runs, skipped {len(skipped)}, groups {len(groups)}")
    if have != want:
        drift = f"only in PG {sorted(have - want)}, in tiers {sorted(want - have)}"
        print(f"family_status drift: {drift}", file=sys.stderr)
        return 1
    return 0


def _print(conn: psycopg.Connection, query: LiteralString) -> None:
    cur = conn.execute(query)
    print("\t".join(c.name for c in cur.description or ()))
    for values in cur:
        print("\t".join("" if v is None else str(v) for v in values))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m proxyloop.obs.store")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("ingest", "rebuild"):
        sub.add_parser(name).add_argument("--root", type=Path, action="append")
    fix = sub.add_parser("fix")
    fix.add_argument("sig")
    fix.add_argument("pr", type=int)
    sub.add_parser("status")
    sub.add_parser("sigs")
    args = parser.parse_args(argv)
    with psycopg.connect(os.environ.get("PL_LEDGER_DSN", DSN)) as conn:
        conn.execute(SCHEMA)
        if args.cmd in ("ingest", "rebuild"):
            roots = args.root or [p for p in (Path("runs"), Path("evidence"))
                                  if p.is_dir()]  # fmt: skip
            if sealed := [str(r) for r in roots if runs.Seal().covers(r)]:
                print(f"refused: {', '.join(sealed)} is sealed (AGENTS rule 11)",
                      file=sys.stderr)  # fmt: skip
                return 2
            if args.cmd == "rebuild":
                conn.execute("TRUNCATE run_grade")
            return ingest(conn, roots)
        if args.cmd == "fix":
            conn.execute("INSERT INTO fix VALUES (%s, %s)", (args.sig, args.pr))
        elif args.cmd == "status":
            _print(conn, "SELECT * FROM family_status ORDER BY grp, family, kind, tier")
        else:
            _print(conn, "SELECT * FROM sig_ledger ORDER BY family, runs DESC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
