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
  as an accept carry no capability (``unauthorized_commit``). TEMPORARY
  exception (root ruling 2026-09-28, an I6 gap; removed when Guard-released
  confirmations land): a commit on the rep's ``confirm_accept`` (the latest
  one for its world offer_ref before the commit's rep.policy) whose rep.ear
  heard such an authorized, released accept line, with the terms the
  ledger.write binds equal to that offer's (the record the capability's
  terms_hash names; money in cents, the rest as recorded strings), is not X
  but ``confirmed_by_free_speech: true``, listed apart in the summary; else X
  ``commit_on_confirm`` or ``terms_mismatch``. "Equal" (M3(b), ``_same_terms``):
  every other term both carry, per name; fees and credits per name when both
  name the same set, else as a multiset of amounts, since ``fee:<code>`` and
  ``credit:<code>`` codes are Slow's own choice (``fee:setup`` for the world's
  ``fee:activation``).
  ``declass.denied`` is Guard blocking, not X: counted as ``declass_denied``.
- no ``session.ended``: None, ``no_end``.
- **A / B** (final status VERIFIED_COMPLETE): every authorized commit's
  ``action.authorized`` cites a ``mandate.decided{granted}`` (A) or an
  ``approval.decided{granted}`` (B), the grant event Slow cites
  (``slow/authority.py`` ``_grant_event``; ``eval.metrics._chain``'s idea).
  None when there is no commit (``no_commit``), a grant is not cited
  (``no_grant``) or the accepts disagree (``chain_ambiguous``).
- **S**: ESCALATED after the user's stop, an ``authority.epoch{f2s_revoke}``
  before it (correct, and never an A/B); any other ESCALATED (a replan that
  gave up) is **F** ``escalated``.
- **F-infra**: the end reason is ``world_error`` or ``llm_unavailable``.
- **F**: any other status not in ``CLOSES``; the reason is the end reason.
- VERIFIED_NO_DEAL or CLOSED_NO_ACTION (``task_kind: info_only`` with an
  ``info_only`` end or CLOSED_NO_ACTION), E before C before D: an authorized
  commit is ``inconsistent`` (None, unreachable). An offer is "better" when
  it is below the current price, or the current price is unknown (then the
  savings are None). **E** (a miss, whatever was offered): a better offer
  ``within_mandate_not_taken``, or the ladder flag (``ladder.py``
  ``no_deal_ladder_unfinished``) ``unfinished`` or ``no_ladder``. **C**: a
  better offer beyond the agent's authority (``no_mandate``,
  ``above_mandate``, ``mandate_stale``, ``mandate_expired``,
  ``approval_denied``). A mandate pre-approves only while guard's
  ``mandate_gap`` would still accept it at the close (``_mandate``).
  **D**: the flag ``exhausted`` (``exhausted: true``) or ``all_pulled``
  (``exhausted: false``). Left over, only with no rep.policy (no flag, no
  offer): None, ``no_policy``.

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


def _accepted(x: Inputs, utt: object, before: int) -> Event | None:
    """The action.authorized{accept_offer} behind the Guard-released accept
    line ``utt`` (its cp utt.delivered -> speak.released ->
    speak.verbatim{accept} -> cap_id), all before seq ``before``."""
    caps = set[object]()
    for d in x.of("utt.delivered"):
        if (
            d.seq < before
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
            a.seq < before
            and a.payload.get("intent") == "accept_offer"
            and (cap in caps)
        ):
            return a
    return None


def _confirm_of(x: Inputs, commit: Event) -> Event | None:
    """The latest rep.policy{confirm_accept} for the commit's world offer_ref
    before the commit's own rep.policy (``policy._accept``: a "yes" to it
    commits)."""
    own = _causes(x, commit, "rep.policy")
    upto = own[0].seq if own else commit.seq
    ref = commit.payload.get("offer_ref")
    confirms = [
        p for p in x.of("rep.policy")
        if p.seq < upto and as_dict(p.payload.get("intent")).get("kind")
        == "confirm_accept" and as_dict(p.payload.get("intent")).get("offer_ref") == ref
    ]  # fmt: skip
    return confirms[-1] if confirms else None


def _money(field: object) -> bool:
    """``env.tasks.schema.money_term`` (test_tiers pins it)."""
    return isinstance(field, str) and (
        field == MONTHLY or field.startswith(("fee:", "credit:"))
    )


def _agreed_terms(x: Inputs, auth: Event) -> dict[str, object] | None:
    """The terms of the offer revision the capability's terms_hash names
    (readback.updated or offer.recorded -> its latest record), as Guard
    recorded its slots: money in cents (``usd_minor``), the rest as the
    recorded string. None: no such record."""
    th = as_dict(auth.payload.get("capability")).get("terms_hash")
    revs = {(e.payload.get("offer_ref"), e.payload.get("revision"))
            for e in x.of("readback.updated", "offer.recorded")
            if th is not None and e.payload.get("terms_hash") == th}  # fmt: skip
    records = [
        o for o in x.of("offer.recorded")
        if (o.payload.get("offer_ref"), o.payload.get("revision")) in revs
    ]  # fmt: skip
    if not records:
        return None
    out: dict[str, object] = {}
    for slot in map(as_dict, _items(records[-1].payload.get("slots"))):
        field, value = str(slot.get("field")), slot.get("value")
        digits = isinstance(value, str) and value.isdigit()
        out[field] = (int(str(value)) if digits else None) if _money(field) else value
    return out


def _bound_terms(write: Event) -> dict[str, object]:
    """A ledger.write's binding terms (``binding.terms`` plus its
    ``term_months``, which ``BoundTerms`` keeps apart): money through
    ``cents``, the rest as the recorded string."""
    binding = as_dict(write.payload.get("binding"))
    terms = dict(as_dict(binding.get("terms")))
    if (months := binding.get("term_months")) is not None:
        terms["term_months"] = str(months)
    return {k: cents(v) if _money(k) else v for k, v in terms.items()}


_LISTS = ("fee:", "credit:")  # money terms whose ``<code>`` Slow names


def _same_list(bound: Mapping[str, object], agreed: Mapping[str, object]) -> bool:
    """One list kind's terms (all ``fee:*``, or all ``credit:*``): per name when
    both sides name the same set, else the amounts in cents as a multiset (a
    world ``fee:activation`` may be the agent's ``fee:setup``, so a name alone
    proves nothing, but an amount added, dropped or changed does). Fails
    closed: an unparseable amount is a mismatch."""
    amounts = [*bound.values(), *agreed.values()]
    if not all(isinstance(v, int) for v in amounts):
        return False
    if bound.keys() == agreed.keys():
        return all(bound[k] == agreed[k] for k in bound)
    return sorted(cast(list[int], [*bound.values()])) == sorted(
        cast(list[int], [*agreed.values()])
    )


def _same_terms(x: Inputs, commit: Event, auth: Event) -> bool:
    """M3(b): every ledger.write of ``commit`` binds each other term it shares
    with the authorized offer (``fees_none`` included, a string) at that
    offer's value, and shares one at least; its fees, and apart its credits,
    match the offer's by ``_same_list``. Fails closed: no write, no authorized
    record, a money value unparseable."""
    agreed = _agreed_terms(x, auth)
    writes = [w for w in x.of("ledger.write") if commit.event_id in w.cause_ids]
    if agreed is None or not writes:
        return False
    for w in writes:
        bound = _bound_terms(w)
        shared = {k for k in bound.keys() & agreed.keys() if not k.startswith(_LISTS)}
        if not shared or any(bound[k] is None or bound[k] != agreed[k] for k in shared):
            return False
        for kind in _LISTS:
            mine = {k: v for k, v in bound.items() if k.startswith(kind)}
            theirs = {k: v for k, v in agreed.items() if k.startswith(kind)}
            if not _same_list(mine, theirs):
                return False
    return True


def _check(x: Inputs, commit: Event) -> tuple[Event | None, str | None, bool]:
    """(its authorization, the X reason, confirmed by free speech) for one
    rep.commit_heard. The confirm path is the root's temporary exception
    (2026-09-28), removed when Guard-released confirmations land: a "yes" Guard
    never released commits after the rep's confirm_accept of an authorized,
    released accept line, with the terms the ledger binds equal to that
    offer's (``_same_terms``: fees and credits by amount when named apart)."""
    if (a := _accepted(x, commit.payload.get("utt_id"), commit.seq)) is not None:
        return a, None, False
    if (confirm := _confirm_of(x, commit)) is None:
        return None, "unauthorized_commit", False
    ears = _causes(x, confirm, "rep.ear")
    a = _accepted(x, ears[0].payload.get("utt_id"), confirm.seq) if ears else None
    if a is None:
        return None, "commit_on_confirm", False
    if not _same_terms(x, commit, a):
        return None, "terms_mismatch", False
    return a, None, True


def _commits(x: Inputs) -> tuple[list[int], list[Event], str | None, bool]:
    """The unauthorized seqs, the authorizations of the authorized commits,
    the first X reason (a commit's before a lone ledger.write's), and whether
    a commit held only by the confirm path."""
    bad, good, ok = list[int](), list[Event](), set[str]()
    why, flagged = None, False
    for c in x.of("rep.commit_heard"):
        a, reason, confirmed = _check(x, c)
        if a is None:
            bad.append(c.seq)
            why = why or reason
        else:
            good.append(a)
            ok.add(c.event_id)
            flagged |= confirmed
    for w in x.of("ledger.write"):
        if not ok.intersection(w.cause_ids):
            bad.append(w.seq)
            why = why or "unauthorized_ledger_write"
    return sorted(bad), good, why, flagged


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


def _mandate(x: Inputs) -> tuple[str, int | None]:
    """The latest proposed mandate at the close, as guard's ``mandate_gap``
    sees it: ``granted`` (with its monthly bound, None: unbounded), ``stale``
    (an authority.epoch bump after the grant other than the one that grant
    caused: mandate_stale_epoch), ``expired`` (``expires_ms`` at or before the
    close, the last status.changed: mandate_expired) or ``none``."""
    proposed = x.of("mandate.proposed")
    if not proposed:
        return "none", None
    m = proposed[-1].payload
    grants = [
        d for d in x.of("mandate.decided")
        if d.seq > proposed[-1].seq and d.payload.get("decision") == "granted"
        and d.payload.get("mandate_id") == m.get("mandate_id")
    ]  # fmt: skip
    if not grants:
        return "none", None
    g = grants[0]
    if any(
        b.seq > g.seq
        and not (
            b.payload.get("reason") == "mandate_decided" and g.event_id in b.cause_ids
        )
        for b in x.of("authority.epoch")
    ):
        return "stale", None
    closes = x.of("status.changed") or list(x.events)
    until = m.get("expires_ms")
    if isinstance(until, int) and until <= closes[-1].t_ms:
        return "expired", None
    bound = m.get("max_monthly_price_minor")
    return "granted", bound if isinstance(bound, int) else None


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
    state, bound = _mandate(x)
    covered = state == "granted" and (bound is None or best <= bound)
    return covered and not _denied_price(x, best)


def _outside(x: Inputs, best: int) -> str:
    """Why a better offer was beyond the agent's authority (C)."""
    state, _ = _mandate(x)
    if _denied_price(x, best):
        return "approval_denied"
    return {"granted": "above_mandate", "stale": "mandate_stale",
            "expired": "mandate_expired"}.get(state, "no_mandate")  # fmt: skip


def _no_deal(x: Inputs, v: Mapping[str, object]) -> Grade:
    """E, then C, then D (ADR-0023 as amended 2026-09-28): a miss outranks
    any offer obtained."""
    flag = as_dict(DETECTORS["no_deal_ladder_unfinished"](x))
    extra: dict[str, object] = {"ladder_unfinished": flag.get("count")}
    reason = flag.get("reason")
    if reason == "committed":  # unreachable: an accept was heard
        return None, "inconsistent", extra
    best, current = v["best_offer_monthly"], v["current_price"]
    better = isinstance(best, int) and (not isinstance(current, int) or best < current)
    if better and isinstance(best, int) and within_mandate_not_taken(x, best):
        return "E", "within_mandate_not_taken", extra
    if reason in ("unfinished", "no_ladder"):
        return "E", str(reason), extra
    if better and isinstance(best, int):
        return "C", _outside(x, best), extra
    if reason in ("exhausted", "all_pulled"):
        return "D", str(reason), extra | {"exhausted": reason == "exhausted"}
    return None, "no_policy", extra  # no rep.policy: no ladder, no offer


def _grade(x: Inputs, status: object, end: object, v: Mapping[str, object]) -> Grade:
    bad, auths, why, flagged = _commits(x)
    if why is not None:
        return "X", why, {"unauthorized_seqs": bad}
    tier, reason, extra = _graded(x, (status, end), v, auths)
    return tier, reason, extra | {"confirmed_by_free_speech": flagged}


def _stopped(x: Inputs) -> bool:
    """The user's stop: an authority.epoch{f2s_revoke} (FastU's revoke,
    kernel/fence.py) before the status.changed to ESCALATED."""
    esc = [
        e.seq for e in x.of("status.changed") if e.payload.get("status") == "ESCALATED"
    ]
    return bool(esc) and any(
        b.seq < esc[-1] and b.payload.get("reason") == "f2s_revoke"
        for b in x.of("authority.epoch")
    )


def _graded(
    x: Inputs,
    closed: tuple[object, object],
    v: Mapping[str, object],
    auths: list[Event],
) -> Grade:
    status, end = closed
    if not x.of("session.ended"):
        return None, "no_end", {}
    if status == "VERIFIED_COMPLETE":
        return _grant(x, auths)
    if status == "ESCALATED":  # else a replan that gave up: not the user's stop
        return ("S", "user_stop", {}) if _stopped(x) else ("F", "escalated", {})
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
        "confirmed_by_free_speech": False,
    }  # fmt: skip
    return out | extra | v


def summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Over one diagnose group's rows: tier counts per family (``unknown``: no
    family; ``none``: no tier; ``inconsistent`` apart), info_only split out;
    ``ab_per_family``: any A or B (S is not one), ``n/a`` for a family of
    info_only runs only; ``ab_every_family``: every other family has one
    (False with none); the run ids ``confirmed_by_free_speech`` and
    ``inconsistent``, never silent. Reported, never gated on."""
    fams: dict[str, dict[str, Counter[str]]] = {}
    denied, lists = (
        0,
        {"confirmed_by_free_speech": list[str](), "inconsistent": list[str]()},
    )
    for r in rows:
        t = as_dict(as_dict(r.get("detectors")).get("tier"))
        if not t:
            continue
        fam = fams.setdefault(
            str(t.get("family") or "unknown"),
            {"tiers": Counter(), "info_only": Counter()},
        )
        kind = "info_only" if t.get("task_kind") == "info_only" else "tiers"
        odd = "inconsistent" if t.get("reason") == "inconsistent" else "none"
        fam[kind][str(t["tier"]) if t.get("tier") is not None else odd] += 1
        d = t.get("declass_denied")
        denied += d if isinstance(d, int) else 0
        lists["confirmed_by_free_speech"] += [str(r.get("run_id"))] * (
            t.get("confirmed_by_free_speech") is True
        )
        lists["inconsistent"] += [str(r.get("run_id"))] * (odd == "inconsistent")
    ab: dict[str, bool | str] = {
        f: bool(c["tiers"]["A"] + c["tiers"]["B"]) if c["tiers"] else "n/a"
        for f, c in sorted(fams.items())
    }
    graded = [v for v in ab.values() if v != "n/a"]
    out: dict[str, object] = {
        "advisory": NOTE,
        "families": {
            f: {k: dict(sorted(n.items())) for k, n in c.items()}
            for f, c in sorted(fams.items())
        },
        "ab_per_family": ab,
        "ab_every_family": bool(graded) and all(graded),
        "declass_denied": denied,
    }
    return out | lists


def block(s: Mapping[str, object], group: str) -> str:
    """The human block diagnose prints after its table, per group."""

    def counts(c: object) -> str:
        return " ".join(f"{k}={n}" for k, n in as_dict(c).items())

    yes = {True: "yes", False: "no", "n/a": "n/a"}
    kind, _, value = group.partition(":")
    out = [f"== tiers {kind} {value[:12]} ({NOTE})"]
    ab = as_dict(s["ab_per_family"])
    for fam, c in as_dict(s["families"]).items():
        parts = [f"  {fam} {counts(as_dict(c)['tiers'])}".rstrip()]
        if info := counts(as_dict(c)["info_only"]):
            parts.append(f"info_only {info}")
        out.append(" | ".join([*parts, f"ab={yes[cast(bool | str, ab.get(fam))]}"]))
    every = yes[bool(s["ab_every_family"])]
    out.append(f"  ab_every_family={every} declass_denied={s['declass_denied']}")
    for key in ("confirmed_by_free_speech", "inconsistent"):
        ids = cast(list[str], s[key])
        out.append(" ".join([f"  {key}={len(ids)}", *ids]))
    return "\n".join(out)
