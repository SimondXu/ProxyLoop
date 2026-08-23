from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from proxyloop_agent_core import (
    OracleAction,
    SafeObservationAdapter,
    SafeOffer,
    ScriptedOracleConsumer,
)
from proxyloop_provider_simulator.environment import (
    EnvironmentDecision,
    ProviderEnvironment,
)
from proxyloop_provider_simulator.episode import Phase01AEpisode
from proxyloop_provider_simulator.scenarios import (
    BENCHMARK_SCENARIOS,
    BenchmarkScenario,
    ProviderTurn,
)
from proxyloop_provider_simulator.splits import generate_split_manifest
from pydantic import ValidationError

from .models import (
    GenerationRecord,
    GeneratorSnapshot,
    LearningContent,
    LicenseRecord,
    NormalizedTrajectory,
    SourceProvenance,
    TrajectoryDecision,
    TrajectoryLineage,
    TrajectoryVerification,
)

SCHEMA_VERSION: Literal["1.0"] = "1.0"
SIMULATOR_VERSION = "phase-01b-v1"
LICENSE_ID = "LicenseRef-ProxyLoop-Synthetic-1.0"
FORBIDDEN_MODEL_KEYS = frozenset(
    {
        "account_state",
        "database_state",
        "entity_cluster",
        "expected_action",
        "expected_outcome",
        "family_id",
        "private_policy",
        "private_reason_codes",
        "reference_action",
        "reward",
        "scenario_label",
        "split",
        "verifier_criteria",
    }
)
HIGH_RISK_PII_FIELDS = frozenset(
    {
        "account_number",
        "credit_card",
        "email",
        "payment_identifier",
        "phone",
        "phone_number",
        "pin",
        "social_security_number",
    }
)
PII_PATTERNS = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"\b(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b"),
)

_RESPONSE_TEMPLATES: dict[OracleAction, tuple[str, ...]] = {
    OracleAction.ACCEPT_OFFER: (
        "This offer meets the stated constraints; proceed with the verified offer.",
        "The quoted terms preserve the required features and fit the target.",
        (
            "I can proceed with this eligible offer because its public terms are "
            "acceptable."
        ),
        "The available offer satisfies the consumer constraints and can move forward.",
    ),
    OracleAction.REQUEST_CLARIFICATION: (
        "Please clarify the allowed service detail before I continue.",
        "I need one permitted service detail to evaluate the available options.",
        (
            "The current information is incomplete; please provide the allowed "
            "clarification."
        ),
        "I cannot select an option until the missing permitted detail is clarified.",
    ),
    OracleAction.ESCALATE: (
        "Please transfer this request to the available specialist.",
        (
            "The current path cannot resolve the constraints, so specialist review "
            "is needed."
        ),
        "Use the offered escalation path for a bounded specialist review.",
        (
            "I will escalate safely because the available terms require specialist "
            "handling."
        ),
    ),
    OracleAction.REQUEST_REPLAN: (
        "The current state cannot support completion; request a revised plan.",
        "I need a fresh plan before taking any consequential action.",
        "The available evidence or authorization is insufficient, so replan first.",
        "Do not claim completion; obtain an updated plan and current evidence.",
    ),
    OracleAction.REFUSE_DISCLOSURE: (
        "I cannot disclose information outside the consumer's delegated authority.",
        "That requested disclosure is not authorized, so I must decline it.",
        "Proceed without the restricted information or use an approved alternative.",
        "The consumer did not permit that disclosure; I will not provide it.",
    ),
    OracleAction.DECLINE: (
        "I decline this offer because it does not satisfy the consumer constraints.",
        "The public terms are not acceptable, so I will not proceed.",
        "This option fails the required checks and must be declined.",
        "Do not accept the current offer; its terms do not meet the stated limits.",
    ),
}


@dataclass(frozen=True)
class PilotBundle:
    accepted: tuple[NormalizedTrajectory, ...]
    quarantined: tuple[dict[str, object], ...]
    manifest: dict[str, object]
    quarantine_manifest: dict[str, object]
    report: dict[str, object]
    review_sample: dict[str, object]
    schema: dict[str, object]


@dataclass(frozen=True)
class ExternalUsage:
    model_call_count: int = 0
    input_token_count: int = 0
    output_token_count: int = 0
    estimated_cost_usd: float = 0.0


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pretty_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _safe_offers(turn: ProviderTurn) -> tuple[SafeOffer, ...]:
    return tuple(
        SafeOffer(
            offer_id=offer.offer_id,
            provider_id=turn.provider_id,
            monthly_price_minor=offer.monthly_price_minor,
            total_cost_12_months_minor=offer.total_cost_12_months_minor,
            currency=offer.currency,
            features=offer.features,
            fees_minor=offer.fees_minor,
            term_months=offer.term_months,
            applied_changes=offer.applied_changes,
            expires_at=offer.expires_at,
        )
        for offer in turn.offers
    )


def _normalize_lexical_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    without_punctuation = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in normalized
    )
    return " ".join(without_punctuation.split())


def _normalize_lexical_value(value: object) -> object:
    if isinstance(value, dict):
        return {key: _normalize_lexical_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_normalize_lexical_value(child) for child in value]
    if isinstance(value, str):
        return _normalize_lexical_text(value)
    return value


def _lexical_fingerprint_payload(content: dict[str, object]) -> dict[str, object]:
    observation = deepcopy(content["observation"])
    assert isinstance(observation, dict)
    observation.pop("case_id", None)
    observation.pop("observed_at", None)
    offers = observation.get("offers")
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                offer.pop("offer_id", None)
                offer.pop("expires_at", None)
    decision = content["decision"]
    assert isinstance(decision, dict)
    payload: dict[str, object] = {
        "observation": observation,
        "action": decision.get("action"),
        "completion_candidate": decision.get("completion_candidate"),
        "assistant_response_text": content["assistant_response_text"],
    }
    normalized = _normalize_lexical_value(payload)
    assert isinstance(normalized, dict)
    return normalized


def lexical_fingerprint(content: dict[str, object]) -> str:
    return fingerprint(_lexical_fingerprint_payload(content))


def _build_trajectory(
    scenario: BenchmarkScenario,
    *,
    response_variant: int,
    split_manifest_hash: str,
    split: str,
) -> NormalizedTrajectory:
    environment = ProviderEnvironment(scenario)
    turn = environment.observe()
    observation = SafeObservationAdapter.build(
        Phase01AEpisode.success().case,
        provider_id=turn.provider_id,
        provider_message=turn.message,
        offers=_safe_offers(turn),
        requested_disclosures=("account_pin",) if turn.disclosure_restricted else (),
        needs_clarification=turn.clarification_required,
        transfer_available=turn.transfer_available,
        approval_current=turn.approval_current,
        confirmation_evidence_available=turn.confirmation_evidence_available,
        observed_at=turn.observed_at,
    )
    oracle = ScriptedOracleConsumer().decide(observation)
    completion_candidate = oracle.offer_id is not None
    verification = environment.apply(
        EnvironmentDecision(
            action=oracle.action.value,
            offer_id=oracle.offer_id,
            completion_candidate=completion_candidate,
        )
    )
    response_text = _RESPONSE_TEMPLATES[oracle.action][response_variant]
    learning_content = LearningContent(
        observation=observation.to_dict(),
        decision=TrajectoryDecision(
            action=oracle.action.value,
            offer_id=oracle.offer_id,
            completion_candidate=completion_candidate,
        ),
        assistant_response_text=response_text,
    )
    verification_record = TrajectoryVerification(
        valid_outcome=verification.valid_outcome,
        completed=verification.completed,
        false_completion=verification.false_completion,
        reason_codes=verification.reason_codes,
        evidence_ref=verification.evidence_ref,
    )
    content_payload = {
        "learning_content": learning_content.model_dump(mode="json"),
        "verification": verification_record.model_dump(mode="json"),
    }
    return NormalizedTrajectory(
        schema_version=SCHEMA_VERSION,
        trajectory_id=f"{scenario.scenario_id}::trajectory-{response_variant + 1}",
        source=SourceProvenance(
            source_id="proxyloop-phase-01b-simulator",
            source_type="project_owned_simulator",
            license=LicenseRecord(
                license_id=LICENSE_ID,
                status="approved",
                allowed_use="research_training_and_evaluation",
            ),
        ),
        lineage=TrajectoryLineage(
            derivation_parent_id=scenario.scenario_id,
            family_id=scenario.family_id,
            family_version=scenario.family_version,
            entity_cluster=scenario.entity_cluster,
            provider_configuration_id=scenario.configuration_id,
            provider_configuration_version=scenario.configuration_version,
            split=split,  # type: ignore[arg-type]
            response_variant=response_variant,
        ),
        generation=GenerationRecord(
            simulator_version=SIMULATOR_VERSION,
            split_manifest_hash=split_manifest_hash,
            prompt_template_hash=fingerprint("safe-observation-fast-turn-v1"),
            generation_config_hash=fingerprint(
                {"response_template_version": "1.0", "variant": response_variant}
            ),
            snapshots=(
                GeneratorSnapshot(
                    role="teacher",
                    adapter_id="scripted-oracle-consumer",
                    version="phase-01b-v1",
                ),
                GeneratorSnapshot(
                    role="provider",
                    adapter_id=scenario.configuration_id,
                    version=scenario.configuration_version,
                ),
                GeneratorSnapshot(
                    role="judge",
                    adapter_id="provider-environment-verifier",
                    version="phase-01b-v1",
                ),
            ),
        ),
        learning_content=learning_content,
        verification=verification_record,
        review_state="pending_human",
        content_hash=fingerprint(content_payload),
        semantic_fingerprint=lexical_fingerprint(
            learning_content.model_dump(mode="json")
        ),
    )


def _forbidden_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in FORBIDDEN_MODEL_KEYS:
                found.add(key)
            found.update(_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_forbidden_keys(child))
    return found


def _has_pii(value: object, *, field_name: str | None = None) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in HIGH_RISK_PII_FIELDS or _has_pii(
                child, field_name=key
            ):
                return True
        return False
    if isinstance(value, list):
        return any(_has_pii(child, field_name=field_name) for child in value)
    if field_name == "case_id" and isinstance(value, str):
        try:
            UUID(value)
        except ValueError:
            pass
        else:
            return False
    return isinstance(value, str) and any(
        pattern.search(value) for pattern in PII_PATTERNS
    )


def _expected_trajectory(
    record: NormalizedTrajectory,
) -> NormalizedTrajectory | None:
    scenario = next(
        (
            item
            for item in BENCHMARK_SCENARIOS
            if item.scenario_id == record.lineage.derivation_parent_id
        ),
        None,
    )
    if scenario is None:
        return None
    split_manifest = generate_split_manifest(BENCHMARK_SCENARIOS)
    return _build_trajectory(
        scenario,
        response_variant=record.lineage.response_variant,
        split_manifest_hash=split_manifest.content_hash,
        split=split_manifest.scenario_split(scenario.scenario_id),
    )


def _intrinsic_rejection(raw: dict[str, object]) -> str | None:
    if "source" not in raw:
        return "missing_provenance"
    raw_content = raw.get("learning_content")
    if _has_pii(raw_content):
        return "pii_detected"
    if _forbidden_keys(raw_content):
        return "forbidden_model_field"
    try:
        record = NormalizedTrajectory.model_validate(raw)
    except ValidationError:
        return "missing_provenance"
    if record.source.license.status != "approved":
        return "unapproved_license"
    expected_record = _expected_trajectory(record)
    if expected_record is None:
        return "split_mismatch"
    if (
        record.source != expected_record.source
        or record.generation != expected_record.generation
    ):
        return "missing_provenance"
    model_content = record.learning_content.model_dump(mode="json")
    if _has_pii(model_content):
        return "pii_detected"
    if _forbidden_keys(model_content):
        return "forbidden_model_field"
    if record.lineage != expected_record.lineage:
        return "split_mismatch"
    if not record.verification.valid_outcome or record.verification.false_completion:
        return "invalid_verifier_outcome"
    content_payload = {
        "learning_content": model_content,
        "verification": record.verification.model_dump(mode="json"),
    }
    if record.content_hash != fingerprint(content_payload):
        return "invalid_verifier_outcome"
    if record.semantic_fingerprint != lexical_fingerprint(model_content):
        return "invalid_verifier_outcome"
    return None


def _matches_environment(record: NormalizedTrajectory) -> bool:
    expected_record = _expected_trajectory(record)
    return (
        expected_record is not None
        and record.learning_content == expected_record.learning_content
        and record.verification == expected_record.verification
    )


def _snapshot_usage(snapshots: tuple[GeneratorSnapshot, ...]) -> ExternalUsage:
    return ExternalUsage(
        model_call_count=sum(snapshot.external_model for snapshot in snapshots),
        input_token_count=sum(
            snapshot.external_input_token_count for snapshot in snapshots
        ),
        output_token_count=sum(
            snapshot.external_output_token_count for snapshot in snapshots
        ),
        estimated_cost_usd=sum(
            snapshot.estimated_external_cost_usd for snapshot in snapshots
        ),
    )


def _raw_snapshot_usage(raw: dict[str, object]) -> ExternalUsage:
    generation = raw.get("generation")
    if not isinstance(generation, dict):
        return ExternalUsage()
    snapshots = generation.get("snapshots")
    if not isinstance(snapshots, (list, tuple)):
        return ExternalUsage()
    model_calls = 0
    input_tokens = 0
    output_tokens = 0
    estimated_cost = 0.0
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        model_calls += int(snapshot.get("external_model") is True)
        input_tokens += _nonnegative_int(snapshot.get("external_input_token_count"))
        output_tokens += _nonnegative_int(snapshot.get("external_output_token_count"))
        estimated_cost += _nonnegative_float(
            snapshot.get("estimated_external_cost_usd")
        )
    return ExternalUsage(model_calls, input_tokens, output_tokens, estimated_cost)


def _usage_payload(usage: ExternalUsage) -> dict[str, int | float]:
    return {
        "external_model_call_count": usage.model_call_count,
        "external_input_token_count": usage.input_token_count,
        "external_output_token_count": usage.output_token_count,
        "estimated_external_cost_usd": usage.estimated_cost_usd,
    }


def _quarantine_usage(records: tuple[dict[str, object], ...]) -> ExternalUsage:
    model_calls = 0
    input_tokens = 0
    output_tokens = 0
    estimated_cost = 0.0
    for record in records:
        audit = record.get("audit")
        if not isinstance(audit, dict):
            continue
        model_calls += _nonnegative_int(audit.get("external_model_call_count"))
        input_tokens += _nonnegative_int(audit.get("external_input_token_count"))
        output_tokens += _nonnegative_int(audit.get("external_output_token_count"))
        estimated_cost += _nonnegative_float(audit.get("estimated_external_cost_usd"))
    return ExternalUsage(model_calls, input_tokens, output_tokens, estimated_cost)


def _nonnegative_int(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


def _nonnegative_float(value: object) -> float:
    if type(value) is int and value >= 0:
        return float(value)
    if isinstance(value, float) and value >= 0:
        return value
    return 0.0


def curate_candidates(
    candidates: list[dict[str, object]],
) -> tuple[tuple[NormalizedTrajectory, ...], tuple[dict[str, object], ...]]:
    accepted: list[NormalizedTrajectory] = []
    quarantined: list[dict[str, object]] = []
    content_splits: dict[str, str] = {}
    semantic_splits: dict[str, str] = {}
    for raw in sorted(candidates, key=lambda item: str(item.get("trajectory_id", ""))):
        reason = _intrinsic_rejection(raw)
        record: NormalizedTrajectory | None = None
        if reason is None:
            record = NormalizedTrajectory.model_validate(raw)
            previous_content_split = content_splits.get(record.content_hash)
            if previous_content_split is not None:
                reason = (
                    "cross_split_semantic_collision"
                    if previous_content_split != record.lineage.split
                    else "exact_duplicate"
                )
            else:
                previous_semantic_split = semantic_splits.get(
                    record.semantic_fingerprint
                )
                if (
                    previous_semantic_split is not None
                    and previous_semantic_split != record.lineage.split
                ):
                    reason = "cross_split_semantic_collision"
            if reason is None and not _matches_environment(record):
                reason = "invalid_verifier_outcome"
        if reason is not None:
            quarantined.append(
                {
                    "candidate_id": str(raw.get("trajectory_id", "missing-id")),
                    "reason_codes": [reason],
                    "audit": _usage_payload(_raw_snapshot_usage(raw)),
                }
            )
            continue
        assert record is not None
        accepted.append(record)
        content_splits[record.content_hash] = record.lineage.split
        semantic_splits.setdefault(record.semantic_fingerprint, record.lineage.split)
    return tuple(accepted), tuple(quarantined)


def _negative_probes(
    valid: tuple[NormalizedTrajectory, ...],
) -> list[dict[str, object]]:
    base = valid[0].model_dump(mode="python")
    probes: list[dict[str, object]] = []

    missing = deepcopy(base)
    missing["trajectory_id"] = "zz-probe-01-missing-provenance"
    del missing["source"]
    probes.append(missing)

    unapproved = deepcopy(base)
    unapproved["trajectory_id"] = "zz-probe-02-unapproved-license"
    unapproved["source"]["license"]["status"] = "unapproved"
    probes.append(unapproved)

    pii = deepcopy(base)
    pii["trajectory_id"] = "zz-probe-03-pii"
    pii["learning_content"]["assistant_response_text"] += " contact test@example.com"
    _refresh_hashes(pii)
    probes.append(pii)

    forbidden = deepcopy(base)
    forbidden["trajectory_id"] = "zz-probe-04-forbidden-field"
    forbidden["learning_content"]["observation"]["expected_action"] = "accept_offer"
    _refresh_hashes(forbidden)
    probes.append(forbidden)

    duplicate = deepcopy(base)
    duplicate["trajectory_id"] = "zz-probe-05-exact-duplicate"
    probes.append(duplicate)

    train_record = next(item for item in valid if item.lineage.split == "train")
    dev_record = next(item for item in valid if item.lineage.split == "development")
    cross_split = dev_record.model_dump(mode="python")
    cross_split["trajectory_id"] = "zz-probe-06-cross-split-semantic"
    cross_split["learning_content"] = train_record.learning_content.model_dump(
        mode="python"
    )
    cross_content = cross_split["learning_content"]
    assert isinstance(cross_content, dict)
    cross_observation = cross_content["observation"]
    assert isinstance(cross_observation, dict)
    provider_message = cross_observation["provider_message"]
    assert isinstance(provider_message, str)
    cross_observation["provider_message"] = "  " + provider_message.upper() + " !!! "
    response_text = cross_content["assistant_response_text"]
    assert isinstance(response_text, str)
    cross_content["assistant_response_text"] = f"  {response_text.upper()} !!! "
    cross_split["verification"] = train_record.verification.model_dump(mode="python")
    _refresh_hashes(cross_split)
    probes.append(cross_split)

    split_mismatch = deepcopy(base)
    split_mismatch["trajectory_id"] = "zz-probe-07-split-mismatch"
    current_split = split_mismatch["lineage"]["split"]
    split_mismatch["lineage"]["split"] = "test" if current_split != "test" else "train"
    probes.append(split_mismatch)

    invalid = deepcopy(base)
    invalid["trajectory_id"] = "zz-probe-08-invalid-verifier"
    invalid["verification"]["valid_outcome"] = False
    _refresh_hashes(invalid)
    probes.append(invalid)
    return probes


def _refresh_hashes(raw: dict[str, object]) -> None:
    learning_content = raw["learning_content"]
    verification = raw["verification"]
    raw["content_hash"] = fingerprint(
        {"learning_content": learning_content, "verification": verification}
    )
    assert isinstance(learning_content, dict)
    raw["semantic_fingerprint"] = lexical_fingerprint(learning_content)


def _summary(record: NormalizedTrajectory) -> dict[str, object]:
    return {
        "trajectory_id": record.trajectory_id,
        "family_id": record.lineage.family_id,
        "family_version": record.lineage.family_version,
        "entity_cluster": record.lineage.entity_cluster,
        "provider_configuration_id": record.lineage.provider_configuration_id,
        "provider_configuration_version": (
            record.lineage.provider_configuration_version
        ),
        "split": record.lineage.split,
        "response_variant": record.lineage.response_variant,
        "source_id": record.source.source_id,
        "license_id": record.source.license.license_id,
        "simulator_version": record.generation.simulator_version,
        "review_state": record.review_state,
        "content_hash": record.content_hash,
        "semantic_fingerprint": record.semantic_fingerprint,
    }


def _redacted_review_sample(
    accepted: tuple[NormalizedTrajectory, ...],
) -> dict[str, object]:
    by_family: dict[str, NormalizedTrajectory] = {}
    for record in accepted:
        by_family.setdefault(record.lineage.family_id, record)
    records: list[dict[str, object]] = []
    for family_id, record in sorted(by_family.items()):
        observation = record.learning_content.observation
        requested = observation.get("requested_disclosures", [])
        records.append(
            {
                "trajectory_id": record.trajectory_id,
                "family_id": family_id,
                "split": record.lineage.split,
                "review_state": record.review_state,
                "provider_message": observation["provider_message"],
                "requested_disclosures": (
                    ["[REDACTED_DISCLOSURE_FIELD]"] if requested else []
                ),
                "oracle_action": record.learning_content.decision.action,
                "assistant_response_text": (
                    record.learning_content.assistant_response_text
                ),
                "verification": record.verification.model_dump(mode="json"),
            }
        )
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "selection_method": "lowest_trajectory_id_per_family",
        "review_status": "pending_human",
        "records": records,
    }
    return {**payload, "sample_fingerprint": fingerprint(payload)}


def _has_complete_provenance(record: NormalizedTrajectory) -> bool:
    expected_record = _expected_trajectory(record)
    return (
        expected_record is not None
        and record.source == expected_record.source
        and record.lineage == expected_record.lineage
        and record.generation == expected_record.generation
    )


def _accepted_cross_split_leakage_count(
    accepted: tuple[NormalizedTrajectory, ...],
) -> int:
    splits_by_fingerprint: dict[str, set[str]] = {}
    for record in accepted:
        splits_by_fingerprint.setdefault(record.semantic_fingerprint, set()).add(
            record.lineage.split
        )
    return sum(len(splits) - 1 for splits in splits_by_fingerprint.values())


def _reason_counts(records: tuple[dict[str, object], ...]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        reason_codes = record["reason_codes"]
        assert isinstance(reason_codes, list)
        for reason in reason_codes:
            assert isinstance(reason, str)
            counts[reason] += 1
    return dict(counts)


def build_quality_report(
    accepted: tuple[NormalizedTrajectory, ...],
    quarantined: tuple[dict[str, object], ...],
) -> dict[str, object]:
    split_counts = dict(Counter(record.lineage.split for record in accepted))
    provenance_complete_count = sum(
        _has_complete_provenance(record) for record in accepted
    )
    accepted_pii_violation_count = sum(
        _has_pii(record.learning_content.model_dump(mode="json")) for record in accepted
    )
    accepted_forbidden_field_count = sum(
        bool(_forbidden_keys(record.learning_content.model_dump(mode="json")))
        for record in accepted
    )
    accepted_exact_duplicate_count = len(accepted) - len(
        {record.content_hash for record in accepted}
    )
    accepted_cross_split_leakage_count = _accepted_cross_split_leakage_count(accepted)
    accepted_usage = _snapshot_usage(
        tuple(
            snapshot for record in accepted for snapshot in record.generation.snapshots
        )
    )
    quarantined_usage = _quarantine_usage(quarantined)
    external_usage = ExternalUsage(
        accepted_usage.model_call_count + quarantined_usage.model_call_count,
        accepted_usage.input_token_count + quarantined_usage.input_token_count,
        accepted_usage.output_token_count + quarantined_usage.output_token_count,
        accepted_usage.estimated_cost_usd + quarantined_usage.estimated_cost_usd,
    )
    provenance_completeness_percent = (
        100.0 * provenance_complete_count / len(accepted) if accepted else 0.0
    )
    automated_audit_passed = (
        provenance_complete_count == len(accepted)
        and accepted_pii_violation_count == 0
        and accepted_forbidden_field_count == 0
        and accepted_exact_duplicate_count == 0
        and accepted_cross_split_leakage_count == 0
        and external_usage == ExternalUsage()
    )
    return {
        "schema_version": "1.0",
        "candidate_count": len(accepted) + len(quarantined),
        "accepted_count": len(accepted),
        "quarantined_count": len(quarantined),
        "split_counts": split_counts,
        "provenance_completeness_percent": provenance_completeness_percent,
        "accepted_pii_violation_count": accepted_pii_violation_count,
        "accepted_forbidden_field_count": accepted_forbidden_field_count,
        "accepted_exact_duplicate_count": accepted_exact_duplicate_count,
        "accepted_cross_split_leakage_count": accepted_cross_split_leakage_count,
        "quarantined_reason_counts": _reason_counts(quarantined),
        **_usage_payload(external_usage),
        "semantic_fingerprint_method": (
            "deterministic-lexical-public-content-case-whitespace-punctuation-v1"
        ),
        "automated_audit_status": "passed" if automated_audit_passed else "failed",
        "human_review_status": "pending_human",
        "training_ready": False,
        "expansion_decision": "conditional_data_factory_expansion",
        "limitations": [
            "one-turn scripted trajectories only",
            "deterministic lexical heuristic, not embedding or semantic equivalence",
            "human review sample is pending",
        ],
    }


def build_pilot(
    scenarios: tuple[BenchmarkScenario, ...] = BENCHMARK_SCENARIOS,
) -> PilotBundle:
    split_manifest = generate_split_manifest(BENCHMARK_SCENARIOS)
    valid = tuple(
        _build_trajectory(
            scenario,
            response_variant=variant,
            split_manifest_hash=split_manifest.content_hash,
            split=split_manifest.scenario_split(scenario.scenario_id),
        )
        for scenario in sorted(scenarios, key=lambda item: item.scenario_id)
        for variant in range(4)
    )
    raw_candidates = [item.model_dump(mode="python") for item in valid]
    raw_candidates.extend(_negative_probes(valid))
    accepted, quarantined = curate_candidates(raw_candidates)
    summaries = [_summary(record) for record in accepted]
    split_counts = dict(Counter(record.lineage.split for record in accepted))
    manifest_body: dict[str, object] = {
        "schema_version": "1.0",
        "split_manifest_hash": split_manifest.content_hash,
        "trajectory_count": len(accepted),
        "scenario_count": len({r.lineage.derivation_parent_id for r in accepted}),
        "family_count": len({r.lineage.family_id for r in accepted}),
        "provider_configuration_count": len(
            {r.lineage.provider_configuration_id for r in accepted}
        ),
        "split_counts": split_counts,
        "records": summaries,
    }
    manifest = {**manifest_body, "manifest_fingerprint": fingerprint(manifest_body)}
    quarantine_body: dict[str, object] = {
        "schema_version": "1.0",
        "candidate_count": len(quarantined),
        "reason_counts": _reason_counts(quarantined),
        "records": list(quarantined),
    }
    quarantine_manifest = {
        **quarantine_body,
        "quarantine_fingerprint": fingerprint(quarantine_body),
    }
    report_body = build_quality_report(accepted, quarantined)
    report = {**report_body, "report_fingerprint": fingerprint(report_body)}
    return PilotBundle(
        accepted=accepted,
        quarantined=quarantined,
        manifest=manifest,
        quarantine_manifest=quarantine_manifest,
        report=report,
        review_sample=_redacted_review_sample(accepted),
        schema=NormalizedTrajectory.model_json_schema(),
    )


def artifact_payloads() -> dict[Path, str]:
    root = Path(__file__).resolve().parents[4]
    bundle = build_pilot()
    return {
        root / "data/schemas/normalized-trajectory-v1.schema.json": pretty_json(
            bundle.schema
        ),
        root / "data/manifests/phase-02-pilot-manifest.json": pretty_json(
            bundle.manifest
        ),
        root / "data/manifests/phase-02-quarantine.json": pretty_json(
            bundle.quarantine_manifest
        ),
        root / "data/manifests/phase-02-quality-report.json": pretty_json(
            bundle.report
        ),
        root / "data/samples/phase-02-review-sample.json": pretty_json(
            bundle.review_sample
        ),
    }


__all__ = [
    "FORBIDDEN_MODEL_KEYS",
    "LICENSE_ID",
    "PilotBundle",
    "artifact_payloads",
    "build_pilot",
    "canonical_json",
    "curate_candidates",
    "fingerprint",
    "lexical_fingerprint",
    "pretty_json",
]
