from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from proxyloop_contracts import (
    Case,
    DialogueAct,
    EvidenceType,
    FastModelView,
    ModelInputPins,
    PlanningBasis,
    StrategyPacket,
)
from proxyloop_contracts.contracts import (
    CompletionClaim,
    EvidenceRequirement,
    ReasonerRequest,
    planning_basis_fingerprint,
)
from proxyloop_evaluation import qwen_mlx
from proxyloop_evaluation.fast_output import FastModelOutput
from proxyloop_evaluation.qwen_mlx import (
    QWEN_MLX_MODEL,
    QWEN_MODEL_REVISION,
    QWEN_RUN_LABEL,
    QWEN_SOURCE_LINEAGE,
    QwenGenerationText,
    QwenMLXAdapter,
    QwenMLXStatus,
    QwenMLXUnavailableError,
    attest_qwen_checkpoint,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.fromisoformat("2026-08-22T12:00:00+00:00")
CASE_ID = UUID("11111111-1111-4111-8111-111111111111")
STRATEGY_ID = UUID("99999999-9999-4999-8999-999999999999")


def _view() -> FastModelView:
    case = Case.model_validate_json(
        (ROOT / "tests" / "fixtures" / "case.valid.json").read_text(encoding="utf-8")
    )
    strategy = StrategyPacket(
        contract_type="strategy_packet",
        schema_version="1.0",
        revision=2,
        strategy_id=STRATEGY_ID,
        case_id=case.case_id,
        case_revision=case.revision,
        fact_ledger_revision=1,
        created_at=NOW,
        expires_at=datetime.fromisoformat("2026-08-23T12:00:00+00:00"),
        primary_objective=case.goal.desired_outcome,
        current_subgoal="Review the latest provider message.",
        hard_constraint_ids=(case.constraints[0].constraint_id,),
        ranked_preference_ids=(),
        allowed_disclosures=case.delegated_authority.allowed_disclosures,
        approval_required_disclosures=(),
        concession_ladder=("Keep hard constraints unchanged.",),
        fallback_outcomes=("Ask the consumer for clarification.",),
        required_completion_evidence=(
            EvidenceRequirement(
                evidence_type=EvidenceType.CONFIRMATION,
                description="A provider confirmation is required.",
            ),
        ),
        escalation_conditions=("The provider changes a material term.",),
        replan_conditions=("The current offer expires.",),
    )
    fingerprints = {
        "goal_fingerprint": "0" * 64,
        "constraints_fingerprint": "1" * 64,
        "delegated_authority_fingerprint": "2" * 64,
        "verified_facts_fingerprint": "3" * 64,
        "material_offers_fingerprint": "4" * 64,
        "approval_state_fingerprint": "5" * 64,
        "provider_config_fingerprint": "6" * 64,
        "capability_manifest_fingerprint": "7" * 64,
    }
    basis = PlanningBasis(
        contract_type="planning_basis",
        schema_version="1.0",
        revision=1,
        **fingerprints,
        planning_basis_fingerprint=planning_basis_fingerprint(**fingerprints),
    )
    pins = ModelInputPins(
        contract_type="model_input_pins",
        schema_version="1.0",
        revision=1,
        case_id=case.case_id,
        case_revision=case.revision,
        constraint_set_revision=case.constraint_set_revision,
        fact_ledger_revision=1,
        strategy_id=strategy.strategy_id,
        strategy_revision=strategy.revision,
        planning_basis_fingerprint=basis.planning_basis_fingerprint,
        event_cursor=2,
        provider_config_ref="simulator.default",
        capability_manifest_version="sim-v1",
    )
    return FastModelView(
        contract_type="fast_model_view",
        schema_version="1.0",
        revision=1,
        case_id=case.case_id,
        pins=pins,
        planning_basis=basis,
        goal=case.goal,
        constraints=case.constraints,
        verified_facts=(),
        strategy=strategy,
        recent_events=(),
        latest_provider_event=None,
        pending_slow_work=False,
        allowed_dialogue_acts=tuple(DialogueAct),
        allowed_disclosures=strategy.allowed_disclosures,
    )


def _decision(view: FastModelView, *, action_intent: object = None) -> str:
    output = FastModelOutput(
        dialogue_act=DialogueAct.CLARIFY,
        fact_updates=(),
        reasoner_request=ReasonerRequest(needed=False, reason_code="none"),
        completion_claim=CompletionClaim(status="not_done", evidence_message_ids=()),
        response_text="I will review that and follow up.",
        action_intent=None,
    )
    payload = output.model_dump(mode="json")
    payload["action_intent"] = action_intent
    return json.dumps(payload, sort_keys=True)


def test_prompt_is_frozen_allowlist_and_has_no_evaluator_fields() -> None:
    prompt = QwenMLXAdapter(generator=lambda _: "{}").build_prompt(_view())

    assert prompt.fingerprint
    assert (
        prompt.fingerprint
        == QwenMLXAdapter(generator=lambda _: "{}").build_prompt(_view()).fingerprint
    )
    serialized = prompt.rendered.casefold()
    for forbidden in (
        "manifest",
        "private",
        "evaluator",
        "oracle",
        "gold",
        "expected_action",
        "expected_outcome",
        "family_id",
        "entity_cluster",
        "configuration_id",
        "chain_of_thought",
        "raw_prompt",
    ):
        assert forbidden not in serialized


def test_fake_valid_generation_returns_canonical_adapter_result() -> None:
    view = _view()
    adapter = QwenMLXAdapter(
        generator=lambda _: QwenGenerationText(
            text=_decision(view), input_tokens=11, output_tokens=22
        ),
    )

    result = adapter.generate(view)

    assert result.status is QwenMLXStatus.SUCCEEDED
    assert result.adapter_result is not None
    assert result.adapter_result.pins == view.pins
    assert result.adapter_result.decision.strategy_id == STRATEGY_ID
    assert result.metadata.model == QWEN_MLX_MODEL
    assert result.metadata.source_lineage == QWEN_SOURCE_LINEAGE
    assert result.metadata.run_label == QWEN_RUN_LABEL
    assert result.metadata.model_revision == QWEN_MODEL_REVISION
    assert result.metadata.checkpoint_fingerprint
    assert result.metadata.tokenizer_fingerprint
    assert result.metadata.chat_template_fingerprint
    assert result.metadata.input_tokens == 11
    assert result.metadata.output_tokens == 22


@pytest.mark.parametrize(
    "generated, error_code",
    [
        ("```json\n{}\n```", "invalid_json"),
        (
            json.dumps({"contract_type": "fast_turn_decision"}),
            "fast_action_intent_forbidden",
        ),
    ],
)
def test_invalid_json_or_schema_is_a_failure_without_repair(
    generated: str, error_code: str
) -> None:
    result = QwenMLXAdapter(generator=lambda _: generated).generate(_view())

    assert result.status is QwenMLXStatus.INVALID_OUTPUT
    assert result.adapter_result is None
    assert result.metadata.error_code == error_code


def test_action_intent_and_infrastructure_fields_are_rejected() -> None:
    view = _view()
    action_result = QwenMLXAdapter(
        generator=lambda _: _decision(view, action_intent={"action": "send"})
    ).generate(view)
    assert action_result.status is QwenMLXStatus.INVALID_OUTPUT
    assert action_result.metadata.error_code == "fast_action_intent_forbidden"

    extra_field = json.loads(_decision(view))
    extra_field["case_id"] = "33333333-3333-4333-8333-333333333333"
    extra_result = QwenMLXAdapter(generator=lambda _: json.dumps(extra_field)).generate(
        view
    )
    assert extra_result.status is QwenMLXStatus.INVALID_OUTPUT
    assert extra_result.metadata.error_code == "schema_validation_error"
    assert extra_result.metadata.json_valid is True
    assert extra_result.metadata.schema_valid is False


def test_missing_mlx_dependency_is_typed_and_never_scripted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = qwen_mlx.importlib.import_module

    def missing(name: str) -> object:
        if name == "mlx_lm":
            raise ModuleNotFoundError("mlx_lm")
        return original_import(name)

    monkeypatch.setattr(qwen_mlx.importlib, "import_module", missing)
    result = QwenMLXAdapter().generate(_view())

    assert result.status is QwenMLXStatus.UNAVAILABLE
    assert result.adapter_result is None
    assert result.metadata.error_code == "mlx_lm_unavailable"
    with pytest.raises(QwenMLXUnavailableError) as error:
        QwenMLXAdapter().decide(_view())
    assert error.value.code == "mlx_lm_unavailable"


def test_real_path_caches_weights_uses_chat_template_and_records_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = _view()
    calls = {"load": 0, "template": 0}

    class FakeTokenizer:
        def apply_chat_template(
            self,
            messages: list[dict[str, str]],
            *,
            add_generation_prompt: bool,
            tokenize: bool,
        ) -> str:
            calls["template"] += 1
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"
            assert add_generation_prompt is True
            assert tokenize is False
            return "official-chat-template"

        def encode(self, text: str) -> list[int]:
            return list(range(len(text)))

    tokenizer = FakeTokenizer()

    def load(_: str) -> tuple[object, FakeTokenizer]:
        calls["load"] += 1
        return object(), tokenizer

    def generate(*_: object, prompt: str, max_tokens: int, verbose: bool) -> str:
        assert prompt == "official-chat-template"
        assert max_tokens == 512
        assert verbose is False
        return _decision(view)

    monkeypatch.setattr(
        qwen_mlx.importlib,
        "import_module",
        lambda name: SimpleNamespace(load=load, generate=generate),
    )
    adapter = QwenMLXAdapter()

    first = adapter.generate(view)
    second = adapter.generate(view)

    assert first.status is QwenMLXStatus.SUCCEEDED
    assert second.status is QwenMLXStatus.SUCCEEDED
    assert calls == {"load": 1, "template": 2}
    assert first.metadata.input_tokens == len("official-chat-template")
    assert first.metadata.output_tokens is not None


def test_checkpoint_attestation_hashes_actual_files_and_rejects_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = tmp_path / QWEN_MODEL_REVISION
    snapshot.mkdir()
    contents = {
        "model.safetensors": b"weights",
        "config.json": b"{}",
        "tokenizer.json": b"tokenizer",
        "tokenizer_config.json": b"{}",
        "chat_template.jinja": b"template",
    }
    for name, content in contents.items():
        (snapshot / name).write_bytes(content)
    rows = {
        name: {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
        for name, content in sorted(contents.items())
    }
    tokenizer_rows = {
        name: rows[name] for name in ("tokenizer.json", "tokenizer_config.json")
    }

    def object_fingerprint(value: object) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    monkeypatch.setattr(
        qwen_mlx,
        "QWEN_CHECKPOINT_FINGERPRINT",
        object_fingerprint(rows),
    )
    monkeypatch.setattr(
        qwen_mlx,
        "QWEN_TOKENIZER_FINGERPRINT",
        object_fingerprint(tokenizer_rows),
    )
    monkeypatch.setattr(
        qwen_mlx,
        "QWEN_CHAT_TEMPLATE_FINGERPRINT",
        hashlib.sha256(b"template").hexdigest(),
    )

    attestation = attest_qwen_checkpoint(str(snapshot))

    assert attestation.checkpoint_fingerprint == object_fingerprint(rows)
    (snapshot / "model.safetensors").write_bytes(b"mutated")
    with pytest.raises(ValueError, match="attestation"):
        attest_qwen_checkpoint(str(snapshot))
