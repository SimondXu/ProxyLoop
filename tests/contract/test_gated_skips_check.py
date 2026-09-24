from __future__ import annotations

from pathlib import Path

from scripts.check_gated_skips import EXPECTED_GATED_SKIPS, check, gated_skips

GATED = (
    '<testcase classname="" name="t{index}" file="../tests/integration/{file}">'
    '<skipped type="pytest.skip" message="PROXYLOOP_TEST_DATABASE_URL is required">'
    "tests/integration/{file}:1: PROXYLOOP_TEST_DATABASE_URL is required"
    "</skipped></testcase>"
)
OTHER_SKIP = (
    '<testcase classname="" name="other" file="../tests/integration/x.py">'
    '<skipped type="pytest.skip" message="needs macOS">x</skipped></testcase>'
)
PASSED = '<testcase classname="" name="ok" file="../tests/integration/x.py"/>'


def report(tmp_path: Path, gated: int) -> Path:
    cases = [
        GATED.format(index=index, file="a.py" if index % 2 else "b.py")
        for index in range(gated)
    ]
    path = tmp_path / "junit.xml"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite>'
        + "".join([*cases, OTHER_SKIP, PASSED])
        + "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return path


def test_counts_only_proxyloop_test_skips_per_file(tmp_path: Path) -> None:
    counts = gated_skips(report(tmp_path, 5))

    assert counts == {"tests/integration/a.py": 2, "tests/integration/b.py": 3}


def test_pinned_count_passes_and_names_the_real_dependency_gates(
    tmp_path: Path,
) -> None:
    ok, lines = check(report(tmp_path, EXPECTED_GATED_SKIPS), {})

    assert ok is True
    text = "\n".join(lines)
    assert f"variable: {EXPECTED_GATED_SKIPS}" in text
    for target in ("postgres-check", "phase05a-check", "phase06b1-check"):
        assert f"make {target}" in text


def test_a_changed_count_fails_either_way(tmp_path: Path) -> None:
    for gated in (EXPECTED_GATED_SKIPS - 1, EXPECTED_GATED_SKIPS + 1):
        ok, lines = check(report(tmp_path, gated), {})

        assert ok is False
        assert lines[-1].startswith(
            f"FAIL: expected {EXPECTED_GATED_SKIPS} gated skips, found {gated}."
        )


def test_a_missing_report_fails(tmp_path: Path) -> None:
    ok, lines = check(tmp_path / "missing.xml", {})

    assert ok is False
    assert "no runtime test report" in lines[0]


def test_the_pin_is_not_enforced_when_a_gate_variable_is_set(
    tmp_path: Path,
) -> None:
    environ = {"PROXYLOOP_TEST_DATABASE_URL": "postgresql://x", "OTHER": "1"}
    ok, lines = check(report(tmp_path, 0), environ)

    assert ok is True
    assert "not enforced: PROXYLOOP_TEST_DATABASE_URL set" in lines[-1]
    empty = {"PROXYLOOP_TEST_DATABASE_URL": ""}
    assert check(report(tmp_path, 0), empty)[0] is False
