"""The committed run manifest of one cloud TRL + PEFT training run.

``ml/training/phase03c_cloud/train.py`` writes ``phase-03c-cloud-run-v1``
manifests, a different shape from the local MLX ``manifest.py`` one.
``check_cloud_run_manifest`` re-derives only what the committed bytes can
prove: every key ``train.py`` always writes is present, ``config_hash`` is
the same sha256 over the stored ``config``, the bundle fingerprint and
``train.jsonl`` hash match the committed cloud bundle, and the selected
checkpoint (violation-free) and its delta over the untuned baseline agree
with the stored eval summaries.  Adapter and
merged-weight hashes are not checked: the weights are not committed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

CLOUD_RUN_MANIFEST_SCHEMA_VERSION: Final = "phase-03c-cloud-run-v1"
ROOT: Final = Path(__file__).resolve().parents[5]
CLOUD_BUNDLE_MANIFEST_PATH: Final = (
    ROOT / "data/experiments/phase-03c/cloud-bundle/bundle-manifest.json"
)
# Every key of ``run_manifest`` in train.py; none is conditional on smoke.
# ``selected`` and ``selected_minus_untuned_act_agreement`` are ``None``
# together when no checkpoint had policy_violation == 0.
CLOUD_RUN_MANIFEST_KEYS: Final = frozenset(
    {
        "schema_version",
        "bundle",
        "base_model",
        "config",
        "config_hash",
        "config_path",
        "loss_masking",
        "warmup_arg",
        "trained_span_check",
        "token_stats",
        "rows_used",
        "dev_eval",
        "trainable_parameters",
        "total_parameters",
        "train_metrics",
        "log_history",
        "evals",
        "untuned_baseline",
        "selected",
        "selected_minus_untuned_act_agreement",
        "adapter_sha256",
        "merged_sha256",
        "packages",
        "gpu",
        "wall_time_s",
        "smoke",
    }
)


def cloud_config_hash(config: object) -> str:
    """The hash train.py records: sha256 of ``json.dumps(sort_keys=True)``."""

    return hashlib.sha256(
        json.dumps(config, sort_keys=True).encode("utf-8")
    ).hexdigest()


def check_cloud_run_manifest(
    path: Path, *, bundle_manifest_path: Path = CLOUD_BUNDLE_MANIFEST_PATH
) -> tuple[str, ...]:
    """Every invariant of a cloud manifest verifiable from committed bytes."""

    if not path.is_file():
        return (f"missing_manifest:{path}",)
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return (f"malformed_manifest:{path}",)
    problems: list[str] = []
    if document.get("schema_version") != CLOUD_RUN_MANIFEST_SCHEMA_VERSION:
        problems.append("schema_version_mismatch")
    problems.extend(
        f"missing_key:{key}"
        for key in sorted(CLOUD_RUN_MANIFEST_KEYS - document.keys())
    )
    if "config" in document and document.get("config_hash") != cloud_config_hash(
        document["config"]
    ):
        problems.append("config_hash_drift")
    bundle = document.get("bundle")
    if not isinstance(bundle, dict):
        bundle = {}
    committed_bundle = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
    if bundle.get("dataset_fingerprint") != committed_bundle["dataset_fingerprint"]:
        problems.append("bundle_fingerprint_mismatch")
    committed_train_sha256 = committed_bundle["files"]["train.jsonl"]["sha256"]
    if bundle.get("train_sha256") != committed_train_sha256:
        problems.append("bundle_train_sha256_mismatch")
    problems.extend(_selection_problems(document))
    return tuple(problems)


def _selection_problems(document: dict[str, object]) -> list[str]:
    evals = document.get("evals")
    untuned = document.get("untuned_baseline")
    selected = document.get("selected")
    delta = document.get("selected_minus_untuned_act_agreement")
    if not isinstance(evals, list) or not isinstance(untuned, dict):
        return ["evals_or_untuned_missing"]
    problems: list[str] = []
    step_zero = [
        record
        for record in evals
        if isinstance(record, dict) and record.get("step") == 0
    ]
    if step_zero != [untuned]:
        problems.append("untuned_baseline_not_step_zero_eval")
    if selected is None:
        if delta is not None:
            problems.append("selected_delta_without_selection")
        return problems
    if not isinstance(selected, dict) or selected not in evals:
        problems.append("selected_not_in_evals")
        return problems
    if selected.get("step", 0) <= 0:
        problems.append("selected_is_untuned_step")
    # train.py's scoring.select_checkpoint only considers violation-free steps.
    if selected.get("policy_violation") != 0:
        problems.append("selected_has_policy_violation")
    expected = selected["oracle_act_agreement"] - untuned["oracle_act_agreement"]
    if delta != expected:
        problems.append("selected_delta_drift")
    return problems


__all__ = [
    "CLOUD_BUNDLE_MANIFEST_PATH",
    "CLOUD_RUN_MANIFEST_KEYS",
    "CLOUD_RUN_MANIFEST_SCHEMA_VERSION",
    "check_cloud_run_manifest",
    "cloud_config_hash",
]
