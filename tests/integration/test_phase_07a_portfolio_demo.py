from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Self

import httpx
import psycopg
import pytest
from local_fast_fake_gateway import FakeGateway
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
        },
        "evidence": [
            {
                "evidence_id": "99999999-9999-4999-8999-999999999999",
                "source_type": "confirmation",
                "observed_at": "2026-08-26T12:00:00Z",
            }
        ],
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

    for source_type in ("provider_message", "provider_event"):
        with pytest.raises(demo.DemoScenarioError, match="channel material"):
            demo.assert_browser_projection_isolated(
                {
                    "snapshot": {"visible_events": []},
                    "evidence": [
                        {
                            "evidence_id": "99999999-9999-4999-8999-999999999999",
                            "source_type": source_type,
                            "observed_at": "2026-08-26T12:00:00Z",
                        }
                    ],
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


def test_refused_start_keeps_the_process_state_of_a_crashed_supervisor(
    tmp_path: Path,
) -> None:
    # C-5: a crashed supervisor leaves pids.json behind while its host services
    # keep running. A refused second start must not delete it, or
    # portfolio-demo-stop can no longer find those processes.
    pids = {name: 4242 for name in demo.HOST_SERVICE_NAMES}
    pid_file = tmp_path / demo.PID_FILE
    pid_file.write_text(json.dumps(pids) + "\n")
    # The crashed supervisor also left its lifecycle lock; its owner is dead,
    # so the second start reclaims the lock and reaches the pids.json refusal.
    exited = subprocess.Popen(["true"])
    exited.wait()
    (tmp_path / demo.LIFECYCLE_LOCK_FILE).write_text(
        json.dumps({"pid": exited.pid}) + "\n"
    )

    with pytest.raises(demo.DemoScenarioError, match="already has a process state"):
        demo.start_demo(state_dir=tmp_path)

    assert demo._read_pids(tmp_path) == pids
    assert not (tmp_path / demo.LIFECYCLE_LOCK_FILE).exists()


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


# PR-11 D6: the launcher's local Fast backend flag.


def test_fast_backend_flag_sets_one_selection_for_worker_and_api() -> None:
    inherited = {"PATH": "/bin", "PROXYLOOP_FAST_BACKEND": "untuned"}

    assert demo.build_demo_environment(inherited)["PROXYLOOP_FAST_BACKEND"] == (
        "scripted"
    )
    environment = demo.build_demo_environment(inherited, fast_backend="distilled")
    assert environment["PROXYLOOP_FAST_BACKEND"] == "distilled"
    assert environment["PROXYLOOP_ORCHESTRATION_MODE"] == "temporal"
    assert environment["PROXYLOOP_RUNTIME_MODE"] == "scripted"
    with pytest.raises(ValueError, match="fast backend"):
        demo.build_demo_environment(inherited, fast_backend="hosted")


def test_a_matching_gateway_passes_the_launcher_check() -> None:
    assert demo.check_fast_backend(demo.build_demo_environment({})) is None
    with FakeGateway(backend="distilled") as gateway:
        environment = demo.build_demo_environment(
            {"PROXYLOOP_FAST_GATEWAY_URL": gateway.url}, fast_backend="distilled"
        )
        assert demo.check_fast_backend(environment) == "local opt-in candidate"
        mismatched = demo.build_demo_environment(
            {"PROXYLOOP_FAST_GATEWAY_URL": gateway.url}, fast_backend="untuned"
        )
        with pytest.raises(demo.DemoScenarioError, match="BACKEND=untuned"):
            demo.check_fast_backend(mismatched)


def test_a_local_fast_backend_without_its_gateway_starts_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    with FakeGateway(backend="distilled") as stopped:
        url = stopped.url
    monkeypatch.setenv("PROXYLOOP_FAST_GATEWAY_URL", url)
    started: list[str] = []
    monkeypatch.setattr(demo, "_check_startup_ports", lambda: None)
    monkeypatch.setattr(
        demo, "_start_compose_dependencies", lambda: started.append("compose")
    )
    monkeypatch.setattr(
        demo, "_build_web_app", lambda *_args: started.append("web-build")
    )
    monkeypatch.setattr(
        demo, "_spawn_host_services", lambda *_args, **_kwargs: started.append("hosts")
    )

    with pytest.raises(
        demo.DemoScenarioError, match="make local-fast-gateway BACKEND=distilled"
    ):
        demo.start_demo(state_dir=tmp_path, fast_backend="distilled")

    assert started == []
    assert not (tmp_path / demo.LIFECYCLE_LOCK_FILE).exists()
    assert not (tmp_path / demo.PID_FILE).exists()


def test_serve_accepts_only_known_fast_backends(monkeypatch) -> None:
    observed: list[str] = []
    monkeypatch.setattr(
        demo,
        "start_demo",
        lambda *, fast_backend, **_ports: observed.append(fast_backend),
    )

    assert demo.main(["serve"]) == 0
    assert demo.main(["serve", "--fast-backend", "untuned"]) == 0
    assert observed == ["scripted", "untuned"]
    with pytest.raises(SystemExit) as raised:
        demo.main(["serve", "--fast-backend", "hosted"])
    assert raised.value.code == 2


def test_make_passes_the_fast_backend_flag() -> None:
    makefile = Path("Makefile").read_text()
    assert "FAST_BACKEND ?= scripted" in makefile
    assert (
        'scripts/run_phase_07a_portfolio_demo.py serve --fast-backend "$(FAST_BACKEND)"'
    ) in makefile


# Phase 07 D2: explicit, fail-closed, loopback-only port overrides.


def test_serve_passes_the_selected_ports(monkeypatch) -> None:
    observed: list[dict[str, object]] = []
    monkeypatch.setattr(demo, "start_demo", lambda **kwargs: observed.append(kwargs))

    assert demo.main(["serve"]) == 0
    assert demo.main(["serve", "--runtime-port", "8011", "--web-port", "3011"]) == 0
    assert observed == [
        {"fast_backend": "scripted", "runtime_port": 8000, "web_port": 3000},
        {"fast_backend": "scripted", "runtime_port": 8011, "web_port": 3011},
    ]


@pytest.mark.parametrize(
    ("runtime_port", "web_port"),
    [
        (0, 3000),
        (8000, 65536),
        (8011, 8011),
        (demo.DEFAULT_POSTGRES_PORT, 3000),
        (8000, demo.DEFAULT_TEMPORAL_PORT),
        (8000, demo.RECOVERY_POSTGRES_PORT),
    ],
)
def test_invalid_or_colliding_ports_are_refused(
    runtime_port: int, web_port: int
) -> None:
    with pytest.raises(demo.DemoScenarioError, match="port"):
        demo.validate_demo_ports(runtime_port, web_port)


def test_invalid_ports_start_nothing(monkeypatch, tmp_path: Path) -> None:
    started: list[str] = []
    monkeypatch.setattr(
        demo, "_start_compose_dependencies", lambda: started.append("compose")
    )

    with pytest.raises(demo.DemoScenarioError, match="port"):
        demo.start_demo(state_dir=tmp_path, runtime_port=8011, web_port=8011)

    assert started == []
    assert not (tmp_path / demo.LIFECYCLE_LOCK_FILE).exists()


def test_startup_checks_exactly_the_selected_ports(monkeypatch) -> None:
    probed: list[int] = []

    def busy_runtime(port: int) -> bool:
        probed.append(port)
        return port != 8011

    monkeypatch.setattr(demo, "_port_is_free", busy_runtime)
    with pytest.raises(demo.DemoScenarioError, match="port 8011 is unavailable"):
        demo._check_startup_ports(runtime_port=8011, web_port=3011)
    assert probed == [3011, 8011]

    probed.clear()

    def all_free(port: int) -> bool:
        probed.append(port)
        return True

    monkeypatch.setattr(demo, "_port_is_free", all_free)
    demo._check_startup_ports()
    assert probed == [
        3000,
        8000,
        demo.DEFAULT_POSTGRES_PORT,
        demo.DEFAULT_TEMPORAL_PORT,
    ]


def test_runtime_origin_is_loopback_for_the_selected_port() -> None:
    assert demo.runtime_origin(8000) == "http://127.0.0.1:8000"
    assert demo.runtime_origin(8011) == "http://127.0.0.1:8011"
    environment = demo.build_demo_environment({}, runtime_port=8011)
    assert environment["PROXYLOOP_RUNTIME_ORIGIN"] == "http://127.0.0.1:8011"
    inherited = {"PROXYLOOP_RUNTIME_ORIGIN": "http://evil.example:80"}
    assert demo.build_demo_environment(inherited)["PROXYLOOP_RUNTIME_ORIGIN"] == (
        "http://127.0.0.1:8000"
    )


def test_web_build_receives_the_selected_runtime_origin(
    monkeypatch, tmp_path: Path
) -> None:
    observed: list[dict[str, str]] = []

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        observed.append(environment)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(demo.subprocess, "run", fake_run)
    demo._build_web_app(tmp_path, runtime_port=8011)

    assert observed[0]["PROXYLOOP_RUNTIME_ORIGIN"] == "http://127.0.0.1:8011"


def test_host_services_bind_the_selected_ports(monkeypatch, tmp_path: Path) -> None:
    launched: list[tuple[list[str], dict[str, str]]] = []

    class FakePopen:
        pid = 4242

        def __init__(self, command: list[str], **kwargs: object) -> None:
            environment = kwargs["env"]
            assert isinstance(environment, dict)
            launched.append((command, environment))

    monkeypatch.setattr(demo.subprocess, "Popen", FakePopen)
    demo._spawn_host_services(tmp_path, runtime_port=8011, web_port=3011)

    commands = {command[-1]: command for command, _ in launched}
    assert "proxyloop_api.server" in commands["8011"]
    assert "start" in commands["3011"]
    assert all(
        environment["PROXYLOOP_RUNTIME_ORIGIN"] == "http://127.0.0.1:8011"
        for _, environment in launched
    )


def test_make_passes_the_port_overrides_and_runtime_url() -> None:
    makefile = Path("Makefile").read_text()
    assert "RUNTIME_PORT ?= 8000" in makefile
    assert "WEB_PORT ?= 3000" in makefile
    assert '--runtime-port "$(RUNTIME_PORT)" --web-port "$(WEB_PORT)"' in makefile
    assert 'scene-channel --runtime-url "http://127.0.0.1:$(RUNTIME_PORT)"' in makefile
    assert "portfolio-demo-journey:" in makefile
    assert 'journey --runtime-url "http://127.0.0.1:$(RUNTIME_PORT)"' in makefile


# Phase 07 D3: Scene J, the scripted journey driver.

MARKER = "zebra-7731"
APPROVAL_ID = "11111111-1111-4111-8111-111111111111"


class _FakeTrace:
    def __init__(self, role: str, result: str) -> None:
        self.role = role
        self.result = result


class _FakeRepository:
    def __init__(self, traces: list[_FakeTrace], *, fresh: bool = True) -> None:
        self._traces = traces
        self._fresh = fresh

    def get(self, _case_id: object) -> object | None:
        return None if self._fresh else object()

    def list_model_traces(self, _case_id: object) -> tuple[_FakeTrace, ...]:
        return tuple(self._traces)


def _payload(
    revision: int,
    events: list[tuple[str, str, str]],
    *,
    approval: str | None,
    executions: int,
    complete: bool,
) -> dict[str, object]:
    return {
        "case_id": str(SCRIPTED_CASE_ID),
        "revision": revision,
        "approval": None
        if approval is None
        else {
            "approval_id": APPROVAL_ID,
            "case_revision": 3,
            "action_intent_revision": 1,
            "decision": approval,
        },
        "snapshot": {
            "visible_events": [
                {
                    "event_cursor": index,
                    "actor": actor,
                    "event_type": kind,
                    "content": text,
                }
                for index, (actor, kind, text) in enumerate(events, start=1)
            ]
        },
        "evidence": [{"evidence_id": "ev-1", "source_type": "confirmation"}]
        if complete
        else [],
        "completion": {
            "decision": "complete" if complete else "not_done",
            "evidence_ids": ["ev-1"] if complete else [],
        },
        "execution_count": executions,
    }


def _fake_runtime(
    *,
    line: str = demo.SCRIPTED_DIALOGUE_LINES[0],
    replay_executes_again: bool = False,
    echo_marker: bool = False,
) -> tuple[httpx.MockTransport, list[tuple[str, str, str | None]]]:
    calls: list[tuple[str, str, str | None]] = []
    offer = ("provider", "provider_offer", "Fictional offer")
    confirm_events = [
        offer,
        ("consumer", "consumer_message", demo.CONFIRMATION_EVENT),
        ("system", "assistant_message", line),
    ]
    approvals = {"count": 0}

    def executions() -> int:
        return approvals["count"] if replay_executes_again else 1

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((request.method, path, request.headers.get("Idempotency-Key")))
        if path == "/health/ready":
            return httpx.Response(
                200,
                json={
                    "ready": True,
                    "adapter_mode": "scripted",
                    "storage_mode": "postgres",
                    "orchestration_mode": "temporal",
                },
            )
        if path == "/intake/proposals":
            body: dict[str, object] = {
                "parser": "intake-parser-v1",
                "proposal": {
                    "current_monthly_total": {"amount_minor": 9200, "currency": "USD"},
                    "target_monthly_total": {"amount_minor": 7500, "currency": "USD"},
                    "mobile_hotspot_required": True,
                    "device_financing_change_forbidden": None,
                },
                "clarifications": [
                    {"field": "device_financing_change_forbidden", "reason": "missing"}
                ],
            }
            if echo_marker:
                body["echo"] = MARKER
            return httpx.Response(200, json=body)
        if path == "/cases" and request.method == "POST":
            created = json.loads(request.content)
            assert created["device_financing_change_forbidden"] is True
            return httpx.Response(
                201,
                json=_payload(2, [offer], approval=None, executions=0, complete=False),
            )
        if path.endswith("/events"):
            return httpx.Response(
                200,
                json=_payload(
                    4, confirm_events, approval="pending", executions=0, complete=False
                ),
            )
        if "/approvals/" in path:
            approvals["count"] += 1
        if "/approvals/" in path or request.method == "GET":
            return httpx.Response(
                200,
                json=_payload(
                    6,
                    confirm_events,
                    approval="approved",
                    executions=executions(),
                    complete=True,
                ),
            )
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler), calls


def _scripted_traces() -> list[_FakeTrace]:
    return [
        _FakeTrace("slow", "succeeded"),
        _FakeTrace("judge", "succeeded"),
        _FakeTrace("fast", "succeeded"),
    ]


def _logs(directory: Path, extra: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name in demo.JOURNEY_LOG_FILES:
        (directory / name).write_text("started\n" + extra)
    return directory


def _operation(request: httpx.Request) -> str:
    path = request.url.path
    if path == "/health/ready":
        return "health_ready"
    if path == "/intake/proposals":
        return "intake_proposal"
    if path == "/cases":
        return "create_case"
    if path.endswith("/events"):
        return "append_event"
    if "/approvals/" in path:
        return "decide_approval"
    return "get_case"


def _run(
    tmp_path: Path,
    transport: httpx.MockTransport,
    traces: list[_FakeTrace],
    *,
    fresh: bool = True,
    log_dir: Path | None = None,
    evidence_path: Path | None = None,
    record: Callable[[httpx.Request, httpx.Response], list[dict[str, object]]]
    | None = None,
) -> dict[str, object]:
    """Run the journey; the fake Runtime appends its operation records (F1)."""

    selected = log_dir if log_dir is not None else _logs(tmp_path / "logs")

    def recorded(request: httpx.Request) -> httpx.Response:
        response = transport.handle_request(request)
        response.read()
        lines = (
            record(request, response)
            if record is not None
            else [
                {
                    "correlation_id": "c",
                    "operation": _operation(request),
                    "error_category": "none",
                    "status": response.status_code,
                }
            ]
        )
        runtime_log = selected / "runtime.log"
        if runtime_log.is_file():
            with runtime_log.open("a") as log_file:
                for line in lines:
                    log_file.write(json.dumps(line) + "\n")
        return response

    with httpx.Client(
        base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(recorded)
    ) as client:
        return demo.run_journey(
            client=client,
            repository=_FakeRepository(traces, fresh=fresh),
            log_dir=selected,
            evidence_path=evidence_path,
        )


def test_journey_drives_the_web_routes_in_order_and_replays_the_approval(
    tmp_path: Path,
) -> None:
    transport, calls = _fake_runtime()
    evidence = _run(tmp_path, transport, _scripted_traces())

    assert [(method, path) for method, path, _ in calls] == [
        ("GET", "/health/ready"),
        ("POST", "/intake/proposals"),
        ("POST", "/cases"),
        ("POST", f"/cases/{SCRIPTED_CASE_ID}/events"),
        ("POST", f"/cases/{SCRIPTED_CASE_ID}/approvals/{APPROVAL_ID}"),
        ("POST", f"/cases/{SCRIPTED_CASE_ID}/approvals/{APPROVAL_ID}"),
        ("GET", f"/cases/{SCRIPTED_CASE_ID}"),
    ]
    approval_keys = [key for _, path, key in calls if "/approvals/" in path]
    assert approval_keys[0] is not None
    assert approval_keys[0] == approval_keys[1]
    assert evidence["assistant_line"] == "model"
    assert evidence["execution_count"] == {"after_approve": 1, "after_replay": 1}
    assert evidence["replay_revision_unchanged"] is True
    assert evidence["receipt_predicate"] is True
    trace_counts = evidence["trace_counts"]
    assert isinstance(trace_counts, dict)
    assert trace_counts["judge"] == {"failed": 0, "rejected": 0, "succeeded": 1}
    assert evidence["revisions"] == {"create": 2, "confirm": 4, "approve": 6}
    assert evidence["marker_absent"] == {
        "proposal_response": True,
        "runtime.log": True,
        "web.log": True,
        "worker.log": True,
    }


def test_journey_evidence_is_content_free_and_deterministic(tmp_path: Path) -> None:
    first = _run(tmp_path, _fake_runtime()[0], _scripted_traces())
    second = _run(tmp_path, _fake_runtime()[0], _scripted_traces())
    encoded = demo.render_journey_evidence(first)

    assert encoded == demo.render_journey_evidence(second)
    for forbidden in (
        MARKER,
        str(SCRIPTED_CASE_ID),
        APPROVAL_ID,
        demo.SCRIPTED_DIALOGUE_LINES[0],
        demo.CONFIRMATION_EVENT,
        "ev-1",
    ):
        assert forbidden not in encoded


def test_journey_writes_evidence_only_when_asked(tmp_path: Path) -> None:
    target = tmp_path / "evidence.json"
    _run(tmp_path, _fake_runtime()[0], _scripted_traces())
    assert not target.exists()
    evidence = _run(
        tmp_path, _fake_runtime()[0], _scripted_traces(), evidence_path=target
    )
    assert target.read_text() == demo.render_journey_evidence(evidence)


@pytest.mark.parametrize(
    "roles",
    [
        ("slow", "fast"),
        ("slow", "judge", "slow", "fast"),
        ("slow", "judge", "fast", "fast"),
    ],
)
def test_journey_refuses_unexpected_scripted_trace_counts(
    tmp_path: Path, roles: tuple[str, ...]
) -> None:
    traces = [_FakeTrace(role, "succeeded") for role in roles]
    with pytest.raises(demo.DemoScenarioError, match="trace"):
        _run(tmp_path, _fake_runtime()[0], traces)


def test_journey_refuses_a_replay_that_executes_again(tmp_path: Path) -> None:
    with pytest.raises(demo.DemoScenarioError, match="execut"):
        _run(
            tmp_path,
            _fake_runtime(replay_executes_again=True)[0],
            _scripted_traces(),
        )


def test_journey_refuses_a_fallback_line_on_the_scripted_backend(
    tmp_path: Path,
) -> None:
    with pytest.raises(demo.DemoScenarioError, match="assistant"):
        _run(
            tmp_path,
            _fake_runtime(line=demo.FAST_FALLBACK_TEXT)[0],
            _scripted_traces(),
        )


def test_journey_refuses_state_that_is_not_fresh(tmp_path: Path) -> None:
    with pytest.raises(demo.DemoScenarioError, match="not fresh"):
        _run(tmp_path, _fake_runtime()[0], _scripted_traces(), fresh=False)


def test_journey_refuses_the_marker_in_a_log(tmp_path: Path) -> None:
    leaky = _logs(tmp_path / "leaky", extra=MARKER)
    with pytest.raises(demo.DemoScenarioError, match="marker"):
        _run(tmp_path, _fake_runtime()[0], _scripted_traces(), log_dir=leaky)


def test_journey_refuses_the_marker_in_the_proposal(tmp_path: Path) -> None:
    with pytest.raises(demo.DemoScenarioError, match="marker"):
        _run(tmp_path, _fake_runtime(echo_marker=True)[0], _scripted_traces())


def test_journey_refuses_a_missing_log(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(demo.DemoScenarioError, match="log"):
        _run(tmp_path, _fake_runtime()[0], _scripted_traces(), log_dir=empty)


def test_receipt_predicate_matches_the_web_rule() -> None:
    complete = _payload(6, [], approval="approved", executions=1, complete=True)
    assert demo.completion_has_verified_evidence(complete) is True
    twice = _payload(6, [], approval="approved", executions=2, complete=True)
    assert demo.completion_has_verified_evidence(twice) is False
    missing = _payload(6, [], approval="approved", executions=1, complete=True)
    missing["evidence"] = []
    assert demo.completion_has_verified_evidence(missing) is False
    pending = _payload(4, [], approval="pending", executions=0, complete=False)
    assert demo.completion_has_verified_evidence(pending) is False


def test_journey_subcommand_is_wired(monkeypatch) -> None:
    observed: list[dict[str, object]] = []
    monkeypatch.setattr(
        demo, "run_journey_command", lambda **kwargs: observed.append(kwargs)
    )
    assert demo.main(["journey", "--runtime-url", "http://127.0.0.1:8011"]) == 0
    assert demo.main(["journey", "--write-evidence"]) == 0
    assert observed[0]["runtime_url"] == "http://127.0.0.1:8011"
    assert observed[0]["write_evidence"] is False
    assert observed[1]["runtime_url"] == demo.DEFAULT_RUNTIME_URL
    assert observed[1]["write_evidence"] is True


def test_journey_uses_the_web_confirmation_and_intake_marker() -> None:
    workspace = Path("apps/web/app/components/conversation-workspace.tsx").read_text()
    assert f'"{demo.CONFIRMATION_EVENT}"' in workspace
    assert demo.JOURNEY_MARKER in demo.JOURNEY_MESSAGE


def test_journey_records_one_operation_record_per_request(tmp_path: Path) -> None:
    evidence = _run(tmp_path, _fake_runtime()[0], _scripted_traces())
    assert evidence["operation_records"] == {
        "count": 7,
        "by_operation": demo.EXPECTED_JOURNEY_OPERATIONS,
        "error_categories": {"none": 7},
    }


def test_journey_refuses_missing_operation_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(demo, "OPERATION_RECORD_WAIT_S", 0.2)
    with pytest.raises(demo.DemoScenarioError, match="operation record"):
        _run(
            tmp_path,
            _fake_runtime()[0],
            _scripted_traces(),
            record=lambda _request, _response: [],
        )


def test_journey_refuses_an_extra_or_failed_operation_record(tmp_path: Path) -> None:
    def doubled(request: httpx.Request, response: httpx.Response):
        line = {
            "correlation_id": "c",
            "operation": _operation(request),
            "error_category": "none",
            "status": response.status_code,
        }
        return [line, line] if request.url.path == "/intake/proposals" else [line]

    with pytest.raises(demo.DemoScenarioError, match="operation record"):
        _run(tmp_path, _fake_runtime()[0], _scripted_traces(), record=doubled)

    def failed(request: httpx.Request, response: httpx.Response):
        category = "stale_cas" if request.url.path.endswith("/events") else "none"
        return [
            {
                "correlation_id": "c",
                "operation": _operation(request),
                "error_category": category,
                "status": response.status_code,
            }
        ]

    with pytest.raises(demo.DemoScenarioError, match="operation record"):
        _run(tmp_path / "second", _fake_runtime()[0], _scripted_traces(), record=failed)
