from __future__ import annotations

import asyncio
import math
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from proxyloop_agent_core import (
    CaseCoordinator,
    FastAdapterResult,
    ScriptedFastAdapter,
    ScriptedSlowAdapter,
)
from proxyloop_api import (
    ModelRuntimeError,
    ThinAgentRuntime,
    create_app,
    runtime_from_environment,
)
from proxyloop_contracts import DialogueAct, EvidenceType
from proxyloop_contracts.contracts import (
    CompletionClaim,
    EvidenceRequirement,
    ReasonerRequest,
)
from proxyloop_openai_adapter import (
    FastModelOutput,
    ModelFailureKind,
    OpenAICompatibleAdapter,
    OpenAICompatibleAdapterError,
    SlowModelOutput,
    StrategyModelOutput,
)
from proxyloop_provider_simulator.episode import Phase01AEpisode


@dataclass
class _Message:
    parsed: object | None
    refusal: str | None = None


@dataclass
class _Choice:
    message: _Message


class _Response:
    def __init__(
        self,
        parsed: object | None,
        *,
        model: str | None = "runtime-model",
        refusal: str | None = None,
    ):
        self.id = "response-1"
        self.model = model
        self.choices = [_Choice(_Message(parsed, refusal=refusal))]


class _FakeCompletions:
    def __init__(self, responses: list[object], error: Exception | None = None):
        self.responses = iter(responses)
        self.error = error
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return next(self.responses)


class _FakeClient:
    def __init__(self, completions: _FakeCompletions):
        self.chat = SimpleNamespace(completions=completions)


def _slow_output() -> SlowModelOutput:
    return SlowModelOutput(
        strategy=StrategyModelOutput(
            primary_objective="Reduce the monthly bill safely.",
            current_subgoal="Review the current fictional Provider offer.",
            ranked_preference_positions=(),
            allowed_disclosures=(),
            approval_required_disclosures=(),
            concession_ladder=("Preserve hard constraints.",),
            fallback_outcomes=("Return control to the Consumer.",),
            required_completion_evidence=(
                EvidenceRequirement(
                    evidence_type=EvidenceType.CONFIRMATION,
                    description="Provider confirmation",
                ),
            ),
            escalation_conditions=("Material terms change.",),
            replan_conditions=("Planning basis changes.",),
        )
    )


def _fast_output() -> FastModelOutput:
    return FastModelOutput(
        dialogue_act=DialogueAct.CLARIFY,
        fact_updates=(),
        reasoner_request=ReasonerRequest(needed=False, reason_code="none"),
        completion_claim=CompletionClaim(status="not_done", evidence_message_ids=()),
        response_text="I am checking that and will update you.",
        action_intent=None,
    )


def _adapter(
    *responses: object,
    error: Exception | None = None,
) -> tuple[OpenAICompatibleAdapter, _FakeCompletions]:
    completions = _FakeCompletions(list(responses), error=error)
    adapter = OpenAICompatibleAdapter(
        model="runtime-model",
        base_url="https://example.invalid/v1",
        api_key="test-only",
        client=_FakeClient(completions),
    )
    return adapter, completions


def test_model_backed_runtime_reaches_pending_approval_with_fake_transport() -> None:
    adapter, transport = _adapter(
        _Response(_slow_output()),
        _Response(_fast_output()),
    )
    runtime = ThinAgentRuntime(fast=adapter, slow=adapter)

    created = runtime.create_case()
    waiting = runtime.append_event(
        created.snapshot.case.case_id,
        content="Please review the current offer.",
    )

    assert waiting.approval is not None
    assert waiting.approval.decision.value == "pending"
    assert waiting.fast_decision is not None
    assert waiting.fast_decision.action_intent is None
    assert len(transport.calls) == 2
    assert all(call["model"] == "runtime-model" for call in transport.calls)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (_Response(None), ModelFailureKind.INVALID_OUTPUT),
        (
            _Response(None, refusal="provider refusal body"),
            ModelFailureKind.INVALID_OUTPUT,
        ),
        (_Response(_fast_output(), model=None), ModelFailureKind.MODEL_METADATA),
        (
            _Response(_fast_output(), model="other-model"),
            ModelFailureKind.MODEL_METADATA,
        ),
    ],
)
def test_model_adapter_rejects_invalid_or_wrong_metadata(
    response: _Response, expected: ModelFailureKind
) -> None:
    adapter, _transport = _adapter(response)
    with pytest.raises(OpenAICompatibleAdapterError) as raised:
        adapter.decide(_fast_view_for_adapter(adapter))
    assert raised.value.kind is expected
    assert "other-model" not in str(raised.value)


def test_model_adapter_fails_closed_on_timeout_and_transport_without_raw_text() -> None:
    for error, expected in (
        (TimeoutError("provider secret body"), ModelFailureKind.TIMEOUT),
        (RuntimeError("Bearer sk-secret-provider-body"), ModelFailureKind.TRANSPORT),
    ):
        adapter, _transport = _adapter(error=error)
        with pytest.raises(OpenAICompatibleAdapterError) as raised:
            adapter.decide(_fast_view_for_adapter(adapter))
        assert raised.value.kind is expected
        assert "secret" not in str(raised.value)
        assert "Bearer" not in str(raised.value)


def test_api_model_error_is_stable_and_does_not_create_approval() -> None:
    adapter, _transport = _adapter(error=RuntimeError("provider secret body"))
    runtime = ThinAgentRuntime(fast=adapter, slow=adapter)

    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime)),
            base_url="http://testserver",
        ) as client:
            return await client.post("/cases")

    response = asyncio.run(request())

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "model_transport",
            "message": "model operation failed safely",
        }
    }
    assert "provider secret" not in response.text


def test_model_mode_requires_explicit_complete_process_configuration() -> None:
    with pytest.raises(ValueError, match="requires API key"):
        runtime_from_environment(mode="model", environ={})
    scripted = runtime_from_environment(mode="scripted", environ={})
    assert scripted._slow.__class__.__name__ == "ScriptedSlowAdapter"


@pytest.mark.parametrize("timeout", [math.nan, math.inf, -math.inf])
def test_adapter_rejects_nonfinite_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout must be positive"):
        OpenAICompatibleAdapter(
            model="runtime-model",
            base_url="https://example.invalid/v1",
            api_key="test-only",
            timeout=timeout,
            client=_FakeClient(_FakeCompletions([])),
        )


@pytest.mark.parametrize("timeout", ["nan", "inf", "-inf"])
def test_process_configuration_rejects_nonfinite_timeout(timeout: str) -> None:
    environment = {
        "PROXYLOOP_MODEL_API_KEY": "test-only",
        "PROXYLOOP_MODEL_BASE_URL": "https://example.invalid/v1",
        "PROXYLOOP_MODEL_NAME": "runtime-model",
        "PROXYLOOP_MODEL_TIMEOUT": timeout,
    }
    with pytest.raises(ValueError, match="positive number"):
        runtime_from_environment(mode="model", environ=environment)


def test_production_client_uses_explicit_timeout_and_zero_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    OpenAICompatibleAdapter(
        model="runtime-model",
        base_url="https://example.invalid/v1",
        api_key="test-only",
        timeout=7.25,
    )

    assert captured["timeout"] == 7.25
    assert captured["max_retries"] == 0


def test_slow_transport_failure_leaves_no_persisted_case() -> None:
    adapter, _transport = _adapter(error=RuntimeError("provider secret body"))
    runtime = ThinAgentRuntime(slow=adapter, fast=adapter)

    with pytest.raises(OpenAICompatibleAdapterError) as raised:
        runtime.create_case()

    assert raised.value.kind is ModelFailureKind.TRANSPORT
    assert runtime.repository.get(_known_case_id()) is None


def test_stale_slow_result_leaves_no_persisted_case_or_authoritative_mutation() -> None:
    class StaleSlow:
        def reason(self, request: Any) -> Any:
            result = ScriptedSlowAdapter().reason(request)
            stale_pins = request.pins.model_copy(
                update={"event_cursor": request.pins.event_cursor + 1}
            )
            return result.model_copy(update={"pins": stale_pins})

    runtime = ThinAgentRuntime(slow=StaleSlow())

    with pytest.raises(ModelRuntimeError, match="rejected safely"):
        runtime.create_case()

    # No repository record means no approval, Provider confirmation, completion,
    # or persisted Evidence could have been created.
    assert runtime.repository.get(_known_case_id()) is None


def test_stale_fast_result_is_rejected_before_approval_or_provider_action() -> None:
    class StaleFast:
        def decide(self, view: Any) -> FastAdapterResult:
            result = ScriptedFastAdapter().decide(view)
            return FastAdapterResult(
                pins=result.pins,
                decision=result.decision.model_copy(
                    update={"case_revision": result.decision.case_revision + 1}
                ),
            )

    runtime = ThinAgentRuntime(fast=StaleFast())
    created = runtime.create_case()
    with pytest.raises(RuntimeError, match="rejected safely"):
        runtime.append_event(
            created.snapshot.case.case_id,
            content="Please review the offer.",
        )
    state = runtime.repository.get(created.snapshot.case.case_id)
    assert state is not None
    assert state.snapshot.approval_requests == ()
    assert state.provider.confirmation is None


def test_localhost_server_black_box_scripted_flow() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = os.environ.copy()
    environment["PROXYLOOP_RUNTIME_MODE"] = "scripted"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "proxyloop_api.server",
            "--mode",
            "scripted",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            while time.monotonic() < deadline:
                try:
                    response = client.post("/cases", timeout=0.5)
                    if response.status_code == 201:
                        break
                except httpx.HTTPError:
                    time.sleep(0.05)
            else:
                raise AssertionError("local Runtime server did not start")
            created = response.json()
            case_id = created["case_id"]
            assert client.get(f"/cases/{case_id}").status_code == 200
            waiting = client.post(
                f"/cases/{case_id}/events",
                json={"content": "Please review the offer."},
            )
            assert waiting.status_code == 200
            approval = waiting.json()["approval"]
            completed = client.post(
                f"/cases/{case_id}/approvals/{approval['approval_id']}",
                json={"decision": "approved"},
            )
            assert completed.status_code == 200
            assert completed.json()["completion"]["decision"] == "complete"
    finally:
        process.terminate()
        process.wait(timeout=5)


def _fast_view_for_adapter(adapter: OpenAICompatibleAdapter) -> Any:
    runtime = ThinAgentRuntime()
    created = runtime.create_case()
    return CaseCoordinator.project_fast_view(created.snapshot)


def _known_case_id() -> Any:
    return Phase01AEpisode.success().case.case_id
