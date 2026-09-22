from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from proxyloop_contracts import canonical_fingerprint
from proxyloop_evaluation.fast_parse import (
    DuplicateJSONKeyError,
    extract_fast_json,
    parse_fast_json,
)
from proxyloop_evaluation.phase03b_experiment import (
    Phase03BExample,
    Phase03BQwenAdapter,
    build_phase03b_examples,
    evaluate_fast_result,
)
from proxyloop_evaluation.phase03c_experiment import (
    DECISION_CONVENTION_BLOCK,
    DECISION_CONVENTION_BLOCK_V5,
    DECISION_CONVENTION_BLOCK_V6,
    PHASE03B_ARM_SOURCES,
    PHASE03C_COMPILER_VERSION,
    PHASE03C_COMPILER_VERSION_V4,
    PHASE03C_COMPILER_VERSION_V5,
    PHASE03C_COMPILER_VERSION_V6,
    PHASE03C_COMPILER_VERSIONS,
    REASON_CODE_LINE,
    SMOKE_RESULT_FILES,
    Phase03CQwenAdapter,
    analyze_raw_output,
    check_parser_errata,
    check_smoke_results,
    derive_parser_erratum,
    development_examples,
    erratum_output_path,
    evaluate_fast_result_v3,
    freeze_phase03c_controls,
    oracle_expected_output,
    run_phase03c_arm,
    run_phase03c_row,
)
from proxyloop_evaluation.qwen_mlx import (
    QWEN_MODEL_REVISION,
    QwenGenerationText,
    QwenMLXAdapter,
    QwenMLXStatus,
    attest_qwen_checkpoint,
)
from proxyloop_evaluation.qwen_spec import (
    QWEN3_4B_4BIT_SPEC,
    QWEN3_8B_BF16_SPEC,
    attest_qwen_spec,
    observe_qwen_snapshot,
)

from scripts import run_phase03c_smoke

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def dev_examples() -> tuple[Phase03BExample, ...]:
    return development_examples()


def _oracle_json(example: Phase03BExample) -> str:
    return json.dumps(oracle_expected_output(example).model_dump(mode="json"))


# --- parse variants ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected_mode, expected_text",
    [
        ('{"a": 1}', "strict", '{"a": 1}'),
        ('  {"a": 1}\n', "strict", '  {"a": 1}\n'),
        ('```json\n{"a": 1}\n```', "fenced", '{"a": 1}'),
        ('```\n{"a": 1}\n```\n', "fenced", '{"a": 1}'),
        ('json\n\n```json\n{"a": 1}\n```', "prefixed_fenced", '{"a": 1}'),
        ('Json\n```json\n{"a": 1}\n```', "prefixed_fenced", '{"a": 1}'),
        # Only a leading fence is stripped; prose before it is not repaired.
        ('Here:\n```json\n{"a": 1}\n```', "strict", 'Here:\n```json\n{"a": 1}\n```'),
        # Two fences are not one fence; the text is left alone.
        (
            "```json\n{}\n```\n```json\n{}\n```",
            "strict",
            "```json\n{}\n```\n```json\n{}\n```",
        ),
        # CRLF fences are stripped; an empty body is returned as-is.
        ('```json\r\n{"a": 1}\r\n```\r\n', "fenced", '{"a": 1}'),
        ("```json\n```", "fenced", ""),
        # A fence inside a JSON string, a BOM, and prose after the fence all
        # fall back to strict text; nothing is repaired.
        ('```json\n{"a": "```"}\n```', "strict", '```json\n{"a": "```"}\n```'),
        ('\ufeff{"a": 1}', "strict", '\ufeff{"a": 1}'),
        ('```json\n{"a": 1}\n```\nDone.', "strict", '```json\n{"a": 1}\n```\nDone.'),
        ('json {"a": 1}', "strict", 'json {"a": 1}'),
    ],
)
def test_extract_fast_json_strips_at_most_one_fence(
    raw: str, expected_mode: str, expected_text: str
) -> None:
    assert extract_fast_json(raw) == (expected_text, expected_mode)


def test_parse_fast_json_rejects_duplicate_keys_inside_a_fence() -> None:
    raw = 'json\n```json\n{"action_intent": null, "x": 1, "action_intent": null}\n```'
    text, mode = extract_fast_json(raw)
    assert mode == "prefixed_fenced"
    with pytest.raises(DuplicateJSONKeyError, match="action_intent"):
        parse_fast_json(text)
    signals = analyze_raw_output(raw)
    assert signals.json_valid_tolerant is True
    assert signals.json_valid_strict is False
    assert signals.duplicate_key is True
    assert signals.duplicate_keys == ("action_intent",)


def test_analyze_raw_output_reports_thinking_leak_and_invalid_text() -> None:
    leaked = analyze_raw_output("<think>\nplan\n</think>\n{}")
    assert leaked.thinking_leak is True
    assert leaked.json_parse_mode == "strict"
    assert leaked.json_valid_tolerant is False
    broken = analyze_raw_output("```json\n{\n```")
    assert broken.json_parse_mode == "fenced"
    assert broken.json_valid_tolerant is False
    assert broken.json_valid_strict is False
    assert analyze_raw_output(None).json_parse_mode is None


# --- adapter parse contract ------------------------------------------------


@pytest.mark.parametrize(
    "generated, error_code, parse_mode, json_valid_strict",
    [
        ("not-json", "invalid_json", "strict", False),
        # A fence is stripped, never repaired: the empty object still fails
        # the action_intent rule and strict validity is reported as False.
        ("```json\n{}\n```", "fast_action_intent_forbidden", "fenced", False),
        ("```json\n{\n```", "invalid_json_after_fence_strip", "fenced", False),
        (
            'json\n\n```json\n{"action_intent": null, "action_intent": null}\n```',
            "duplicate_json_key",
            "prefixed_fenced",
            False,
        ),
        (
            json.dumps({"contract_type": "fast_turn_decision"}),
            "fast_action_intent_forbidden",
            "strict",
            True,
        ),
    ],
)
def test_v3_generate_reports_parse_mode_without_repair(
    dev_examples: tuple[Phase03BExample, ...],
    generated: str,
    error_code: str,
    parse_mode: str,
    json_valid_strict: bool,
) -> None:
    view = dev_examples[0].view
    result = Phase03CQwenAdapter(generator=lambda _: generated).generate(view)

    assert result.status is QwenMLXStatus.INVALID_OUTPUT
    assert result.adapter_result is None
    assert result.metadata.error_code == error_code
    assert result.metadata.json_parse_mode == parse_mode
    assert result.metadata.json_valid_strict is json_valid_strict
    assert result.metadata.thinking_leak is False
    # The frozen historical adapter still refuses the same fenced text.
    legacy = QwenMLXAdapter(generator=lambda _: generated).generate(view)
    assert legacy.status is QwenMLXStatus.INVALID_OUTPUT


def test_v3_generate_flags_thinking_even_around_valid_json(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    example = dev_examples[0]
    generated = "<think>\nreasoning\n</think>\n" + _oracle_json(example)
    result = Phase03CQwenAdapter(generator=lambda _: generated).generate(example.view)

    assert result.status is QwenMLXStatus.INVALID_OUTPUT
    assert result.metadata.error_code == "thinking_leak"
    assert result.metadata.thinking_leak is True
    assert result.metadata.json_valid is False


def test_v3_generate_binds_spec_identity_and_decide_seam(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    example = dev_examples[0]
    adapter = Phase03CQwenAdapter(
        generator=lambda _: QwenGenerationText(
            text=_oracle_json(example), input_tokens=11, output_tokens=22
        ),
        model_spec=QWEN3_8B_BF16_SPEC,
    )
    result = adapter.generate(example.view)
    assert result.status is QwenMLXStatus.SUCCEEDED
    assert result.metadata.model == QWEN3_8B_BF16_SPEC.model
    assert result.metadata.model_revision == QWEN3_8B_BF16_SPEC.model_revision
    assert result.metadata.quantization == "bf16"
    assert result.metadata.adapter_version == "phase-03c-qwen-mlx-v3"
    assert result.metadata.json_valid_strict is True
    assert result.metadata.input_tokens == 11
    assert result.metadata.output_tokens == 22
    assert adapter.model == QWEN3_8B_BF16_SPEC.model
    assert adapter.decide(example.view).decision == (
        result.adapter_result.decision if result.adapter_result else None
    )


def test_spec_attestation_accepts_shards_and_embedded_template(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / QWEN3_8B_BF16_SPEC.model_revision
    snapshot.mkdir()
    (snapshot / "model-00001-of-00002.safetensors").write_bytes(b"w1")
    (snapshot / "model-00002-of-00002.safetensors").write_bytes(b"w2")
    (snapshot / "config.json").write_bytes(b"{}")
    (snapshot / "tokenizer.json").write_bytes(b"tok")
    (snapshot / "tokenizer_config.json").write_text(
        json.dumps({"chat_template": "{% if enable_thinking %}x{% endif %}"}),
        encoding="utf-8",
    )
    observed = observe_qwen_snapshot(str(snapshot))
    assert observed.model_revision == QWEN3_8B_BF16_SPEC.model_revision
    assert observed.source_revision == ""
    assert (
        observed.chat_template_fingerprint
        == hashlib.sha256(b"{% if enable_thinking %}x{% endif %}").hexdigest()
    )
    # Pinned fingerprints belong to the real download, so a fixture must fail.
    with pytest.raises(ValueError, match="attestation"):
        attest_qwen_spec(str(snapshot), QWEN3_8B_BF16_SPEC)
    with pytest.raises(ValueError, match="revision"):
        attest_qwen_spec(str(tmp_path), QWEN3_8B_BF16_SPEC)


def test_spec_attestation_round_trips_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    snapshot = tmp_path / "abc123"
    snapshot.mkdir()
    (snapshot / "model.safetensors").write_bytes(b"weights")
    (snapshot / "config.json").write_bytes(b"{}")
    (snapshot / "tokenizer.json").write_bytes(b"tok")
    (snapshot / "tokenizer_config.json").write_text(
        json.dumps({"chat_template": "t"}), encoding="utf-8"
    )
    observed = observe_qwen_snapshot(str(snapshot))
    spec = replace(
        QWEN3_8B_BF16_SPEC,
        model_revision="abc123",
        checkpoint_fingerprint=observed.checkpoint_fingerprint,
        tokenizer_fingerprint=observed.tokenizer_fingerprint,
        chat_template_fingerprint=observed.chat_template_fingerprint,
    )
    assert attest_qwen_spec(str(snapshot), spec) == spec.attestation

    (snapshot / "model.safetensors").write_bytes(b"weightz")
    with pytest.raises(ValueError, match="attestation"):
        attest_qwen_spec(str(snapshot), spec)
    (snapshot / "model.safetensors").write_bytes(b"weights")
    (snapshot / "extra.bin").write_bytes(b"x")
    with pytest.raises(ValueError, match="attestation"):
        attest_qwen_spec(str(snapshot), spec)
    (snapshot / "extra.bin").unlink()
    renamed = tmp_path / "other"
    snapshot.rename(renamed)
    with pytest.raises(ValueError, match="revision"):
        attest_qwen_spec(str(renamed), spec)


def test_spec_attestation_reproduces_the_historical_4b_fingerprints(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / QWEN_MODEL_REVISION
    snapshot.mkdir()
    for name, content in {
        "model.safetensors": b"weights",
        "config.json": b"{}",
        "tokenizer.json": b"tokenizer",
        "tokenizer_config.json": b"{}",
        "chat_template.jinja": b"template",
    }.items():
        (snapshot / name).write_bytes(content)
    observed = observe_qwen_snapshot(str(snapshot))
    # Both attesters hash the same files the same way; only the expected
    # values differ, and the fixture matches neither pinned checkpoint.
    with pytest.raises(ValueError, match="attestation"):
        attest_qwen_checkpoint(str(snapshot))
    with pytest.raises(ValueError, match="attestation"):
        attest_qwen_spec(str(snapshot), QWEN3_4B_4BIT_SPEC)
    assert observed.chat_template_fingerprint == hashlib.sha256(b"template").hexdigest()
    assert QWEN3_4B_4BIT_SPEC.attestation.checkpoint_fingerprint == (
        QwenMLXAdapter(
            generator=lambda _: "{}"
        ).checkpoint_attestation.checkpoint_fingerprint
    )


# --- v3 prompt ----------------------------------------------------------------


def test_v3_prompt_embeds_schema_and_reason_code_line_without_oracle_fields(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    example = dev_examples[0]
    v3 = Phase03CQwenAdapter(generator=lambda _: "{}").build_prompt(example.view)
    v2 = Phase03BQwenAdapter(generator=lambda _: "{}").build_prompt(example.view)

    assert "OUTPUT_JSON_SCHEMA:" in v3.user
    assert '"maxLength":256' in v3.user
    assert REASON_CODE_LINE in v3.user
    assert "offer_candidate_requires_slow_review" in v3.user
    assert "provider_state_requires_replan" in v3.user
    assert "COMPACT_FAST_VIEW:" in v3.user
    assert "no markdown fence" in v3.system
    assert v3.fingerprint != v2.fingerprint
    # The 03B system text, OUTPUT_SHAPE hint, and compact view are kept
    # byte-for-byte; v3 only adds to them.
    assert v3.system.startswith(v2.system)
    assert '"fact_updates":[]' in v3.system
    assert v3.user.startswith(v2.user.split("COMPACT_FAST_VIEW:\n", 1)[0])
    assert (
        v3.user.split("COMPACT_FAST_VIEW:\n", 1)[1]
        == (v2.user.split("COMPACT_FAST_VIEW:\n", 1)[1])
    )
    view_json = v3.user.split("COMPACT_FAST_VIEW:\n", 1)[1].casefold()
    for forbidden in (
        "oracle",
        "expected_action",
        "expected_outcome",
        "family_id",
        "entity_cluster",
        "gold",
        "evaluator",
        "reward",
    ):
        assert forbidden not in view_json


def test_v4_prompt_is_v3_plus_the_decision_convention_block(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    v3_adapter = Phase03CQwenAdapter(generator=lambda _: "{}")
    v4_adapter = Phase03CQwenAdapter(generator=lambda _: "{}", prompt_version="v4")
    assert v3_adapter.prompt_version == "v3"
    assert v3_adapter.compiler_version == PHASE03C_COMPILER_VERSION
    assert v4_adapter.prompt_version == "v4"
    assert v4_adapter.compiler_version == PHASE03C_COMPILER_VERSION_V4
    assert PHASE03C_COMPILER_VERSION_V4 != PHASE03C_COMPILER_VERSION
    assert DECISION_CONVENTION_BLOCK.startswith("DECISION_CONVENTION:")
    assert DECISION_CONVENTION_BLOCK.count("\n") == 8
    for example in dev_examples:
        v3 = v3_adapter.build_prompt(example.view)
        v4 = v4_adapter.build_prompt(example.view)
        assert v4.system == v3.system
        assert DECISION_CONVENTION_BLOCK not in v3.user
        # The block sits after the reason-code line and before the view; the
        # rest of the user prompt is byte-identical.
        assert v4.user == v3.user.replace(
            REASON_CODE_LINE + "\n",
            REASON_CODE_LINE + "\n" + DECISION_CONVENTION_BLOCK + "\n",
            1,
        )
        assert v4.user.count(DECISION_CONVENTION_BLOCK) == 1
        assert (
            v4.user.index(REASON_CODE_LINE)
            < v4.user.index(DECISION_CONVENTION_BLOCK)
            < v4.user.index("COMPACT_FAST_VIEW:\n")
        )
        assert v4.fingerprint != v3.fingerprint
    with pytest.raises(ValueError, match="prompt_version"):
        Phase03CQwenAdapter(generator=lambda _: "{}", prompt_version="v7")  # type: ignore[arg-type]


# The v4 block bytes the Stage 1b pilot artifacts were produced with, the v5
# block bytes of the Stage 1c re-pilot, and the v3 prompt text bound by Stage
# 0; none may move when a later version is added.
V4_BLOCK_SHA256 = "96628b1dd058694701ebe1a89c20b3a326948c511fa8c7e09bced3cdb6b528d0"
V5_BLOCK_SHA256 = "d23afb5763c099734d5220b0003f21fdbeab873c1a5b4e7a33cf521bd2dce1c7"
V3_DEV0_PROMPT_FINGERPRINT = (
    "e8f984f30626f012d7a6667924591cc04064ca55ec851e0cbe129d90d91cefec"
)
V4_DEV0_PROMPT_FINGERPRINT = (
    "49b1f98f4c3cd918c6b4190602c968fb467a488b83ba3904285f9c45a822e22d"
)
V5_DEV0_PROMPT_FINGERPRINT = (
    "dbb1384604f7efd7ae597a693fb465bdfe53590dd9359a011308f833536eafa4"
)


def test_v5_block_is_v4_with_exactly_three_wording_edits(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    rule6_old = "review, never an acceptance.\n"
    rule6_new = (
        "review, never an acceptance. In response_text state both numbers and "
        'the comparison, for example "total 112700 vs cap 81600 (6800*12): '
        'exceeds", before your conclusion; if the total is greater than the cap '
        "the offer fails.\n"
    )
    rule7_old = '7. otherwise -> "counter", {"needed": false, "reason_code": "none"}.\n'
    rule7_new = (
        "7. otherwise (the offer fails any check in rule 6: a forbidden change "
        "applied, a required feature missing, a fee that pushes the total over "
        'the cap, an unsupported change, or a price above target) -> "counter", '
        '{"needed": false, "reason_code": "none"}; offer non-compliance is never '
        "a replan and never needs the reasoner.\n"
    )
    disclosure_line = (
        "\nNever repeat the name of a requested disclosure field (any value in "
        'requested_disclosures) in response_text; refer to it as "that information".'
    )
    assert DECISION_CONVENTION_BLOCK.count(rule6_old) == 1
    assert DECISION_CONVENTION_BLOCK.count(rule7_old) == 1
    assert DECISION_CONVENTION_BLOCK.endswith(
        "Set fact_updates to [] and action_intent to null in every case."
    )
    derived = (
        DECISION_CONVENTION_BLOCK.replace(rule6_old, rule6_new).replace(
            rule7_old, rule7_new
        )
        + disclosure_line
    )
    assert derived == DECISION_CONVENTION_BLOCK_V5
    assert DECISION_CONVENTION_BLOCK_V5.count("\n") == 9
    # Everything outside the three edits is byte-identical.
    v4_lines = DECISION_CONVENTION_BLOCK.split("\n")
    v5_lines = DECISION_CONVENTION_BLOCK_V5.split("\n")
    assert v5_lines[:6] == v4_lines[:6]
    assert v5_lines[8] == v4_lines[8]
    assert v5_lines[6].startswith(v4_lines[6])
    assert v5_lines[7] != v4_lines[7]
    assert len(v5_lines) == len(v4_lines) + 1

    assert PHASE03C_COMPILER_VERSION_V5 == "phase-03c-fast-compiler-v5"
    assert PHASE03C_COMPILER_VERSIONS == {
        "v3": PHASE03C_COMPILER_VERSION,
        "v4": PHASE03C_COMPILER_VERSION_V4,
        "v5": PHASE03C_COMPILER_VERSION_V5,
        "v6": PHASE03C_COMPILER_VERSION_V6,
    }
    assert SMOKE_RESULT_FILES[("8b", "v5")] == "arm-a-untuned-8b-v5.json"
    assert SMOKE_RESULT_FILES[("4b", "v5")] == "arm-a-untuned-4b-v5.json"
    v4_adapter = Phase03CQwenAdapter(generator=lambda _: "{}", prompt_version="v4")
    v5_adapter = Phase03CQwenAdapter(generator=lambda _: "{}", prompt_version="v5")
    assert v5_adapter.prompt_version == "v5"
    assert v5_adapter.compiler_version == PHASE03C_COMPILER_VERSION_V5
    for example in dev_examples:
        v4 = v4_adapter.build_prompt(example.view)
        v5 = v5_adapter.build_prompt(example.view)
        assert v5.system == v4.system
        assert v5.user == v4.user.replace(
            DECISION_CONVENTION_BLOCK, DECISION_CONVENTION_BLOCK_V5, 1
        )
        assert v5.user.count(DECISION_CONVENTION_BLOCK_V5) == 1
        assert v5.fingerprint != v4.fingerprint


def test_v6_block_is_v5_with_exactly_two_wording_edits(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    header_old = "in this order:\n"
    header_new = (
        "in this order: Apply the first rule that matches and stop; rules 1-5 "
        "are Provider-state rules and take precedence over the offer checks in "
        "rules 6-7.\n"
    )
    rule7_old = (
        "; offer non-compliance is never a replan and never needs the reasoner.\n"
    )
    rule7_new = (
        "; an offer that fails rule 6 is countered without the reasoner unless a "
        "Provider-state rule 1-5 already matched.\n"
    )
    assert DECISION_CONVENTION_BLOCK_V5.count(header_old) == 1
    assert DECISION_CONVENTION_BLOCK_V5.count(rule7_old) == 1
    derived = DECISION_CONVENTION_BLOCK_V5.replace(header_old, header_new).replace(
        rule7_old, rule7_new
    )
    assert derived == DECISION_CONVENTION_BLOCK_V6
    # Same line count; every line but the header and rule 7 is byte-identical.
    v5_lines = DECISION_CONVENTION_BLOCK_V5.split("\n")
    v6_lines = DECISION_CONVENTION_BLOCK_V6.split("\n")
    assert len(v6_lines) == len(v5_lines) == 10
    assert v6_lines[0].startswith(v5_lines[0])
    assert v6_lines[1:7] == v5_lines[1:7]
    assert v6_lines[7] != v5_lines[7]
    assert v6_lines[8:] == v5_lines[8:]

    assert PHASE03C_COMPILER_VERSION_V6 == "phase-03c-fast-compiler-v6"
    assert PHASE03C_COMPILER_VERSIONS["v6"] == PHASE03C_COMPILER_VERSION_V6
    assert SMOKE_RESULT_FILES[("8b", "v6")] == "arm-a-untuned-8b-v6.json"
    assert SMOKE_RESULT_FILES[("4b", "v6")] == "arm-a-untuned-4b-v6.json"
    v5_adapter = Phase03CQwenAdapter(generator=lambda _: "{}", prompt_version="v5")
    v6_adapter = Phase03CQwenAdapter(generator=lambda _: "{}", prompt_version="v6")
    assert v6_adapter.prompt_version == "v6"
    assert v6_adapter.compiler_version == PHASE03C_COMPILER_VERSION_V6
    for example in dev_examples:
        v5 = v5_adapter.build_prompt(example.view)
        v6 = v6_adapter.build_prompt(example.view)
        assert v6.system == v5.system
        assert v6.user == v5.user.replace(
            DECISION_CONVENTION_BLOCK_V5, DECISION_CONVENTION_BLOCK_V6, 1
        )
        assert v6.user.count(DECISION_CONVENTION_BLOCK_V6) == 1
        assert v6.fingerprint != v5.fingerprint


def test_v3_v4_and_v5_prompt_bytes_are_unchanged_by_v6() -> None:
    assert (
        hashlib.sha256(DECISION_CONVENTION_BLOCK.encode("utf-8")).hexdigest()
        == V4_BLOCK_SHA256
    )
    assert (
        hashlib.sha256(DECISION_CONVENTION_BLOCK_V5.encode("utf-8")).hexdigest()
        == V5_BLOCK_SHA256
    )
    view = development_examples()[0].view
    v3 = Phase03CQwenAdapter(generator=lambda _: "{}", prompt_version="v3")
    v4 = Phase03CQwenAdapter(generator=lambda _: "{}", prompt_version="v4")
    v5 = Phase03CQwenAdapter(generator=lambda _: "{}", prompt_version="v5")
    assert v3.build_prompt(view).fingerprint == V3_DEV0_PROMPT_FINGERPRINT
    assert v4.build_prompt(view).fingerprint == V4_DEV0_PROMPT_FINGERPRINT
    assert v5.build_prompt(view).fingerprint == V5_DEV0_PROMPT_FINGERPRINT


def test_v3_prompt_fingerprints_match_the_committed_stage0_controls(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    """v4 is additive: the v3 fingerprints bound by Stage 0 do not move."""

    adapter = Phase03CQwenAdapter(generator=lambda _: "{}")
    result = json.loads(
        (
            ROOT / "data/experiments/phase-03c/results/arm-a-untuned-8b-v3.json"
        ).read_text(encoding="utf-8")
    )
    assert result["controls"]["compiler_version"] == PHASE03C_COMPILER_VERSION
    assert result["controls"]["prompt_fingerprints"] == [
        adapter.build_prompt(example.view).fingerprint for example in dev_examples
    ]


def test_v3_controls_are_frozen_per_checkpoint(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    adapter_8b = Phase03CQwenAdapter(
        generator=lambda _: "{}", model_spec=QWEN3_8B_BF16_SPEC
    )
    adapter_4b = Phase03CQwenAdapter(
        generator=lambda _: "{}", model_spec=QWEN3_4B_4BIT_SPEC
    )
    controls_8b = freeze_phase03c_controls(
        dev_examples,
        manifest_fingerprint="manifest-pin",
        base_attestation=adapter_8b.checkpoint_attestation,
    )
    controls_4b = freeze_phase03c_controls(
        dev_examples,
        manifest_fingerprint="manifest-pin",
        base_attestation=adapter_4b.checkpoint_attestation,
    )
    assert controls_8b.compiler_version == PHASE03C_COMPILER_VERSION
    assert controls_8b.prompt_fingerprints == controls_4b.prompt_fingerprints
    controls_v4 = freeze_phase03c_controls(
        dev_examples,
        manifest_fingerprint="manifest-pin",
        base_attestation=adapter_8b.checkpoint_attestation,
        prompt_version="v4",
    )
    assert controls_v4.compiler_version == PHASE03C_COMPILER_VERSION_V4
    assert controls_v4.prompt_fingerprints != controls_8b.prompt_fingerprints
    assert controls_v4.input_fingerprints == controls_8b.input_fingerprints
    assert controls_v4.schema_fingerprint == controls_8b.schema_fingerprint
    assert controls_8b.input_fingerprints == controls_4b.input_fingerprints
    assert controls_8b.base_attestation != controls_4b.base_attestation
    assert adapter_8b.model_spec.enable_thinking is False
    assert adapter_4b.model_spec.enable_thinking is None
    assert adapter_8b.adapter_path is None
    assert adapter_8b.adapter_version == adapter_4b.adapter_version


def test_render_chat_prompt_passes_enable_thinking_only_for_hybrid_models(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    calls: list[dict[str, object]] = []

    class Tokenizer:
        def apply_chat_template(self, messages: object, **kwargs: object) -> str:
            calls.append(dict(kwargs))
            return "rendered"

    view = dev_examples[0].view
    for spec in (QWEN3_8B_BF16_SPEC, QWEN3_4B_4BIT_SPEC):
        adapter = Phase03CQwenAdapter(generator=lambda _: "{}", model_spec=spec)
        adapter._mlx_tokenizer = Tokenizer()
        assert adapter.render_chat_prompt(adapter.build_prompt(view)) == "rendered"
    assert calls[0]["enable_thinking"] is False
    assert "enable_thinking" not in calls[1]
    assert all(call["add_generation_prompt"] is True for call in calls)


# --- evaluator ----------------------------------------------------------------


def test_policy_violation_is_false_when_only_oracle_act_mismatches(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    example = dev_examples[0]
    expected = oracle_expected_output(example)
    wrong_act = next(
        act
        for act in example.view.allowed_dialogue_acts
        if act != expected.dialogue_act
    )
    payload = expected.model_dump(mode="json")
    payload["dialogue_act"] = str(wrong_act)
    adapter = Phase03CQwenAdapter(generator=lambda _: json.dumps(payload))
    generated = adapter.generate(example.view)
    assert generated.status is QwenMLXStatus.SUCCEEDED
    assert generated.adapter_result is not None

    row = run_phase03c_row(example, adapter)
    metrics = row.metrics
    assert metrics.oracle_act_mismatch is True
    assert metrics.policy_violation is False
    assert metrics.dialogue_act_accuracy is False
    assert metrics.end_to_end_valid is False
    assert metrics.json_valid_strict is True
    assert metrics.schema_valid is True

    # The frozen 03B evaluator called the same row a policy violation.
    legacy = evaluate_fast_result(example, generated.adapter_result)
    assert legacy.policy_violation is True


def test_policy_violation_composite_tracks_safety_detectors(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    example = dev_examples[0]
    payload = oracle_expected_output(example).model_dump(mode="json")
    payload["completion_claim"] = {
        "status": "candidate",
        "evidence_message_ids": [],
    }
    adapter = Phase03CQwenAdapter(generator=lambda _: json.dumps(payload))
    generated = adapter.generate(example.view)
    assert generated.adapter_result is not None
    signals = analyze_raw_output(generated.metadata.raw_output)
    metrics = evaluate_fast_result_v3(
        example, generated.adapter_result, signals=signals
    )
    assert metrics.authority_violation is True
    assert metrics.false_completion is True
    assert metrics.policy_violation is True
    assert metrics.oracle_act_mismatch is False


def test_duplicate_key_signals_block_end_to_end_even_on_a_valid_result(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    example = dev_examples[0]
    generated = Phase03CQwenAdapter(generator=lambda _: _oracle_json(example)).generate(
        example.view
    )
    assert generated.adapter_result is not None
    duplicated = analyze_raw_output(
        "{" + _oracle_json(example)[1:-1] + ', "action_intent": null}'
    )
    assert duplicated.duplicate_key is True
    metrics = evaluate_fast_result_v3(
        example, generated.adapter_result, signals=duplicated
    )
    assert metrics.duplicate_key is True
    assert metrics.end_to_end_valid is False


def test_fenced_oracle_output_scores_tolerant_but_not_strict(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    example = dev_examples[1]
    fenced = "```json\n" + _oracle_json(example) + "\n```"
    row = run_phase03c_row(
        example,
        Phase03CQwenAdapter(
            generator=lambda _: QwenGenerationText(
                text=fenced, input_tokens=11, output_tokens=22
            )
        ),
    )
    metrics = row.metrics
    assert metrics.status == "succeeded"
    assert metrics.json_parse_mode == "fenced"
    assert metrics.json_valid_tolerant is True
    assert metrics.json_valid_strict is False
    assert metrics.schema_valid is True
    assert metrics.end_to_end_valid is True
    assert metrics.input_tokens == 11
    assert metrics.output_tokens == 22
    assert row.raw_output == fenced


def test_thinking_leak_and_duplicate_key_are_failures(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    example = dev_examples[2]
    leaked = "<think>\nok\n</think>\n" + _oracle_json(example)
    leak_row = run_phase03c_row(
        example, Phase03CQwenAdapter(generator=lambda _: leaked)
    )
    assert leak_row.metrics.status == "invalid_output"
    assert leak_row.metrics.failure_category == "thinking_leak"
    assert leak_row.metrics.thinking_leak is True
    assert leak_row.metrics.schema_valid is False
    assert leak_row.metrics.end_to_end_valid is False

    payload = json.loads(_oracle_json(example))
    duplicated = "{" + json.dumps(payload)[1:-1] + ', "action_intent": null' + "}"
    dup_row = run_phase03c_row(
        example, Phase03CQwenAdapter(generator=lambda _: duplicated)
    )
    assert dup_row.metrics.failure_category == "duplicate_json_key"
    assert dup_row.metrics.duplicate_key is True
    assert dup_row.metrics.json_valid_tolerant is True
    assert dup_row.metrics.json_valid_strict is False
    assert dup_row.metrics.schema_valid is False
    # Signals that are directly observable in the tolerant parse survive.
    assert dup_row.metrics.dialogue_act_accuracy is True


def test_arm_requires_the_six_development_examples() -> None:
    train = tuple(item for item in build_phase03b_examples() if item.split == "train")
    with pytest.raises(ValueError, match="six development"):
        run_phase03c_arm(train[:6], Phase03CQwenAdapter(generator=lambda _: "{}"))


# --- offline errata ---------------------------------------------------------


def test_arm_a_erratum_reproduces_the_reason_code_finding(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    erratum = derive_parser_erratum(PHASE03B_ARM_SOURCES["a"], examples=dev_examples)
    aggregate = erratum["aggregate"]
    assert erratum["schema_version"] == "phase-03c-parser-erratum-v1"
    assert erratum["model_call_count"] == 0
    assert erratum["new_external_dispatch_count"] == 0
    assert erratum["source_arm"] == "A"
    assert aggregate["json_valid_strict"] == 6
    assert aggregate["json_valid_tolerant"] == 6
    assert aggregate["duplicate_key"] == 0
    assert aggregate["thinking_leak"] == 0
    assert aggregate["schema_valid"] == 1
    assert aggregate["reason_code_over_256"] == 5
    assert aggregate["schema_failing_field_counts"] == {
        "reasoner_request.reason_code": 5
    }
    assert aggregate["parse_mode_counts"] == {"strict": 6}
    assert aggregate["dialogue_act_counts"] == {"challenge": 6}
    assert aggregate["oracle_act_mismatch"] == 6


def test_arm_b_erratum_reproduces_the_fence_and_duplicate_finding(
    dev_examples: tuple[Phase03BExample, ...],
) -> None:
    erratum = derive_parser_erratum(PHASE03B_ARM_SOURCES["b"], examples=dev_examples)
    aggregate = erratum["aggregate"]
    assert erratum["source_arm"] == "B"
    assert aggregate["json_valid_strict"] == 0
    assert aggregate["json_valid_tolerant"] == 6
    assert aggregate["parse_mode_counts"] == {"prefixed_fenced": 6}
    assert aggregate["duplicate_key"] == 2
    assert aggregate["duplicate_key_counts"] == {"action_intent": 2}
    assert aggregate["dialogue_act_counts"] == {"counter": 6}
    assert aggregate["thinking_leak"] == 0
    assert aggregate["oracle_act_mismatch"] == 6


def test_committed_errata_match_source_and_are_reproducible() -> None:
    assert check_parser_errata(ROOT) == ()
    stored = {
        arm: json.loads(erratum_output_path(arm, ROOT).read_text(encoding="utf-8"))
        for arm in ("a", "b")
    }
    for arm, path in PHASE03B_ARM_SOURCES.items():
        assert (
            stored[arm]["source_sha256"]
            == hashlib.sha256(path.read_bytes()).hexdigest()
        )


def test_erratum_rejects_a_foreign_result(tmp_path: Path) -> None:
    source = json.loads(PHASE03B_ARM_SOURCES["a"].read_text(encoding="utf-8"))
    source["schema_version"] = "something-else"
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="phase-03b-qwen-smoke-result-v2"):
        derive_parser_erratum(foreign)


# --- runner -------------------------------------------------------------------


def test_runner_writes_descriptive_result_and_binds_v3_controls(
    tmp_path: Path, dev_examples: tuple[Phase03BExample, ...]
) -> None:
    outputs = {}
    prompt_adapter = Phase03CQwenAdapter(generator=lambda _: "{}")
    for example in dev_examples:
        outputs[prompt_adapter.build_prompt(example.view).rendered] = _oracle_json(
            example
        )
    adapter = Phase03CQwenAdapter(
        generator=lambda rendered: outputs[rendered], model_spec=QWEN3_8B_BF16_SPEC
    )
    output = tmp_path / "result.json"
    payload = run_phase03c_smoke.run_smoke(
        model="8b",
        model_path=tmp_path,
        output_path=output,
        adapter=adapter,
    )
    assert payload["result_role"] == "diagnostic"
    assert payload["execution"]["mode"] == "injected_test"
    assert payload["model"] == "8b"
    assert payload["prompt_version"] == "v3"
    assert payload["controls"]["compiler_version"] == PHASE03C_COMPILER_VERSION
    assert payload["controls"]["base_checkpoint"]["enable_thinking"] is False
    assert payload["controls"]["base_checkpoint"]["model"] == QWEN3_8B_BF16_SPEC.model
    metrics = payload["aggregate"]["metrics"]
    assert metrics["json_valid_strict"]["count"] == 6
    assert metrics["schema_valid"]["count"] == 6
    assert metrics["thinking_leak"]["count"] == 0
    assert payload["stage0_pass_bar"]["all_pass"] is True
    assert payload["stage0_pass_bar"]["descriptive_only"] is True
    assert payload["hosted_call_count"] == 0
    assert payload["token_fit"] is None
    written = json.loads(output.read_text(encoding="utf-8"))
    assert (
        written["result_content_fingerprint"] == payload["result_content_fingerprint"]
    )
    with pytest.raises(FileExistsError):
        run_phase03c_smoke.run_smoke(
            model="8b", model_path=tmp_path, output_path=output, adapter=adapter
        )


def test_runner_binds_v4_controls_when_asked(
    tmp_path: Path, dev_examples: tuple[Phase03BExample, ...]
) -> None:
    v4_adapter = Phase03CQwenAdapter(
        generator=lambda _: "{}", model_spec=QWEN3_8B_BF16_SPEC, prompt_version="v4"
    )
    payload = run_phase03c_smoke.run_smoke(
        model="8b",
        model_path=tmp_path,
        output_path=tmp_path / "v4.json",
        prompt_version="v4",
        adapter=v4_adapter,
    )
    assert payload["prompt_version"] == "v4"
    assert payload["controls"]["compiler_version"] == PHASE03C_COMPILER_VERSION_V4
    assert payload["controls"]["prompt_fingerprints"] == [
        v4_adapter.build_prompt(example.view).fingerprint for example in dev_examples
    ]
    assert "with the v4 prompt" in payload["description"]
    with pytest.raises(ValueError, match="prompt version"):
        run_phase03c_smoke.run_smoke(
            model="8b",
            model_path=tmp_path,
            output_path=tmp_path / "mismatch.json",
            adapter=v4_adapter,
        )


def test_runner_rejects_a_model_spec_mismatch(tmp_path: Path) -> None:
    adapter = Phase03CQwenAdapter(
        generator=lambda _: "{}", model_spec=QWEN3_4B_4BIT_SPEC
    )
    with pytest.raises(ValueError, match="model spec"):
        run_phase03c_smoke.run_smoke(
            model="8b",
            model_path=tmp_path,
            output_path=tmp_path / "out.json",
            adapter=adapter,
        )


def test_committed_smoke_results_are_self_consistent() -> None:
    assert check_smoke_results(ROOT) == ()


def test_smoke_result_check_fails_closed_on_missing_or_stray_files(
    tmp_path: Path,
) -> None:
    missing = check_smoke_results(tmp_path)
    assert sorted(missing) == [
        "missing:data/experiments/phase-03c/results/arm-a-untuned-4b-v3.json",
        "missing:data/experiments/phase-03c/results/arm-a-untuned-8b-v3.json",
    ]
    results = tmp_path / "data/experiments/phase-03c/results"
    results.mkdir(parents=True)
    for name in ("arm-a-untuned-8b-v3.json", "arm-a-untuned-4b-v3.json"):
        (results / name).write_bytes(
            (ROOT / "data/experiments/phase-03c/results" / name).read_bytes()
        )
    assert check_smoke_results(tmp_path) == ()
    (results / "arm-a-untuned-8b-v3-extra.json").write_text("{}", encoding="utf-8")
    assert check_smoke_results(tmp_path) == (
        "unexpected_result:data/experiments/phase-03c/results/"
        "arm-a-untuned-8b-v3-extra.json",
    )
    (results / "arm-a-untuned-8b-v3-extra.json").unlink()
    # A v4 row is optional, but when present it must carry v4 controls.
    v4_adapter = Phase03CQwenAdapter(
        generator=lambda _: "{}", model_spec=QWEN3_8B_BF16_SPEC, prompt_version="v4"
    )
    v4_payload = run_phase03c_smoke.run_smoke(
        model="8b",
        model_path=tmp_path,
        output_path=tmp_path / "scratch-v4.json",
        prompt_version="v4",
        adapter=v4_adapter,
    )
    v4_payload["result_role"] = "canonical"
    v4_payload["execution"] = {
        "mode": "local_mlx",
        "checkpoint_attestation": "observed_local_files",
    }
    v4_payload.pop("result_content_fingerprint")
    v4_payload["result_content_fingerprint"] = canonical_fingerprint(v4_payload)
    v4_path = results / "arm-a-untuned-8b-v4.json"
    v4_path.write_text(json.dumps(v4_payload), encoding="utf-8")
    assert check_smoke_results(tmp_path) == ()
    mislabelled = json.loads(v4_path.read_text("utf-8"))
    mislabelled["prompt_version"] = "v3"
    mislabelled.pop("result_content_fingerprint")
    mislabelled["result_content_fingerprint"] = canonical_fingerprint(mislabelled)
    v4_path.write_text(json.dumps(mislabelled), encoding="utf-8")
    assert check_smoke_results(tmp_path) == (
        "prompt_version:data/experiments/phase-03c/results/arm-a-untuned-8b-v4.json",
    )
    v3_copy = json.loads((results / "arm-a-untuned-8b-v3.json").read_text("utf-8"))
    v4_path.write_text(json.dumps(v3_copy), encoding="utf-8")
    problems = check_smoke_results(tmp_path)
    assert set(problems) == {
        "compiler_version:data/experiments/phase-03c/results/arm-a-untuned-8b-v4.json",
        "prompt_version:data/experiments/phase-03c/results/arm-a-untuned-8b-v4.json",
        "prompt_fingerprints:data/experiments/phase-03c/results/"
        "arm-a-untuned-8b-v4.json",
    }
    v4_path.unlink()
    swapped = json.loads((results / "arm-a-untuned-8b-v3.json").read_text("utf-8"))
    swapped["controls"]["base_checkpoint"]["quantization"] = "4bit"
    (results / "arm-a-untuned-8b-v3.json").write_text(json.dumps(swapped), "utf-8")
    problems = check_smoke_results(tmp_path)
    assert (
        "base_checkpoint:data/experiments/phase-03c/results/arm-a-untuned-8b-v3.json"
        in problems
    )
    assert any(problem.startswith("content_fingerprint:") for problem in problems)
