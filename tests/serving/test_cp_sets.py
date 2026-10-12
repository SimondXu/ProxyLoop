"""The cp decision-table state sets (ADR-0029): constructed post-commit states.
Offline: no model call."""

from __future__ import annotations

import json
from pathlib import Path

from tests.serving.test_profile_check import on_hold
from tests.serving.test_teacher_select import cp_view, mk

from proxyloop.contract.state import CaseStatus, OfferPublic, ReadbackSlot
from proxyloop.contract.views import FastView
from scripts.mod import cp_sets as cs
from scripts.mod import cp_table as ct
from scripts.mod import probe_same_state as pss

OFFER = OfferPublic(
    offer_ref="o1",
    revision=1,
    slots=(
        ReadbackSlot(
            field="monthly_price", value="6900", unit="usd_minor", role="recurring"
        ),
        ReadbackSlot(field="term_months", value="24", unit="months", role="recurring"),
        ReadbackSlot(field="fees_none", value="true", unit="bool", role="one_time"),
    ),
)


def source(status: CaseStatus = CaseStatus.COMMIT_AUTHORIZED) -> FastView:
    fv = cp_view(lines=("The rate is 69 a month.",), offers=(OFFER,))
    return on_hold(fv, "offer").model_copy(update={"status": status})


def test_the_accept_is_said_in_the_kernel_wording() -> None:
    assert cs.said(OFFER) == (
        "Yes, we accept these terms: monthly price $69.00; term months 24 months; "
        "fees none true."
    )


def test_an_s1_state_is_committed_with_no_hold(tmp_path: Path) -> None:
    (entry,) = cs.s1_states([mk(source(), run="r1", turn="t9")], ["r1"], 1, seed=3)
    path = tmp_path / "s1.json"
    path.write_text(json.dumps({"views": [entry]}))
    (v,) = pss.read_views(path)
    assert (v.view.status, v.view.hold, v.view.trigger.kind) == (
        CaseStatus.COMMITTED,
        None,
        "rep_spoke",
    )
    accept, rep = v.view.transcript[-2:]
    assert (accept.speaker, accept.text) == ("agent", cs.said(OFFER))
    assert rep.speaker == "partner" and rep.text.startswith("Done, the offer")
    assert ct.rule(v) == "S1" and v.turn == "t9~s1-0" and v.counterfactual


def test_scarce_sources_reuse_the_next_template() -> None:
    views = [mk(source(), run="r1", turn="t1")]
    out = cs.s1_states(views, ["r1"], 3, seed=0)
    assert [x["turn"] for x in out] == ["t1~s1-0", "t1~s1-1", "t1~s1-2"]
    assert len({x["template"] for x in out}) == 3
    # Only the card statuses with an offer and a rep line are sources.
    later = mk(source(CaseStatus.IN_CALL), run="r1", turn="t2")
    assert cs.s1_states([later], ["r1"], 3, seed=0) == []
    assert cs.s1_states(views, ["other-run"], 3, seed=0) == []
