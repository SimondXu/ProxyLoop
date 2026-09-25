"""Phase 07 D5: the offline, deterministic `make ops-report`."""

from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest

from scripts import run_ops_report as ops

ROOT = Path(__file__).resolve().parents[2]


def _fake_collector(_root: Path, files: tuple[str, ...]) -> int:
    return 10 * len(files)


def _copy_inputs(target: Path) -> Path:
    for path in (
        ops.MAKEFILE,
        ops.GATED_SKIPS_SCRIPT,
        *ops.SPLIT_REPORTS.values(),
        ops.M1_REPORT,
        ops.M2_REPORT,
    ):
        (target / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target / path)
    return target


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ops-report opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_report_is_deterministic_and_opens_no_socket(no_network: None) -> None:
    first = ops.render(ops.build_report(ROOT, collector=_fake_collector))
    second = ops.render(ops.build_report(ROOT, collector=_fake_collector))
    assert first == second


def test_gates_come_from_the_makefile_and_the_pin() -> None:
    report = ops.build_report(ROOT, collector=_fake_collector)
    gates = report["gates"]
    makefile = (ROOT / "Makefile").read_text()
    assert "fast-slow-split-check" in gates["make_test_checks"]
    assert "ops-report-check" in gates["make_test_checks"]
    assert gates["make_test_check_count"] == len(gates["make_test_checks"])
    assert set(gates["real_dependency_gates"]) == {
        "postgres-check",
        "phase05a-check",
        "phase06b1-check",
    }
    for gate in gates["real_dependency_gates"].values():
        assert all(path in makefile for path in gate["files"])
    pin = report["gated_skip_pin"]
    gated = ops._load_gated_skips(ROOT)
    assert pin["total"] == gated.EXPECTED_GATED_SKIPS
    assert pin["every_pinned_file_is_in_a_gate"] is True


def test_split_reports_carry_labels_and_mark_the_local_ones_pre_judge() -> None:
    split = ops.build_report(ROOT, collector=_fake_collector)["fast_slow_split"]
    assert split["scripted"]["judge_backend"] == "scripted_judge"
    assert "judge_calls_by_result" in split["scripted"]["scenarios"]["demo_path"]
    for backend in ("distilled", "untuned"):
        assert split[backend]["judge"] == ops.PRE_JUDGE_NOTE
        assert "judge_calls_by_result" not in split[backend]["scenarios"]["demo_path"]
        assert split[backend]["label"]
        assert split[backend]["claim_boundary"]
    assert split["distilled"]["label"] == "local opt-in candidate"


def test_parity_headlines_match_the_committed_reports() -> None:
    parity = ops.build_report(ROOT, collector=_fake_collector)["parity"]
    m1 = parity["m1_stack_parity"]["verdict"]
    assert m1["result"] == "stack parity held"
    assert round(m1["distilled_local_act_agreement"], 3) == 0.983
    arms = parity["m2_product_path"]["arms"]
    assert arms["distilled"]["delivered_line"]["count"] == 0
    assert arms["untuned"]["delivered_line"]["count"] == 8
    assert arms["distilled"]["act_agreement_true_oracle"]["count"] == 157
    assert arms["untuned"]["act_agreement_true_oracle"]["count"] == 97
    assert arms["distilled"]["rows"] == 240


def test_trace_health_invariants_hold_on_the_committed_split_reports() -> None:
    health = ops.build_report(ROOT, collector=_fake_collector)["trace_and_log_health"]
    for backend in ("scripted", "distilled", "untuned"):
        for scenario in health["split_reports"][backend].values():
            assert scenario["one_line_per_dialogue_turn"] is True
    for scenario in health["split_reports"]["scripted"].values():
        assert scenario["judge_calls_equal_admitted_slow"] is True
        assert scenario["slow_retries"] == 0
        assert scenario["fast_failed"] == 0


def test_journey_is_reported_as_not_recorded_until_it_exists(tmp_path: Path) -> None:
    root = _copy_inputs(tmp_path)
    report = ops.build_report(root, collector=_fake_collector)
    assert report["trace_and_log_health"]["journey"]["status"] == "not_recorded"
    assert all(item["path"] != str(ops.JOURNEY_REPORT) for item in report["inputs"])

    journey = {
        "readiness": {"adapter_mode": "scripted"},
        "trace_counts": {
            role: {"failed": 0, "rejected": 0, "succeeded": 1}
            for role in ("fast", "judge", "slow")
        },
        "execution_count": {"after_approve": 1, "after_replay": 1},
        "receipt_predicate": True,
        "marker_absent": {"proposal_response": True, "runtime.log": True},
    }
    (root / ops.JOURNEY_REPORT).write_text(json.dumps(journey))
    recorded = ops.build_report(root, collector=_fake_collector)
    health = recorded["trace_and_log_health"]["journey"]
    assert health["status"] == "recorded"
    assert health["executed_once_after_replay"] is True
    assert health["judge_calls_equal_slow_results"] is True
    assert health["marker_absent_everywhere"] is True
    assert any(item["path"] == str(ops.JOURNEY_REPORT) for item in recorded["inputs"])


def test_an_input_change_changes_the_report(tmp_path: Path) -> None:
    root = _copy_inputs(tmp_path)
    before = ops.render(ops.build_report(root, collector=_fake_collector))
    path = root / ops.SPLIT_REPORTS["untuned"]
    path.write_text(path.read_text() + " ")
    after = ops.render(ops.build_report(root, collector=_fake_collector))
    assert before != after


def test_the_report_is_content_free_of_the_demo_marker() -> None:
    text = ops.render(ops.build_report(ROOT, collector=_fake_collector))
    assert "zebra-7731" not in text


def test_committed_report_is_current() -> None:
    committed = (ROOT / ops.REPORT_PATH).read_text()
    assert committed == ops.render(ops.build_report(ROOT))


def test_make_wires_the_report_and_its_check_into_make_test() -> None:
    makefile = (ROOT / "Makefile").read_text()
    assert "ops-report:" in makefile
    assert "ops-report-check:" in makefile
    test_line = next(line for line in makefile.splitlines() if line.startswith("test:"))
    assert "ops-report-check" in test_line.split()
