#!/usr/bin/env python
"""M1 stack parity: local MLX vs the committed cloud held-out outputs.

Three modes:

``--run --backend distilled|untuned --model-path SNAPSHOT``
    Loads the gateway core (base attestation, adapter attestation, LoRA
    self-check) and generates the 240 held-out rows in the cloud report's
    order, rebuilt from the reserved seeds exactly as
    ``rescore_phase03c_heldout.build_index`` does.  Rows go to a git-ignored,
    resumable JSONL under ``local-parity/runs/``.  Needs MLX and the local
    model; set ``HF_HUB_OFFLINE=1``.
``--write``
    Combines both arms' JSONL with the cloud report into the committed
    ``parity-report.json`` (per-row raw outputs included, 03C precedent).
``--check``
    Recomputes every derived field of the committed report from its own
    observed fields (raw outputs, tokens, timings, identity, host) with the
    repository evaluator and requires the bytes to match.  No model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from proxyloop_evaluation.local_fast.identity import (  # noqa: E402
    BACKENDS,
    installed_mlx_versions,
)
from proxyloop_evaluation.local_fast.parity import (  # noqa: E402
    BAR_MIN_ACT_AGREEMENT,
    BAR_MIN_CLOUD_CONCORDANCE,
    CLOUD_ARMS,
    PARITY_HELD,
    PARITY_NOT_ESTABLISHED,
    PARITY_SCHEMA_VERSION,
    nearest_rank,
    parsed_act,
    verdict,
)
from proxyloop_evaluation.phase03c_prompt_set import render_prompt_view  # noqa: E402
from rescore_phase03c_heldout import (  # noqa: E402
    aggregate,
    build_index,
    oracle_act,
    score_row,
    wilson,
)

PROMPT_VERSION = "v6"
CLOUD_REPORT = (
    ROOT / "data/experiments/phase-03c/training/cloud-run-01/eval/heldout-report.json"
)
PARITY_DIR = ROOT / "data/experiments/phase-03c/local-parity"
RUNS_DIR = PARITY_DIR / "runs"
REPORT = PARITY_DIR / "parity-report.json"
ATTESTATION = ROOT / "ml/serving/phase-03c-cloud-run-01-mlx-attestation.json"
DEFAULT_ADAPTER = (
    ROOT / "data/experiments/phase-03c/training/cloud-run-01/train/mlx/adapters"
)
OBSERVED_ROW_KEYS = (
    "prompt_id",
    "raw_output",
    "status",
    "detail_code",
    "input_tokens",
    "output_tokens",
    "generation_ms",
    "wall_ms",
    "prompt_fingerprint",
)
OBSERVED_ARM_KEYS = ("identity", "host", "load_ms", "code_state")
CODE_STATE_KEYS = frozenset({"head", "dirty_paths", "note"})
CLAIM_BOUNDARY = (
    "M1 stack parity only (E2): the trained-format prompts of the 240 Phase 03C "
    "held-out rows, generated sequentially on one Apple-silicon machine with "
    "MLX and the unmerged LoRA adapter, compared with the committed cloud "
    "outputs (vLLM, merged bf16 checkpoint, A100). It is not the product input "
    "path (M2 is pending), and it measures no p95, capacity, concurrency, OOM or "
    "production latency. The distilled backend is a local opt-in candidate, "
    "never promoted; the four Phase 03C caveats and E1-E5 of decision 18 "
    "(harness/context/audit-remediation-decisions.md) apply to every number. "
    "Integrity limits: --check verifies that every derived field, the row set "
    "and order, and each arm's identity follow from the recorded fields; it "
    "cannot verify that the raw outputs came from the model (that needs the "
    "git-ignored adapter and a rerun), and report_fingerprint is computed by "
    "this script over the document, a consistency check, not a signature."
)
NOT_MEASURED = (
    "M2 input parity through the product rendering path (needs PR-9a)",
    "gate pass rate under PR-8's fast gate (needs PR-8a)",
    "Fast/Slow split reports for the local backends (needs PR-9a)",
    "p95, capacity, concurrency, OOM, production latency",
    "fresh-clone reproduction of the model outputs (the adapter is git-ignored)",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--backend", choices=BACKENDS)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--adapter-path", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--limit", type=int, default=None, help="smoke: first N rows")
    parser.add_argument(
        "--code-state",
        type=Path,
        default=None,
        help="--write: JSON {backend: code_state} for run files whose header "
        "predates automatic code-state capture",
    )
    return parser.parse_args(argv)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def current_code_state() -> dict[str, object]:
    """The commit and the uncommitted paths the run process imports from."""

    dirty = sorted(line[3:] for line in _git("status", "--porcelain").splitlines())
    return {
        "head": _git("rev-parse", "HEAD").strip(),
        "dirty_paths": dirty,
        "note": None,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sysctl(name: str) -> str | None:
    try:
        result = subprocess.run(
            ["sysctl", "-n", name], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def host_facts() -> dict[str, object]:
    memory = _sysctl("hw.memsize")
    return {
        "chip": _sysctl("machdep.cpu.brand_string"),
        "memory_bytes": int(memory) if memory else None,
        "os": f"macOS {platform.mac_ver()[0]}" if platform.mac_ver()[0] else None,
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "packages": installed_mlx_versions(),
    }


def _cloud_prompt_ids(cloud: dict[str, Any], backend: str) -> list[str]:
    return [
        str(row["prompt_id"]) for row in cloud["arms"][CLOUD_ARMS[backend]]["outputs"]
    ]


def run(args: argparse.Namespace) -> int:
    from proxyloop_evaluation.local_fast.gateway_core import LocalFastGatewayCore
    from proxyloop_evaluation.local_fast.mlx_adapter_conversion import (
        load_attestation,
    )

    if args.backend is None or args.model_path is None:
        raise SystemExit("--run needs --backend and --model-path")
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        raise SystemExit("set HF_HUB_OFFLINE=1: the parity run never downloads")
    cloud = json.loads(CLOUD_REPORT.read_text(encoding="utf-8"))
    prompt_ids = _cloud_prompt_ids(cloud, args.backend)[: args.limit]
    index = build_index(PROMPT_VERSION)

    distilled = args.backend == "distilled"
    started = time.monotonic()
    core = LocalFastGatewayCore.load(
        backend=args.backend,
        model_path=args.model_path,
        adapter_path=args.adapter_path if distilled else None,
        attestation=load_attestation(ATTESTATION) if distilled else None,
    )
    load_ms = round((time.monotonic() - started) * 1000)
    identity = core.identity.to_dict()
    print(
        f"loaded {args.backend} in {load_ms} ms; identity "
        f"{identity['identity_fingerprint']}",
        flush=True,
    )

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"{args.backend}.jsonl"
    done: set[str] = set()
    if path.exists():
        lines = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        if not lines or lines[0].get("identity") != identity:
            raise SystemExit(f"{path.name} was produced by a different identity")
        done = {str(line["prompt_id"]) for line in lines[1:]}
    else:
        header = {
            "kind": "header",
            "identity": identity,
            "host": host_facts(),
            "load_ms": load_ms,
            "code_state": current_code_state(),
        }
        path.write_text(json.dumps(header, sort_keys=True) + "\n", encoding="utf-8")

    with path.open("a", encoding="utf-8") as stream:
        for number, prompt_id in enumerate(prompt_ids, start=1):
            if prompt_id in done:
                continue
            scenario, position, _ = index[prompt_id]
            view = render_prompt_view(scenario, position)
            began = time.monotonic()
            result = core.decide(view, position.observation)
            wall_ms = round((time.monotonic() - began) * 1000)
            record = {
                "kind": "row",
                "prompt_id": prompt_id,
                "raw_output": result.raw_output,
                "status": result.status,
                "detail_code": result.detail_code,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "generation_ms": result.generation_ms,
                "wall_ms": wall_ms,
                "prompt_fingerprint": result.prompt_fingerprint,
            }
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            print(
                f"{number}/{len(prompt_ids)} {result.status} "
                f"act={parsed_act(result.raw_output)} {wall_ms} ms "
                f"out={result.output_tokens}",
                flush=True,
            )
    return 0


def _observed_from_runs(code_state_path: Path | None) -> dict[str, dict[str, Any]]:
    cloud = json.loads(CLOUD_REPORT.read_text(encoding="utf-8"))
    supplied: dict[str, Any] = (
        json.loads(code_state_path.read_text(encoding="utf-8"))
        if code_state_path is not None
        else {}
    )
    observed: dict[str, dict[str, Any]] = {}
    for backend in BACKENDS:
        path = RUNS_DIR / f"{backend}.jsonl"
        lines = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        header, rows = lines[0], {str(row["prompt_id"]): row for row in lines[1:]}
        order = _cloud_prompt_ids(cloud, backend)
        if set(rows) != set(order) or len(lines) - 1 != len(order):
            raise SystemExit(f"{path.name} has {len(lines) - 1}/{len(order)} rows")
        if "code_state" not in header:
            if backend not in supplied:
                raise SystemExit(f"{path.name} has no code_state; pass --code-state")
            header = {**header, "code_state": supplied[backend]}
        observed[backend] = {
            **{key: header[key] for key in OBSERVED_ARM_KEYS},
            "rows": [
                {key: rows[pid][key] for key in OBSERVED_ROW_KEYS} for pid in order
            ],
        }
    return observed


def validate_observed(observed: dict[str, dict[str, Any]]) -> None:
    """Refuse a row set, order, or identity that the run could not have produced.

    Every arm must hold exactly the cloud arm's prompt ids in the cloud order
    (no dropped, duplicated, or reordered rows), and its identity must equal
    the one ``GatewayIdentity`` computes for that backend, the committed
    adapter attestation, and the recorded MLX versions, fingerprint included.
    """

    from proxyloop_evaluation.local_fast.identity import GatewayIdentity

    cloud = json.loads(CLOUD_REPORT.read_text(encoding="utf-8"))
    attestation = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    if set(observed) != set(BACKENDS):
        raise SystemExit("the report needs both the distilled and untuned arms")
    for backend in BACKENDS:
        arm = observed[backend]
        prompt_ids = [str(row["prompt_id"]) for row in arm["rows"]]
        if prompt_ids != _cloud_prompt_ids(cloud, backend):
            raise SystemExit(
                f"{backend} rows differ from the cloud {CLOUD_ARMS[backend]} "
                "prompt ids (dropped, duplicated, or reordered rows)"
            )
        recorded = arm["identity"]
        expected = GatewayIdentity(
            backend=backend,
            adapter_fingerprint=(
                str(attestation["output"]["content_fingerprint"])
                if backend == "distilled"
                else None
            ),
            mlx_versions=dict(recorded.get("mlx_versions", {})),
        ).to_dict()
        if recorded != expected:
            raise SystemExit(f"{backend} identity differs from the served identity")
        if recorded["mlx_versions"] != arm["host"]["packages"]:
            raise SystemExit(f"{backend} identity and host disagree on MLX versions")
        state = arm["code_state"]
        if not isinstance(state, dict) or set(state) != CODE_STATE_KEYS:
            raise SystemExit(
                f"{backend} code_state must carry {sorted(CODE_STATE_KEYS)}"
            )


def _observed_from_report(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        backend: {
            **{key: arm[key] for key in OBSERVED_ARM_KEYS},
            "rows": [
                {key: row[key] for key in OBSERVED_ROW_KEYS} for row in arm["rows"]
            ],
        }
        for backend, arm in report["arms"].items()
    }


def _count(rows: list[dict[str, Any]], key: str) -> dict[str, float | int]:
    count = sum(1 for row in rows if row[key])
    return {"count": count, **wilson(count, len(rows))}


def build_report(observed: dict[str, dict[str, Any]]) -> dict[str, object]:
    """Derive every non-observed field.  Callers validate first
    (``validate_observed``); tests replay row subsets through this directly."""

    cloud = json.loads(CLOUD_REPORT.read_text(encoding="utf-8"))
    attestation = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    index = build_index(PROMPT_VERSION)
    if set(observed) != set(BACKENDS):
        raise SystemExit("the report needs both the distilled and untuned arms")
    arms: dict[str, object] = {}
    for backend in BACKENDS:
        arm = observed[backend]
        if arm["identity"]["backend"] != backend:
            raise SystemExit(f"{backend} arm carries another backend's identity")
        expected_adapter = (
            attestation["output"]["content_fingerprint"]
            if backend == "distilled"
            else None
        )
        if arm["identity"]["adapter_fingerprint"] != expected_adapter:
            raise SystemExit(f"{backend} arm adapter differs from the attestation")
        cloud_arm_id = CLOUD_ARMS[backend]
        cloud_rows = {
            str(row["prompt_id"]): row for row in cloud["arms"][cloud_arm_id]["outputs"]
        }
        rows: list[dict[str, Any]] = []
        for observed_row in arm["rows"]:
            prompt_id = str(observed_row["prompt_id"])
            scenario, position, rendered = index[prompt_id]
            cloud_row = cloud_rows[prompt_id]
            raw = observed_row["raw_output"]
            local_act, cloud_act = parsed_act(raw), parsed_act(cloud_row["raw_output"])
            metrics = score_row(scenario, position, rendered, raw, PROMPT_VERSION)
            rows.append(
                {
                    **observed_row,
                    "family_id": str(rendered["family_id"]),
                    "split": str(rendered["split"]),
                    "oracle_act": oracle_act(rendered),
                    "local_act": local_act,
                    "cloud_act": cloud_act,
                    "act_concordant": local_act == cloud_act,
                    "cloud_act_agreement": bool(
                        cloud_row["metrics"]["dialogue_act_accuracy"]
                    ),
                    "raw_exact_match_cloud": raw == cloud_row["raw_output"],
                    "input_tokens_equal_cloud": (
                        observed_row["input_tokens"] == cloud_row["input_tokens"]
                    ),
                    "prompt_fingerprint_matches": (
                        observed_row["prompt_fingerprint"]
                        == rendered["prompt_fingerprint"]
                    ),
                    "metrics": metrics,
                }
            )
        scored = [{"metrics": row["metrics"]} for row in rows]
        by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_family[row["family_id"]].append(row)
        generation = [int(row["generation_ms"]) for row in rows]
        output_tokens = [int(row["output_tokens"]) for row in rows]
        arms[backend] = {
            **{key: arm[key] for key in OBSERVED_ARM_KEYS},
            "cloud_arm": cloud_arm_id,
            "cloud_label": cloud["arms"][cloud_arm_id]["label"],
            "summary": {
                "rows": len(rows),
                "status_counts": dict(
                    sorted(Counter(r["status"] for r in rows).items())
                ),
                "local_act_agreement": aggregate(scored)["dialogue_act_accuracy"],
                "cloud_act_agreement": _count(rows, "cloud_act_agreement"),
                "cloud_act_concordance": _count(rows, "act_concordant"),
                "both_unparseable_rows": sum(
                    1
                    for row in rows
                    if row["local_act"] is None and row["cloud_act"] is None
                ),
                "raw_exact_match_cloud": _count(rows, "raw_exact_match_cloud"),
                "input_tokens_equal_cloud": _count(rows, "input_tokens_equal_cloud"),
                "prompt_fingerprint_matches": _count(
                    rows, "prompt_fingerprint_matches"
                ),
                "evaluator": aggregate(scored),
                "per_family_local_act_agreement": {
                    family: sum(
                        1 for row in items if row["metrics"]["dialogue_act_accuracy"]
                    )
                    for family, items in sorted(by_family.items())
                },
                "local_acts": dict(
                    sorted(Counter(str(row["local_act"]) for row in rows).items())
                ),
                "generation_ms": {
                    "p50": nearest_rank(generation, 50),
                    "max": max(generation),
                    "total": sum(generation),
                },
                "output_tokens": {
                    "p50": nearest_rank(output_tokens, 50),
                    "p95": nearest_rank(output_tokens, 95),
                    "total": sum(output_tokens),
                },
            },
            "rows": rows,
        }
    distilled = cast(dict[str, Any], arms["distilled"])["summary"]
    agreement = float(distilled["local_act_agreement"]["rate"])
    concordance = float(distilled["cloud_act_concordance"]["rate"])
    document: dict[str, object] = {
        "schema_version": PARITY_SCHEMA_VERSION,
        "result_role": "local_measurement",
        "measurement": "M1 stack parity (E2)",
        "labels": {
            "distilled": "local opt-in candidate",
            "untuned": "untuned local baseline",
        },
        "pre_registration": {
            "source": "harness/context/pr9-local-distilled-fast-design.md §3.1, Q2",
            "rule": (
                "stack parity held iff the distilled arm's local act agreement "
                f">= {BAR_MIN_ACT_AGREEMENT} and its per-row act concordance with "
                f"cloud A3 >= {BAR_MIN_CLOUD_CONCORDANCE} (point rates); the "
                "untuned arm has no bar"
            ),
            "on_failure": (
                f"the backend is labelled '{PARITY_NOT_ESTABLISHED}'; it is not removed"
            ),
            "concordance_definition": (
                "local and cloud outputs name the same dialogue_act after tolerant "
                "JSON extraction; two unparseable outputs count as concordant"
            ),
            "concordance_definition_timing": (
                "the bar was pre-registered; the rule for two unparseable outputs "
                "was written after the run; each arm's both_unparseable_rows shows "
                "how many rows it decides"
            ),
        },
        "source_cloud_report": {
            "path": str(CLOUD_REPORT.relative_to(ROOT)),
            "sha256": _sha256(CLOUD_REPORT),
        },
        "attestation": {
            "path": str(ATTESTATION.relative_to(ROOT)),
            "content_fingerprint": attestation["output"]["content_fingerprint"],
        },
        "prompt_version": PROMPT_VERSION,
        "decoding": {
            "greedy": True,
            "temperature": 0.0,
            "seed": 0,
            "max_tokens": 512,
            "enable_thinking": False,
        },
        "clustering_note": (
            "Every held-out family's rows share one oracle dialogue_act, so the 240 "
            "rows carry 6 decision rules and the row-level Wilson intervals are "
            "optimistic."
        ),
        "verdict": {
            "distilled_local_act_agreement": agreement,
            "distilled_cloud_act_concordance": concordance,
            "result": verdict(agreement, concordance),
            "held_value": PARITY_HELD,
        },
        "claim_boundary": CLAIM_BOUNDARY,
        "not_measured": list(NOT_MEASURED),
        "arms": arms,
    }
    document["report_fingerprint"] = hashlib.sha256(
        json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return document


def _render(document: dict[str, object]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.run:
        return run(args)
    if args.write:
        observed = _observed_from_runs(args.code_state)
        validate_observed(observed)
        rendered = _render(build_report(observed))
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(rendered, encoding="utf-8")
        print(f"wrote {REPORT.relative_to(ROOT)}")
    else:
        committed = REPORT.read_text(encoding="utf-8")
        observed = _observed_from_report(json.loads(committed))
        validate_observed(observed)
        rendered = _render(build_report(observed))
        if committed != rendered:
            raise SystemExit(f"{REPORT.relative_to(ROOT)} is stale or was edited")
        print(f"checked {REPORT.relative_to(ROOT)}")
    result = json.loads(rendered)["verdict"]
    print(
        f"M1: distilled act agreement {result['distilled_local_act_agreement']:.3f}, "
        f"cloud concordance {result['distilled_cloud_act_concordance']:.3f} -> "
        f"{result['result']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
