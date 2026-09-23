#!/usr/bin/env python
"""Re-score a Phase 03C cloud report with the repository evaluator.

``ml/training/phase03c_cloud/scoring.py`` is a repository-free copy of the
row evaluator, parity-tested but not canonical.  The contract requires every
raw output that came back from the cloud to be scored again here, with
``run_phase03c_row`` and a ``Phase03CQwenAdapter`` whose generator replays
the stored text, before any Stage 3 decision is recorded.

The held-out rows are not in the committed prompt set (they use the reserved
seeds), so the scenarios are rebuilt deterministically from the same
generator the bundle used and matched by ``prompt_id``.

    RUN=data/experiments/phase-03c/training/cloud-run-01/eval
    python -m scripts.rescore_phase03c_heldout \
        --report $RUN/heldout-report.json --out $RUN/heldout-rescored.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_phase03c_cloud_bundle import (  # noqa: E402
    DEFAULT_HELDOUT_SEEDS,
    heldout_families,
    render_eval_row,
)
from proxyloop_data_pipeline import NormalizedTrajectory  # noqa: E402
from proxyloop_evaluation.fast_output import FastModelOutput  # noqa: E402
from proxyloop_evaluation.phase03b_experiment import Phase03BExample  # noqa: E402
from proxyloop_evaluation.phase03c_experiment import (  # noqa: E402
    Phase03CQwenAdapter,
    run_phase03c_row,
)
from proxyloop_evaluation.phase03c_prompt_set import (  # noqa: E402
    PROMPT_SET_MANIFEST_PATH,
    load_prompt_set_manifest,
    render_prompt_view,
    resolve_row,
)
from proxyloop_evaluation.phase03c_scenarios import harvest_positions  # noqa: E402
from proxyloop_evaluation.qwen_spec import QWEN3_8B_BF16_SPEC  # noqa: E402
from proxyloop_provider_simulator.scenarios import (  # noqa: E402
    SCENARIO_FAMILIES,
    build_parameterised_scenarios,
)

SCHEMA_VERSION = "phase-03c-heldout-rescored-v1"
# Cloud-side only, or not reproducible from a replayed string.
UNCOMPARED = frozenset({"latency_ms", "input_tokens", "output_tokens"})
# Repository field names. The cloud report carries both spellings (it copies
# four repository fields to its own names, scoring.py:_RATE_SOURCE), so the
# alias is folded in and the two copies are asserted equal rather than
# trusted; a divergence there would mean the cloud report contradicts itself.
RATE_FIELDS = (
    "dialogue_act_accuracy",
    "schema_valid",
    "policy_violation",
    "false_completion",
    "unsupported_response_violation",
    "end_to_end_valid",
)
CLOUD_ALIAS = {
    "oracle_act_agreement": "dialogue_act_accuracy",
    "reasoner_request_agreement": "reasoner_request_quality",
    "strict_json": "json_valid_strict",
    "tolerant_json": "json_valid_tolerant",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prompt-version", default="v6")
    parser.add_argument(
        "--check",
        action="store_true",
        help="recompute and compare with --out instead of writing it",
    )
    return parser.parse_args(argv)


def build_index(prompt_version: str) -> dict[str, tuple[Any, Any, dict[str, object]]]:
    """``prompt_id`` -> (scenario, position, rendered row), as the bundle built it."""

    split_by_family = dict(heldout_families())
    families = tuple(
        family for family in SCENARIO_FAMILIES if family.family_id in split_by_family
    )
    index: dict[str, tuple[Any, Any, dict[str, object]]] = {}
    for scenario in build_parameterised_scenarios(
        seeds=DEFAULT_HELDOUT_SEEDS, families=families
    ):
        for position in harvest_positions(scenario):
            row = render_eval_row(
                scenario,
                position,
                split=split_by_family[scenario.family_id],
                prompt_version=cast(Any, prompt_version),
            )
            index[str(row["prompt_id"])] = (scenario, position, row)

    # The dev round scores the committed prompt set instead of the reserved
    # held-out seeds, so both sources go into one index.
    for prompt_row in load_prompt_set_manifest(ROOT / PROMPT_SET_MANIFEST_PATH):
        scenario, position = resolve_row(prompt_row)
        row = render_eval_row(
            scenario,
            position,
            split="development",
            prompt_version=cast(Any, prompt_version),
        )
        index.setdefault(str(row["prompt_id"]), (scenario, position, row))
    return index


def score_row(
    scenario: Any, position: Any, row: dict[str, object], raw: str | None, version: str
) -> dict[str, object]:
    example = Phase03BExample(
        # Inert for scoring: run_phase03c_row never reads it, and the dataclass
        # only admits train/development while held-out rows are also "test".
        # The row's real split is carried in this script's own output.
        split="development",
        scenario_id=scenario.scenario_id,
        family_id=scenario.family_id,
        source_record=cast(NormalizedTrajectory, None),
        public_observation=position.observation,
        view=render_prompt_view(scenario, position),
        # the strict model rejects a plain dict; the canonical target is JSON
        target=FastModelOutput.model_validate_json(json.dumps(row["oracle_target"])),
    )

    def generator(_: str) -> str:
        if raw is None:
            raise RuntimeError("no raw output was returned for this row")
        return raw

    adapter = Phase03CQwenAdapter(
        generator=generator,
        model_spec=QWEN3_8B_BF16_SPEC,
        prompt_version=cast(Any, version),
    )
    executed = run_phase03c_row(example, adapter)
    return {
        key: value
        for key, value in asdict(executed.metrics).items()
        if key not in UNCOMPARED
    }


def oracle_act(row: dict[str, object]) -> str:
    """The scripted oracle's dialogue act for a rendered evaluation row."""

    return str(cast(dict[str, object], row["oracle_target"])["dialogue_act"])


def wilson(count: int, total: int, z: float = 1.959963985) -> dict[str, float]:
    if total == 0:
        return {"rate": 0.0, "low": 0.0, "high": 0.0}
    p = count / total
    den = 1 + z * z / total
    centre = p + z * z / (2 * total)
    adj = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return {
        "rate": p,
        "low": max(0.0, (centre - adj) / den),
        "high": min(1.0, (centre + adj) / den),
    }


def aggregate(scored: list[dict[str, Any]]) -> dict[str, object]:
    total = len(scored)
    out: dict[str, object] = {"rows": total}
    for field in RATE_FIELDS:
        count = sum(1 for item in scored if bool(item["metrics"][field]))
        out[field] = {"count": count, **wilson(count, total)}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    index = build_index(args.prompt_version)

    arms: dict[str, object] = {}
    disagreements: list[dict[str, object]] = []
    for arm_id, arm in sorted(report["arms"].items()):
        scored: list[dict[str, Any]] = []
        for output in arm["outputs"]:
            prompt_id = str(output["prompt_id"])
            if prompt_id not in index:
                raise SystemExit(f"cannot rebuild scenario for {prompt_id}")
            scenario, position, row = index[prompt_id]
            metrics = score_row(
                scenario, position, row, output.get("raw_output"), args.prompt_version
            )
            raw_metrics = output["metrics"]
            for alias, repo_name in CLOUD_ALIAS.items():
                both = alias in raw_metrics and repo_name in raw_metrics
                if both and raw_metrics[alias] != raw_metrics[repo_name]:
                    raise SystemExit(
                        f"{prompt_id}: cloud {alias} disagrees with {repo_name}"
                    )
            cloud = {
                CLOUD_ALIAS.get(key, key): value
                for key, value in raw_metrics.items()
                if key not in UNCOMPARED
            }
            differing = {
                key: {"repository": metrics[key], "cloud": cloud.get(key)}
                for key in metrics
                if key in cloud and metrics[key] != cloud[key]
            }
            if differing:
                disagreements.append(
                    {"arm": arm_id, "prompt_id": prompt_id, "fields": differing}
                )
            scored.append(
                {
                    "prompt_id": prompt_id,
                    "family_id": str(row["family_id"]),
                    "split": str(row["split"]),
                    "metrics": metrics,
                }
            )

        by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in scored:
            by_family[str(item["family_id"])].append(item)
            by_split[str(item["split"])].append(item)
        arms[arm_id] = {
            "label": arm.get("label"),
            "aggregate": aggregate(scored),
            "per_family": {k: aggregate(v) for k, v in sorted(by_family.items())},
            "per_split": {k: aggregate(v) for k, v in sorted(by_split.items())},
            "oracle_acts": dict(
                Counter(oracle_act(index[str(item["prompt_id"])][2]) for item in scored)
            ),
        }

    first_arm = cast(dict[str, Any], next(iter(arms.values())))
    effective_n = len(first_arm["per_family"])
    # The clustering note below is a claim about the data; check it.
    acts_by_family: dict[str, set[str]] = defaultdict(set)
    for _, _, row in index.values():
        acts_by_family[str(row["family_id"])].add(oracle_act(row))
    scored_families = set(first_arm["per_family"])
    multi = {
        family: sorted(acts)
        for family, acts in acts_by_family.items()
        if family in scored_families and len(acts) > 1
    }
    if multi:
        raise SystemExit(f"families with more than one oracle act: {multi}")
    document = {
        "schema_version": SCHEMA_VERSION,
        "result_role": "repository_canonical",
        "source_report": str(args.report),
        "source_schema_version": report.get("schema_version"),
        "prompt_version": args.prompt_version,
        "evaluator": "proxyloop_evaluation.run_phase03c_row via Phase03CQwenAdapter",
        "family_oracle_acts_verified": True,
        "clustering_note": (
            "Every family's rows share one oracle dialogue_act, so the rows are "
            f"not independent: {effective_n} distinct decision rules carry the "
            "result and the row-level Wilson intervals are optimistic."
        ),
        "cloud_disagreements": disagreements,
        "cloud_disagreement_count": len(disagreements),
        "arms": arms,
    }
    rendered = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.out.is_file():
            raise SystemExit(f"missing {args.out}; run without --check first")
        committed = args.out.read_text(encoding="utf-8")
        if committed != rendered:
            raise SystemExit(f"{args.out} is stale; rerun without --check")
        print(f"checked {args.out}")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.out}")
    print(f"cloud disagreements: {len(disagreements)}")
    for arm_id, arm in sorted(arms.items()):
        agg = cast(dict[str, Any], arm)["aggregate"]
        print(
            f"  {arm_id}: act={agg['dialogue_act_accuracy']['rate']:.3f} "
            f"schema={agg['schema_valid']['rate']:.3f} "
            f"pv={agg['policy_violation']['count']} "
            f"fc={agg['false_completion']['count']}"
        )
    return 0 if not disagreements else 1


if __name__ == "__main__":
    raise SystemExit(main())
