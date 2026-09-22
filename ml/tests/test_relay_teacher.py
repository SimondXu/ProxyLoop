from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from proxyloop_contracts import FastModelView
from proxyloop_evaluation.fast_output import FastModelOutput
from proxyloop_evaluation.openai_frontier import (
    FRONTIER_API_KEY_ENV,
    FRONTIER_BASE_URL,
    FrontierCallStatus,
    FrontierUnavailableError,
)
from proxyloop_evaluation.phase03c_experiment import (
    DECISION_CONVENTION_BLOCK,
    PHASE03C_COMPILER_VERSION,
    PHASE03C_COMPILER_VERSION_V4,
    Phase03CQwenAdapter,
    _fingerprint,
    development_examples,
)
from proxyloop_evaluation.relay_teacher import (
    DEFAULT_TEACHER_RATES_PATH,
    PROMPT_CHARS_PER_TOKEN,
    TEACHER_ACCOUNTING_LABEL,
    TEACHER_TIMEOUT_SECONDS,
    RelayTeacherAdapter,
    TeacherBudgetExceededError,
    TeacherCredentialError,
    TeacherLedger,
    load_teacher_rate,
)

MODEL = "claude-sonnet-5"
FAKE_KEY = "sk-test-only-0123456789abcdef"


@pytest.fixture
def view() -> FastModelView:
    return development_examples()[0].view


@dataclass
class _Usage:
    prompt_tokens: int = 1_000
    completion_tokens: int = 200


@dataclass
class _Message:
    content: str | None


@dataclass
class _Choice:
    message: _Message
    finish_reason: str | None = None


@dataclass
class _Response:
    choices: list[_Choice]
    model: str = MODEL
    id: str = "chatcmpl-test-001"
    usage: _Usage = field(default_factory=_Usage)


@dataclass
class _Completions:
    outcomes: list[object]
    calls: list[dict[str, object]] = field(default_factory=list)

    def create(self, **kwargs: object) -> _Response:
        self.calls.append(kwargs)
        outcome = self.outcomes[len(self.calls) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, _Response)
        return outcome


@dataclass
class _Client:
    completions: _Completions

    @property
    def chat(self) -> SimpleNamespace:
        return SimpleNamespace(completions=self.completions)


def _ok(content: str = '{"dialogue_act":"ask_clarification"}') -> _Response:
    return _Response(choices=[_Choice(_Message(content))])


def _client(*outcomes: object) -> _Client:
    return _Client(_Completions(list(outcomes)))


def _adapter(client: _Client | None, **overrides: object) -> RelayTeacherAdapter:
    kwargs: dict[str, object] = {
        "model": MODEL,
        "client": client,
        "usd_ceiling": 1.0,
    }
    kwargs.update(overrides)
    return RelayTeacherAdapter(**kwargs)  # type: ignore[arg-type]


def test_rates_file_is_the_placeholder_upper_bound() -> None:
    document = json.loads(DEFAULT_TEACHER_RATES_PATH.read_text(encoding="utf-8"))
    assert "placeholder" in document["note"].lower()
    assert document["unit"] == "usd_per_million_tokens"
    rate = load_teacher_rate(MODEL, DEFAULT_TEACHER_RATES_PATH)
    assert (rate.input_usd_per_million, rate.output_usd_per_million) == (3.0, 15.0)
    with pytest.raises(ValueError, match="no teacher rate"):
        load_teacher_rate("unknown-model", DEFAULT_TEACHER_RATES_PATH)


def test_sample_sends_exact_v4_prompt_k_times(view: FastModelView) -> None:
    client = _client(_ok("{}"), _ok("{}"), _ok("{}"))
    adapter = _adapter(client, temperature=0.9, max_output_tokens=321)

    batch = adapter.sample(view, k=3, seed_tag="dev-0")

    assert adapter.prompt_version == "v4"
    assert adapter.compiler_version == PHASE03C_COMPILER_VERSION_V4
    expected = Phase03CQwenAdapter(
        generator=lambda _: "{}", prompt_version="v4"
    ).build_prompt(view)
    assert DECISION_CONVENTION_BLOCK in expected.user
    assert len(client.completions.calls) == 3
    for call in client.completions.calls:
        assert call["model"] == MODEL
        assert call["messages"] == [
            {"role": "system", "content": expected.system},
            {"role": "user", "content": expected.user},
        ]
        assert call["temperature"] == 0.9
        assert call["max_tokens"] == 321
        assert call["response_format"] == {"type": "json_object"}
        assert set(call) == {
            "model",
            "messages",
            "temperature",
            "max_tokens",
            "response_format",
        }
    assert batch.model == MODEL
    assert batch.seed_tag == "dev-0"
    assert batch.prompt_fingerprint == expected.fingerprint
    assert batch.schema_fingerprint == _fingerprint(FastModelOutput.model_json_schema())
    assert batch.contents == ("{}", "{}", "{}")
    assert [s.record.status for s in batch.samples] == [
        FrontierCallStatus.SUCCEEDED
    ] * 3
    assert all(
        s.record.prompt_fingerprint == expected.fingerprint for s in batch.samples
    )


def test_sample_can_send_the_v3_prompt_when_asked(view: FastModelView) -> None:
    client = _client(_ok("{}"))
    adapter = _adapter(client, prompt_version="v3")

    batch = adapter.sample(view, k=1, seed_tag="dev-0")

    expected = Phase03CQwenAdapter(generator=lambda _: "{}").build_prompt(view)
    assert adapter.compiler_version == PHASE03C_COMPILER_VERSION
    assert DECISION_CONVENTION_BLOCK not in expected.user
    assert client.completions.calls[0]["messages"][1]["content"] == expected.user
    assert batch.prompt_fingerprint == expected.fingerprint


def test_ledger_multiplies_usage_by_rates(view: FastModelView) -> None:
    client = _client(_ok(), _ok())
    adapter = _adapter(client)

    batch = adapter.sample(view, k=2, seed_tag="dev-0")

    # 1_000 input at $3/M + 200 output at $15/M = 0.003 + 0.003 per call.
    per_call = 1_000 * 3.0 / 1e6 + 200 * 15.0 / 1e6
    assert batch.samples[0].record.estimated_cost_usd == pytest.approx(per_call)
    assert batch.samples[0].record.actual_cost_usd is None
    assert batch.samples[0].record.input_tokens == 1_000
    assert batch.samples[0].record.output_tokens == 200
    ledger = adapter.ledger.to_dict()
    assert ledger["accounting"] == TEACHER_ACCOUNTING_LABEL
    assert "worst" in TEACHER_ACCOUNTING_LABEL and "reset" in TEACHER_ACCOUNTING_LABEL
    assert ledger["total_calls"] == 2
    assert ledger["total_estimated_usd"] == pytest.approx(2 * per_call)
    assert ledger["per_model"] == {
        MODEL: {
            "calls": 2,
            "succeeded": 2,
            "failed": 0,
            "input_tokens": 2_000,
            "output_tokens": 400,
            "estimated_usd": pytest.approx(2 * per_call),
        }
    }


def test_ceiling_rejects_before_the_call_that_would_exceed(
    view: FastModelView,
) -> None:
    prompt = Phase03CQwenAdapter(
        generator=lambda _: "{}", prompt_version="v4"
    ).build_prompt(view)
    prompt_tokens = -(
        -(len(prompt.system) + len(prompt.user)) // PROMPT_CHARS_PER_TOKEN
    )
    worst_case = prompt_tokens * 3.0 / 1e6 + 512 * 15.0 / 1e6
    per_call = 1_000 * 3.0 / 1e6 + 200 * 15.0 / 1e6
    # One real call fits; the second call's worst case does not.
    client = _client(_ok(), _ok(), _ok())
    adapter = _adapter(client, usd_ceiling=per_call + worst_case - 1e-9)
    assert adapter.worst_case_call_usd(view) == pytest.approx(worst_case)

    with pytest.raises(TeacherBudgetExceededError) as exc_info:
        adapter.sample(view, k=3, seed_tag="dev-0")

    assert len(client.completions.calls) == 1
    assert adapter.calls_started == 1
    assert exc_info.value.status is FrontierCallStatus.NOT_RUN_BUDGET_EXCEEDED
    assert len(exc_info.value.completed) == 1
    assert adapter.ledger.total_calls == 1

    # A zero-budget adapter never calls at all.
    idle = _client(_ok())
    with pytest.raises(TeacherBudgetExceededError):
        _adapter(idle, usd_ceiling=0.0).sample(view, k=1, seed_tag="dev-0")
    assert idle.completions.calls == []


def test_provider_error_is_sanitized_and_batch_continues(
    view: FastModelView, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(FRONTIER_API_KEY_ENV, FAKE_KEY)

    class RelayError(RuntimeError):
        status_code = 429
        request_id = f"req-1 Bearer {FAKE_KEY}"
        body: ClassVar[dict[str, object]] = {
            "error": {
                "code": f"rate_limited {FAKE_KEY}",
                "type": "rate_limit_error",
                "param": None,
                "message": f"secret {FAKE_KEY} leaked",
            }
        }

    client = _client(_ok("first"), RelayError(f"boom {FAKE_KEY}"), _ok("third"))
    adapter = _adapter(client)

    batch = adapter.sample(view, k=3, seed_tag="dev-0")

    assert len(client.completions.calls) == 3
    assert batch.contents == ("first", "third")
    failed = batch.samples[1]
    assert failed.content is None
    assert failed.record.status is FrontierCallStatus.FAILED_PROVIDER_CALL
    assert failed.record.error == "RelayError"
    assert failed.record.estimated_cost_usd == pytest.approx(
        adapter.worst_case_call_usd(view)
    )
    assert failed.error is not None
    assert failed.error.error_class == "RelayError"
    assert failed.error.status_code == 429
    assert failed.error.provider_type == "rate_limit_error"
    assert failed.error.call_index == 2
    assert FAKE_KEY not in json.dumps(asdict(failed), default=str)
    assert "[REDACTED]" in (failed.error.request_id or "")
    assert "[REDACTED]" in (failed.error.provider_code or "")
    totals = adapter.ledger.to_dict()["per_model"]
    assert isinstance(totals, dict)
    assert totals[MODEL]["succeeded"] == 2
    assert totals[MODEL]["failed"] == 1


def test_missing_content_fails_but_missing_usage_keeps_content(
    view: FastModelView,
) -> None:
    empty = _Response(choices=[_Choice(_Message(None))])
    no_usage = _ok("ok")
    no_usage.usage = _Usage(prompt_tokens=-1)
    adapter = _adapter(_client(empty, no_usage))

    batch = adapter.sample(view, k=2, seed_tag="dev-0")

    assert batch.contents == ("ok",)
    missing_content, missing_usage = batch.samples
    assert missing_content.record.status is FrontierCallStatus.FAILED_INVALID_RESPONSE
    assert missing_content.record.error == "MissingContent"
    assert missing_content.usage_missing is False
    assert missing_usage.content == "ok"
    assert missing_usage.usage_missing is True
    assert missing_usage.record.status is FrontierCallStatus.SUCCEEDED
    assert missing_usage.record.error == "MissingUsage"
    assert missing_usage.error is not None
    assert missing_usage.error.error_class == "MissingUsage"
    assert (missing_usage.record.input_tokens, missing_usage.record.output_tokens) == (
        0,
        0,
    )
    # Both are charged at the pre-call worst case so the ledger stays an
    # upper bound.
    worst = adapter.worst_case_call_usd(view)
    assert missing_content.record.estimated_cost_usd == pytest.approx(worst)
    assert missing_usage.record.estimated_cost_usd == pytest.approx(worst)
    totals = adapter.ledger.to_dict()["per_model"]
    assert isinstance(totals, dict)
    assert (totals[MODEL]["succeeded"], totals[MODEL]["failed"]) == (1, 1)


def test_finish_reason_is_recorded_per_sample(view: FastModelView) -> None:
    stopped = _ok("{}")
    stopped.choices[0].finish_reason = "stop"
    truncated = _ok("{")
    truncated.choices[0].finish_reason = "length"
    adapter = _adapter(_client(stopped, truncated, _ok("{}")))

    batch = adapter.sample(view, k=3, seed_tag="dev-0")

    assert [s.finish_reason for s in batch.samples] == ["stop", "length", None]
    assert all(s.usage_missing is False for s in batch.samples)


def test_missing_env_key_raises_typed_error_without_key_material(
    view: FastModelView, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(FRONTIER_API_KEY_ENV, raising=False)
    monkeypatch.delenv("PROXYLOOP_TEACHER_KEY", raising=False)
    adapter = _adapter(None, api_key_env="PROXYLOOP_TEACHER_KEY")

    with pytest.raises(TeacherCredentialError) as exc_info:
        adapter.sample(view, k=1, seed_tag="dev-0")

    assert isinstance(exc_info.value, FrontierUnavailableError)
    assert exc_info.value.status is FrontierCallStatus.NOT_RUN_MISSING_CREDENTIALS
    assert str(exc_info.value) == (
        "PROXYLOOP_TEACHER_KEY is not present in the process environment"
    )
    assert adapter.calls_started == 0


def test_lazy_sdk_client_uses_env_key_no_retries_and_timeout(
    view: FastModelView, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    fake = _client(_ok("{}"))

    def factory(**kwargs: object) -> _Client:
        captured.update(kwargs)
        return fake

    monkeypatch.setenv(FRONTIER_API_KEY_ENV, FAKE_KEY)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=factory))
    adapter = _adapter(None)

    batch = adapter.sample(view, k=1, seed_tag="dev-0")

    assert captured == {
        "api_key": FAKE_KEY,
        "base_url": FRONTIER_BASE_URL,
        "max_retries": 0,
        "timeout": TEACHER_TIMEOUT_SECONDS,
    }
    assert batch.contents == ("{}",)
    assert len(fake.completions.calls) == 1


def test_shared_ledger_accumulates_across_models(
    view: FastModelView, tmp_path: Path
) -> None:
    rates = tmp_path / "rates.json"
    rates.write_text(
        json.dumps(
            {
                "rates": {
                    "a": {"input": 1.0, "output": 1.0},
                    "b": {"input": 2.0, "output": 2.0},
                }
            }
        ),
        encoding="utf-8",
    )
    ledger = TeacherLedger(usd_ceiling=1.0, rates_path=rates)
    a = RelayTeacherAdapter(
        model="a",
        client=_client(_ok()),
        usd_ceiling=1.0,
        rates_path=rates,
        ledger=ledger,
    )
    b = RelayTeacherAdapter(
        model="b",
        client=_client(_ok()),
        usd_ceiling=1.0,
        rates_path=rates,
        ledger=ledger,
    )
    a.sample(view, k=1, seed_tag="x")
    b.sample(view, k=1, seed_tag="x")

    summary = ledger.to_dict()
    assert summary["total_calls"] == 2
    assert summary["total_estimated_usd"] == pytest.approx(
        1_200 * 1.0 / 1e6 + 1_200 * 2.0 / 1e6
    )
