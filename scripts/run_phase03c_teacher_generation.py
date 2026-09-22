"""Run, estimate, or check the Phase 03C Stage 1c full teacher generation.

Samples every train row of the prompt set (no development rows) for one
relay model at ``--k`` samples per prompt under ``--usd-ceiling``, with
``--concurrency`` prompts in flight, then curates the samples and writes the
model-prefixed manifest / quarantine / quality report plus
``phase-03c-teacher-generation-report.json``.  ``--dry-run`` prints the
worst-case USD without constructing a client.  ``--check`` recomputes a
committed generation report from the raw JSONL when present (raw samples of
the full run are git-ignored, so the committed check may only validate the
stored report's derived fields) with the report's stored ``prompt_version``.

The run stops early on a budget stop or the teacher's circuit breaker (a
401/403 or five consecutive failed calls); the report records
``stop_reason``, ``prompts_complete``, and ``run_complete`` so a partial run
is never mistaken for a full one.  Failed calls are charged at the pre-call
worst case, so after an outage the ledger overstates spend.  Ledger reset
procedure: run ``--reset-failed-charges`` (same ``--out-dir``, ``--model``,
``--usd-ceiling``) to rebuild ``phase-03c-cost-ledger.json`` from the raw
samples JSONL, keeping each succeeded call's recorded estimate and charging
failed calls at zero; it prints the totals before and after and writes
nothing else.  Then rerun without flags: the resumed run tops every prompt
up to ``--k`` successes and rewrites the curation artifacts and report.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from proxyloop_data_pipeline.teacher_pipeline import (
    GENERATION_REPORT_FILENAME,
    GENERATION_REPORT_SCHEMA_VERSION,
    LEDGER_FILENAME,
    compute_training_ready,
    curate_candidates,
    generation_report,
    load_ledger,
    manifest_path,
    quality_report_path,
    quarantine_path,
    report_prompt_version,
    reset_failed_charges,
    rows_for_prompt_version,
    sample_teacher,
    samples_path,
    write_curation_artifacts,
)
from proxyloop_evaluation.phase03c_experiment import (
    PHASE03C_COMPILER_VERSIONS,
    PromptVersion,
)
from proxyloop_evaluation.phase03c_prompt_set import (
    PROMPT_SET_MANIFEST_PATH,
    STAGE1B_PROMPT_VERSION,
    PromptSetRow,
    load_prompt_set_manifest,
    prompt_set_compiler_version,
)
from proxyloop_evaluation.phase03c_teacher_filters import build_candidate_context
from proxyloop_evaluation.relay_teacher import RelayTeacherAdapter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = Path("data/experiments/phase-03c/teacher-full")
DEFAULT_MODEL = "claude-sonnet-5"
RATE_KEYS = (
    "calls",
    "samples",
    "prompts",
    "f1_rate",
    "f2_act_needed_rate",
    "f2_rate",
    "f1_f4_rate",
    "f2_given_f1_rate",
    "per_family",
)
CURATION_KEYS = (
    "accepted_count",
    "accepted_prompts",
    "accepted_per_family",
    "accepted_families_coverage",
    "quarantine_per_filter",
    "training_ready",
)
COMPLETENESS_KEYS = (
    "prompts_sampled",
    "prompts_complete",
    "run_complete",
    "budget_stopped",
    "stop_reason",
)


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _display(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _prompt_version(args: argparse.Namespace) -> PromptVersion:
    return cast(PromptVersion, args.prompt_version)


def _train_rows(
    args: argparse.Namespace, *, prompt_version: PromptVersion
) -> tuple[PromptSetRow, ...]:
    manifest = ROOT / args.manifest
    rows = tuple(
        row for row in load_prompt_set_manifest(manifest) if row.split == "train"
    )
    return rows_for_prompt_version(
        rows,
        prompt_version=prompt_version,
        manifest_compiler_version=prompt_set_compiler_version(manifest),
    )


def dry_run(args: argparse.Namespace) -> int:
    rows = _train_rows(args, prompt_version=_prompt_version(args))
    adapter = RelayTeacherAdapter(
        model=args.model,
        usd_ceiling=args.usd_ceiling,
        prompt_version=_prompt_version(args),
    )
    worst = (
        sum(
            adapter.worst_case_call_usd(build_candidate_context(row).view)
            for row in rows
        )
        * args.k
    )
    print(
        f"train prompts: {len(rows)} (k={args.k}, prompt {args.prompt_version}, "
        f"concurrency {args.concurrency})"
    )
    print(f"{args.model}: worst-case USD {worst:.4f} for {len(rows) * args.k} calls")
    print(f"total worst-case USD {worst:.4f} (ceiling {args.usd_ceiling:.2f})")
    return 0 if worst <= args.usd_ceiling else 1


def run(args: argparse.Namespace) -> int:
    prompt_version = _prompt_version(args)
    rows = _train_rows(args, prompt_version=prompt_version)
    out_dir = ROOT / args.out_dir
    ledger_path = out_dir / LEDGER_FILENAME
    ledger = load_ledger(ledger_path, usd_ceiling=args.usd_ceiling)
    if ledger.total_calls:
        _log(
            f"resuming: ledger already holds {ledger.total_calls} calls, "
            f"USD {ledger.total_estimated_usd:.4f}"
        )
    adapter = RelayTeacherAdapter(
        model=args.model,
        usd_ceiling=args.usd_ceiling,
        ledger=ledger,
        prompt_version=prompt_version,
    )

    def progress(done: int, total: int) -> None:
        _log(
            f"{args.model}: {done}/{total} prompts, "
            f"ledger USD {ledger.total_estimated_usd:.4f}"
        )

    summary = sample_teacher(
        rows,
        adapter,
        k=args.k,
        out_dir=out_dir,
        ledger=ledger,
        progress=progress,
        concurrency=args.concurrency,
    )
    _log(
        f"{args.model}: sampled {summary.prompts_sampled}, skipped "
        f"{summary.prompts_skipped}, calls {summary.calls_written}, "
        f"budget_stopped={summary.budget_stopped}, "
        f"stop_reason={summary.stop_reason}"
    )
    path = samples_path(out_dir, args.model)
    curated = curate_candidates(rows, path, prompt_version=prompt_version)
    write_curation_artifacts(curated, out_dir=out_dir, model=args.model)
    report = generation_report(
        rows,
        path,
        ledger.to_dict(),
        curated,
        k=args.k,
        model=args.model,
        concurrency=args.concurrency,
    )
    report_path = out_dir / GENERATION_REPORT_FILENAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    rates = report["rates"]
    assert isinstance(rates, dict)
    print(
        json.dumps(
            {
                "accepted_count": report["accepted_count"],
                "accepted_per_family": report["accepted_per_family"],
                "f1_rate": rates["f1_rate"],
                "f2_act_needed_rate": rates["f2_act_needed_rate"],
                "f1_f4_rate": rates["f1_f4_rate"],
                "estimated_usd_total": ledger.total_estimated_usd,
                "prompts_complete": report["prompts_complete"],
                "run_complete": report["run_complete"],
                "stop_reason": report["stop_reason"],
                "training_ready": report["training_ready"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(f"training_ready: {report['training_ready']} ({_display(report_path)})")
    return 1 if summary.stop_reason is not None else 0


def reset(args: argparse.Namespace) -> int:
    out_dir = ROOT / args.out_dir
    path = samples_path(out_dir, args.model)
    if not path.is_file():
        print(f"no samples at {_display(path)}; nothing to reset")
        return 1
    ledger_path = out_dir / LEDGER_FILENAME
    before, after = reset_failed_charges(
        [path], ledger_path, usd_ceiling=args.usd_ceiling
    )
    for label, document in (("before", before), ("after", after)):
        print(
            f"ledger {label}: {document['total_calls']} calls, "
            f"USD {float(str(document['total_estimated_usd'])):.4f}"
        )
    print(f"ledger rebuilt from raw samples ({_display(ledger_path)})")
    return 0


def check(args: argparse.Namespace) -> int:
    out_dir = ROOT / args.out_dir
    report_path = out_dir / GENERATION_REPORT_FILENAME
    if not report_path.is_file():
        print(f"no generation report at {_display(report_path)}; nothing to check")
        return 0
    committed = json.loads(report_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if committed.get("schema_version") != GENERATION_REPORT_SCHEMA_VERSION:
        problems.append("schema_version_mismatch")
    model = committed.get("model")
    selection = committed.get("selection")
    criteria = committed.get("training_ready_criteria")
    if not isinstance(model, str) or not isinstance(selection, dict):
        return _report_problems([*problems, "report_shape_invalid"])
    try:
        prompt_version = report_prompt_version(committed)
    except ValueError:
        return _report_problems([*problems, "prompt_version_invalid"])
    if committed.get("compiler_version") != PHASE03C_COMPILER_VERSIONS[prompt_version]:
        problems.append("compiler_version_mismatch")
    if not isinstance(criteria, dict) or committed.get(
        "training_ready"
    ) != compute_training_ready(criteria):
        problems.append("training_ready_not_derived")
    for path in (
        manifest_path(out_dir, model),
        quarantine_path(out_dir, model),
        quality_report_path(out_dir, model),
    ):
        if not path.is_file():
            problems.append(f"curation_artifact_missing:{path.name}")
    quality = quality_report_path(out_dir, model)
    if quality.is_file():
        document = json.loads(quality.read_text(encoding="utf-8"))
        stored_criteria = document.get("training_ready_criteria")
        if not isinstance(stored_criteria, dict) or document.get(
            "training_ready"
        ) != compute_training_ready(stored_criteria):
            problems.append(f"training_ready_not_derived:{model}")
        for key in ("accepted_count", "accepted_prompts", "training_ready"):
            if document.get(key) != committed.get(key):
                problems.append(f"quality_report_drift:{key}")
    path = samples_path(out_dir, model)
    ledger_path = out_dir / LEDGER_FILENAME
    if path.is_file() and ledger_path.is_file():
        rows = _train_rows(args, prompt_version=prompt_version)
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        curated = curate_candidates(rows, path, prompt_version=prompt_version)
        fresh = generation_report(
            rows,
            path,
            ledger,
            curated,
            k=int(selection["k"]),
            model=model,
            concurrency=int(selection.get("concurrency", 1)),
        )
        stored_rates = committed.get("rates")
        fresh_rates = fresh["rates"]
        assert isinstance(fresh_rates, dict)
        if not isinstance(stored_rates, dict):
            problems.append("rates_missing")
        else:
            for key in RATE_KEYS:
                if stored_rates.get(key) != fresh_rates.get(key):
                    problems.append(f"rate_drift:{key}")
        for key in CURATION_KEYS:
            if committed.get(key) != fresh[key]:
                problems.append(f"curation_drift:{key}")
        for key in COMPLETENESS_KEYS:
            if committed.get(key) != fresh[key]:
                problems.append(f"completeness_drift:{key}")
        print("generation report recomputed from raw samples")
    else:
        print("raw samples absent; checked stored report and curation artifacts only")
    return _report_problems(problems)


def _report_problems(problems: list[str]) -> int:
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print("phase03c teacher generation report is consistent")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--usd-ceiling", type=float, default=140.0)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--manifest", type=Path, default=PROMPT_SET_MANIFEST_PATH)
    parser.add_argument(
        "--prompt-version",
        choices=tuple(PHASE03C_COMPILER_VERSIONS),
        default=STAGE1B_PROMPT_VERSION,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument(
        "--reset-failed-charges",
        action="store_true",
        help="rebuild the ledger from the samples JSONL: failed calls at zero",
    )
    args = parser.parse_args(argv)
    if args.dry_run:
        return dry_run(args)
    if args.check:
        return check(args)
    if args.reset_failed_charges:
        return reset(args)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
