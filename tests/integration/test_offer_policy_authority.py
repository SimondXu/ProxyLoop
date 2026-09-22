"""One offer-policy authority, one material-terms hash, one change list."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from proxyloop_agent_core import (
    CapabilityExecutionRequest,
    CapabilityExecutionStatus,
    CapabilityExecutor,
    CaseCoordinator,
    PreparedSimulatorExecution,
)
from proxyloop_contracts import (
    ActionIntent,
    ActionType,
    ApprovalDecision,
    ApprovalRequest,
    CapabilityDefinition,
    CapabilityManifest,
    CapabilityProposal,
    Case,
    CaseContextSnapshot,
    Evidence,
    EvidenceType,
    FactLedger,
    FactStatus,
    MaterialTerm,
    ModelInputPins,
    PlanningBasis,
    ProviderOffer,
    StrategyPacket,
    canonical_fingerprint,
    planning_basis_fingerprint,
)
from proxyloop_contracts.contracts import EvidenceRequirement
from proxyloop_contracts.material_terms import (
    material_terms_hash,
    offer_material_terms,
)
from proxyloop_openai_adapter import (
    AcceptOfferCapabilityModelOutput,
    SlowModelOutput,
    StrategyModelOutput,
    compile_slow_output,
)
from proxyloop_provider_simulator.episode import Phase01AEpisode
from proxyloop_telecom_domain import (
    material_terms_hash as domain_material_terms_hash,
)
from proxyloop_telecom_domain import (
    offer_material_terms as domain_offer_material_terms,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 23, 12, 20, tzinfo=UTC)
PROVIDER_CONFIG_REF = "cooperative-v1"

# Digests captured from ``proxyloop_telecom_domain.material_terms_hash`` on
# ``main`` @ 5eef7c0 before the hash moved; they freeze the wire bytes.
THREE_TERMS = (
    MaterialTerm(name="monthly_price", value="7200"),
    MaterialTerm(name="total_cost", value="86400"),
    MaterialTerm(name="term_months", value="12"),
)
THREE_TERMS_DIGEST = "6d25bd2d7d6bc483c6fa9418bb279189bda612c59ddca9a4cd10da51f7bca104"
SIX_TERMS = (
    MaterialTerm(name="monthly_price_minor", value="7200"),
    MaterialTerm(name="total_cost_12_months_minor", value="86400"),
    MaterialTerm(name="currency", value="USD"),
    MaterialTerm(name="term_months", value="12"),
    MaterialTerm(name="features", value="5g_access,mobile_hotspot"),
    MaterialTerm(name="offer_expires_at", value="2026-08-23T13:00:00Z"),
)
SIX_TERMS_DIGEST = "b303382dc39c52ccacd1fc3a97a39cf0136836e79ffa4d70d41f3f35e9478312"


def _manifest() -> CapabilityManifest:
    return CapabilityManifest(
        contract_type="capability_manifest",
        schema_version="1.0",
        revision=1,
        namespace="simulator",
        manifest_version="offer-policy-authority-v1",
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=2),
        capabilities=(
            CapabilityDefinition(
                capability_id="simulator.accept_offer",
                version="1.0",
                description="Accept a current fictional Provider offer.",
                namespace="simulator",
                allowed_action_types=(ActionType.ACCEPT_OFFER,),
                expires_at=NOW + timedelta(hours=1),
            ),
        ),
    )


def _basis(
    *,
    case: Case,
    ledger: FactLedger,
    offers: tuple[ProviderOffer, ...],
    approvals: tuple[ApprovalRequest, ...],
    manifest: CapabilityManifest,
) -> PlanningBasis:
    components = {
        "goal_fingerprint": canonical_fingerprint(case.goal),
        "constraints_fingerprint": canonical_fingerprint(
            tuple(sorted(case.constraints, key=lambda item: str(item.constraint_id)))
        ),
        "delegated_authority_fingerprint": canonical_fingerprint(
            case.delegated_authority
        ),
        "verified_facts_fingerprint": canonical_fingerprint(
            tuple(item for item in ledger.entries if item.status is FactStatus.VERIFIED)
        ),
        "material_offers_fingerprint": canonical_fingerprint(offers),
        "approval_state_fingerprint": canonical_fingerprint(approvals),
        "provider_config_fingerprint": canonical_fingerprint(PROVIDER_CONFIG_REF),
        "capability_manifest_fingerprint": canonical_fingerprint(manifest),
    }
    return PlanningBasis(
        contract_type="planning_basis",
        schema_version="1.0",
        revision=1,
        **components,
        planning_basis_fingerprint=planning_basis_fingerprint(**components),
    )


def _snapshot(
    case: Case,
    offer: ProviderOffer,
    *,
    strategy: StrategyPacket | None,
    approvals: tuple[ApprovalRequest, ...] = (),
) -> CaseContextSnapshot:
    manifest = _manifest()
    ledger = FactLedger(
        contract_type="fact_ledger",
        schema_version="1.0",
        revision=1,
        ledger_id=UUID("77777777-7777-4777-8777-777777777777"),
        case_id=case.case_id,
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW,
        entries=(),
    )
    basis = _basis(
        case=case,
        ledger=ledger,
        offers=(offer,),
        approvals=approvals,
        manifest=manifest,
    )
    pins = ModelInputPins(
        contract_type="model_input_pins",
        schema_version="1.0",
        revision=1,
        case_id=case.case_id,
        case_revision=case.revision,
        constraint_set_revision=case.constraint_set_revision,
        fact_ledger_revision=1,
        strategy_id=strategy.strategy_id if strategy is not None else None,
        strategy_revision=strategy.revision if strategy is not None else 0,
        planning_basis_fingerprint=basis.planning_basis_fingerprint,
        event_cursor=0,
        provider_config_ref=PROVIDER_CONFIG_REF,
        capability_manifest_version=manifest.manifest_version,
    )
    return CaseContextSnapshot(
        contract_type="case_context_snapshot",
        schema_version="1.0",
        revision=1,
        case=case,
        fact_ledger=ledger,
        strategy=strategy,
        offers=(offer,),
        approval_requests=approvals,
        visible_events=(),
        event_cursor=0,
        planning_basis=basis,
        pins=pins,
        provider_config_ref=PROVIDER_CONFIG_REF,
        capability_manifest=manifest,
    )


def _approve(intent: ActionIntent, *, decided_at: datetime) -> ApprovalRequest:
    return ApprovalRequest(
        contract_type="approval_request",
        schema_version="1.0",
        revision=2,
        approval_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
        case_id=intent.case_id,
        case_revision=intent.case_revision,
        action_intent_id=intent.intent_id,
        action_intent_revision=intent.revision,
        action_type=intent.action_type,
        strategy_id=intent.strategy_id,
        strategy_revision=intent.strategy_revision,
        constraint_set_revision=intent.constraint_set_revision,
        offer_ref=intent.offer_ref,
        material_terms_hash=intent.material_terms_hash,
        requested_at=intent.created_at,
        expires_at=intent.created_at + timedelta(minutes=10),
        decision=ApprovalDecision.APPROVED,
        decided_at=decided_at,
    )


class _AcceptCapability:
    def prepare(
        self, proposal: CapabilityProposal, *, idempotency_key: str
    ) -> PreparedSimulatorExecution:
        del proposal
        evidence = Evidence(
            contract_type="evidence",
            schema_version="1.0",
            evidence_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
            case_id=self.case_id,
            source_type=EvidenceType.SIMULATOR_TRANSITION,
            source_ref=idempotency_key,
            content_hash="e" * 64,
            observed_at=NOW,
            captured_at=NOW,
            media_type="application/json",
        )
        return PreparedSimulatorExecution(evidence=evidence, commit=lambda: None)

    def __init__(self, case_id: UUID) -> None:
        self.case_id = case_id


def test_compiled_slow_accept_binds_the_domain_material_terms_and_hash() -> None:
    episode = Phase01AEpisode.success()
    offer = episode.issue_offer()
    request = CaseCoordinator.build_slow_request(
        _snapshot(episode.case, offer, strategy=None),
        reason_code="case_initialization",
        created_at=NOW,
    )
    output = SlowModelOutput(
        strategy=StrategyModelOutput(
            primary_objective="Reduce the recurring bill safely.",
            current_subgoal="Accept the compliant fictional offer.",
            ranked_preference_positions=(),
            allowed_disclosures=(),
            approval_required_disclosures=(),
            concession_ladder=(),
            fallback_outcomes=(),
            required_completion_evidence=(
                EvidenceRequirement(
                    evidence_type=EvidenceType.CONFIRMATION,
                    description="A fictional Provider confirmation is required.",
                ),
            ),
            escalation_conditions=(),
            replan_conditions=(),
        ),
        next_capability=AcceptOfferCapabilityModelOutput(
            capability="accept_offer", offer_position=0
        ),
    )

    result = compile_slow_output(request, output)

    assert result.strategy_proposal is not None
    (intent,) = result.action_proposals
    (proposal,) = result.capability_proposals
    assert intent.material_terms == offer_material_terms(offer)
    assert intent.material_terms_hash == material_terms_hash(intent.material_terms)

    executed_at = NOW + timedelta(minutes=1)
    approval = _approve(intent, decided_at=NOW)
    snapshot = _snapshot(
        episode.case,
        offer,
        strategy=result.strategy_proposal,
        approvals=(approval,),
    )
    outcome = CapabilityExecutor(
        _AcceptCapability(episode.case.case_id),
        terms_derivation=offer_material_terms,
    ).execute(
        CapabilityExecutionRequest(
            snapshot=snapshot,
            source_pins=snapshot.pins,
            proposal=proposal,
            action_intent=intent,
            approval=approval,
            executed_at=executed_at,
        )
    )

    assert "current_offer_terms_mismatch" not in outcome.reason_codes
    assert "action_material_terms_hash_mismatch" not in outcome.reason_codes
    assert outcome.status is CapabilityExecutionStatus.EXECUTED, outcome.reason_codes


def test_material_terms_hash_bytes_are_frozen() -> None:
    assert material_terms_hash(THREE_TERMS) == THREE_TERMS_DIGEST
    assert material_terms_hash(SIX_TERMS) == SIX_TERMS_DIGEST
    # Order-insensitive: the hash sorts by (name, value).
    assert material_terms_hash(tuple(reversed(SIX_TERMS))) == SIX_TERMS_DIGEST


def test_telecom_domain_re_exports_the_contracts_authority() -> None:
    assert domain_material_terms_hash is material_terms_hash
    assert domain_offer_material_terms is offer_material_terms


# Historical byte-equal copies of the material-terms derivation and hash that
# are deliberately left in place: ``slow_output.py`` is frozen by the r4
# execution contract; the other two reproduce historical artifacts and use
# ``CapabilityExecutor`` without ``terms_derivation`` so they cannot mismatch
# the executor. Any new copy outside this allowlist fails the test below.
HISTORICAL_COPIES = frozenset(
    {
        "ml/evaluation/src/proxyloop_evaluation/slow_output.py",
        "ml/evaluation/src/proxyloop_evaluation/legacy_slow_output.py",
        "scripts/run_phase_03a1_harness.py",
    }
)


def _python_sources() -> list[Path]:
    skipped = {"__pycache__", ".venv", "node_modules"}
    found: list[Path] = []
    for root in ("runtime", "ml", "scripts"):
        for path in (REPO_ROOT / root).rglob("*.py"):
            if skipped.isdisjoint(path.parts):
                found.append(path)
    return found


def test_exactly_one_definition_of_each_policy_authority() -> None:
    # Renamed private copies (``_material_terms_hash``, ``_material_terms``)
    # count as definitions too; only the recorded historical copies may hold one.
    patterns = {
        "offer_compliance_violations": re.compile(
            r"^def _?offer_compliance_violations\(", re.MULTILINE
        ),
        "material_terms_hash": re.compile(
            r"^def _?material_terms_hash\(", re.MULTILINE
        ),
        "offer_material_terms": re.compile(
            r"^def _?(offer_)?material_terms\(", re.MULTILINE
        ),
        "SUPPORTED_APPLIED_CHANGES": re.compile(
            r"^_?SUPPORTED_APPLIED_CHANGES\s*[:=]", re.MULTILINE
        ),
    }
    definitions: dict[str, list[str]] = {name: [] for name in patterns}
    for path in _python_sources():
        relative = str(path.relative_to(REPO_ROOT))
        if relative in HISTORICAL_COPIES:
            continue
        text = path.read_text(encoding="utf-8")
        for name, pattern in patterns.items():
            if pattern.search(text):
                definitions[name].append(relative)
    assert {name: len(paths) for name, paths in definitions.items()} == {
        name: 1 for name in patterns
    }, definitions


def test_legacy_predicate_and_private_change_list_are_gone() -> None:
    pattern = re.compile(r"_legacy_offer_is_valid|_SUPPORTED_APPLIED_CHANGES")
    hits = [
        str(path.relative_to(REPO_ROOT))
        for path in _python_sources()
        if str(path.relative_to(REPO_ROOT)) not in HISTORICAL_COPIES
        and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert hits == []
