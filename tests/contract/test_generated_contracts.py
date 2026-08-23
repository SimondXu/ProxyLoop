from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "contracts" / "jsonschema" / "proxyloop-contracts.schema.json"
FIXTURES = ROOT / "tests" / "fixtures"


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_generated_schema_is_valid_and_accepts_representative_case() -> None:
    schema = load_json(SCHEMA)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        load_json(FIXTURES / "case.valid.json")
    )


def test_generated_schema_rejects_representative_invalid_fixtures() -> None:
    validator = Draft202012Validator(
        load_json(SCHEMA),
        format_checker=FormatChecker(),
    )

    for name in (
        "case.unknown-field.invalid.json",
        "approval.mismatched-reference.invalid.json",
        "approval.missing-offer.invalid.json",
        "completion.unsupported.invalid.json",
    ):
        assert not validator.is_valid(load_json(FIXTURES / name)), name


def test_generated_schema_enforces_uuid4_and_utc_wire_rules() -> None:
    schema = load_json(SCHEMA)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    valid_case = load_json(FIXTURES / "case.valid.json")
    assert isinstance(valid_case, dict)

    invalid_uuid = deepcopy(valid_case)
    invalid_uuid["case_id"] = "11111111-1111-1111-8111-111111111111"
    assert not validator.is_valid(invalid_uuid)

    non_utc = deepcopy(valid_case)
    non_utc["created_at"] = "2026-08-22T13:00:00+01:00"
    assert not validator.is_valid(non_utc)

    naive = deepcopy(valid_case)
    naive["created_at"] = "2026-08-22T12:00:00"
    assert not validator.is_valid(naive)


def test_generated_types_accept_exact_representative_fixture() -> None:
    subprocess.run(
        ["pnpm", "exec", "tsc", "--noEmit", "-p", "contracts/typescript/tsconfig.json"],
        cwd=ROOT,
        check=True,
    )


def test_generated_artifacts_have_no_drift() -> None:
    subprocess.run(
        [sys.executable, "scripts/generate_contracts.py", "--check"],
        cwd=ROOT,
        check=True,
    )
