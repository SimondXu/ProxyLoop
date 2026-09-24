from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from scripts.check_gated_skips import (
    EXPECTED_GATED_SKIPS,
    EXPECTED_GATED_SKIPS_PER_FILE,
    check,
    gated_skips,
)

GATED = (
    '<testcase classname="" name="t{index}" file="../{file}">'
    '<skipped type="pytest.skip" message="PROXYLOOP_TEST_DATABASE_URL is required">'
    "{file}:1: PROXYLOOP_TEST_DATABASE_URL is required"
    "</skipped></testcase>"
)
OTHER_SKIP = (
    '<testcase classname="" name="other" file="../tests/integration/x.py">'
    '<skipped type="pytest.skip" message="needs macOS">x</skipped></testcase>'
)
PASSED = '<testcase classname="" name="ok" file="../tests/integration/x.py"/>'
DATABASE = "PROXYLOOP_TEST_DATABASE_URL"
TEMPORAL = "PROXYLOOP_TEST_TEMPORAL_ADDRESS"
BOTH = {DATABASE: "postgresql://x", TEMPORAL: "localhost:7233"}


def report(tmp_path: Path, per_file: Mapping[str, int]) -> Path:
    cases = [
        GATED.format(index=f"{file}-{index}", file=file)
        for file, count in per_file.items()
        for index in range(count)
    ]
    path = tmp_path / "junit.xml"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite>'
        + "".join([*cases, OTHER_SKIP, PASSED])
        + "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return path


def pinned(**changes: int) -> dict[str, int]:
    """The pinned per-file counts, with files changed by their basename."""

    counts = dict(EXPECTED_GATED_SKIPS_PER_FILE)
    for file in counts:
        stem = Path(file).stem
        if stem in changes:
            counts[file] += changes[stem]
    return counts


def test_counts_only_proxyloop_test_skips_per_file(tmp_path: Path) -> None:
    counts = gated_skips(report(tmp_path, {"tests/a.py": 2, "tests/b.py": 3}))

    assert counts == {"tests/a.py": 2, "tests/b.py": 3}


def test_pinned_count_passes_and_names_the_real_dependency_gates(
    tmp_path: Path,
) -> None:
    ok, lines = check(report(tmp_path, pinned()), {})

    assert ok is True
    text = "\n".join(lines)
    assert f"variable: {EXPECTED_GATED_SKIPS}" in text
    for target in ("postgres-check", "phase05a-check", "phase06b1-check"):
        assert f"make {target}" in text


def test_a_changed_count_fails_either_way(tmp_path: Path) -> None:
    for delta in (-1, 1):
        gated = EXPECTED_GATED_SKIPS + delta
        ok, lines = check(
            report(tmp_path, pinned(test_phase_05a_case_runtime=delta)), {}
        )

        assert ok is False
        assert any(
            line.startswith(
                f"FAIL: expected {EXPECTED_GATED_SKIPS} gated skips, found {gated}."
            )
            for line in lines
        )


def test_a_per_file_mismatch_with_the_same_total_fails(tmp_path: Path) -> None:
    moved = pinned(test_phase_05a_case_runtime=-1)
    moved["tests/integration/test_new_unrelated.py"] = 1
    ok, lines = check(report(tmp_path, moved), {})

    assert ok is False
    text = "\n".join(lines)
    assert "integration/test_phase_05a_case_runtime.py: expected 2, found 1" in text
    assert "integration/test_new_unrelated.py: expected 0, found 1" in text
    assert "removed, added, or moved between files" in text


def test_a_missing_report_fails(tmp_path: Path) -> None:
    ok, lines = check(tmp_path / "missing.xml", {})

    assert ok is False
    assert "no runtime test report" in lines[0]


def test_an_unknown_gate_variable_is_ignored(tmp_path: Path) -> None:
    environ = {"PROXYLOOP_TEST_SOMETHING_ELSE": "1", "OTHER": "1"}

    assert check(report(tmp_path, pinned()), environ)[0] is True
    ok, lines = check(report(tmp_path, {}), environ)
    assert ok is False
    assert any(line.startswith("FAIL: expected") for line in lines)


def test_an_empty_gate_variable_counts_as_unset(tmp_path: Path) -> None:
    ok, _ = check(report(tmp_path, {}), {DATABASE: "", TEMPORAL: ""})

    assert ok is False


def test_both_variables_set_require_zero_gated_skips(tmp_path: Path) -> None:
    ok, lines = check(report(tmp_path, {}), BOTH)
    assert ok is True
    assert lines[-1] == f"{DATABASE} and {TEMPORAL} set: no gated test skipped."

    ok, lines = check(report(tmp_path, {"tests/a.py": 1}), BOTH)
    assert ok is False
    assert lines[-1].startswith(
        f"FAIL: {DATABASE} and {TEMPORAL} are set, but 1 gated test skipped."
    )


def test_exactly_one_variable_set_is_report_only(tmp_path: Path) -> None:
    for name in (DATABASE, TEMPORAL):
        ok, lines = check(report(tmp_path, {"tests/a.py": 3}), {name: "set"})

        assert ok is True
        assert lines[-1] == (
            f"Pin not enforced: only {name} is set, "
            "so gated tests may have run instead of skipping."
        )
