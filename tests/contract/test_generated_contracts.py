from __future__ import annotations

import json
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from proxyloop_contracts import validate_contract_json
from pydantic import ValidationError

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


CONTRACT_SET_1_1_VALID = (
    "strategy_packet.v1_0.valid.json",
    "strategy_packet.v1_1.valid.json",
    "model_trace.v1_1.valid.json",
    "execution_claim.valid.json",
    "completion_receipt.valid.json",
)
CONTRACT_SET_1_1_INVALID = (
    (
        "strategy_packet.v1_1-missing-basis.invalid.json",
        "planning_basis_fingerprint is required at schema_version 1.1",
    ),
    (
        "strategy_packet.v1_0-with-basis.invalid.json",
        "planning_basis_fingerprint is not part of schema_version 1.0",
    ),
    (
        "model_trace.v1_1-missing-role.invalid.json",
        "role is required at schema_version 1.1",
    ),
    (
        "model_trace.v1_0-with-role.invalid.json",
        "role is not part of schema_version 1.0",
    ),
    ("execution_claim.v1_0.invalid.json", "Input should be '1.1'"),
    (
        "execution_claim.command-without-fingerprint.invalid.json",
        "command_id and command_fingerprint travel together",
    ),
    ("completion_receipt.v1_0.invalid.json", "Input should be '1.1'"),
    ("case.v1_1.invalid.json", "Input should be '1.0'"),
)


@pytest.mark.parametrize("name", CONTRACT_SET_1_1_VALID)
def test_contract_set_1_1_valid_fixtures_pass_both_validators(name: str) -> None:
    validator = Draft202012Validator(load_json(SCHEMA), format_checker=FormatChecker())
    text = (FIXTURES / name).read_text(encoding="utf-8")

    validate_contract_json(text)
    validator.validate(json.loads(text))


@pytest.mark.parametrize(("name", "reason"), CONTRACT_SET_1_1_INVALID)
def test_contract_set_1_1_invalid_fixtures_fail_both_validators(
    name: str, reason: str
) -> None:
    validator = Draft202012Validator(load_json(SCHEMA), format_checker=FormatChecker())
    text = (FIXTURES / name).read_text(encoding="utf-8")

    with pytest.raises(ValidationError, match=re.escape(reason)):
        validate_contract_json(text)
    assert not validator.is_valid(json.loads(text)), name


@pytest.mark.parametrize(
    ("name", "key"),
    (
        ("strategy_packet.v1_0.valid.json", "planning_basis_fingerprint"),
        ("model_trace.v1_1.valid.json", "role"),
        ("model_trace.v1_1.valid.json", "reason_codes"),
        ("model_trace.v1_1.valid.json", "request_id"),
        ("model_trace.v1_1.valid.json", "input_pins"),
    ),
)
def test_a_null_1_1_key_in_a_1_0_document_fails_both_validators(
    name: str, key: str
) -> None:
    validator = Draft202012Validator(load_json(SCHEMA), format_checker=FormatChecker())
    document = load_json(FIXTURES / name)
    assert isinstance(document, dict)
    document = {
        k: v
        for k, v in document.items()
        if k not in {"role", "reason_codes", "request_id", "input_pins"}
    }
    document["schema_version"] = "1.0"
    assert validator.is_valid(document)
    validate_contract_json(json.dumps(document))

    document[key] = None
    with pytest.raises(ValidationError, match=r"not part of schema_version 1\.0"):
        validate_contract_json(json.dumps(document))
    assert not validator.is_valid(document)


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
