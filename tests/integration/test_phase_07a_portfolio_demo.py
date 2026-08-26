from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Self

import psycopg
import pytest
from proxyloop_case_runtime import SCRIPTED_CASE_ID

from scripts import run_phase_07a_portfolio_demo as demo


def test_explicit_temporal_demo_environment_strips_model_keys() -> None:
    environment = demo.build_demo_environment(
        {
            "PATH": "/bin",
            "PROXYLOOP_MODEL_API_KEY": "must-not-reach-demo",
            "PROXYLOOP_MODEL_BASE_URL": "https://example.invalid",
            "PROXYLOOP_MODEL_NAME": "secret-model",
        }
    )

    assert "PROXYLOOP_MODEL_API_KEY" not in environment
    assert "PROXYLOOP_MODEL_BASE_URL" not in environment
    assert "PROXYLOOP_MODEL_NAME" not in environment
    assert environment["PROXYLOOP_RUNTIME_MODE"] == "scripted"
    assert environment["PROXYLOOP_STORAGE_MODE"] == "postgres"
    assert environment["PROXYLOOP_ORCHESTRATION_MODE"] == "temporal"
    assert environment["PROXYLOOP_DATABASE_URL"] == demo.DEFAULT_DATABASE_URL
    assert environment["PROXYLOOP_TEMPORAL_ADDRESS"] == "127.0.0.1:7234"
    assert environment["PROXYLOOP_TEMPORAL_NAMESPACE"] == "default"
    assert environment["PROXYLOOP_TEMPORAL_TASK_QUEUE"] == "proxyloop-case-workflow"


def test_fixture_payload_is_stable_json_and_signed_as_exact_bytes() -> None:
    now = demo.parse_utc("2026-08-26T12:00:00Z")
    raw = demo.build_provider_message_body(now)
    payload = json.loads(raw)

    assert payload["schema_version"] == "local-mailbox-v1"
    assert payload["event_id"] == str(demo.INBOUND_EVENT_ID)
    assert payload["binding_ref"] == "fictional-provider-local-mailbox"
    assert demo.build_fixture_headers(raw)["X-ProxyLoop-Local-Signature"].startswith(
        "sha256="
    )
    assert demo.build_fixture_headers(raw)["X-ProxyLoop-Local-Signature"] == (
        "sha256=" + demo.sha256_hex(raw)
    )
    assert demo.INBOUND_EVENT_ID != SCRIPTED_CASE_ID
    assert demo.CALLBACK_EVENT_ID not in {SCRIPTED_CASE_ID, demo.INBOUND_EVENT_ID}


def test_browser_projection_assertion_rejects_channel_material() -> None:
    safe = {
        "snapshot": {
            "visible_events": [{"actor": "provider", "event_type": "provider_offer"}],
            "evidence": [
                {
                    "source_type": "provider_message",
                    "source_ref": "pine-mobile:offer:pine-value-5g:v1",
                }
            ],
        },
        "evidence": [],
    }
    demo.assert_browser_projection_isolated(
        safe,
        forbidden=("local-provider-123", "channel-message-body", "deadbeef"),
    )

    unsafe = {"snapshot": {"visible_events": [{"content": "channel-message-body"}]}}
    try:
        demo.assert_browser_projection_isolated(
            unsafe,
            forbidden=("local-provider-123", "channel-message-body", "deadbeef"),
        )
    except demo.DemoScenarioError as exc:
        assert str(exc) == "browser projection contains channel material"
    else:
        raise AssertionError("unsafe browser projection was accepted")

    with pytest.raises(demo.DemoScenarioError, match="channel material"):
        demo.assert_browser_projection_isolated(
            {
                "snapshot": {
                    "visible_events": [],
                    "evidence": [
                        {
                            "source_type": "provider_message",
                            "source_ref": str(demo.INBOUND_EVENT_ID),
                        }
                    ],
                }
            },
            forbidden=(),
        )


def test_channel_evidence_assertion_ignores_existing_offer_evidence() -> None:
    evidence_refs = [
        ("provider_message", "pine-mobile:offer:pine-value-5g:v1"),
        ("provider_message", str(demo.INBOUND_EVENT_ID)),
        ("provider_event", "local-provider-demo"),
    ]

    demo.assert_authoritative_channel_evidence(
        evidence_refs, provider_message_id="local-provider-demo"
    )


def test_stop_refuses_a_reused_pid_before_kill(monkeypatch, tmp_path: Path) -> None:
    pid_file = tmp_path / demo.PID_FILE
    pid_file.write_text(
        json.dumps({name: 4242 for name in demo.HOST_SERVICE_NAMES}) + "\n"
    )
    monkeypatch.setattr(demo, "_pid_is_running", lambda _pid: True)
    monkeypatch.setattr(
        demo, "_pid_matches_expected_process", lambda _name, _pid: False
    )

    with pytest.raises(demo.DemoScenarioError, match="unexpected process"):
        demo._running_processes(tmp_path)


def test_stop_signals_supervisor_before_terminating_hosts(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / demo.PID_FILE).write_text(
        json.dumps({name: 4242 for name in demo.HOST_SERVICE_NAMES}) + "\n"
    )
    observed: list[bool] = []
    monkeypatch.setattr(demo, "_running_processes", lambda _state_dir: {})
    monkeypatch.setattr(
        demo,
        "_terminate_processes",
        lambda _processes: observed.append((tmp_path / demo.STOP_FILE).exists()),
    )
    monkeypatch.setattr(
        demo,
        "_compose",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
    )

    demo.stop_demo(state_dir=tmp_path)

    assert observed == [True]
    assert not (tmp_path / demo.STOP_FILE).exists()


def test_second_start_refuses_atomic_lifecycle_lock(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(demo, "_pid_matches_lifecycle_owner", lambda _pid: True)
    demo._claim_lifecycle_lock(tmp_path)

    with pytest.raises(demo.DemoScenarioError, match="already starting or running"):
        demo._claim_lifecycle_lock(tmp_path)

    demo._release_lifecycle_lock(tmp_path)


def test_start_claims_lifecycle_before_clearing_stop_request(
    monkeypatch, tmp_path: Path
) -> None:
    stop_file = tmp_path / demo.STOP_FILE
    stop_file.write_text("stale request\n")
    observed: list[bool] = []
    original_claim = demo._claim_lifecycle_lock

    def claim(state_dir: Path) -> None:
        observed.append((state_dir / demo.STOP_FILE).exists())
        original_claim(state_dir)

    monkeypatch.setattr(demo, "_claim_lifecycle_lock", claim)
    demo._initialize_startup_state(tmp_path)

    assert observed == [True]
    assert not stop_file.exists()
    demo._release_lifecycle_lock(tmp_path)


def test_second_start_cannot_clear_active_stop_request(
    monkeypatch, tmp_path: Path
) -> None:
    stop_file = tmp_path / demo.STOP_FILE
    stop_file.write_text("external stop requested\n")
    demo._claim_lifecycle_lock(tmp_path)
    monkeypatch.setattr(demo, "_pid_matches_lifecycle_owner", lambda _pid: True)

    with pytest.raises(demo.DemoScenarioError, match="already starting or running"):
        demo._initialize_startup_state(tmp_path)

    assert stop_file.read_text() == "external stop requested\n"
    demo._release_lifecycle_lock(tmp_path)


def test_stop_during_startup_requests_stop_before_waiting(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / demo.LIFECYCLE_LOCK_FILE).write_text('{"pid": 4242}\n')
    observed: list[bool] = []
    monkeypatch.setattr(demo, "_running_processes", lambda _state_dir: {})
    monkeypatch.setattr(demo, "_terminate_processes", lambda _processes: None)
    monkeypatch.setattr(
        demo,
        "_compose",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
    )

    def wait_for_release(state_dir: Path, **_kwargs: object) -> None:
        observed.append((state_dir / demo.STOP_FILE).exists())
        (state_dir / demo.LIFECYCLE_LOCK_FILE).unlink()

    monkeypatch.setattr(demo, "_wait_for_lifecycle_release", wait_for_release)
    demo.stop_demo(state_dir=tmp_path)

    assert observed == [True]


def test_reset_removes_containers_before_named_volume_and_verifies_absence(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(demo, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(demo, "_running_processes", lambda _state_dir: {})
    monkeypatch.setattr(demo, "_terminate_processes", lambda _processes: None)
    compose_calls: list[tuple[str, ...]] = []

    def fake_compose(*args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        compose_calls.append(args)
        return subprocess.CompletedProcess([], 0, "", "")

    docker_calls: list[tuple[str, ...]] = []

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        docker_calls.append(tuple(command))
        if command[-2:] == ["inspect", demo.COMPOSE_VOLUME_NAME]:
            return subprocess.CompletedProcess(
                command, 0 if len(docker_calls) == 1 else 1, "", ""
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(demo, "_compose", fake_compose)
    monkeypatch.setattr(demo.subprocess, "run", fake_run)

    demo.reset_demo()

    assert compose_calls == [
        ("stop", *demo.COMPOSE_SERVICES),
        ("rm", "-sf", *demo.COMPOSE_SERVICES),
    ]
    assert docker_calls == [
        ("docker", "volume", "inspect", demo.COMPOSE_VOLUME_NAME),
        ("docker", "volume", "rm", demo.COMPOSE_VOLUME_NAME),
        ("docker", "volume", "inspect", demo.COMPOSE_VOLUME_NAME),
    ]


def test_compose_start_waits_for_default_temporal_namespace(monkeypatch) -> None:
    monkeypatch.setattr(
        demo,
        "_compose",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
    )
    monkeypatch.setattr(demo, "_wait_for_postgres", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(demo, "_wait_for_tcp", lambda *_args, **_kwargs: True)
    observed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        demo,
        "_wait_for_temporal_namespace",
        lambda address, namespace, **_kwargs: (
            observed.append((address, namespace)) or True
        ),
        raising=False,
    )

    demo._start_compose_dependencies()

    assert observed == [(demo.DEFAULT_TEMPORAL_ADDRESS, "default")]


def test_postgres_readiness_retries_until_a_query_succeeds(monkeypatch) -> None:
    attempts = 0

    class _Connection:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, query: str) -> None:
            assert query == "SELECT 1"

    def connect(_database_url: str, **_kwargs: object) -> _Connection:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise psycopg.OperationalError("database is still starting")
        return _Connection()

    monkeypatch.setattr(demo.psycopg, "connect", connect)
    monkeypatch.setattr(demo.time, "sleep", lambda _seconds: None)

    assert demo._wait_for_postgres("postgresql://demo", timeout=1) is True
    assert attempts == 2


def test_make_exposes_bounded_demo_lifecycle_commands() -> None:
    makefile = Path("Makefile").read_text()
    for target in (
        "portfolio-demo:",
        "portfolio-demo-stop:",
        "portfolio-demo-reset:",
        "portfolio-demo-channel:",
        "portfolio-demo-recovery:",
    ):
        assert target in makefile


def test_web_demo_uses_production_build_and_start(monkeypatch, tmp_path: Path) -> None:
    observed: list[list[str]] = []

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        observed.append(command)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(demo.subprocess, "run", fake_run)
    demo._build_web_app(tmp_path)

    assert observed == [["pnpm", "--filter", "@proxyloop/web", "build"]]
    source = Path(demo.__file__).read_text()
    assert '"@proxyloop/web",\n            "start"' in source
    assert '"@proxyloop/web",\n            "dev"' not in source
