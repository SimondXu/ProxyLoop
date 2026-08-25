"""Small, deterministic Phase 03B Gate 0 source-to-Fast review packet.

This module deliberately stops at a human-review artifact.  It does not train,
load, or call a model.  Phase 02's oracle fields remain reviewer-only and the
compiled Fast target cannot authorize an action or claim completion.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

from proxyloop_contracts import DialogueAct
from proxyloop_contracts.contracts import CompletionClaim, ReasonerRequest
from proxyloop_data_pipeline import NormalizedTrajectory, PilotBundle, build_pilot
from proxyloop_provider_simulator.scenarios import (
    BENCHMARK_SCENARIOS,
    BenchmarkScenario,
)
from proxyloop_provider_simulator.splits import generate_split_manifest

from proxyloop_evaluation.fast_output import FastModelOutput

SCHEMA_VERSION = "phase-03b-readiness-packet-v1"
SELECTION_METHOD = (
    "train-dev-only:retention-gated-v1-variant-0-per-family-plus-"
    "transparent-public-v1-high-risk-variant-0"
)
RETENTION_SUFFIX = "::retention-gated-v1@1.0"
TRANSPARENT_SUFFIX = "::transparent-public-v1@1.0"
HIGH_RISK_SCENARIOS = (
    "fee-total-cost-trap@1.0::transparent-public-v1@1.0",
    "disclosure-restriction@1.0::transparent-public-v1@1.0",
    "plan-change@1.0::transparent-public-v1@1.0",
)
REVIEW_QUESTIONS = (
    "action_correct",
    "response_grounded",
    "pii_safe",
    "disclosure_safe",
    "completion_safe",
    "escalation_correct",
    "authority_safe",
)
EXPECTED_SOURCE_COUNTS = {
    "accepted_total": 128,
    "train": 80,
    "development": 24,
    "test": 24,
}
SOURCE_MANIFEST_FINGERPRINT = (
    "11a8dead41ce4098df522742b163bd8eb6552f25455f09bb93b6dce7b9344258"
)
CANONICAL_RESPONSES = {
    "accept_offer": (
        "This visible offer appears to meet the stated constraints. Requesting "
        "Slow review before any acceptance."
    ),
    "decline": "This offer does not meet the stated constraints; do not accept it.",
    "request_clarification": (
        "Please clarify the allowed service detail before I continue."
    ),
    "request_replan": (
        "The current state cannot support safe continuation; request a revised "
        "strategy."
    ),
    "escalate": "Please transfer this request to the available specialist.",
    "refuse_disclosure": (
        "I cannot disclose information outside the consumer's delegated authority."
    ),
}
TARGET_DIALOGUE_ACTS = {
    "accept_offer": ("confirm", True, "offer_candidate_requires_slow_review"),
    "decline": ("counter", False, "none"),
    "request_clarification": ("clarify", False, "none"),
    "request_replan": ("counter", True, "provider_state_requires_replan"),
    "escalate": ("escalate", False, "none"),
    "refuse_disclosure": ("challenge", False, "none"),
}
FORBIDDEN_MODEL_INPUT_KEYS = frozenset(
    {
        "account_state",
        "database_state",
        "entity_cluster",
        "oracle_action",
        "oracle_offer_id",
        "oracle_completion_candidate",
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
        "reviewer_only",
        "source_label_for_human_review",
    }
)

ROOT = Path(__file__).resolve().parents[4]
PACKET_PATH = ROOT / "data/reviews/phase-03b-train-dev-review-packet.json"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _object(value: object) -> dict[str, object]:
    parsed = json.loads(json.dumps(value, ensure_ascii=False))
    if not isinstance(parsed, dict):
        raise TypeError("expected a JSON object")
    return cast(dict[str, object], parsed)


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in _all_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


def _train_dev_scenarios() -> tuple[BenchmarkScenario, ...]:
    split_manifest = generate_split_manifest(BENCHMARK_SCENARIOS)
    selected = tuple(
        scenario
        for scenario in BENCHMARK_SCENARIOS
        if split_manifest.scenario_split(scenario.scenario_id)
        in {"train", "development"}
    )
    if len(selected) != 26:
        raise RuntimeError(f"expected_26_train_dev_scenarios:{len(selected)}")
    if any(
        split_manifest.scenario_split(scenario.scenario_id) == "test"
        for scenario in selected
    ):
        raise RuntimeError("test_scenario_selected")
    return selected


def _accepted_train_dev_records(
    bundle: PilotBundle,
) -> tuple[NormalizedTrajectory, ...]:
    accepted = tuple(bundle.accepted)
    if len(accepted) != 104:
        raise RuntimeError(f"expected_104_train_dev_records:{len(accepted)}")
    if any(record.lineage.split == "test" for record in accepted):
        raise RuntimeError("test_record_accepted")
    train_count = sum(record.lineage.split == "train" for record in accepted)
    development_count = sum(
        record.lineage.split == "development" for record in accepted
    )
    if (train_count, development_count) != (80, 24):
        raise RuntimeError(
            f"train_dev_record_counts_changed:{train_count}:{development_count}"
        )
    return accepted


def _records_by_scenario(
    records: tuple[NormalizedTrajectory, ...],
) -> dict[str, tuple[NormalizedTrajectory, ...]]:
    groups: dict[str, list[NormalizedTrajectory]] = {}
    for record in records:
        groups.setdefault(record.lineage.derivation_parent_id, []).append(record)
    return {
        key: tuple(sorted(value, key=lambda item: item.lineage.response_variant))
        for key, value in groups.items()
    }


def _find_exact(
    records: tuple[NormalizedTrajectory, ...], *, scenario_id: str, variant: int
) -> NormalizedTrajectory:
    matches = tuple(
        record
        for record in records
        if record.lineage.derivation_parent_id == scenario_id
        and record.lineage.response_variant == variant
    )
    if len(matches) != 1:
        raise RuntimeError(f"missing_or_ambiguous_source_pin:{scenario_id}:{variant}")
    if matches[0].lineage.split == "test":
        raise RuntimeError(f"test_record_selected:{matches[0].trajectory_id}")
    return matches[0]


def _select_records(
    records: tuple[NormalizedTrajectory, ...],
) -> tuple[NormalizedTrajectory, ...]:
    train_dev = tuple(
        record for record in records if record.lineage.split in {"train", "development"}
    )
    family_ids = sorted(
        {
            record.lineage.family_id
            for record in train_dev
            if record.lineage.derivation_parent_id.endswith(RETENTION_SUFFIX)
            and record.lineage.response_variant == 0
        }
    )
    if len(family_ids) != 13:
        raise RuntimeError(f"expected_13_train_dev_families:{len(family_ids)}")
    selected = [
        _find_exact(
            train_dev,
            scenario_id=f"{family_id}@1.0{RETENTION_SUFFIX}",
            variant=0,
        )
        for family_id in family_ids
    ]
    selected.extend(
        _find_exact(train_dev, scenario_id=scenario_id, variant=0)
        for scenario_id in HIGH_RISK_SCENARIOS
    )
    selected_records = tuple(sorted(selected, key=lambda record: record.trajectory_id))
    if len(selected_records) != 16:
        raise RuntimeError(f"expected_16_selected_records:{len(selected_records)}")
    if any(record.lineage.split == "test" for record in selected_records):
        raise RuntimeError("test_record_selected")
    if len({record.lineage.family_id for record in selected_records}) != 13:
        raise RuntimeError("selected_family_count_mismatch")
    if len({record.lineage.derivation_parent_id for record in selected_records}) != 16:
        raise RuntimeError("selected_scenario_count_mismatch")
    return selected_records


def proposed_fast_target(action: str) -> dict[str, object]:
    try:
        dialogue_act, needed, reason_code = TARGET_DIALOGUE_ACTS[action]
        response = CANONICAL_RESPONSES[action]
    except KeyError as exc:
        raise ValueError(f"unsupported_oracle_action:{action}") from exc
    raw_target = {
        "dialogue_act": DialogueAct(dialogue_act),
        "fact_updates": (),
        "reasoner_request": ReasonerRequest(needed=needed, reason_code=reason_code),
        "completion_claim": CompletionClaim(status="not_done", evidence_message_ids=()),
        "response_text": response,
        "action_intent": None,
    }
    validated = FastModelOutput.model_validate(raw_target)
    return _object(validated.model_dump(mode="json"))


def _record_payload(
    record: NormalizedTrajectory,
    *,
    source_groups: dict[str, tuple[NormalizedTrajectory, ...]],
) -> dict[str, object]:
    action = record.learning_content.decision.action
    observation = _object(record.learning_content.observation)
    forbidden = FORBIDDEN_MODEL_INPUT_KEYS.intersection(_all_keys(observation))
    if forbidden:
        raise RuntimeError(f"private_fields_in_public_observation:{sorted(forbidden)}")
    source_group = source_groups.get(record.lineage.derivation_parent_id)
    if source_group is None or len(source_group) != 4:
        raise RuntimeError(
            "response_variant_group_mismatch:" + record.lineage.derivation_parent_id
        )
    if any(item.lineage.split == "test" for item in source_group):
        raise RuntimeError("test_record_in_variant_group")
    source_response_variants = [
        item.learning_content.assistant_response_text for item in source_group
    ]
    canonical_response = CANONICAL_RESPONSES.get(action)
    if canonical_response is None:
        raise ValueError(f"unsupported_oracle_action:{action}")
    decision = record.learning_content.decision
    source_label = {
        "reviewer_only": True,
        "oracle_action": action,
        "oracle_offer_id": decision.offer_id,
        "oracle_completion_candidate": decision.completion_candidate,
        "source_response_text": record.learning_content.assistant_response_text,
        "source_response_variants": source_response_variants,
    }
    return {
        "trajectory_id": record.trajectory_id,
        "source_fingerprint": _fingerprint(record.source.model_dump(mode="json")),
        "content_hash": record.content_hash,
        "semantic_fingerprint": record.semantic_fingerprint,
        "lineage": _object(record.lineage.model_dump(mode="json")),
        "model_input": {"public_observation": observation},
        "source_label_for_human_review": source_label,
        "proposed_fast_target": proposed_fast_target(action),
        "proposed_allowed_fast_response_texts": [canonical_response],
        "source_variant_group_size": len(source_group),
        "source_variant_grouped": True,
        "review_questions": {question: None for question in REVIEW_QUESTIONS},
        "human_decision": "pending",
        "notes": "",
    }


def build_packet() -> dict[str, object]:
    bundle = build_pilot(_train_dev_scenarios())
    train_dev = _accepted_train_dev_records(bundle)
    selected = _select_records(train_dev)
    source_groups = _records_by_scenario(train_dev)
    source_scenario_counts = {
        split: len(
            {
                record.lineage.derivation_parent_id
                for record in train_dev
                if record.lineage.split == split
            }
        )
        for split in ("train", "development")
    }
    source_variant_counts = {
        split: sum(
            len(group) == 4 and group[0].lineage.split == split
            for group in source_groups.values()
        )
        for split in ("train", "development")
    }
    records = tuple(
        _record_payload(record, source_groups=source_groups) for record in selected
    )
    body: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "selection_method": SELECTION_METHOD,
        "source_manifest_fingerprint": SOURCE_MANIFEST_FINGERPRINT,
        "source_counts": EXPECTED_SOURCE_COUNTS,
        "source_scenario_counts": source_scenario_counts,
        "source_variant_group_counts": source_variant_counts,
        "selection_counts": {
            "train": sum(record.lineage.split == "train" for record in selected),
            "development": sum(
                record.lineage.split == "development" for record in selected
            ),
        },
        "scenario_count": len(
            {record.lineage.derivation_parent_id for record in selected}
        ),
        "family_count": len({record.lineage.family_id for record in selected}),
        "records": list(records),
    }
    return {**body, "packet_fingerprint": _fingerprint(body)}


def packet_json() -> str:
    return (
        json.dumps(build_packet(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )


def check_packet_artifact(path: Path = PACKET_PATH) -> tuple[str, ...]:
    if not path.exists() or path.read_text(encoding="utf-8") != packet_json():
        return ("artifact_drift",)
    return ()


__all__ = [
    "PACKET_PATH",
    "build_packet",
    "check_packet_artifact",
    "packet_json",
    "proposed_fast_target",
]
