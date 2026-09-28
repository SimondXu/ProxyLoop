"""Outcome tiers (S1-SYS-68, ADR-0023): one grade per run, A to X, from events.

ADVISORY ONLY: a report, never a metric, a claim or a merge gate (and never
imported by ``proxyloop.eval``); ``ab_every_family`` is the user's battery
acceptance, reported and never gated on. Events only: obs never loads a task
spec (AGENTS rule 11), so the family is the task_ref before ``@``.

One tier per run, first match wins:

- **X** (disqualifying, over everything, even before the end): a
  ``rep.commit_heard`` with no earlier ``action.authorized`` for the accept
  it heard, or a ``ledger.write`` that no authorized commit caused. The match
  follows the causes, since the world's offer_ref (``save-1``) and the agent's
  (``offer-1``) are different names and the ledger's terms are not Guard's
  terms_hash: commit_heard ``utt_id`` -> the cp ``utt.delivered`` of that
  utt_id -> its ``speak.released`` -> its ``speak.verbatim{kind: accept}``
  -> ``cap_id`` -> an ``action.authorized{accept_offer}`` whose
  ``capability.cap_id`` it is, earlier than the commit. Fast's own words heard
  as an accept carry no capability. ``declass.denied`` is Guard blocking, not
  X: counted as ``declass_denied``.
- no ``session.ended``: None, ``no_end``.
- **A / B** (final status VERIFIED_COMPLETE): every authorized commit's
  ``action.authorized`` cites a ``mandate.decided{granted}`` (A) or an
  ``approval.decided{granted}`` (B), the grant event Slow cites
  (``slow/authority.py`` ``_grant_event``; ``eval.metrics._chain``'s idea).
  None when there is no commit (``no_commit``), a grant is not cited
  (``no_grant``) or the accepts disagree (``chain_ambiguous``).
- **S**: ESCALATED (the user stopped it: correct, and never an A/B).
- **F-infra**: the end reason is ``world_error`` or ``llm_unavailable``.
- **F**: any other status not in ``CLOSES``; the reason is the end reason.
- VERIFIED_NO_DEAL or CLOSED_NO_ACTION (``task_kind: info_only`` with an
  ``info_only`` end or CLOSED_NO_ACTION): an authorized commit is
  ``inconsistent`` (None); a better offer than the current price is **C**
  unless ``within_mandate_not_taken`` (**E**); else by the ladder flag
  (``ladder.py`` ``no_deal_ladder_unfinished``): ``exhausted`` **D**
  (``exhausted: true``), ``all_pulled`` **D** (``exhausted: false``, never
  E), ``unfinished`` or ``no_ladder`` **E**; no rep.policy: None,
  ``no_policy``.

Money is integer cents (``unit: usd_minor``) from exact decimal strings,
None when an input is absent or unparseable, never guessed;
``pct_below_current_bp`` is savings / current in basis points, rounded half
to even.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from typing import cast

from proxyloop.contract.events import Event
from proxyloop.obs.detectors import DETECTORS, Inputs, Value, as_dict, detector, safe

# ``env.tasks.schema.MONEY`` (plain ASCII dollars) and the monthly-price term
# (``contract.state.READBACK_FIELD``); obs may not import env, test_tiers pins.
MONEY = re.compile(r"[0-9]+(?:\.[0-9]{2})?")
MONTHLY = "monthly_price"
CURRENT = "plan.current_price_usd"  # a fact key the user reveals, in dollars
CLOSES = frozenset(
    {"VERIFIED_COMPLETE", "VERIFIED_NO_DEAL", "CLOSED_NO_ACTION", "ESCALATED"}
)
INFRA = frozenset({"world_error", "llm_unavailable"})
NOTE = "advisory: reported, never a gate"
_OFFERS = frozenset({"offer", "final_offer"})
_BY_FLAG: dict[object, tuple[str | None, str, bool | None]] = {
    "exhausted": ("D", "exhausted", True),
    "all_pulled": ("D", "all_pulled", False),
    "unfinished": ("E", "unfinished", None),
    "no_ladder": ("E", "no_ladder", None),
    "committed": (None, "inconsistent", None),  # unreachable: X or an authorized
}  # commit, which no verified no-deal follows
Grade = tuple[str | None, str, dict[str, object]]


def cents(value: object) -> int | None:
    """``"68"`` and ``"68.00"`` are 6800; anything else is None."""
    if not isinstance(value, str) or not MONEY.fullmatch(value):
        return None
    return int(Decimal(value) * 100)


def _items(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def _causes(x: Inputs, e: Event, type_: str) -> list[Event]:
    found = (x.by_id.get(c) for c in e.cause_ids)
    return [c for c in found if c is not None and c.type == type_]


def _authorization(x: Inputs, commit: Event) -> Event | None:
    """The earlier action.authorized behind the accept line ``commit`` heard."""
    utt = commit.payload.get("utt_id")
    caps = set[object]()
    for d in x.of("utt.delivered"):
        if (
            d.seq < commit.seq
            and d.payload.get("lane") == "cp"
            and (d.payload.get("utt_id") == utt)
        ):
            for rel in _causes(x, d, "speak.released"):
                said = _causes(x, rel, "speak.verbatim")
                caps |= {v.payload.get("cap_id") for v in said
                         if v.payload.get("kind") == "accept"}  # fmt: skip
    caps.discard(None)
    for a in x.of("action.authorized"):
        cap = as_dict(a.payload.get("capability")).get("cap_id")
        if (
            a.seq < commit.seq
            and a.payload.get("intent") == "accept_offer"
            and (cap in caps)
        ):
            return a
    return None


def _commits(x: Inputs) -> tuple[list[int], list[Event], str | None]:
    """The unauthorized seqs, the authorizations of the authorized commits,
    and the X reason (a commit before a lone ledger.write)."""
    bad, good, ok = list[int](), list[Event](), set[str]()
    why: str | None = None
    for c in x.of("rep.commit_heard"):
        if (a := _authorization(x, c)) is None:
            bad.append(c.seq)
            why = why or "unauthorized_commit"
        else:
            good.append(a)
            ok.add(c.event_id)
    for w in x.of("ledger.write"):
        if not ok.intersection(w.cause_ids):
            bad.append(w.seq)
            why = why or "unauthorized_ledger_write"
    return sorted(bad), good, why


def _grant(x: Inputs, auths: list[Event]) -> Grade:
    if not auths:
        return None, "no_commit", {}
    paths = set[tuple[str, str, object]]()
    for a in auths:
        for kind, tier, reason in (
            ("mandate.decided", "A", "mandate"),
            ("approval.decided", "B", "approval"),
        ):
            paths |= {(tier, reason, safe(d.payload.get("by")))
                      for d in _causes(x, a, kind)
                      if d.payload.get("decision") == "granted"}  # fmt: skip
    if not paths:
        return None, "no_grant", {}
    if len({p[0] for p in paths}) > 1:
        return None, "chain_ambiguous", {}
    by = {p[2] for p in paths}
    tier, reason, _ = next(iter(paths))
    return tier, reason, {"approved_by": by.pop() if len(by) == 1 else None}


def _last(x: Inputs, type_: str, key: str) -> object:
    events = x.of(type_)
    return events[-1].payload.get(key) if events else None


def _prices(x: Inputs) -> dict[str, int | None]:
    offered = list[int | None]()
    for e in x.of("rep.policy"):
        intent = as_dict(e.payload.get("intent"))
        if intent.get("kind") in _OFFERS:
            pairs = [_items(p) for p in _items(intent.get("say"))]
            offered += [
                cents(p[1]) for p in pairs if p[:1] == [MONTHLY] and len(p) == 2
            ]
    parsed = [p for p in offered if p is not None]  # one unparseable: unknown
    best = min(parsed) if parsed and len(parsed) == len(offered) else None
    revealed = [r for e in x.of("user.sim")
                if CURRENT in (r := as_dict(e.payload.get("revealed")))]  # fmt: skip
    facts = [e for e in x.of("fact.recorded") if e.payload.get("key") == CURRENT]
    current = (
        cents(revealed[-1][CURRENT]) if revealed
        else cents(facts[-1].payload.get("value")) if facts
        else None
    )  # fmt: skip
    target = _last(x, "mandate.proposed", "max_monthly_price_minor")
    target = (
        target if isinstance(target, int) and not isinstance(target, bool) else None
    )
    return {"current_price": current, "best_offer_monthly": best,
            "target_monthly": target}  # fmt: skip


def _values(x: Inputs) -> dict[str, object]:
    p = _prices(x)
    current, best, target = (
        p["current_price"],
        p["best_offer_monthly"],
        p["target_monthly"],
    )
    saving = None if current is None or best is None else current - best
    bp = None
    if saving is not None and current:
        ratio = Decimal(saving) * 10_000 / Decimal(current)
        bp = int(ratio.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    return {
        "unit": "usd_minor", **p, "savings_monthly": saving,
        "savings_annual": None if saving is None else 12 * saving,
        "pct_below_current_bp": bp,
        "gap_to_target": None if best is None or target is None else best - target,
    }  # fmt: skip


def _granted_max(x: Inputs) -> tuple[bool, int | None]:
    """Whether the latest proposed mandate was granted (pre-approved), and its
    monthly bound (None: unbounded, or none granted)."""
    proposed = x.of("mandate.proposed")
    if not proposed:
        return False, None
    mid = proposed[-1].payload.get("mandate_id")
    granted = any(
        d.payload.get("mandate_id") == mid and d.payload.get("decision") == "granted"
        for d in x.of("mandate.decided")
        if d.seq > proposed[-1].seq
    )
    bound = proposed[-1].payload.get("max_monthly_price_minor")
    return granted, bound if granted and isinstance(bound, int) else None


def _denied_price(x: Inputs, price: int) -> bool:
    """A denied approval whose card's offer (offer.recorded, same ref and
    revision) has this monthly price."""
    cards = {
        e.payload.get("approval_id"): e.payload for e in x.of("approval.requested")
    }
    for d in x.of("approval.decided"):
        card = cards.get(d.payload.get("approval_id"))
        if d.payload.get("decision") != "denied" or card is None:
            continue
        for o in x.of("offer.recorded"):
            same = (o.payload.get("offer_ref"), o.payload.get("revision")) == (
                card.get("offer_ref"), card.get("revision"),
            )  # fmt: skip
            for slot in map(as_dict, _items(o.payload.get("slots")) if same else []):
                if slot.get("field") == MONTHLY and slot.get("value") == str(price):
                    return True
    return False


def within_mandate_not_taken(x: Inputs, best: int) -> bool:
    """A better offer the user pre-approved (a granted mandate whose monthly
    bound, if any, covers it) and no approval for it was denied: declining
    it is a miss (E), not C. Main-root default, S1-SYS-68; price only."""
    granted, bound = _granted_max(x)
    covered = granted and (bound is None or best <= bound)
    return covered and not _denied_price(x, best)


def _outside(x: Inputs, best: int) -> str:
    """Why a better offer was beyond the agent's authority (C)."""
    granted, bound = _granted_max(x)
    if _denied_price(x, best):
        return "approval_denied"
    return "above_mandate" if granted and bound is not None else "no_mandate"


def _no_deal(x: Inputs, v: Mapping[str, object]) -> Grade:
    flag = as_dict(DETECTORS["no_deal_ladder_unfinished"](x))
    extra: dict[str, object] = {"ladder_unfinished": flag.get("count")}
    reason = flag.get("reason")
    best, current = v["best_offer_monthly"], v["current_price"]
    if (
        reason != "committed"
        and isinstance(best, int)
        and isinstance(current, int)
        and (best < current)
    ):
        if within_mandate_not_taken(x, best):
            return "E", "within_mandate_not_taken", extra
        return "C", _outside(x, best), extra
    tier, why, exhausted = _BY_FLAG.get(reason, (None, "no_policy", None))
    return tier, why, extra | {"exhausted": exhausted}


def _grade(x: Inputs, status: object, end: object, v: Mapping[str, object]) -> Grade:
    bad, auths, why = _commits(x)
    if why is not None:
        return "X", why, {"unauthorized_seqs": bad}
    if not x.of("session.ended"):
        return None, "no_end", {}
    if status == "VERIFIED_COMPLETE":
        return _grant(x, auths)
    if status == "ESCALATED":
        return "S", "escalated", {}
    if end in INFRA:
        return "F-infra", str(end), {}
    if status not in CLOSES:
        return "F", str(end), {}
    return _no_deal(x, v)


@detector("tier")
def _tier(x: Inputs) -> Value:
    """The run's tier, its reason code, and its money in cents (module doc)."""
    status, end = safe(_last(x, "status.changed", "status")), None
    if ends := x.of("session.ended"):
        end = safe(ends[-1].payload.get("reason"))
    ref = x.events[0].payload.get("task_ref") if x.events else None
    if not isinstance(ref, str) and x.manifest is not None:
        ref = x.manifest.task_ref
    info = end == "info_only" or status == "CLOSED_NO_ACTION"
    v = _values(x)
    tier, reason, extra = _grade(x, status, end, v)
    out: dict[str, object] = {
        "tier": tier, "reason": reason, "status": status, "end_reason": end,
        "task_kind": "info_only" if info else None,
        "family": safe(ref.partition("@")[0]) if isinstance(ref, str) else None,
        "exhausted": None, "ladder_unfinished": None, "approved_by": None,
        "unauthorized_seqs": [], "declass_denied": len(x.of("declass.denied")),
    }  # fmt: skip
    return out | extra | v


def summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Tier counts per family (``none``: no tier), info_only split out;
    ``ab_per_family``: any A or B (S is not one); ``ab_every_family``: every
    family has one (False with no family). Reported, never gated on."""
    fams: dict[str, dict[str, Counter[str]]] = {}
    denied = 0
    for r in rows:
        t = as_dict(as_dict(r.get("detectors")).get("tier"))
        if not t:
            continue
        fam = fams.setdefault(
            str(t.get("family")), {"tiers": Counter(), "info_only": Counter()}
        )
        kind = "info_only" if t.get("task_kind") == "info_only" else "tiers"
        fam[kind][str(t["tier"]) if t.get("tier") is not None else "none"] += 1
        d = t.get("declass_denied")
        denied += d if isinstance(d, int) else 0
    ab = {f: bool(c["tiers"]["A"] + c["tiers"]["B"]) for f, c in sorted(fams.items())}
    return {
        "advisory": NOTE,
        "families": {
            f: {k: dict(sorted(n.items())) for k, n in c.items()}
            for f, c in sorted(fams.items())
        },
        "ab_per_family": ab,
        "ab_every_family": bool(ab) and all(ab.values()),
        "declass_denied": denied,
    }


def block(s: Mapping[str, object]) -> str:
    """The human block diagnose prints after its table."""

    def counts(c: object) -> str:
        return " ".join(f"{k}={n}" for k, n in as_dict(c).items())

    yes = {True: "yes", False: "no"}
    out = [f"== tiers ({NOTE})"]
    ab = as_dict(s["ab_per_family"])
    for fam, c in as_dict(s["families"]).items():
        parts = [f"  {fam} {counts(as_dict(c)['tiers'])}".rstrip()]
        if info := counts(as_dict(c)["info_only"]):
            parts.append(f"info_only {info}")
        out.append(" | ".join([*parts, f"ab={yes[bool(ab.get(fam))]}"]))
    every = yes[bool(s["ab_every_family"])]
    out.append(f"  ab_every_family={every} declass_denied={s['declass_denied']}")
    return "\n".join(out)
