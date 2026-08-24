from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def document(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_phase_03a0_required_documents_exist() -> None:
    required_documents = (
        "docs/decisions/2026-08-23-fast-slow-orchestration.md",
        "harness/build/phase-03a0-fast-slow-architecture.md",
        "harness/context/phase-03a0-preflight.md",
        "CONTEXT.md",
        "PLANS.md",
    )

    missing = [path for path in required_documents if not (ROOT / path).is_file()]
    assert not missing, f"missing Phase 03A0 architecture documents: {missing}"


def test_phase_03a0_freezes_authority_matrix_and_model_boundaries() -> None:
    decision = document("docs/decisions/2026-08-23-fast-slow-orchestration.md")
    build = document("harness/build/phase-03a0-fast-slow-architecture.md")
    context = document("harness/context/phase-03a0-preflight.md")

    assert "### Authority matrix" in decision
    for marker in (
        "| Mandatory Fast/Slow scheduling | Deterministic Router |",
        "| Low-latency dialogue, candidate facts, and escalation signal | Fast Model |",
        "| Strategy, complex reasoning, and bounded capability/action plan "
        "| Slow Reasoner |",
        "| Schema, disclosure, delegated authority, capability, and "
        "current-state validation | Deterministic policy gate |",
        "| Version-bound consequential permission | Approval coordinator "
        "and Consumer decision |",
        "| Simulator, tool, MCP, or channel invocation | Capability executor |",
        "| Business facts, offers, approvals, Evidence, and Case state "
        "| Model-external Case state |",
        "| Final completion | Deterministic verifier |",
    ):
        assert marker in decision

    model_boundary_documents = decision + build + context
    for marker in (
        "neither model calls the other or mutates shared state",
        "Models never execute.",
        "deterministic Evidence verification remains the only path to `complete`",
        "Phase 03A1 exposes fictional-Provider simulator capabilities only.",
    ):
        assert marker in model_boundary_documents


def test_phase_03a0_freezes_router_and_stale_result_semantics() -> None:
    decision = document("docs/decisions/2026-08-23-fast-slow-orchestration.md")

    for outcome in (
        "`fast_now`",
        "`slow_refresh`",
        "`fast_now_and_slow_refresh`",
        "`wait_for_approval`",
        "`verify_only`",
        "`terminal`",
    ):
        assert outcome in decision

    for marker in (
        "Mandatory Slow work takes priority",
        "planning_basis_fingerprint",
        "a stale Fast result is traced and rejected",
        "a stale Slow result is traced and rejected",
        "one serialized state-write and side-effect lane",
    ):
        assert marker in decision


def test_phase_03a0_preserves_pine_evidence_boundary() -> None:
    decision = document("docs/decisions/2026-08-23-fast-slow-orchestration.md")

    for marker in (
        "Pine's public, self-reported product principles",
        "The protocol below is a ProxyLoop decision",
        "Pine's undisclosed implementation",
    ):
        assert marker in decision


def test_phase_03a0_allowlisted_views_exclude_non_authoritative_inputs() -> None:
    decision = document("docs/decisions/2026-08-23-fast-slow-orchestration.md")
    build = document("harness/build/phase-03a0-fast-slow-architecture.md")

    for marker in (
        "FastModelView",
        "SlowReasonerView",
        "Separate allowlisted projections",
    ):
        assert marker in decision
    for marker in (
        "hidden chain-of-thought",
        "model KV caches",
        "raw prompts",
        "free-form model memory",
        "Provider-private",
        "gold outcomes",
        "evaluator criteria",
    ):
        assert marker in decision + build


def test_phase_03a0_fast_reasoner_request_cannot_bypass_router_policy() -> None:
    decision = document("docs/decisions/2026-08-23-fast-slow-orchestration.md")
    context = document("harness/context/phase-03a0-preflight.md")

    for marker in (
        "Fast may request Slow, but cannot suppress or force routing.",
        "Fast `reasoner_request` accepted by Router policy",
        "Fast `reasoner_request` is advisory input to those rules.",
    ):
        assert marker in decision + context


def test_phase_03a0_executor_rechecks_all_current_authority_pins() -> None:
    decision = document("docs/decisions/2026-08-23-fast-slow-orchestration.md")
    build = document("harness/build/phase-03a0-fast-slow-architecture.md")

    for marker in (
        "re-check current strategy/basis",
        "delegated authority",
        "approval",
        "expiry",
        "capability",
        "idempotency",
    ):
        assert marker in decision + build


def test_phase_03a0_requires_eval_first_before_later_data_expansion() -> None:
    decision = document("docs/decisions/2026-08-23-fast-slow-orchestration.md")
    build = document("harness/build/phase-03a0-fast-slow-architecture.md")
    plans = document("PLANS.md")

    for marker in (
        "multi-turn evaluation-harness and frozen-test-set implementation",
        "untuned Fast with Slow disabled and enabled",
        "scripted-oracle",
        "frontier reference baselines",
        "Open-data SFT and project-specific generation remain later "
        "evidence-driven decisions.",
    ):
        assert marker in decision + build
    assert "| 03B | Open-data SFT, gap-driven project data, and evaluation |" in plans
    assert "Decided from Phase 03A1 failure slices" in plans


def test_phase_03a0_freezes_router_precedence_and_single_outcome() -> None:
    decision = document("docs/decisions/2026-08-23-fast-slow-orchestration.md")
    routing = decision[decision.index("### Routing") :]
    outcomes = (
        "terminal",
        "verify_only",
        "wait_for_approval",
        "slow_refresh",
        "fast_now_and_slow_refresh",
        "fast_now",
    )
    positions = [routing.index(f"`{outcome}`") for outcome in outcomes]

    assert positions == sorted(positions)
    assert re.search(r"(?:exactly one|one and only one|one) outcome", routing, re.I)


def test_phase_03a0_disables_fast_action_intent_and_limits_qwen_training() -> None:
    decision = document("docs/decisions/2026-08-23-fast-slow-orchestration.md")
    build = document("harness/build/phase-03a0-fast-slow-architecture.md")

    assert (
        "Phase 03A1 Fast requests and accepted outputs require it to be `null`"
        in decision
    )
    assert "Phase 03A1 requires `FastTurnDecision.action_intent=null`." in build

    for marker in (
        "dialogue-act selection",
        "candidate fact extraction",
        "reasoner-request classification",
        "It is not trained to own strategy generation",
        "multi-step tool selection or argument planning",
        "MCP/phone execution",
        "long-term memory",
        "approval",
        "Evidence verification",
        "final completion",
        "workflow durability",
    ):
        assert marker in decision


def test_phase_03a0_records_phase_status_and_phase02_merge() -> None:
    build = document("harness/build/phase-03a0-fast-slow-architecture.md")
    context = document("harness/context/phase-03a0-preflight.md")
    plans = document("PLANS.md")

    assert "**Status**: Complete;" in build
    assert "54afcb8" in build
    assert "f45b1ea" in build
    assert "f45b1ea" in context
    assert "Phase 03A0" in context
    assert "Phase 03A0" in plans
    assert "f45b1ea" in plans
    assert "Phase 03A0" in plans and "Complete" in plans
    assert "Phase 03A1-H" in plans and "Local gate approved" in plans
    assert "| 03B |" in plans and "Not started" in plans
