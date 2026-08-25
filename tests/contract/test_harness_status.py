from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_layout import validate_harness_status


def status(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": 1,
        "product_phase_state": "idle",
        "active_product_phase": "",
        "active_contract": "",
        "next_phase_authorized": False,
    }
    result.update(overrides)
    return result


def test_idle_status_is_valid(tmp_path: Path) -> None:
    assert validate_harness_status(status(), root=tmp_path) is None


@pytest.mark.parametrize("schema_version", (True, 1.0))
def test_schema_version_must_be_integer_one(
    tmp_path: Path, schema_version: object
) -> None:
    error = validate_harness_status(
        status(schema_version=schema_version), root=tmp_path
    )

    assert error == "harness/status.toml must use schema_version = 1."


def test_active_status_requires_phase_name(tmp_path: Path) -> None:
    error = validate_harness_status(
        status(product_phase_state="in_progress"), root=tmp_path
    )

    assert error == "A non-idle harness status must name active_product_phase."


def test_active_status_requires_contract_name(tmp_path: Path) -> None:
    error = validate_harness_status(
        status(product_phase_state="in_progress", active_product_phase="Phase 05"),
        root=tmp_path,
    )

    assert error == "A non-idle harness status must name active_contract."


@pytest.mark.parametrize(
    "contract",
    (
        "/tmp/phase.md",
        "harness/context/phase.md",
        "harness/build/../context/phase.md",
        "harness/build/phase.toml",
    ),
)
def test_active_status_restricts_contract_location(
    tmp_path: Path, contract: str
) -> None:
    error = validate_harness_status(
        status(
            product_phase_state="in_progress",
            active_product_phase="Phase 05",
            active_contract=contract,
        ),
        root=tmp_path,
    )

    assert error == "active_contract must be a Markdown file under harness/build/."


def test_active_status_requires_existing_contract(tmp_path: Path) -> None:
    error = validate_harness_status(
        status(
            product_phase_state="in_progress",
            active_product_phase="Phase 05",
            active_contract="harness/build/phase-05.md",
        ),
        root=tmp_path,
    )

    assert error == "active_contract does not exist: harness/build/phase-05.md."


def test_active_status_accepts_existing_contract(tmp_path: Path) -> None:
    contract = tmp_path / "harness/build/phase-05.md"
    contract.parent.mkdir(parents=True)
    contract.touch()

    error = validate_harness_status(
        status(
            product_phase_state="in_progress",
            active_product_phase="Phase 05",
            active_contract="harness/build/phase-05.md",
        ),
        root=tmp_path,
    )

    assert error is None


def test_active_status_rejects_contract_symlink_outside_build(tmp_path: Path) -> None:
    outside_contract = tmp_path / "outside.md"
    outside_contract.touch()
    contract = tmp_path / "harness/build/phase-05.md"
    contract.parent.mkdir(parents=True)
    contract.symlink_to(outside_contract)

    error = validate_harness_status(
        status(
            product_phase_state="in_progress",
            active_product_phase="Phase 05",
            active_contract="harness/build/phase-05.md",
        ),
        root=tmp_path,
    )

    assert error == "active_contract must resolve within harness/build/."


def test_next_phase_authorized_must_be_boolean(tmp_path: Path) -> None:
    error = validate_harness_status(
        status(next_phase_authorized="false"), root=tmp_path
    )

    assert error == "harness/status.toml next_phase_authorized must be a boolean."
