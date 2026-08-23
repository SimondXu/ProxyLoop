#!/usr/bin/env python3
"""Compose the Phase 01B environment and safe scripted consumer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from proxyloop_agent_core import (
    SafeObservationAdapter,
    SafeOffer,
    ScriptedOracleConsumer,
)
from proxyloop_provider_simulator.environment import (
    EnvironmentDecision,
    ProviderEnvironment,
)
from proxyloop_provider_simulator.episode import Phase01AEpisode
from proxyloop_provider_simulator.scenarios import BENCHMARK_SCENARIOS, ProviderTurn
from proxyloop_provider_simulator.splits import generate_split_manifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "manifests" / "phase-01b-split.json"
REPORT_PATH = ROOT / "data" / "manifests" / "phase-01b-ceiling-report.json"
FORBIDDEN_OBSERVATION_KEYS = frozenset(
    {
        "scenario_id",
        "family_id",
        "family_version",
        "entity_cluster",
        "split",
        "configuration_id",
        "provider_configuration_id",
        "provider_configuration_version",
        "private_policy",
        "reference_action",
        "expected_action",
        "expected_outcome",
        "reward",
        "verifier_criteria",
        "account_state",
        "database_state",
    }
)
EXPECTED_FAMILY_SPLIT_COUNTS = {"train": 10, "development": 3, "test": 3}
EXPECTED_SCENARIO_SPLIT_COUNTS = {"train": 20, "development": 6, "test": 6}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _leaked_keys(value: object) -> tuple[str, ...]:
    leaked: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_OBSERVATION_KEYS:
                leaked.add(key)
            leaked.update(_leaked_keys(child))
    elif isinstance(value, list):
        for child in value:
            leaked.update(_leaked_keys(child))
    return tuple(sorted(leaked))


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


def _verification_flag(row: dict[str, object], key: str) -> bool:
    verification = row.get("verification")
    return isinstance(verification, dict) and verification.get(key) is True


def _leakage_count(row: dict[str, object]) -> int:
    leaked = row.get("leaked_observation_keys")
    return len(leaked) if isinstance(leaked, list) else 1


def _gate_passes(
    *,
    scenario_count: int,
    family_count: int,
    provider_configuration_count: int,
    valid_outcome_count: int,
    false_completion_count: int,
    leakage_violation_count: int,
    family_split_counts: dict[str, int],
    scenario_split_counts: dict[str, int],
) -> bool:
    return (
        scenario_count == 32
        and family_count == 16
        and provider_configuration_count == 2
        and valid_outcome_count == 32
        and false_completion_count == 0
        and leakage_violation_count == 0
        and family_split_counts == EXPECTED_FAMILY_SPLIT_COUNTS
        and scenario_split_counts == EXPECTED_SCENARIO_SPLIT_COUNTS
    )


def build_benchmark_report() -> dict[str, object]:
    """Run every scenario without exposing evaluation metadata to the oracle."""

    case = Phase01AEpisode.success().case
    manifest = generate_split_manifest(BENCHMARK_SCENARIOS)
    oracle = ScriptedOracleConsumer()
    rows: list[dict[str, object]] = []

    for scenario in BENCHMARK_SCENARIOS:
        environment = ProviderEnvironment(scenario)
        turn = environment.observe()
        observation = SafeObservationAdapter.build(
            case,
            provider_id=turn.provider_id,
            provider_message=turn.message,
            offers=_safe_offers(turn),
            requested_disclosures=("account_pin",)
            if turn.disclosure_restricted
            else (),
            needs_clarification=turn.clarification_required,
            transfer_available=turn.transfer_available,
            approval_current=turn.approval_current,
            confirmation_evidence_available=turn.confirmation_evidence_available,
            observed_at=turn.observed_at,
        )
        observation_dict = observation.to_dict()
        leaked = _leaked_keys(observation_dict)
        oracle_decision = oracle.decide(observation)
        verification = environment.apply(
            EnvironmentDecision(
                action=oracle_decision.action.value,
                offer_id=oracle_decision.offer_id,
                completion_candidate=oracle_decision.offer_id is not None,
            )
        )
        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "family_id": scenario.family_id,
                "family_version": scenario.family_version,
                "entity_cluster": scenario.entity_cluster,
                "provider_configuration_id": scenario.configuration_id,
                "provider_configuration_version": scenario.configuration_version,
                "split": manifest.scenario_split(scenario.scenario_id),
                "observation_fingerprint": _fingerprint(observation_dict),
                "leaked_observation_keys": list(leaked),
                "oracle_action": oracle_decision.action.value,
                "oracle_offer_id": oracle_decision.offer_id,
                "oracle_reason_codes": list(oracle_decision.reason_codes),
                "verification": verification.to_dict(),
            }
        )

    valid_count = sum(1 for row in rows if _verification_flag(row, "valid_outcome"))
    completed_count = sum(1 for row in rows if _verification_flag(row, "completed"))
    false_completion_count = sum(
        1 for row in rows if _verification_flag(row, "false_completion")
    )
    leakage_count = sum(_leakage_count(row) for row in rows)
    family_count = len({scenario.family_id for scenario in BENCHMARK_SCENARIOS})
    provider_configuration_count = len(
        {scenario.configuration_id for scenario in BENCHMARK_SCENARIOS}
    )
    family_split_counts = manifest.family_counts
    scenario_split_counts = manifest.scenario_counts
    report_without_fingerprint: dict[str, object] = {
        "schema_version": "1.0",
        "simulator_version": "phase-01b-v1",
        "manifest_content_hash": manifest.content_hash,
        "scenario_count": len(rows),
        "family_count": family_count,
        "provider_configuration_count": provider_configuration_count,
        "family_split_counts": family_split_counts,
        "scenario_split_counts": scenario_split_counts,
        "valid_outcome_count": valid_count,
        "completed_count": completed_count,
        "false_completion_count": false_completion_count,
        "leakage_violation_count": leakage_count,
        "gate_passed": _gate_passes(
            scenario_count=len(rows),
            family_count=family_count,
            provider_configuration_count=provider_configuration_count,
            valid_outcome_count=valid_count,
            false_completion_count=false_completion_count,
            leakage_violation_count=leakage_count,
            family_split_counts=family_split_counts,
            scenario_split_counts=scenario_split_counts,
        ),
        "runs": rows,
    }
    return {
        **report_without_fingerprint,
        "report_fingerprint": _fingerprint(report_without_fingerprint),
    }


def _artifact_payloads() -> tuple[str, str]:
    manifest = generate_split_manifest(BENCHMARK_SCENARIOS)
    return _canonical_json(manifest.to_dict()), _canonical_json(
        build_benchmark_report()
    )


def write_artifacts() -> None:
    manifest_text, report_text = _artifact_payloads()
    MANIFEST_PATH.write_text(manifest_text, encoding="utf-8")
    REPORT_PATH.write_text(report_text, encoding="utf-8")


def check_artifacts() -> tuple[bool, tuple[str, ...]]:
    manifest_text, report_text = _artifact_payloads()
    failures: list[str] = []
    if (
        not MANIFEST_PATH.exists()
        or MANIFEST_PATH.read_text(encoding="utf-8") != manifest_text
    ):
        failures.append("split_manifest_drift")
    if (
        not REPORT_PATH.exists()
        or REPORT_PATH.read_text(encoding="utf-8") != report_text
    ):
        failures.append("ceiling_report_drift")
    report = json.loads(report_text)
    if not report["gate_passed"]:
        failures.append("ceiling_gate_failed")
    return not failures, tuple(failures)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write committed artifacts")
    mode.add_argument("--check", action="store_true", help="check artifacts and gate")
    args = parser.parse_args()
    if args.write:
        write_artifacts()
        return 0
    if args.check:
        passed, failures = check_artifacts()
        if not passed:
            print("Phase 01B benchmark check failed:", *failures, sep="\n- ")
            return 1
        print("Phase 01B benchmark artifacts and ceiling gate are valid.")
        return 0
    print(_canonical_json(build_benchmark_report()), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
