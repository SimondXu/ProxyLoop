"""Phase 03C Stage 1b rejection-sampling pipeline over the relay teacher.

``select_pilot_rows`` picks the pilot subset, ``sample_teacher`` writes raw
JSONL plus the cost ledger (resumable), ``curate_candidates`` applies the
F1-F5 verifier filters and dedup and derives ``training_ready``, and
``pilot_report`` recomputes the pilot rates and the Go/Stop decision.  The
teacher adapter is injected; nothing here reads credentials or the network.
Teacher provenance reuses ``GeneratorSnapshot`` (``role="teacher"``); the
Phase 02 ``NormalizedTrajectory`` shape (oracle decision plus response
variants, three-snapshot generation record) does not fit a raw structured
Fast completion and is not forced onto it.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Final

from proxyloop_evaluation.fast_output import FastModelOutput
from proxyloop_evaluation.phase03b_readiness import FORBIDDEN_MODEL_INPUT_KEYS
from proxyloop_evaluation.phase03c_experiment import PromptVersion
from proxyloop_evaluation.phase03c_prompt_set import (
    STAGE1B_PROMPT_VERSION,
    PromptSetRow,
    render_prompt,
    train_families,
)
from proxyloop_evaluation.phase03c_teacher_filters import (
    FILTER_ORDER,
    STRICT_JSON_SCHEMA,
    AgreementFilter,
    CandidateContext,
    FilterResult,
    act_needed_agrees,
    apply_filters,
    build_candidate_context,
    content_hash,
    filter_detectors,
    filter_strict_json_schema,
    filter_target_agreement,
    filter_verifier_replay,
    lexical_fingerprint,
)
from proxyloop_evaluation.relay_teacher import (
    RelayTeacherAdapter,
    TeacherBudgetExceededError,
    TeacherLedger,
    TeacherModelTotals,
    TeacherSample,
)
from proxyloop_provider_simulator.scenarios import BENCHMARK_SCENARIOS
from proxyloop_provider_simulator.splits import generate_split_manifest

from .models import GeneratorSnapshot

SAMPLES_SUFFIX: Final = "-samples.jsonl"
ACCEPTED_SUFFIX: Final = "-accepted.jsonl"
LEDGER_FILENAME: Final = "phase-03c-cost-ledger.json"
MANIFEST_FILENAME: Final = "phase-03c-teacher-manifest.json"
QUARANTINE_FILENAME: Final = "phase-03c-teacher-quarantine.json"
QUALITY_REPORT_FILENAME: Final = "phase-03c-teacher-quality-report.json"
PILOT_REPORT_FILENAME: Final = "phase-03c-teacher-pilot-report.json"
TEACHER_MANIFEST_SCHEMA_VERSION: Final = "phase-03c-teacher-manifest-v1"
PILOT_REPORT_SCHEMA_VERSION: Final = "phase-03c-teacher-pilot-report-v1"
DECISION_RULE_VERSION: Final = "phase-03c-pilot-v1"
ACCEPTED_TARGET: Final = 2_500
MAX_KEPT_PER_PROMPT: Final = 2
DEDUP: Final = "dedup"
CALL_FAILED: Final = "call_failed"
SPLIT_GUARD: Final = "split_guard"
PROMPT_DRIFT: Final = "prompt_drift"
PROGRESS_EVERY: Final = 20
# Contract thresholds over the total-sample denominator.  The contract's
# literal F2 is act + ``needed`` agreement (``f2_act_needed_rate``); training
# acceptance uses the full reasoner-request equality (``f2_rate``).
GO_F1_MIN: Final = 0.95
GO_F2_ACT_NEEDED_MIN: Final = 0.60
GO_F1_F4_MIN: Final = 0.40
STOP_F2_ACT_NEEDED_BELOW: Final = 0.40

ProgressCallback = Callable[[int, int], None]


def samples_path(out_dir: Path, model: str) -> Path:
    return out_dir / f"{model}{SAMPLES_SUFFIX}"


def accepted_path(out_dir: Path, model: str) -> Path:
    return out_dir / f"{model}{ACCEPTED_SUFFIX}"


def manifest_path(out_dir: Path, model: str) -> Path:
    return out_dir / f"{model}-{MANIFEST_FILENAME}"


def quarantine_path(out_dir: Path, model: str) -> Path:
    return out_dir / f"{model}-{QUARANTINE_FILENAME}"


def quality_report_path(out_dir: Path, model: str) -> Path:
    return out_dir / f"{model}-{QUALITY_REPORT_FILENAME}"


def _write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _int(value: object) -> int:
    return value if type(value) is int else 0


def _float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


# --- pilot selection -------------------------------------------------------


def select_pilot_rows(
    rows: Sequence[PromptSetRow], per_family: int = 20, seed: int = 0
) -> tuple[PromptSetRow, ...]:
    """``per_family`` train prompts per train family, balanced over strata.

    Strata are (configuration, position); ``per_family`` is split evenly over
    the four strata with any remainder assigned round-robin.  Rows are sorted
    by ``prompt_id`` before ``random.Random(seed)`` samples them, so the
    selection is deterministic for a given manifest.
    """

    if per_family < 1:
        raise ValueError("per_family must be positive")
    rng = random.Random(seed)
    by_family: dict[str, dict[tuple[str, int], list[PromptSetRow]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in sorted(rows, key=lambda item: item.prompt_id):
        if row.split == "train":
            by_family[row.family_id][(row.configuration_id, row.position_index)].append(
                row
            )
    selected: list[PromptSetRow] = []
    for family_id in sorted(by_family):
        strata = by_family[family_id]
        keys = sorted(strata)
        base, extra = divmod(per_family, len(keys))
        for index, key in enumerate(keys):
            want = base + (1 if index < extra else 0)
            pool = strata[key]
            if len(pool) < want:
                raise ValueError(f"family {family_id} stratum {key} has {len(pool)}")
            selected.extend(rng.sample(pool, want))
    selected.sort(key=lambda item: item.prompt_id)
    return tuple(selected)


# --- sampling ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SampleRun:
    """What one ``sample_teacher`` invocation did; nothing about content."""

    model: str
    samples_path: Path
    prompts_requested: int
    prompts_skipped: int
    prompts_sampled: int
    calls_written: int
    budget_stopped: bool


def _sample_line(
    *,
    row: PromptSetRow,
    model: str,
    sample: TeacherSample,
    prompt_fingerprint: str,
    schema_fingerprint: str,
) -> dict[str, object]:
    return {
        "prompt_id": row.prompt_id,
        "model": model,
        "call_index": sample.call_index,
        "seed_tag": row.prompt_id,
        "content": sample.content,
        "prompt_fingerprint": prompt_fingerprint,
        "schema_fingerprint": schema_fingerprint,
        "record": asdict(sample.record),
        "error": asdict(sample.error) if sample.error is not None else None,
        "finish_reason": sample.finish_reason,
        "usage_missing": sample.usage_missing,
    }


@dataclass(slots=True)
class _PromptProgress:
    """Per prompt: call indices already written and how many carried content."""

    call_indices: set[int] = field(default_factory=set)
    succeeded: int = 0

    @property
    def next_call_index(self) -> int:
        return max(self.call_indices, default=-1) + 1


def _existing_progress(path: Path) -> dict[str, _PromptProgress]:
    progress: dict[str, _PromptProgress] = defaultdict(_PromptProgress)
    if not path.is_file():
        return progress
    for sample in load_samples(path):
        entry = progress[sample.prompt_id]
        entry.call_indices.add(sample.call_index)
        if sample.content is not None:
            entry.succeeded += 1
    return progress


def load_ledger(path: Path, *, usd_ceiling: float) -> TeacherLedger:
    """Restore a written ledger so a resumed run keeps counting toward the cap."""

    ledger = TeacherLedger(usd_ceiling=usd_ceiling)
    if not path.is_file():
        return ledger
    document = json.loads(path.read_text(encoding="utf-8"))
    per_model = document.get("per_model") if isinstance(document, dict) else None
    if not isinstance(per_model, dict):
        raise ValueError(f"malformed ledger: {path}")
    for model, totals in per_model.items():
        if not isinstance(totals, dict):
            raise ValueError(f"malformed ledger totals for {model!r}: {path}")
        ledger.per_model[str(model)] = TeacherModelTotals(
            calls=_int(totals.get("calls")),
            succeeded=_int(totals.get("succeeded")),
            failed=_int(totals.get("failed")),
            input_tokens=_int(totals.get("input_tokens")),
            output_tokens=_int(totals.get("output_tokens")),
            estimated_usd=_float(totals.get("estimated_usd")),
        )
    return ledger


def sample_teacher(
    rows: Sequence[PromptSetRow],
    teacher: RelayTeacherAdapter,
    *,
    k: int = 3,
    out_dir: Path,
    ledger: TeacherLedger,
    progress: ProgressCallback | None = None,
) -> SampleRun:
    """Sample ``k`` completions per row into ``<model>-samples.jsonl``.

    A resumed run tops every prompt up to ``k`` successful samples: prompts
    that already hold ``k`` are skipped and the rest receive only the missing
    calls, with ``call_index`` continuing after the indices already on disk.
    A budget stop keeps the samples completed for the current row, writes the
    ledger, and returns ``budget_stopped=True``; the ledger is rewritten after
    every row so an interrupted run still leaves a valid ledger on disk.
    """

    if teacher.ledger is not ledger:
        raise ValueError("teacher must share the ledger that is written to disk")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = samples_path(out_dir, teacher.model)
    ledger_path = out_dir / LEDGER_FILENAME
    progress_by_prompt = _existing_progress(path)
    skipped = sampled = written = 0
    budget_stopped = False
    with path.open("a", encoding="utf-8") as handle:
        for index, row in enumerate(rows, start=1):
            entry = progress_by_prompt[row.prompt_id]
            missing = k - entry.succeeded
            if missing <= 0:
                skipped += 1
                continue
            context = build_candidate_context(row)
            prompt_fingerprint = render_prompt(
                context.view, prompt_version=teacher.prompt_version
            ).fingerprint
            if prompt_fingerprint != row.prompt_fingerprint:
                raise ValueError(f"prompt_drift:{row.prompt_id}")
            try:
                batch = teacher.sample(context.view, k=missing, seed_tag=row.prompt_id)
                samples: tuple[TeacherSample, ...] = batch.samples
            except TeacherBudgetExceededError as exc:
                samples = exc.completed
                budget_stopped = True
            offset = entry.next_call_index
            for sample in samples:
                sample = replace(sample, call_index=offset + sample.call_index)
                handle.write(
                    json.dumps(
                        _sample_line(
                            row=row,
                            model=teacher.model,
                            sample=sample,
                            prompt_fingerprint=prompt_fingerprint,
                            schema_fingerprint=teacher.schema_fingerprint,
                        ),
                        sort_keys=True,
                    )
                    + "\n"
                )
                entry.call_indices.add(sample.call_index)
                if sample.content is not None:
                    entry.succeeded += 1
                written += 1
            handle.flush()
            _write_json(ledger_path, ledger.to_dict())
            if samples:
                sampled += 1
            if budget_stopped:
                break
            if progress is not None and index % PROGRESS_EVERY == 0:
                progress(index, len(rows))
    _write_json(ledger_path, ledger.to_dict())
    return SampleRun(
        model=teacher.model,
        samples_path=path,
        prompts_requested=len(rows),
        prompts_skipped=skipped,
        prompts_sampled=sampled,
        calls_written=written,
        budget_stopped=budget_stopped,
    )


# --- curation ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RawSample:
    prompt_id: str
    model: str
    call_index: int
    content: str | None
    prompt_fingerprint: str
    schema_fingerprint: str
    record: dict[str, object]


def load_samples(path: Path) -> tuple[RawSample, ...]:
    """Read the raw JSONL; a repeated ``(prompt_id, call_index)`` keeps its first."""

    samples: list[RawSample] = []
    seen: set[tuple[str, int]] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            record = item["record"]
            if not isinstance(record, dict):
                raise ValueError(f"malformed sample record in {path}")
            key = (str(item["prompt_id"]), int(item["call_index"]))
            if key in seen:
                continue
            seen.add(key)
            samples.append(
                RawSample(
                    prompt_id=str(item["prompt_id"]),
                    model=str(item["model"]),
                    call_index=int(item["call_index"]),
                    content=item["content"],
                    prompt_fingerprint=str(item["prompt_fingerprint"]),
                    schema_fingerprint=str(item["schema_fingerprint"]),
                    record=record,
                )
            )
    return tuple(samples)


@dataclass(frozen=True, slots=True)
class AcceptedSample:
    """One accepted completion plus the metadata the manifest records."""

    row: PromptSetRow
    sample: RawSample
    content: str
    result: FilterResult
    content_hash: str
    lexical_fingerprint: str

    def manifest_row(self) -> dict[str, object]:
        return {
            "prompt_id": self.row.prompt_id,
            "family_id": self.row.family_id,
            "seed": self.row.seed,
            "position_index": self.row.position_index,
            "model": self.sample.model,
            "call_index": self.sample.call_index,
            "content_hash": self.content_hash,
            "lexical_fingerprint": self.lexical_fingerprint,
            "prompt_fingerprint": self.sample.prompt_fingerprint,
            "second_family_act_agrees": self.result.second_family_act_agrees,
        }

    def training_record(
        self, context: CandidateContext, *, prompt_version: PromptVersion
    ) -> dict[str, object]:
        """The git-ignored accepted row: prompt messages plus teacher provenance."""

        prompt = render_prompt(context.view, prompt_version=prompt_version)
        record = self.sample.record
        return {
            "prompt_id": self.row.prompt_id,
            "prompt_fingerprint": self.sample.prompt_fingerprint,
            "schema_fingerprint": self.sample.schema_fingerprint,
            "content_hash": self.content_hash,
            "lexical_fingerprint": self.lexical_fingerprint,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
                {"role": "assistant", "content": self.content},
            ],
            "generator": GeneratorSnapshot(
                role="teacher",
                adapter_id=self.sample.model,
                version=str(
                    record.get("response_model_version")
                    or record.get("response_model")
                    or self.sample.model
                ),
                external_model=True,
                external_input_token_count=_int(record.get("input_tokens")),
                external_output_token_count=_int(record.get("output_tokens")),
                estimated_external_cost_usd=_float(record.get("estimated_cost_usd")),
            ).model_dump(mode="json"),
        }


@dataclass(frozen=True, slots=True)
class CurationResult:
    accepted: tuple[AcceptedSample, ...]
    contexts: dict[str, CandidateContext]
    quarantine: dict[str, object]
    quality_report: dict[str, object]
    prompt_version: PromptVersion = STAGE1B_PROMPT_VERSION

    @property
    def training_ready(self) -> bool:
        return bool(self.quality_report["training_ready"])


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in _all_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


def _train_family_ids() -> frozenset[str]:
    manifest = generate_split_manifest(BENCHMARK_SCENARIOS)
    return frozenset(family.family_id for family in train_families(manifest))


def _read_ledger(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    return document if isinstance(document, dict) else None


def compute_training_ready(criteria: dict[str, bool]) -> bool:
    """``training_ready`` is the conjunction of the recorded criteria, only."""

    return all(criteria.values())


@dataclass(slots=True)
class _FilterTally:
    per_filter: Counter[str] = field(default_factory=Counter)
    per_reason: Counter[str] = field(default_factory=Counter)

    def add(self, reason: str) -> None:
        self.per_filter[reason.split(":", 1)[0]] += 1
        self.per_reason[reason] += 1


def curate_candidates(
    rows: Sequence[PromptSetRow],
    samples_path: Path,
    *,
    second_family: AgreementFilter | None = None,
    ledger_path: Path | None = None,
    prompt_version: PromptVersion = STAGE1B_PROMPT_VERSION,
) -> CurationResult:
    """Filter, dedup, and score the raw samples of one model.

    ``ledger_path`` defaults to the cost ledger beside ``samples_path``.  The
    quality report's ``training_ready`` is derived from its recorded criteria
    by ``compute_training_ready`` and never set directly.
    """

    rows_by_id = {row.prompt_id: row for row in rows}
    samples = load_samples(samples_path)
    train_ids = _train_family_ids()
    tally = _FilterTally()
    accepted: list[AcceptedSample] = []
    contexts: dict[str, CandidateContext] = {}
    kept_per_prompt: Counter[str] = Counter()
    seen_hashes: dict[str, set[str]] = defaultdict(set)
    seen_lexical: dict[str, set[str]] = defaultdict(set)
    models: set[str] = set()
    for sample in samples:
        models.add(sample.model)
        row = rows_by_id.get(sample.prompt_id)
        if row is None:
            raise ValueError(f"unknown prompt_id in samples: {sample.prompt_id}")
        if sample.content is None:
            tally.add(f"{CALL_FAILED}:{sample.record.get('status')}")
            continue
        if row.split != "train" or row.family_id not in train_ids:
            tally.add(f"{SPLIT_GUARD}:{row.split}")
            continue
        context = contexts.get(row.prompt_id)
        if context is None:
            context = contexts[row.prompt_id] = build_candidate_context(row)
        rendered = render_prompt(
            context.view, prompt_version=prompt_version
        ).fingerprint
        if not (sample.prompt_fingerprint == row.prompt_fingerprint == rendered):
            tally.add(PROMPT_DRIFT)
            continue
        result = apply_filters(context, sample.content, second_family=second_family)
        if result.reason is not None or result.output is None:
            tally.add(result.reason or f"{STRICT_JSON_SCHEMA}:unknown")
            continue
        exact = content_hash(sample.content)
        lexical = lexical_fingerprint(result.output.response_text)
        if exact in seen_hashes[row.prompt_id]:
            tally.add(f"{DEDUP}:exact_duplicate")
            continue
        if lexical in seen_lexical[row.prompt_id]:
            tally.add(f"{DEDUP}:lexical_duplicate")
            continue
        if kept_per_prompt[row.prompt_id] >= MAX_KEPT_PER_PROMPT:
            tally.add(f"{DEDUP}:per_prompt_cap")
            continue
        seen_hashes[row.prompt_id].add(exact)
        seen_lexical[row.prompt_id].add(lexical)
        kept_per_prompt[row.prompt_id] += 1
        accepted.append(
            AcceptedSample(
                row=row,
                sample=sample,
                content=sample.content,
                result=result,
                content_hash=exact,
                lexical_fingerprint=lexical,
            )
        )

    ledger = _read_ledger(ledger_path or samples_path.parent / LEDGER_FILENAME)
    ledger_total = (
        float(str(ledger["total_estimated_usd"])) if ledger is not None else None
    )
    ledger_cap = float(str(ledger["usd_ceiling"])) if ledger is not None else None
    forbidden_key_rows = sum(
        bool(
            FORBIDDEN_MODEL_INPUT_KEYS
            & _all_keys(
                item.training_record(
                    contexts[item.row.prompt_id], prompt_version=prompt_version
                )
            )
        )
        for item in accepted
    )
    accepted_families = sorted({item.row.family_id for item in accepted})
    cross_split_families = sorted(set(accepted_families) - train_ids)
    criteria = {
        "accepted_at_least_target": len(accepted) >= ACCEPTED_TARGET,
        "zero_cross_split_families": not cross_split_families,
        "zero_forbidden_model_input_keys": forbidden_key_rows == 0,
        "ledger_within_cap": (
            ledger_total is not None
            and ledger_cap is not None
            and ledger_total <= ledger_cap
        ),
    }
    quarantine = {
        "schema_version": TEACHER_MANIFEST_SCHEMA_VERSION,
        "samples_path": samples_path.name,
        "filter_order": list(FILTER_ORDER),
        "quarantined_total": sum(tally.per_filter.values()),
        "per_filter": dict(sorted(tally.per_filter.items())),
        "per_reason": dict(sorted(tally.per_reason.items())),
    }
    quality_report = {
        "schema_version": TEACHER_MANIFEST_SCHEMA_VERSION,
        "models": sorted(models),
        "samples_total": len(samples),
        "prompts_sampled": len({sample.prompt_id for sample in samples}),
        "accepted_count": len(accepted),
        "accepted_prompts": len(kept_per_prompt),
        "accepted_target": ACCEPTED_TARGET,
        "max_kept_per_prompt": MAX_KEPT_PER_PROMPT,
        "accepted_families": accepted_families,
        "cross_split_families": cross_split_families,
        "forbidden_model_input_key_rows": forbidden_key_rows,
        "second_family_filter_active": second_family is not None,
        "ledger_total_estimated_usd": ledger_total,
        "ledger_usd_ceiling": ledger_cap,
        "quarantined_total": quarantine["quarantined_total"],
        "training_ready_criteria": criteria,
        "training_ready": compute_training_ready(criteria),
    }
    return CurationResult(
        accepted=tuple(accepted),
        contexts=contexts,
        quarantine=quarantine,
        quality_report=quality_report,
        prompt_version=prompt_version,
    )


def teacher_manifest(result: CurationResult) -> dict[str, object]:
    rows = [item.manifest_row() for item in result.accepted]
    return {
        "schema_version": TEACHER_MANIFEST_SCHEMA_VERSION,
        "accepted_count": len(rows),
        "family_counts": dict(
            sorted(Counter(item.row.family_id for item in result.accepted).items())
        ),
        "rows": rows,
    }


def write_curation_artifacts(
    result: CurationResult, *, out_dir: Path, model: str
) -> tuple[Path, ...]:
    """Write the model-prefixed manifest, quarantine, quality report, and JSONL."""

    manifest = manifest_path(out_dir, model)
    quarantine = quarantine_path(out_dir, model)
    report = quality_report_path(out_dir, model)
    _write_json(manifest, teacher_manifest(result))
    _write_json(quarantine, result.quarantine)
    _write_json(report, result.quality_report)
    accepted = accepted_path(out_dir, model)
    with accepted.open("w", encoding="utf-8") as handle:
        for item in result.accepted:
            record = item.training_record(
                result.contexts[item.row.prompt_id],
                prompt_version=result.prompt_version,
            )
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return manifest, quarantine, report, accepted


# --- pilot report ------------------------------------------------------------


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def pilot_decision(model_rates: dict[str, object]) -> str:
    """Go / Stop / Hold from the contract rule; ``None`` rates never pass.

    Stop and Go both read the contract's literal F2 (act + ``needed``) over the
    total-sample denominator; ``f2_given_f1_rate`` is informational only.
    """

    f1 = model_rates.get("f1_rate")
    f2 = model_rates.get("f2_act_needed_rate")
    f1_f4 = model_rates.get("f1_f4_rate")
    if isinstance(f2, float) and f2 < STOP_F2_ACT_NEEDED_BELOW:
        return "Stop"
    if (
        isinstance(f1, float)
        and isinstance(f2, float)
        and isinstance(f1_f4, float)
        and f1 >= GO_F1_MIN
        and f2 >= GO_F2_ACT_NEEDED_MIN
        and f1_f4 >= GO_F1_F4_MIN
    ):
        return "Go"
    return "Hold"


def overall_decision(decisions: Iterable[str]) -> str:
    items = list(decisions)
    if not items:
        return "Hold"
    if "Go" in items:
        return "Go"
    if all(item == "Stop" for item in items):
        return "Stop"
    return "Hold"


@dataclass(slots=True)
class _FamilyTally:
    samples: int = 0
    f2_act_needed: int = 0
    f2: int = 0


def _model_rates(
    samples: Sequence[RawSample],
    contexts: dict[str, CandidateContext],
    rows_by_id: dict[str, PromptSetRow],
) -> dict[str, object]:
    succeeded = [sample for sample in samples if sample.content is not None]
    f1 = f2_act_needed = f2 = f1_f4 = 0
    families: dict[str, _FamilyTally] = defaultdict(_FamilyTally)
    reasons: Counter[str] = Counter()
    for sample in succeeded:
        assert sample.content is not None
        row = rows_by_id[sample.prompt_id]
        family = families[row.family_id]
        family.samples += 1
        context = contexts.get(sample.prompt_id)
        if context is None:
            context = contexts[sample.prompt_id] = build_candidate_context(row)
        reason = filter_strict_json_schema(sample.content)
        if reason is not None:
            reasons[reason] += 1
            continue
        f1 += 1
        output = FastModelOutput.model_validate_json(sample.content)
        if act_needed_agrees(output, row.oracle_action):
            f2_act_needed += 1
            family.f2_act_needed += 1
        reason = filter_target_agreement(output, row.oracle_action)
        if reason is not None:
            reasons[reason] += 1
            continue
        f2 += 1
        family.f2 += 1
        reason = filter_verifier_replay(context, output) or filter_detectors(
            context, output
        )
        if reason is not None:
            reasons[reason] += 1
            continue
        f1_f4 += 1
    total = len(succeeded)
    rates: dict[str, object] = {
        "calls": len(samples),
        "calls_failed": len(samples) - total,
        "samples": total,
        "prompts": len({sample.prompt_id for sample in samples}),
        "f1_pass": f1,
        "f2_act_needed_pass": f2_act_needed,
        "f2_pass": f2,
        "f1_f4_pass": f1_f4,
        "f1_rate": _rate(f1, total),
        "f2_act_needed_rate": _rate(f2_act_needed, total),
        "f2_rate": _rate(f2, total),
        "f1_f4_rate": _rate(f1_f4, total),
        "f2_given_f1_rate": _rate(f2, f1),
        "per_family": {
            family_id: {
                "samples": tally.samples,
                "f2_act_needed_rate": _rate(tally.f2_act_needed, tally.samples),
                "f2_rate": _rate(tally.f2, tally.samples),
            }
            for family_id, tally in sorted(families.items())
        },
        "failure_reasons": dict(sorted(reasons.items())),
    }
    rates["decision"] = pilot_decision(rates)
    return rates


def pilot_report(
    rows: Sequence[PromptSetRow],
    samples_paths: Sequence[Path],
    ledger: dict[str, object],
    *,
    per_family: int,
    seed: int,
    k: int,
    models: Sequence[str],
) -> dict[str, object]:
    """Per-model F1 / F2 / F1-F4 rates, per-family F2, cost, and decision.

    ``f2_act_needed_rate`` is the contract's literal F2 (act + ``needed``) and
    drives the decision; ``f2_rate`` is the full reasoner-request equality
    used for training acceptance.  Both use successful calls as denominator;
    failed calls are counted separately so relay errors do not masquerade as
    teacher quality.  F5 is optional and not part of the pilot rates.  The
    selection parameters are stored so ``--check`` can rebuild the same rows.
    """

    rows_by_id = {row.prompt_id: row for row in rows}
    contexts: dict[str, CandidateContext] = {}
    by_model: dict[str, list[RawSample]] = defaultdict(list)
    for path in samples_paths:
        for sample in load_samples(path):
            if sample.prompt_id not in rows_by_id:
                raise ValueError(f"unknown prompt_id in samples: {sample.prompt_id}")
            by_model[sample.model].append(sample)
    per_model_ledger = ledger.get("per_model")
    if not isinstance(per_model_ledger, dict):
        per_model_ledger = {}
    per_model: dict[str, object] = {}
    for model in sorted(by_model):
        rates = _model_rates(by_model[model], contexts, rows_by_id)
        totals = per_model_ledger.get(model)
        rates["estimated_usd"] = (
            totals.get("estimated_usd") if isinstance(totals, dict) else None
        )
        per_model[model] = rates
    decisions = [
        str(rates["decision"])
        for rates in per_model.values()
        if isinstance(rates, dict)
    ]
    return {
        "schema_version": PILOT_REPORT_SCHEMA_VERSION,
        "decision_rule_version": DECISION_RULE_VERSION,
        "decision_rule": {
            "go": {
                "f1_rate_min": GO_F1_MIN,
                "f2_act_needed_rate_min": GO_F2_ACT_NEEDED_MIN,
                "f1_f4_rate_min": GO_F1_F4_MIN,
            },
            "stop": {"f2_act_needed_rate_below": STOP_F2_ACT_NEEDED_BELOW},
            "otherwise": "Hold",
        },
        "selection": {"per_family": per_family, "seed": seed, "k": k},
        "models": list(models),
        "prompt_count": len(rows),
        "samples_files": [path.name for path in samples_paths],
        "per_model": per_model,
        "estimated_usd_total": ledger.get("total_estimated_usd"),
        "usd_ceiling": ledger.get("usd_ceiling"),
        "accounting": ledger.get("accounting"),
        "decision": overall_decision(decisions),
    }


__all__ = [
    "ACCEPTED_SUFFIX",
    "ACCEPTED_TARGET",
    "DECISION_RULE_VERSION",
    "LEDGER_FILENAME",
    "MANIFEST_FILENAME",
    "MAX_KEPT_PER_PROMPT",
    "PILOT_REPORT_FILENAME",
    "PILOT_REPORT_SCHEMA_VERSION",
    "PROGRESS_EVERY",
    "QUALITY_REPORT_FILENAME",
    "QUARANTINE_FILENAME",
    "SAMPLES_SUFFIX",
    "TEACHER_MANIFEST_SCHEMA_VERSION",
    "AcceptedSample",
    "CurationResult",
    "RawSample",
    "SampleRun",
    "accepted_path",
    "compute_training_ready",
    "curate_candidates",
    "load_ledger",
    "load_samples",
    "manifest_path",
    "overall_decision",
    "pilot_decision",
    "pilot_report",
    "quality_report_path",
    "quarantine_path",
    "sample_teacher",
    "samples_path",
    "select_pilot_rows",
    "teacher_manifest",
    "write_curation_artifacts",
]
