#!/usr/bin/env python
"""Phase 03C Stage 3: arms A1-A4 over the frozen held-out set with vLLM.

A1  untuned Qwen/Qwen3-8B bf16, plain decoding
A2  A1 + vLLM structured outputs (guided JSON from ``schema.json``)
A3  selected adapter merged into bf16 (``<run-dir>/merged``), plain
A4  A3 + guided JSON

Greedy, ``max_tokens`` 512, ``enable_thinking=False``.  Every raw output is
stored so the repository evaluator can re-score the report offline.  A0 (the
oracle ceiling) is computed offline from the bundle; A5/A6 (hosted teachers
as Fast) are out of scope for this package and are never called here.
"""

import argparse
import gc
import hashlib
import json
import platform
import sys
import time
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scoring  # noqa: E402

REPORT_SCHEMA_VERSION = "phase-03c-heldout-v1"
ARMS = {
    "A1": {"label": "untuned Qwen3-8B bf16, plain", "model": "base", "guided": False},
    "A2": {
        "label": "untuned Qwen3-8B bf16, guided JSON",
        "model": "base",
        "guided": True,
    },
    "A3": {
        "label": "distilled (merged LoRA), plain",
        "model": "merged",
        "guided": False,
    },
    "A4": {
        "label": "distilled (merged LoRA), guided JSON",
        "model": "merged",
        "guided": True,
    },
}
FIELDS_NOT_COMPUTED_ON_CLOUD = [
    "stale_pin_violation (always False in the adapter path; reported False)",
    "verifier end-to-end replay through runner_v2 (local only)",
    "A0 oracle ceiling (offline from the bundle's oracle_target)",
    "A5/A6 hosted arms (out of scope)",
]


def log(message: str) -> None:
    print(f"[eval] {time.strftime('%H:%M:%S')} {message}", flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def package_versions() -> dict:
    versions = {}
    for name in ("vllm", "torch", "transformers", "pydantic", "xgrammar"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    versions["python"] = platform.python_version()
    return versions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="train.py output dir (needs merged/ and run-manifest.json) for A3/A4",
    )
    parser.add_argument("--arms", default="A1,A2,A3,A4")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="score dev-eval.jsonl instead of heldout.jsonl",
    )
    parser.add_argument(
        "--previous-report",
        type=Path,
        default=None,
        help="merge arms from an earlier report (e.g. A1/A2 run before training)",
    )
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--latency-rows", type=int, default=24)
    parser.add_argument("--max-model-len", type=int, default=4096)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.85)
    parser.add_argument("--limit", type=int, default=None, help="debug: first N rows")
    return parser.parse_args()


def guided_kwargs(schema: dict) -> tuple[dict, str]:
    """``SamplingParams`` kwargs for guided JSON across vLLM API generations."""

    try:
        from vllm.sampling_params import StructuredOutputsParams

        return {"structured_outputs": StructuredOutputsParams(json=schema)}, (
            "structured_outputs"
        )
    except ImportError:
        from vllm.sampling_params import GuidedDecodingParams

        return {"guided_decoding": GuidedDecodingParams(json=schema)}, "guided_decoding"


def request_latency_ms(output) -> float | None:
    metrics = getattr(output, "metrics", None)
    arrival = getattr(metrics, "arrival_time", None)
    finished = getattr(metrics, "finished_time", None)
    if arrival is None or finished is None:
        return None
    return (finished - arrival) * 1000


def run_arm(
    llm,
    rows: list[dict],
    prompts: list[str],
    *,
    guided: bool,
    schema: dict,
    max_tokens: int,
    latency_rows: int,
) -> dict:
    from vllm import SamplingParams

    extra, api = guided_kwargs(schema) if guided else ({}, None)
    params = SamplingParams(temperature=0.0, max_tokens=max_tokens, seed=0, **extra)
    started = time.perf_counter()
    outputs = llm.generate(prompts, params, use_tqdm=False)
    batched_wall = time.perf_counter() - started
    generated = []
    for output in outputs:
        completion = output.outputs[0]
        generated.append(
            {
                "raw_output": completion.text,
                "finish_reason": completion.finish_reason,
                "input_tokens": len(output.prompt_token_ids or []),
                "output_tokens": len(completion.token_ids or []),
                "latency_ms": request_latency_ms(output),
            }
        )
    scored = [
        scoring.score_row(row, item["raw_output"])
        for row, item in zip(rows, generated, strict=True)
    ]
    aggregate = scoring.aggregate(scored)
    single_stream = []
    for prompt in prompts[:latency_rows]:
        t0 = time.perf_counter()
        llm.generate([prompt], params, use_tqdm=False)
        single_stream.append((time.perf_counter() - t0) * 1000)
    request_latencies = [
        g["latency_ms"] for g in generated if g["latency_ms"] is not None
    ]
    return {
        "guided_json": guided,
        "structured_outputs_api": api,
        "rows": len(rows),
        "aggregate": aggregate,
        "per_family": scoring.per_family(scored, [row["family_id"] for row in rows]),
        "per_split": scoring.per_family(scored, [row["split"] for row in rows]),
        "latency_ms": {
            "single_stream_sample_rows": len(single_stream),
            "single_stream_p50": scoring.percentile(single_stream, 0.5),
            "single_stream_p95": scoring.percentile(single_stream, 0.95),
            "request_metrics_rows": len(request_latencies),
            "request_p50": scoring.percentile(request_latencies, 0.5),
            "request_p95": scoring.percentile(request_latencies, 0.95),
            "batched_wall_s": round(batched_wall, 2),
            "batched_rows_per_s": round(len(rows) / batched_wall, 2)
            if batched_wall
            else None,
        },
        "tokens": {
            "input_total": sum(g["input_tokens"] for g in generated),
            "output_total": sum(g["output_tokens"] for g in generated),
            "output_p50": scoring.percentile(
                [g["output_tokens"] for g in generated], 0.5
            ),
            "output_p95": scoring.percentile(
                [g["output_tokens"] for g in generated], 0.95
            ),
            "finish_reason_counts": _counts(g["finish_reason"] for g in generated),
        },
        "outputs": [
            {
                "prompt_id": row["prompt_id"],
                "family_id": row["family_id"],
                "split": row["split"],
                **item,
                "metrics": metrics,
            }
            for row, item, metrics in zip(rows, generated, scored, strict=True)
        ],
    }


def _counts(values) -> dict:
    counts: dict = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def load_llm(
    model: str, revision, *, max_model_len: int, gpu_memory_utilization: float
):
    from vllm import LLM

    kwargs = dict(
        model=model,
        dtype="bfloat16",
        seed=0,
        max_model_len=max_model_len,
        gpu_memory_utilization=gpu_memory_utilization,
    )
    if revision is not None:
        kwargs["revision"] = revision
        kwargs["tokenizer_revision"] = revision
    return LLM(**kwargs)


def release_gpu() -> None:
    """Free the engine after the caller dropped its last reference."""

    import torch

    gc.collect()
    torch.cuda.empty_cache()


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    bundle = args.bundle_dir
    manifest = json.loads((bundle / "bundle-manifest.json").read_text(encoding="utf-8"))
    schema = json.loads((bundle / "schema.json").read_text(encoding="utf-8"))
    schema_ok = scoring.schema_matches(schema)
    rows_file = bundle / ("dev-eval.jsonl" if args.dev else "heldout.jsonl")
    rows = read_jsonl(rows_file)
    if args.limit:
        rows = rows[: args.limit]
    requested = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
    unknown = [arm for arm in requested if arm not in ARMS]
    if unknown:
        raise SystemExit(f"unknown arms: {unknown}")
    base = manifest["base_model"]["model"]
    revision = manifest["base_model"]["revision"]
    merged_dir = args.run_dir / "merged" if args.run_dir is not None else None
    run_manifest = None
    if any(ARMS[arm]["model"] == "merged" for arm in requested):
        if merged_dir is None or not (merged_dir / "config.json").is_file():
            raise SystemExit("A3/A4 need --run-dir with merged/ from train.py --merge")
        run_manifest = json.loads(
            (args.run_dir / "run-manifest.json").read_text(encoding="utf-8")
        )
        if (
            run_manifest["bundle"]["dataset_fingerprint"]
            != manifest["dataset_fingerprint"]
        ):
            raise SystemExit("run-manifest dataset fingerprint differs from the bundle")

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(base, revision=revision)
    prompts = [
        tokenizer.apply_chat_template(
            row["messages"],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        for row in rows
    ]
    import torch

    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    log(
        f"gpu={gpu} rows={len(rows)} file={rows_file.name} arms={requested} "
        f"schema_matches={schema_ok}"
    )

    arms: dict = {}
    if args.previous_report is not None:
        previous = json.loads(args.previous_report.read_text(encoding="utf-8"))
        if previous.get("dataset", {}).get("sha256") != sha256_file(rows_file):
            raise SystemExit("--previous-report was produced on a different row file")
        arms.update(previous.get("arms", {}))
        log(f"merged arms {sorted(previous['arms'])} from {args.previous_report}")

    for model_kind, model_path, model_revision in (
        ("base", base, revision),
        ("merged", str(merged_dir) if merged_dir else None, None),
    ):
        arm_ids = [arm for arm in requested if ARMS[arm]["model"] == model_kind]
        if not arm_ids:
            continue
        log(f"loading {model_kind}: {model_path}")
        llm = load_llm(
            model_path,
            model_revision,
            max_model_len=args.max_model_len,
            gpu_memory_utilization=args.gpu_memory_utilization,
        )
        for arm in arm_ids:
            log(f"running {arm}: {ARMS[arm]['label']}")
            t0 = time.perf_counter()
            result = run_arm(
                llm,
                rows,
                prompts,
                guided=bool(ARMS[arm]["guided"]),
                schema=schema,
                max_tokens=args.max_tokens,
                latency_rows=args.latency_rows,
            )
            result.update(
                {
                    "label": ARMS[arm]["label"],
                    "model": model_path,
                    "model_revision": model_revision,
                    "wall_time_s": round(time.perf_counter() - t0, 1),
                }
            )
            arms[arm] = result
            metrics = result["aggregate"]["metrics"]
            log(
                f"{arm}: act_agreement={metrics['oracle_act_agreement']['rate']:.3f} "
                f"schema_valid={metrics['schema_valid']['rate']:.3f} "
                f"policy_violation={metrics['policy_violation']['count']} "
                f"false_completion={metrics['false_completion']['count']} "
                f"({result['wall_time_s']}s)"
            )
        del llm
        release_gpu()

    aggregates = {arm: result["aggregate"] for arm, result in arms.items()}
    decision = scoring.decide(aggregates)
    comparisons = {}
    if "A1" in aggregates:
        for arm in ("A2", "A3", "A4"):
            if arm in aggregates:
                comparisons[f"{arm}_minus_A1_act_agreement"] = (
                    scoring.newcombe_difference(
                        aggregates[arm]["metrics"]["oracle_act_agreement"]["count"],
                        aggregates[arm]["rows"],
                        aggregates["A1"]["metrics"]["oracle_act_agreement"]["count"],
                        aggregates["A1"]["rows"],
                    )
                )
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "result_role": "cloud_candidate",
        "note": (
            "Scored on the cloud with scoring.py; the repository evaluator "
            "re-scores every raw_output offline before the report is canonical."
        ),
        "dataset": {
            "file": rows_file.name,
            "rows": len(rows),
            "sha256": sha256_file(rows_file),
            "bundle_dataset_fingerprint": manifest["dataset_fingerprint"],
            "prompt_version": manifest["prompt_version"],
            "compiler_version": manifest["compiler_version"],
            "split_counts": _counts(row["split"] for row in rows),
        },
        "base_model": manifest["base_model"],
        "distilled": (
            {
                "run_dir": str(args.run_dir),
                "selected_step": run_manifest["selected"],
                "adapter_sha256": run_manifest["adapter_sha256"],
                "merged_sha256": run_manifest["merged_sha256"],
                "config_hash": run_manifest["config_hash"],
            }
            if run_manifest is not None
            else None
        ),
        "decoding": {
            "greedy": True,
            "temperature": 0.0,
            "max_tokens": args.max_tokens,
            "enable_thinking": False,
            "seed": 0,
            "max_model_len": args.max_model_len,
        },
        "scorer": {
            "schema_matches_bundle": schema_ok,
            "fields_not_computed_on_cloud": FIELDS_NOT_COMPUTED_ON_CLOUD,
            "ci_method": "Wilson 95% per arm; Newcombe hybrid score for differences",
        },
        "runtime": {"gpu": gpu, "packages": package_versions()},
        "arms": arms,
        "comparisons": comparisons,
        "decision": decision,
        "wall_time_s": round(time.perf_counter() - started, 1),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    name = "dev-report.json" if args.dev else "heldout-report.json"
    (args.out_dir / name).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    log(f"decision={decision.get('decision')} ({decision.get('reason')})")
    log(f"wrote {args.out_dir / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
