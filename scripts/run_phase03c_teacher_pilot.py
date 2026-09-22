"""Run, estimate, or check the Phase 03C Stage 1b 200-prompt teacher pilot.

``--dry-run`` renders the pilot prompts and prints the worst-case USD per
model without constructing a client.  A real run samples each model through
``RelayTeacherAdapter`` under one shared ledger (the key comes only from the
process environment variable the adapter names), curates each model's
samples, and writes the pilot report.  ``--check`` recomputes a committed
pilot report from the raw JSONL when present and always recomputes its
decision from its stored rates.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from proxyloop_data_pipeline.teacher_pipeline import (
    DECISION_RULE_VERSION,
    LEDGER_FILENAME,
    PILOT_REPORT_FILENAME,
    compute_training_ready,
    curate_candidates,
    load_ledger,
    manifest_path,
    overall_decision,
    pilot_decision,
    pilot_report,
    quality_report_path,
    quarantine_path,
    sample_teacher,
    samples_path,
    select_pilot_rows,
    write_curation_artifacts,
)
from proxyloop_evaluation.phase03c_experiment import PromptVersion
from proxyloop_evaluation.phase03c_prompt_set import (
    PROMPT_SET_MANIFEST_PATH,
    STAGE1B_PROMPT_VERSION,
    PromptSetRow,
    load_prompt_set_manifest,
)
from proxyloop_evaluation.phase03c_teacher_filters import build_candidate_context
from proxyloop_evaluation.relay_teacher import RelayTeacherAdapter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = Path("data/experiments/phase-03c/teacher")
DEFAULT_MODELS = ("gemini-3.6-flash", "claude-sonnet-5")
RATE_KEYS = (
    "f1_rate",
    "f2_act_needed_rate",
    "f2_rate",
    "f1_f4_rate",
    "f2_given_f1_rate",
    "per_family",
    "decision",
)


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _display(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _rows(
    args: argparse.Namespace, *, per_family: int, seed: int
) -> tuple[PromptSetRow, ...]:
    rows = load_prompt_set_manifest(ROOT / args.manifest)
    return select_pilot_rows(rows, per_family=per_family, seed=seed)


def _prompt_version(args: argparse.Namespace) -> PromptVersion:
    return cast(PromptVersion, args.prompt_version)


def dry_run(args: argparse.Namespace) -> int:
    rows = _rows(args, per_family=args.per_family, seed=args.seed)
    views = [build_candidate_context(row).view for row in rows]
    total = 0.0
    print(f"pilot prompts: {len(rows)} (k={args.k})")
    for model in args.models:
        adapter = RelayTeacherAdapter(
            model=model,
            usd_ceiling=args.usd_ceiling,
            prompt_version=_prompt_version(args),
        )
        worst = sum(adapter.worst_case_call_usd(view) for view in views) * args.k
        total += worst
        print(f"{model}: worst-case USD {worst:.4f} for {len(rows) * args.k} calls")
    print(f"total worst-case USD {total:.4f} (ceiling {args.usd_ceiling:.2f})")
    return 0 if total <= args.usd_ceiling else 1


def run(args: argparse.Namespace) -> int:
    rows = _rows(args, per_family=args.per_family, seed=args.seed)
    out_dir = ROOT / args.out_dir
    ledger_path = out_dir / LEDGER_FILENAME
    ledger = load_ledger(ledger_path, usd_ceiling=args.usd_ceiling)
    if ledger.total_calls:
        _log(
            f"resuming: ledger already holds {ledger.total_calls} calls, "
            f"USD {ledger.total_estimated_usd:.4f}"
        )
    stopped = False
    for model in args.models:
        adapter = RelayTeacherAdapter(
            model=model,
            usd_ceiling=args.usd_ceiling,
            ledger=ledger,
            prompt_version=_prompt_version(args),
        )

        def progress(done: int, total: int, model: str = model) -> None:
            _log(
                f"{model}: {done}/{total} prompts, "
                f"ledger USD {ledger.total_estimated_usd:.4f}"
            )

        summary = sample_teacher(
            rows, adapter, k=args.k, out_dir=out_dir, ledger=ledger, progress=progress
        )
        _log(
            f"{model}: sampled {summary.prompts_sampled}, skipped "
            f"{summary.prompts_skipped}, calls {summary.calls_written}, "
            f"budget_stopped={summary.budget_stopped}"
        )
        if summary.budget_stopped:
            stopped = True
            break
    paths = []
    for model in args.models:
        path = samples_path(out_dir, model)
        if not path.is_file():
            continue
        paths.append(path)
        result = curate_candidates(rows, path, prompt_version=_prompt_version(args))
        write_curation_artifacts(result, out_dir=out_dir, model=model)
        _log(
            f"{model}: accepted {result.quality_report['accepted_count']}, "
            f"quarantined {result.quality_report['quarantined_total']}"
        )
    report = pilot_report(
        rows,
        paths,
        ledger.to_dict(),
        per_family=args.per_family,
        seed=args.seed,
        k=args.k,
        models=args.models,
    )
    report_path = out_dir / PILOT_REPORT_FILENAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["per_model"], indent=2, sort_keys=True))
    print(f"decision: {report['decision']} ({_display(report_path)})")
    return 1 if stopped else 0


def check(args: argparse.Namespace) -> int:
    out_dir = ROOT / args.out_dir
    report_path = out_dir / PILOT_REPORT_FILENAME
    if not report_path.is_file():
        print(f"no pilot report at {_display(report_path)}; nothing to check")
        return 0
    committed = json.loads(report_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if committed.get("decision_rule_version") != DECISION_RULE_VERSION:
        problems.append("decision_rule_version_mismatch")
    per_model = committed.get("per_model")
    selection = committed.get("selection")
    models = committed.get("models")
    if (
        not isinstance(per_model, dict)
        or not isinstance(selection, dict)
        or not isinstance(models, list)
    ):
        return _report_problems([*problems, "report_shape_invalid"])
    decisions = []
    for model, rates in sorted(per_model.items()):
        if not isinstance(rates, dict):
            problems.append(f"malformed_rates:{model}")
            continue
        expected = pilot_decision(rates)
        if rates.get("decision") != expected:
            problems.append(f"decision_drift:{model}:{expected}")
        decisions.append(expected)
    if committed.get("decision") != overall_decision(decisions):
        problems.append("overall_decision_drift")
    for model in models:
        for path in (
            manifest_path(out_dir, str(model)),
            quarantine_path(out_dir, str(model)),
            quality_report_path(out_dir, str(model)),
        ):
            if not path.is_file():
                problems.append(f"curation_artifact_missing:{path.name}")
        quality = quality_report_path(out_dir, str(model))
        if quality.is_file():
            document = json.loads(quality.read_text(encoding="utf-8"))
            criteria = document.get("training_ready_criteria")
            if not isinstance(criteria, dict) or document.get(
                "training_ready"
            ) != compute_training_ready(criteria):
                problems.append(f"training_ready_not_derived:{model}")
    paths = [samples_path(out_dir, str(model)) for model in models]
    ledger_path = out_dir / LEDGER_FILENAME
    if paths and all(path.is_file() for path in paths) and ledger_path.is_file():
        rows = _rows(
            args,
            per_family=int(selection["per_family"]),
            seed=int(selection["seed"]),
        )
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        recomputed = pilot_report(
            rows,
            paths,
            ledger,
            per_family=int(selection["per_family"]),
            seed=int(selection["seed"]),
            k=int(selection["k"]),
            models=[str(model) for model in models],
        )
        fresh = recomputed["per_model"]
        assert isinstance(fresh, dict)
        for model, rates in sorted(per_model.items()):
            fresh_rates = fresh.get(model)
            if not isinstance(fresh_rates, dict) or not isinstance(rates, dict):
                problems.append(f"model_missing_in_samples:{model}")
                continue
            for key in RATE_KEYS:
                if rates.get(key) != fresh_rates.get(key):
                    problems.append(f"rate_drift:{model}:{key}")
            curated = curate_candidates(
                rows,
                samples_path(out_dir, str(model)),
                prompt_version=_prompt_version(args),
            )
            quality = quality_report_path(out_dir, str(model))
            if quality.is_file():
                stored = json.loads(quality.read_text(encoding="utf-8"))
                for key in ("accepted_count", "quarantined_total", "training_ready"):
                    if stored.get(key) != curated.quality_report[key]:
                        problems.append(f"quality_drift:{model}:{key}")
        if recomputed["decision"] != committed.get("decision"):
            problems.append("recomputed_decision_drift")
        print("pilot report recomputed from raw samples")
    else:
        print("raw samples absent; checked stored rates and decision only")
    return _report_problems(problems)


def _report_problems(problems: list[str]) -> int:
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print("phase03c teacher pilot report is consistent")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--per-family", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--usd-ceiling", type=float, default=15.0)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--manifest", type=Path, default=PROMPT_SET_MANIFEST_PATH)
    parser.add_argument(
        "--prompt-version", choices=("v3", "v4"), default=STAGE1B_PROMPT_VERSION
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run:
        return dry_run(args)
    if args.check:
        return check(args)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
