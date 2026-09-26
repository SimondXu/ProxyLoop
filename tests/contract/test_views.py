"""Views: the private-value counterfactual (I4), the view_cp AST rule, SlowView (I5)."""

from __future__ import annotations

import ast
import inspect

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from proxyloop.contract import views
from proxyloop.contract.config import SlowViewMode
from proxyloop.contract.messages import FastToSlow, Guide, GuideMove
from proxyloop.contract.protocol import render_messages
from proxyloop.contract.state import (
    Approval,
    ApprovalCard,
    Blackboard,
    CaseStatus,
    ChannelState,
    Fact,
    HoldState,
    Line,
    Mandate,
    OfferPublic,
    PrivateState,
    PublicFact,
    PublicState,
    ReadbackBinding,
    ReadbackSlot,
)
from proxyloop.contract.views import FastView, Trigger, view_cp, view_slow, view_user

TEXT = st.text(alphabet="abcdefgh xyz0123456789$.,:'-@\n", max_size=60)
DIGITS = st.integers(min_value=0, max_value=99_999).map(str)
KEYS = st.sampled_from(
    ["competitor_quote", "rep.name", "plan", "account.pin", "tenure"]
)


@st.composite
def offers(draw: st.DrawFn) -> OfferPublic:
    ref = draw(st.sampled_from(["o1", "o2", "o3"]))
    fields = draw(st.sets(st.sampled_from(["monthly_price", "fee:activation"])))
    slots = tuple(
        ReadbackSlot(
            field=f,
            value=draw(DIGITS),
            unit="usd_minor",
            role="recurring" if f == "monthly_price" else "one_time",
            status=draw(st.sampled_from(["unknown", "heard", "confirmed"])),
        )
        for f in sorted(fields)
    )
    return OfferPublic(offer_ref=ref, revision=draw(st.integers(1, 3)), slots=slots)


@st.composite
def publics(draw: st.DrawFn) -> PublicState:
    facts = {
        k: PublicFact(key=k, value=draw(TEXT), source="cp_utt", source_ref="c1")
        for k in draw(st.sets(KEYS, max_size=3))
    }
    offer_list = draw(st.lists(offers(), max_size=2, unique_by=lambda o: o.offer_ref))
    slots = [f"fact:{k}" for k in facts] + [f"offer:{o.offer_ref}" for o in offer_list]
    slots += [f"offer:{o.offer_ref}.{s.field}" for o in offer_list for s in o.slots]
    guides = draw(
        st.lists(
            st.builds(
                Guide,
                move=st.sampled_from(list(GuideMove)),
                slots=st.lists(st.sampled_from(slots), max_size=2).map(tuple)
                if slots
                else st.just(()),
            ),
            max_size=3,
        )
    )
    return PublicState(
        summary=draw(TEXT),
        facts=facts,
        offers={o.offer_ref: o for o in offer_list},
        guidance_cp=tuple(guides),
        action_log=tuple(draw(st.lists(TEXT, max_size=12))),
        status=draw(st.sampled_from(list(CaseStatus))),
        cp_hold=draw(
            st.none()
            | st.builds(HoldState, reason=st.just("offer"), since_ms=st.just(1))
        ),
    )


def _lines(prefix: str) -> st.SearchStrategy[tuple[Line, ...]]:
    return st.lists(
        st.builds(
            Line,
            utt_id=st.just(prefix),
            speaker=st.sampled_from(["partner", "agent"]),
            text=TEXT,
        ),
        max_size=6,
    ).map(tuple)


@st.composite
def privates(draw: st.DrawFn) -> PrivateState:
    n = draw(st.integers(0, 10_000))
    mandate = Mandate(
        mandate_id=f"m{n}",
        mandate_hash=f"h{n}",
        status=draw(st.sampled_from(["proposed", "granted", "denied", "revoked"])),
        epoch=n % 5,
        max_monthly_price_minor=n,
        max_term_months=n % 48,
        max_one_time_fees_minor=n // 2,
        required_features=(f"feature{n}",),
    )
    binding = ReadbackBinding(
        offer_ref="o1",
        revision=1,
        account_ref=f"acct{n}",
        principal_ref="p",
        purpose="lower bill",
        authority_epoch=n % 5,
    )
    card = ApprovalCard(
        approval_id=f"a{n}",
        offer_ref="o1",
        revision=1,
        terms_hash=f"t{n}",
        readback_text=draw(TEXT),
        authority_epoch=n % 5,
        expires_ms=n,
        binding=binding,
    )
    return PrivateState(
        summary=draw(TEXT),
        case_facts={
            k: Fact(key=k, value=draw(TEXT), protected=draw(st.booleans()))
            for k in draw(st.sets(KEYS, max_size=3))
        },
        mandate=draw(st.none() | st.just(mandate)),
        pending_approval=draw(st.none() | st.just(card)),
        approvals={
            f"a{n}": Approval(
                approval_id=f"a{n}",
                decision="granted",
                by="ui",
                terms_hash=f"t{n}",
                authority_epoch=n % 5,
            )
        }
        if draw(st.booleans())
        else {},
    )


@st.composite
def blackboards(draw: st.DrawFn) -> Blackboard:
    return Blackboard(
        seq=draw(st.integers(0, 500)),
        t_ms=draw(st.integers(0, 10**6)),
        epoch=draw(st.integers(0, 5)),
        public=draw(publics()),
        private=draw(privates()),
        channels={
            "user": ChannelState(lines=draw(_lines("u"))),
            "cp": ChannelState(
                lines=draw(_lines("c")), strikes=draw(st.integers(0, 2))
            ),
        },
    )


CP_TRIGGERS = st.sampled_from(
    [
        Trigger(kind="rep_spoke"),
        Trigger(kind="guidance"),
        Trigger(kind="call_connected"),
        Trigger(kind="hold_wait", wait_s=7),
    ]
)


def _cp_render(bb: Blackboard, trigger: Trigger) -> tuple[object, ...]:
    return render_messages(view_cp(bb, trigger, "Call the company."), "pl_cp_v1")


@settings(max_examples=500, deadline=None)
@given(bb=blackboards(), other=privates(), trigger=CP_TRIGGERS)
def test_private_value_counterfactual(
    bb: Blackboard, other: PrivateState, trigger: Trigger
) -> None:
    """Perturbing any PrivateState field leaves the cp render byte-identical."""

    base = _cp_render(bb, trigger)
    for name in PrivateState.model_fields:
        private = bb.private.model_copy(update={name: getattr(other, name)})
        perturbed = bb.model_copy(update={"private": private})
        assert _cp_render(perturbed, trigger) == base, name
    assert _cp_render(bb.model_copy(update={"private": other}), trigger) == base


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(views))
    return next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name
    )


def _bb_uses(fn: ast.FunctionDef) -> set[str]:
    """Every way ``bb`` is used: an attribute name, or ``<bare>`` for anything else."""

    parents = {
        child: node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)
    }
    uses: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id == "bb":
            parent = parents.get(node)
            uses.add(parent.attr if isinstance(parent, ast.Attribute) else "<bare>")
    return uses


def test_view_cp_reads_only_public_and_channels() -> None:
    fn = _function("view_cp")
    assert _bb_uses(fn) == {"public", "channels"}
    assert not [
        n for n in ast.walk(fn) if isinstance(n, ast.Attribute) and n.attr == "private"
    ]
    assert "private" not in ast.unparse(fn)


def test_the_ast_rule_is_not_vacuous() -> None:
    assert "private" in _bb_uses(_function("view_user"))


def _bb_with_relays() -> Blackboard:
    relay = FastToSlow(
        msg_id="f1", lane="user", gen_id="g1", utt_ref="u1", type="NOTE", text="hi"
    )
    lines = (Line(utt_id="u1", speaker="partner", text="my PIN is 4921"),)
    return Blackboard(
        f2s_pending=(relay,),
        channels={"user": ChannelState(lines=lines), "cp": ChannelState(lines=lines)},
    )


def test_slow_view_is_relay_only_by_default() -> None:
    bb = _bb_with_relays()
    view = view_slow(bb, SlowViewMode.RELAY_ONLY, "brief")
    assert view.relays == bb.f2s_pending
    assert view.transcripts == {}
    assert "4921" not in view.model_dump_json()


def test_raw_transcript_ablation_adds_both_transcripts() -> None:
    bb = _bb_with_relays()
    view = view_slow(bb, SlowViewMode.RAW_TRANSCRIPT, "brief")
    assert set(view.transcripts) == {"user", "cp"}


def test_cp_view_rejects_private_fields() -> None:
    view = view_cp(Blackboard(), Trigger(kind="rep_spoke"), "b")
    with pytest.raises(ValueError, match="no private"):
        FastView.model_validate(view.model_dump() | {"private_summary": "secret"})
    with pytest.raises(ValueError, match="not a cp trigger"):
        FastView.model_validate(view.model_dump() | {"trigger": {"kind": "user_msg"}})


def test_view_user_needs_a_pending_slow_message() -> None:
    with pytest.raises(ValueError, match="no pending"):
        view_user(Blackboard(), Trigger(kind="slow_msg", msg_id="s9"), "b")
