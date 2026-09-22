from __future__ import annotations

import inspect
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
from proxyloop_data_pipeline.teacher_pipeline import (
    ACCEPTED_TARGET,
    DECISION_RULE_VERSION,
    LEDGER_FILENAME,
    MAX_KEPT_PER_PROMPT,
    PILOT_REPORT_FILENAME,
    compute_training_ready,
    curate_candidates,
    load_ledger,
    load_samples,
    pilot_decision,
    pilot_report,
    sample_teacher,
    samples_path,
    select_pilot_rows,
    teacher_manifest,
    write_curation_artifacts,
)
from proxyloop_evaluation.phase03b_readiness import (
    FORBIDDEN_MODEL_INPUT_KEYS,
    proposed_fast_target,
)
from proxyloop_evaluation.phase03c_experiment import DECISION_CONVENTION_BLOCK
from proxyloop_evaluation.phase03c_prompt_set import (
    PROMPT_SET_MANIFEST_PATH,
    PromptSetRow,
    load_prompt_set_manifest,
    render_prompt,
    train_families,
)
from proxyloop_evaluation.phase03c_teacher_filters import (
    DETECTORS,
    SECOND_FAMILY_AGREEMENT,
    STRICT_JSON_SCHEMA,
    TARGET_AGREEMENT,
    VERIFIER_REPLAY,
    CandidateContext,
    apply_filters,
    build_candidate_context,
    filter_verifier_replay,
)
from proxyloop_evaluation.relay_teacher import RelayTeacherAdapter, TeacherLedger
from proxyloop_provider_simulator.scenarios import BENCHMARK_SCENARIOS
from proxyloop_provider_simulator.splits import generate_split_manifest

from scripts import run_phase03c_teacher_pilot

ROOT = Path(__file__).resolve().parents[2]
MODEL = "claude-sonnet-5"
TRAIN_FAMILIES = frozenset(
    family.family_id
    for family in train_families(generate_split_manifest(BENCHMARK_SCENARIOS))
)


@pytest.fixture(scope="module")
def all_rows() -> tuple[PromptSetRow, ...]:
    return load_prompt_set_manifest(ROOT / PROMPT_SET_MANIFEST_PATH)


@pytest.fixture(scope="module")
def rows(all_rows: tuple[PromptSetRow, ...]) -> tuple[PromptSetRow, ...]:
    # Two prompts per family keeps every family and both positions in play.
    return select_pilot_rows(all_rows, per_family=2, seed=0)


@pytest.fixture(scope="module")
def contexts(rows: tuple[PromptSetRow, ...]) -> dict[str, CandidateContext]:
    return {row.prompt_id: build_candidate_context(row) for row in rows}


def perfect_content(row: PromptSetRow) -> str:
    return json.dumps(proposed_fast_target(row.oracle_action), sort_keys=True)


def variant(row: PromptSetRow, **overrides: object) -> str:
    target = proposed_fast_target(row.oracle_action)
    target.update(overrides)
    return json.dumps(target, sort_keys=True)


@dataclass
class _Completions:
    """Fake relay: answers by matching the exact v3 user prompt to a row."""

    by_user_prompt: dict[str, list[str]]
    calls: list[dict[str, object]] = field(default_factory=list)

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        contents = self.by_user_prompt[messages[1]["content"]]
        content = contents[(len(self.calls) - 1) % len(contents)]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            model=MODEL,
            id=f"chatcmpl-{len(self.calls)}",
            usage=SimpleNamespace(prompt_tokens=1_500, completion_tokens=120),
        )


@dataclass
class _Client:
    completions: _Completions

    @property
    def chat(self) -> SimpleNamespace:
        return SimpleNamespace(completions=self.completions)


def fake_client(
    contexts: dict[str, CandidateContext],
    responder: object = None,
) -> _Client:
    table: dict[str, list[str]] = {}
    for context in contexts.values():
        contents = (
            responder(context.row)
            if callable(responder)
            else [perfect_content(context.row)]
        )
        table[render_prompt(context.view).user] = list(contents)
    assert len(table) == len(contexts), "every prompt must render distinctly"
    return _Client(_Completions(table))


def adapter(client: _Client, ledger: TeacherLedger) -> RelayTeacherAdapter:
    return RelayTeacherAdapter(
        model=MODEL, client=client, usd_ceiling=ledger.usd_ceiling, ledger=ledger
    )


def test_perfect_teacher_passes_every_filter_and_pilot_is_go(
    rows: tuple[PromptSetRow, ...],
    contexts: dict[str, CandidateContext],
    tmp_path: Path,
) -> None:
    ledger = TeacherLedger(usd_ceiling=5.0)
    client = fake_client(contexts)
    run = sample_teacher(
        rows, adapter(client, ledger), k=3, out_dir=tmp_path, ledger=ledger
    )

    assert run.prompts_sampled == len(rows) == 20
    assert run.calls_written == 60 == len(client.completions.calls)
    assert not run.budget_stopped
    path = samples_path(tmp_path, MODEL)
    assert path == tmp_path / f"{MODEL}-samples.jsonl"
    assert len(load_samples(path)) == 60
    ledger_document = json.loads((tmp_path / LEDGER_FILENAME).read_text())
    assert ledger_document["total_calls"] == 60
    assert ledger_document["per_model"][MODEL]["succeeded"] == 60

    result = curate_candidates(rows, path)
    # k = 3 identical completions collapse to one kept sample per prompt.
    assert len(result.accepted) == 20
    per_prompt = Counter(item.row.prompt_id for item in result.accepted)
    assert max(per_prompt.values()) <= MAX_KEPT_PER_PROMPT
    assert result.quarantine["per_filter"] == {"dedup": 40}
    assert result.quarantine["per_reason"] == {"dedup:exact_duplicate": 40}
    assert all(item.result.second_family_act_agrees is None for item in result.accepted)
    report = result.quality_report
    assert report["accepted_count"] == 20
    assert report["cross_split_families"] == []
    assert report["forbidden_model_input_key_rows"] == 0
    assert set(report["accepted_families"]) <= TRAIN_FAMILIES
    assert report["second_family_filter_active"] is False
    assert report["ledger_total_estimated_usd"] == pytest.approx(
        ledger.total_estimated_usd
    )
    assert report["training_ready_criteria"] == {
        "accepted_at_least_target": False,
        "zero_cross_split_families": True,
        "zero_forbidden_model_input_keys": True,
        "ledger_within_cap": True,
    }
    assert report["training_ready"] is False

    manifest = teacher_manifest(result)
    first = manifest["rows"][0]
    assert set(first) == {
        "prompt_id",
        "family_id",
        "seed",
        "position_index",
        "model",
        "call_index",
        "content_hash",
        "lexical_fingerprint",
        "prompt_fingerprint",
        "second_family_act_agrees",
    }
    assert first["second_family_act_agrees"] is None

    pilot = pilot_report(
        rows, [path], ledger.to_dict(), per_family=2, seed=0, k=3, models=[MODEL]
    )
    rates = pilot["per_model"][MODEL]
    assert pilot["decision_rule_version"] == DECISION_RULE_VERSION
    assert pilot["selection"] == {"per_family": 2, "seed": 0, "k": 3}
    assert pilot["models"] == [MODEL]
    assert (rates["f1_rate"], rates["f2_act_needed_rate"], rates["f1_f4_rate"]) == (
        1.0,
        1.0,
        1.0,
    )
    assert rates["f2_rate"] == rates["f2_given_f1_rate"] == 1.0
    assert set(rates["per_family"]) == TRAIN_FAMILIES
    assert all(
        (item["f2_act_needed_rate"], item["f2_rate"]) == (1.0, 1.0)
        for item in rates["per_family"].values()
    )
    assert rates["calls"] == 60 and rates["calls_failed"] == 0
    assert rates["estimated_usd"] == pytest.approx(ledger.total_estimated_usd)
    assert rates["decision"] == "Go"
    assert pilot["decision"] == "Go"


def test_accepted_records_carry_v4_prompt_provenance_and_no_forbidden_keys(
    rows: tuple[PromptSetRow, ...],
    contexts: dict[str, CandidateContext],
    tmp_path: Path,
) -> None:
    ledger = TeacherLedger(usd_ceiling=5.0)
    sample_teacher(
        rows,
        adapter(fake_client(contexts), ledger),
        k=1,
        out_dir=tmp_path,
        ledger=ledger,
    )
    result = curate_candidates(rows, samples_path(tmp_path, MODEL))
    paths = write_curation_artifacts(result, out_dir=tmp_path, model=MODEL)
    assert [path.name for path in paths] == [
        f"{MODEL}-phase-03c-teacher-manifest.json",
        f"{MODEL}-phase-03c-teacher-quarantine.json",
        f"{MODEL}-phase-03c-teacher-quality-report.json",
        f"{MODEL}-accepted.jsonl",
    ]
    accepted_jsonl = paths[-1]
    records = [json.loads(line) for line in accepted_jsonl.read_text().splitlines()]
    assert len(records) == 20
    record = records[0]
    context = contexts[record["prompt_id"]]
    prompt = render_prompt(context.view)
    assert result.prompt_version == "v4"
    assert DECISION_CONVENTION_BLOCK in prompt.user
    assert record["messages"][0] == {"role": "system", "content": prompt.system}
    assert record["messages"][1] == {"role": "user", "content": prompt.user}
    assert record["messages"][2]["content"] == perfect_content(context.row)
    assert (
        record["prompt_fingerprint"]
        == prompt.fingerprint
        == context.row.prompt_fingerprint
    )
    assert record["generator"]["role"] == "teacher"
    assert record["generator"]["adapter_id"] == MODEL
    assert record["generator"]["external_model"] is True
    assert record["generator"]["external_input_token_count"] == 1_500

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {k for child in value.values() for k in keys(child)}
        if isinstance(value, list):
            return {k for child in value for k in keys(child)}
        return set()

    assert not any(FORBIDDEN_MODEL_INPUT_KEYS & keys(item) for item in records)
    for path in paths[:-1]:
        assert json.loads(path.read_text())


def test_each_defect_lands_in_its_filter_bucket_first_failure_wins(
    contexts: dict[str, CandidateContext],
) -> None:
    context = next(
        item for item in contexts.values() if item.row.oracle_action == "decline"
    )
    row = context.row
    good = perfect_content(row)
    other_act = variant(row, dialogue_act="escalate")
    fenced = f"```json\n{good}\n```"
    duplicate = good[:-1] + ', "dialogue_act": "counter"}'
    leaked = f"<think>hmm</think>{good}"
    claiming = variant(
        row, completion_claim={"status": "candidate", "evidence_message_ids": []}
    )
    pii = variant(row, response_text="Call me at 555-123-4567 about this offer.")
    completed = variant(row, response_text="Your request has been completed.")
    # Even a fact update whose source id exists in the view is rejected.
    known_id = str(context.view.recent_events[-1].event_id)
    update = {
        "key": "k",
        "value": "v",
        "source_message_id": known_id,
        "confidence": 0.5,
    }
    with_update = variant(row, fact_updates=[update])

    def reason(content: str) -> str | None:
        return apply_filters(context, content).reason

    assert reason(good) is None
    assert reason(fenced) == f"{STRICT_JSON_SCHEMA}:fenced"
    assert reason(duplicate) == f"{STRICT_JSON_SCHEMA}:duplicate_key"
    assert reason(leaked) == f"{STRICT_JSON_SCHEMA}:thinking_leak"
    assert reason("not json") == f"{STRICT_JSON_SCHEMA}:invalid_json"
    assert reason('{"dialogue_act": "counter"}') == f"{STRICT_JSON_SCHEMA}:schema"
    assert reason(other_act) == f"{TARGET_AGREEMENT}:dialogue_act"
    target_reasoner = proposed_fast_target(row.oracle_action)["reasoner_request"]
    assert isinstance(target_reasoner, dict)
    wrong_code = variant(
        row, reasoner_request={**target_reasoner, "reason_code": "something_else"}
    )
    assert reason(wrong_code) == f"{TARGET_AGREEMENT}:reasoner_reason_code"
    assert reason(claiming) == f"{TARGET_AGREEMENT}:completion_claim"
    assert reason(pii) == f"{DETECTORS}:pii"
    assert reason(completed) == f"{DETECTORS}:false_completion"
    assert reason(with_update) == f"{DETECTORS}:fact_updates_present"
    # First failure wins: a fenced wrong act is an F1 failure, a wrong act
    # with PII is an F2 failure.
    assert reason(f"```json\n{other_act}\n```") == f"{STRICT_JSON_SCHEMA}:fenced"
    assert (
        reason(variant(row, dialogue_act="escalate", response_text="555-123-4567 now"))
        == f"{TARGET_AGREEMENT}:dialogue_act"
    )
    # F3 on its own: an act the oracle did not choose fails the verifier replay.
    from proxyloop_evaluation.fast_output import FastModelOutput

    escalate = FastModelOutput.model_validate_json(other_act)
    assert (
        filter_verifier_replay(context, escalate)
        == f"{VERIFIER_REPLAY}:invalid_outcome"
    )
    assert (
        filter_verifier_replay(context, FastModelOutput.model_validate_json(good))
        is None
    )


def test_second_family_filter_is_optional_and_recorded(
    rows: tuple[PromptSetRow, ...],
    contexts: dict[str, CandidateContext],
    tmp_path: Path,
) -> None:
    ledger = TeacherLedger(usd_ceiling=5.0)
    sample_teacher(
        rows,
        adapter(fake_client(contexts), ledger),
        k=1,
        out_dir=tmp_path,
        ledger=ledger,
    )
    path = samples_path(tmp_path, MODEL)
    agree = curate_candidates(rows, path, second_family=lambda view: True)
    assert len(agree.accepted) == 20
    assert all(item.result.second_family_act_agrees is True for item in agree.accepted)
    assert agree.quality_report["second_family_filter_active"] is True
    disagree = curate_candidates(rows, path, second_family=lambda view: False)
    assert disagree.accepted == ()
    assert disagree.quarantine["per_filter"] == {SECOND_FAMILY_AGREEMENT: 20}


def test_dedup_keeps_at_most_two_distinct_samples_per_prompt(
    rows: tuple[PromptSetRow, ...],
    contexts: dict[str, CandidateContext],
    tmp_path: Path,
) -> None:
    def three_distinct(row: PromptSetRow) -> list[str]:
        base = perfect_content(row)
        text = proposed_fast_target(row.oracle_action)["response_text"]
        assert isinstance(text, str)
        return [
            base,
            variant(row, response_text=text.upper()),  # lexical duplicate
            variant(row, response_text=text + " Please confirm."),
            variant(row, response_text=text + " Thank you."),
        ]

    ledger = TeacherLedger(usd_ceiling=5.0)
    sample_teacher(
        rows,
        adapter(fake_client(contexts, three_distinct), ledger),
        k=4,
        out_dir=tmp_path,
        ledger=ledger,
    )
    result = curate_candidates(rows, samples_path(tmp_path, MODEL))
    per_prompt = Counter(item.row.prompt_id for item in result.accepted)
    assert set(per_prompt.values()) == {MAX_KEPT_PER_PROMPT}
    assert result.quarantine["per_reason"] == {
        "dedup:lexical_duplicate": 20,
        "dedup:per_prompt_cap": 20,
    }


def test_sampling_is_resumable_with_zero_client_calls(
    rows: tuple[PromptSetRow, ...],
    contexts: dict[str, CandidateContext],
    tmp_path: Path,
) -> None:
    ledger = TeacherLedger(usd_ceiling=5.0)
    first_client = fake_client(contexts)
    sample_teacher(
        rows, adapter(first_client, ledger), k=2, out_dir=tmp_path, ledger=ledger
    )
    assert len(first_client.completions.calls) == 40

    second_client = fake_client(contexts)
    resumed = TeacherLedger(usd_ceiling=5.0)
    run = sample_teacher(
        rows, adapter(second_client, resumed), k=2, out_dir=tmp_path, ledger=resumed
    )
    assert second_client.completions.calls == []
    assert run.prompts_skipped == 20 and run.prompts_sampled == 0
    assert len(load_samples(samples_path(tmp_path, MODEL))) == 40


def test_budget_stop_leaves_valid_partial_jsonl_and_ledger(
    rows: tuple[PromptSetRow, ...],
    contexts: dict[str, CandidateContext],
    tmp_path: Path,
) -> None:
    probe = adapter(fake_client(contexts), TeacherLedger(usd_ceiling=1.0))
    view = next(iter(contexts.values())).view
    # 1_500 input at $3/M + 120 output at $15/M per fake call.
    per_call = 1_500 * 3.0 / 1e6 + 120 * 15.0 / 1e6
    # Budget for 4 real calls plus the pre-call worst case of the 5th.
    ceiling = 4 * per_call + probe.worst_case_call_usd(view) - 1e-9
    ledger = TeacherLedger(usd_ceiling=ceiling)
    client = fake_client(contexts)

    run = sample_teacher(
        rows, adapter(client, ledger), k=3, out_dir=tmp_path, ledger=ledger
    )

    assert run.budget_stopped is True
    assert len(client.completions.calls) == 4
    samples = load_samples(samples_path(tmp_path, MODEL))
    assert len(samples) == 4
    assert [s.call_index for s in samples] == [0, 1, 2, 0]
    assert all(s.content is not None for s in samples)
    document = json.loads((tmp_path / LEDGER_FILENAME).read_text())
    assert document["total_calls"] == 4
    assert document["total_estimated_usd"] <= document["usd_ceiling"] == ceiling
    restored = load_ledger(tmp_path / LEDGER_FILENAME, usd_ceiling=5.0)
    assert restored.total_calls == 4
    assert restored.total_estimated_usd == pytest.approx(4 * per_call)
    # On resume the complete prompt is skipped, the interrupted prompt is
    # topped up from 1 to 3 (call indices 1 and 2), and the remaining 18
    # prompts are sampled in full under a larger ceiling.
    resume_client = fake_client(contexts)
    resumed = sample_teacher(
        rows, adapter(resume_client, restored), k=3, out_dir=tmp_path, ledger=restored
    )
    assert resumed.prompts_skipped == 1 and resumed.prompts_sampled == 19
    assert len(resume_client.completions.calls) == 2 + 54
    samples = load_samples(samples_path(tmp_path, MODEL))
    assert len(samples) == 60
    per_prompt = Counter(s.prompt_id for s in samples)
    assert set(per_prompt.values()) == {3}
    topped_up = [s.call_index for s in samples if s.prompt_id == rows[1].prompt_id]
    assert topped_up == [0, 1, 2]


def test_training_ready_is_derived_never_hand_set(
    rows: tuple[PromptSetRow, ...],
    contexts: dict[str, CandidateContext],
    tmp_path: Path,
) -> None:
    assert "training_ready" not in inspect.signature(curate_candidates).parameters
    ledger = TeacherLedger(usd_ceiling=5.0)
    sample_teacher(
        rows,
        adapter(fake_client(contexts), ledger),
        k=1,
        out_dir=tmp_path,
        ledger=ledger,
    )
    result = curate_candidates(rows, samples_path(tmp_path, MODEL))
    report = result.quality_report
    criteria = report["training_ready_criteria"]
    assert isinstance(criteria, dict)
    assert report["accepted_count"] < ACCEPTED_TARGET
    assert criteria["accepted_at_least_target"] is False
    assert report["training_ready"] is compute_training_ready(criteria) is False
    assert compute_training_ready({**criteria, "accepted_at_least_target": True})
    assert result.training_ready is False


def test_development_rows_are_never_accepted(
    all_rows: tuple[PromptSetRow, ...], tmp_path: Path
) -> None:
    dev_row = next(row for row in all_rows if row.split == "development")
    dev_context = build_candidate_context(dev_row)
    ledger = TeacherLedger(usd_ceiling=5.0)
    sample_teacher(
        (dev_row,),
        adapter(fake_client({dev_row.prompt_id: dev_context}), ledger),
        k=1,
        out_dir=tmp_path,
        ledger=ledger,
    )
    result = curate_candidates((dev_row,), samples_path(tmp_path, MODEL))
    assert result.accepted == ()
    assert result.quarantine["per_reason"] == {"split_guard:development": 1}
    assert set(result.quality_report["accepted_families"]) <= TRAIN_FAMILIES


def test_select_pilot_rows_is_balanced_and_deterministic(
    all_rows: tuple[PromptSetRow, ...],
) -> None:
    pilot = select_pilot_rows(all_rows, per_family=20, seed=0)
    assert len(pilot) == 200
    assert Counter(row.family_id for row in pilot) == dict.fromkeys(TRAIN_FAMILIES, 20)
    assert {row.split for row in pilot} == {"train"}
    strata = Counter(
        (row.family_id, row.configuration_id, row.position_index) for row in pilot
    )
    assert set(strata.values()) == {5}
    assert len({row.prompt_id for row in pilot}) == 200
    assert pilot == select_pilot_rows(all_rows, per_family=20, seed=0)
    assert pilot != select_pilot_rows(all_rows, per_family=20, seed=1)
    assert pilot == tuple(sorted(pilot, key=lambda row: row.prompt_id))


def test_pilot_decision_rule_uses_unconditional_act_needed_f2() -> None:
    def rates(f1: float, f2_act_needed: float, f1_f4: float) -> dict[str, object]:
        # The full F2 and the conditional F2 are deliberately set to values
        # that would flip the decision if they were consulted.
        return {
            "f1_rate": f1,
            "f2_act_needed_rate": f2_act_needed,
            "f2_rate": 0.0,
            "f1_f4_rate": f1_f4,
            "f2_given_f1_rate": 0.0,
        }

    assert pilot_decision(rates(0.95, 0.60, 0.40)) == "Go"
    assert pilot_decision(rates(0.94, 0.60, 0.40)) == "Hold"
    assert pilot_decision(rates(0.99, 0.59, 0.40)) == "Hold"
    assert pilot_decision(rates(0.99, 0.60, 0.39)) == "Hold"
    assert pilot_decision(rates(0.99, 0.39, 0.39)) == "Stop"
    assert pilot_decision(rates(0.10, 0.40, 0.10)) == "Hold"
    assert pilot_decision({"f1_rate": None}) == "Hold"


def test_dry_run_prints_worst_case_under_the_pilot_cap(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_phase03c_teacher_pilot.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "pilot prompts: 200 (k=3)" in out
    total = float(out.split("total worst-case USD ")[1].split(" ")[0])
    assert 0 < total < 15.0


def test_check_validates_a_written_pilot_report(
    rows: tuple[PromptSetRow, ...],
    contexts: dict[str, CandidateContext],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_dir = tmp_path / "teacher"
    # ``--check`` reads per_family/seed/k/models from the report, not the CLI.
    args = ["--out-dir", str(out_dir), "--per-family", "7"]
    assert run_phase03c_teacher_pilot.main(["--check", *args]) == 0
    assert "nothing to check" in capsys.readouterr().out

    ledger = TeacherLedger(usd_ceiling=5.0)
    sample_teacher(
        rows,
        adapter(fake_client(contexts), ledger),
        k=2,
        out_dir=out_dir,
        ledger=ledger,
    )
    path = samples_path(out_dir, MODEL)
    write_curation_artifacts(
        curate_candidates(rows, path), out_dir=out_dir, model=MODEL
    )
    report = pilot_report(
        rows, [path], ledger.to_dict(), per_family=2, seed=0, k=2, models=[MODEL]
    )
    report_path = out_dir / PILOT_REPORT_FILENAME
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    assert run_phase03c_teacher_pilot.main(["--check", *args]) == 0
    assert "recomputed from raw samples" in capsys.readouterr().out

    tampered = json.loads(report_path.read_text())
    tampered["per_model"][MODEL]["decision"] = "Stop"
    report_path.write_text(json.dumps(tampered))
    assert run_phase03c_teacher_pilot.main(["--check", *args]) == 1
    out = capsys.readouterr().out
    assert f"decision_drift:{MODEL}:Go" in out
    assert f"rate_drift:{MODEL}:decision" in out

    (out_dir / f"{MODEL}-phase-03c-teacher-quarantine.json").unlink()
    assert run_phase03c_teacher_pilot.main(["--check", *args]) == 1
    assert "curation_artifact_missing" in capsys.readouterr().out


def test_script_run_writes_every_artifact_with_a_fake_relay(
    all_rows: tuple[PromptSetRow, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sys

    from proxyloop_evaluation.openai_frontier import FRONTIER_API_KEY_ENV

    pilot = select_pilot_rows(all_rows, per_family=1, seed=0)
    pilot_contexts = {row.prompt_id: build_candidate_context(row) for row in pilot}
    created: list[dict[str, object]] = []

    def factory(**kwargs: object) -> _Client:
        created.append(kwargs)
        return fake_client(pilot_contexts)

    monkeypatch.setenv(FRONTIER_API_KEY_ENV, "sk-test-only-not-a-real-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=factory))
    out_dir = tmp_path / "teacher"
    args = ["--out-dir", str(out_dir), "--per-family", "1", "--models", MODEL]

    assert run_phase03c_teacher_pilot.main(["--k", "2", *args]) == 0

    captured = capsys.readouterr()
    assert len(created) == 1 and created[0]["api_key"] == "sk-test-only-not-a-real-key"
    assert "decision: Go" in captured.out
    assert f"{MODEL}: sampled 10, skipped 0, calls 20" in captured.err
    for name in (
        LEDGER_FILENAME,
        PILOT_REPORT_FILENAME,
        f"{MODEL}-phase-03c-teacher-manifest.json",
        f"{MODEL}-phase-03c-teacher-quarantine.json",
        f"{MODEL}-phase-03c-teacher-quality-report.json",
        f"{MODEL}-samples.jsonl",
        f"{MODEL}-accepted.jsonl",
    ):
        assert (out_dir / name).is_file(), name
    report = json.loads((out_dir / PILOT_REPORT_FILENAME).read_text())
    assert report["decision_rule_version"] == DECISION_RULE_VERSION
    assert report["per_model"][MODEL]["prompts"] == 10
    assert report["estimated_usd_total"] == pytest.approx(
        report["per_model"][MODEL]["estimated_usd"]
    )
    assert run_phase03c_teacher_pilot.main(["--check", *args]) == 0
    assert "recomputed from raw samples" in capsys.readouterr().out
    # A second run resumes: zero new calls, same artifacts rewritten.
    assert run_phase03c_teacher_pilot.main(["--k", "2", *args]) == 0
    assert f"{MODEL}: sampled 0, skipped 10, calls 0" in capsys.readouterr().err


def test_reason_code_mismatch_counts_as_act_needed_f2_but_not_full_f2(
    rows: tuple[PromptSetRow, ...],
    contexts: dict[str, CandidateContext],
    tmp_path: Path,
) -> None:
    def wrong_reason_code(row: PromptSetRow) -> list[str]:
        reasoner = proposed_fast_target(row.oracle_action)["reasoner_request"]
        assert isinstance(reasoner, dict)
        return [variant(row, reasoner_request={**reasoner, "reason_code": "other"})]

    ledger = TeacherLedger(usd_ceiling=5.0)
    sample_teacher(
        rows,
        adapter(fake_client(contexts, wrong_reason_code), ledger),
        k=1,
        out_dir=tmp_path,
        ledger=ledger,
    )
    path = samples_path(tmp_path, MODEL)
    result = curate_candidates(rows, path)
    assert result.accepted == ()
    assert result.quarantine["per_reason"] == {
        f"{TARGET_AGREEMENT}:reasoner_reason_code": 20
    }
    report = pilot_report(
        rows, [path], ledger.to_dict(), per_family=2, seed=0, k=1, models=[MODEL]
    )
    rates = report["per_model"][MODEL]
    assert rates["f2_act_needed_rate"] == 1.0
    assert rates["f2_rate"] == 0.0
    assert rates["f1_f4_rate"] == 0.0
    # The contract's F2 passes, F1-F4 does not: Hold, not Stop.
    assert rates["decision"] == "Hold"


def test_v3_teacher_against_the_v4_manifest_is_prompt_drift(
    rows: tuple[PromptSetRow, ...],
    contexts: dict[str, CandidateContext],
    tmp_path: Path,
) -> None:
    ledger = TeacherLedger(usd_ceiling=5.0)
    v3_teacher = RelayTeacherAdapter(
        model=MODEL,
        client=fake_client(contexts),
        usd_ceiling=ledger.usd_ceiling,
        ledger=ledger,
        prompt_version="v3",
    )
    with pytest.raises(ValueError, match="prompt_drift"):
        sample_teacher(rows, v3_teacher, k=1, out_dir=tmp_path, ledger=ledger)
    assert v3_teacher.calls_started == 0

    sample_teacher(
        rows,
        adapter(fake_client(contexts), ledger),
        k=1,
        out_dir=tmp_path,
        ledger=ledger,
    )
    result = curate_candidates(rows, samples_path(tmp_path, MODEL), prompt_version="v3")
    assert result.accepted == ()
    assert result.quarantine["per_filter"] == {"prompt_drift": 20}


def test_prompt_drift_is_quarantined_never_accepted(
    rows: tuple[PromptSetRow, ...],
    contexts: dict[str, CandidateContext],
    tmp_path: Path,
) -> None:
    ledger = TeacherLedger(usd_ceiling=5.0)
    sample_teacher(
        rows,
        adapter(fake_client(contexts), ledger),
        k=1,
        out_dir=tmp_path,
        ledger=ledger,
    )
    path = samples_path(tmp_path, MODEL)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    lines[0]["prompt_fingerprint"] = "0" * 64
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))

    result = curate_candidates(rows, path)

    assert len(result.accepted) == 19
    assert result.quarantine["per_filter"] == {"prompt_drift": 1}
    assert lines[0]["prompt_id"] not in {item.row.prompt_id for item in result.accepted}
