"""Small, credential-free supervisor and fixture driver for Phase 07A.

The supervisor owns only the local demo process lifecycle.  It deliberately
does not become a service manager: Compose owns infrastructure, while this
script starts and stops the host Worker, Runtime, and Web processes.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, Protocol
from uuid import UUID

import httpx
import psycopg
from proxyloop_case_runtime import SCRIPTED_CASE_ID, PostgresCaseRepository
from proxyloop_connectors import (
    BINDING_REF,
    SCHEMA_VERSION,
    build_fixture_headers,
)
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client
from temporalio.service import RPCError

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POSTGRES_PORT = 55433
DEFAULT_TEMPORAL_PORT = 7234
DEFAULT_DATABASE_URL = (
    f"postgresql://proxyloop:proxyloop@127.0.0.1:{DEFAULT_POSTGRES_PORT}/proxyloop"
)
DEFAULT_TEMPORAL_ADDRESS = f"127.0.0.1:{DEFAULT_TEMPORAL_PORT}"
DEFAULT_RUNTIME_URL = "http://127.0.0.1:8000"
DEFAULT_WEB_URL = "http://127.0.0.1:3000"
DEFAULT_STATE_DIR = Path(tempfile.gettempdir()) / "proxyloop-portfolio-demo"
COMPOSE_PROJECT_NAME = "proxyloop-portfolio-demo"
COMPOSE_VOLUME_NAME = f"{COMPOSE_PROJECT_NAME}_postgres-data"
PID_FILE = "pids.json"
STOP_FILE = "stop.requested"
LIFECYCLE_LOCK_FILE = "lifecycle.lock"
COMMAND_LOCK_FILE = "command.lock"
LOG_DIR_NAME = "logs"
COMPOSE_SERVICES = ("postgres", "temporal")
COMPOSE_OVERRIDE_KEYS = (
    "COMPOSE_FILE",
    "COMPOSE_PROJECT_NAME",
    "COMPOSE_PROFILES",
    "POSTGRES_DB",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
    "POSTGRES_TEST_PORT",
    "POSTGRES_USER",
    "TEMPORAL_PORT",
    "TEMPORAL_UI_PORT",
)
HOST_SERVICE_NAMES = ("worker", "runtime", "web")
HOST_PROCESS_MARKERS = {
    "worker": "proxyloop_workflow_worker.worker",
    "runtime": "proxyloop_api.server",
    "web": "@proxyloop/web",
}
MODEL_ENVIRONMENT_KEYS = (
    "PROXYLOOP_MODEL_API_KEY",
    "PROXYLOOP_MODEL_BASE_URL",
    "PROXYLOOP_MODEL_NAME",
)
INBOUND_EVENT_ID = UUID("77777777-7777-4777-8777-777777777777")
CALLBACK_EVENT_ID = UUID("88888888-8888-4888-8888-888888888888")
CREATE_IDEMPOTENCY_KEY = "33333333-3333-4333-8333-333333333333"
INBOUND_CONTENT = "Synthetic Provider message for the local portfolio demo."
RECOVERY_DATABASE_URL = (
    "postgresql://proxyloop:proxyloop@127.0.0.1:55434/proxyloop_test"
)


class DemoScenarioError(RuntimeError):
    """A safe, user-actionable local demo failure."""


class _ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...


class _PidHandle:
    """Minimal process handle for stopping a process recorded by another shell."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> int | None:
        return None if _pid_is_running(self.pid) else 0


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_utc(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include UTC")
    return parsed.astimezone(UTC)


def build_demo_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return explicit demo settings without inheriting model credentials."""

    values = dict(os.environ if environ is None else environ)
    for key in MODEL_ENVIRONMENT_KEYS:
        values.pop(key, None)
    values.update(
        {
            "PROXYLOOP_RUNTIME_MODE": "scripted",
            "PROXYLOOP_STORAGE_MODE": "postgres",
            "PROXYLOOP_ORCHESTRATION_MODE": "temporal",
            "PROXYLOOP_DATABASE_URL": DEFAULT_DATABASE_URL,
            "PROXYLOOP_TEMPORAL_ADDRESS": DEFAULT_TEMPORAL_ADDRESS,
            "PROXYLOOP_TEMPORAL_NAMESPACE": "default",
            "PROXYLOOP_TEMPORAL_TASK_QUEUE": "proxyloop-case-workflow",
            "PROXYLOOP_TEMPORAL_CONTINUE_AS_NEW_AFTER": "32",
        }
    )
    return values


def build_provider_message_body(occurred_at: datetime) -> bytes:
    payload = {
        "binding_ref": BINDING_REF,
        "content": INBOUND_CONTENT,
        "event_id": str(INBOUND_EVENT_ID),
        "kind": "provider_message",
        "occurred_at": occurred_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "schema_version": SCHEMA_VERSION,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return encoded.encode("utf-8")


def build_delivery_body(
    delivery_id: UUID,
    provider_message_id: str,
    occurred_at: datetime,
) -> bytes:
    payload = {
        "binding_ref": BINDING_REF,
        "delivery_id": str(delivery_id),
        "delivery_status": "delivered",
        "event_id": str(CALLBACK_EVENT_ID),
        "kind": "delivery",
        "occurred_at": occurred_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "provider_message_id": provider_message_id,
        "schema_version": SCHEMA_VERSION,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return encoded.encode("utf-8")


def assert_browser_projection_isolated(
    payload: Mapping[str, Any], *, forbidden: tuple[str, ...]
) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if any(value and value in encoded for value in forbidden):
        raise DemoScenarioError("browser projection contains channel material")
    snapshot = payload.get("snapshot")
    snapshot_evidence = (
        snapshot.get("evidence") if isinstance(snapshot, Mapping) else None
    )
    for container in (
        payload.get("evidence"),
        snapshot_evidence,
    ):
        if not isinstance(container, list):
            continue
        if any(
            isinstance(item, Mapping) and _is_channel_evidence(item)
            for item in container
        ):
            raise DemoScenarioError("browser projection contains channel material")
    visible_events = (
        snapshot.get("visible_events") if isinstance(snapshot, Mapping) else None
    )
    if isinstance(visible_events, list) and any(
        isinstance(item, Mapping)
        and item.get("actor") == "provider"
        and item.get("event_type") in {"provider_message", "provider_event"}
        for item in visible_events
    ):
        raise DemoScenarioError("browser projection contains channel material")


def _is_channel_evidence(item: Mapping[str, Any]) -> bool:
    source_type = item.get("source_type")
    if source_type == "provider_event":
        return True
    if source_type != "provider_message":
        return False
    source_ref = item.get("source_ref")
    if not isinstance(source_ref, str):
        return False
    try:
        parsed = UUID(source_ref)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == source_ref


def assert_authoritative_channel_evidence(
    evidence_refs: Sequence[tuple[str, str]], *, provider_message_id: str
) -> None:
    expected = (
        ("provider_message", str(INBOUND_EVENT_ID)),
        ("provider_event", provider_message_id),
    )
    if any(evidence_refs.count(reference) != 1 for reference in expected):
        raise DemoScenarioError("authoritative channel Evidence was incomplete")


def _state_dir(path: Path | None = None) -> Path:
    return path or DEFAULT_STATE_DIR


def _log_dir(path: Path | None = None) -> Path:
    return _state_dir(path) / LOG_DIR_NAME


def _pid_file(path: Path | None = None) -> Path:
    return _state_dir(path) / PID_FILE


def _stop_file(path: Path | None = None) -> Path:
    return _state_dir(path) / STOP_FILE


def _lifecycle_lock_file(path: Path | None = None) -> Path:
    return _state_dir(path) / LIFECYCLE_LOCK_FILE


def _command_lock_file(path: Path | None = None) -> Path:
    return _state_dir(path) / COMMAND_LOCK_FILE


@contextmanager
def _lifecycle_command_guard(state_dir: Path, *, blocking: bool) -> Iterator[None]:
    state_dir.mkdir(parents=True, exist_ok=True)
    with _command_lock_file(state_dir).open("a+") as stream:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(stream.fileno(), flags)
        except BlockingIOError:
            raise DemoScenarioError(
                "another portfolio demo lifecycle command is in progress"
            ) from None
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _claim_lifecycle_lock(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_file = _lifecycle_lock_file(state_dir)
    for _attempt in range(2):
        try:
            descriptor = os.open(
                lock_file,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            owner = _read_lifecycle_owner(state_dir)
            if _pid_matches_lifecycle_owner(owner):
                raise DemoScenarioError(
                    "portfolio demo is already starting or running"
                ) from None
            try:
                lock_file.unlink()
            except FileNotFoundError:
                continue
        else:
            try:
                with os.fdopen(descriptor, "w") as stream:
                    json.dump({"pid": os.getpid()}, stream)
                    stream.write("\n")
            except OSError:
                lock_file.unlink(missing_ok=True)
                raise
            return
    raise DemoScenarioError("could not claim the portfolio demo lifecycle lock")


def _read_lifecycle_owner(state_dir: Path) -> int:
    try:
        value = json.loads(_lifecycle_lock_file(state_dir).read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise DemoScenarioError("portfolio demo lifecycle state is invalid") from exc
    owner = value.get("pid") if isinstance(value, dict) else None
    if not isinstance(owner, int) or isinstance(owner, bool) or owner <= 1:
        raise DemoScenarioError("portfolio demo lifecycle state is invalid")
    return owner


def _pid_matches_lifecycle_owner(pid: int) -> bool:
    if not _pid_is_running(pid):
        return False
    try:
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return (
        command.returncode == 0
        and "run_phase_07a_portfolio_demo.py" in command.stdout
        and "serve" in command.stdout
    )


def _release_lifecycle_lock(state_dir: Path) -> None:
    lock_file = _lifecycle_lock_file(state_dir)
    if not lock_file.exists():
        return
    if _read_lifecycle_owner(state_dir) != os.getpid():
        raise DemoScenarioError("portfolio demo lifecycle ownership changed")
    lock_file.unlink()


def _wait_for_lifecycle_release(state_dir: Path, *, timeout: float = 30) -> None:
    lock_file = _lifecycle_lock_file(state_dir)
    deadline = time.monotonic() + timeout
    while lock_file.exists() and time.monotonic() < deadline:
        try:
            owner = _read_lifecycle_owner(state_dir)
        except DemoScenarioError:
            time.sleep(0.1)
            continue
        if not _pid_matches_lifecycle_owner(owner):
            lock_file.unlink(missing_ok=True)
            return
        time.sleep(0.1)
    if lock_file.exists():
        raise DemoScenarioError(
            "portfolio demo stop was requested but the supervisor is still running"
        )


def _raise_if_stop_requested(state_dir: Path) -> None:
    if _stop_file(state_dir).exists():
        raise KeyboardInterrupt


def _initialize_startup_state(state_dir: Path) -> None:
    with _lifecycle_command_guard(state_dir, blocking=False):
        _claim_lifecycle_lock(state_dir)
        try:
            _stop_file(state_dir).unlink(missing_ok=True)
        except OSError:
            _release_lifecycle_lock(state_dir)
            raise


def _request_supervisor_stop(state_dir: Path, *, reason: str) -> None:
    lifecycle_active = _lifecycle_lock_file(state_dir).exists()
    if lifecycle_active or _pid_file(state_dir).exists():
        _stop_file(state_dir).write_text(reason)
    if lifecycle_active:
        _wait_for_lifecycle_release(state_dir)
    processes = _running_processes(state_dir)
    _terminate_processes(processes)
    _pid_file(state_dir).unlink(missing_ok=True)


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    for key in (*MODEL_ENVIRONMENT_KEYS, *COMPOSE_OVERRIDE_KEYS):
        environment.pop(key, None)
    environment.update(
        {
            "POSTGRES_DB": "proxyloop",
            "POSTGRES_USER": "proxyloop",
            "POSTGRES_PASSWORD": "proxyloop",
            "POSTGRES_PORT": str(DEFAULT_POSTGRES_PORT),
            "POSTGRES_TEST_PORT": "55434",
            "TEMPORAL_PORT": str(DEFAULT_TEMPORAL_PORT),
        }
    )
    return subprocess.run(
        ["docker", "compose", "--project-name", COMPOSE_PROJECT_NAME, *args],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=check,
        text=True,
        capture_output=True,
    )


def _wait_for_tcp(host: str, port: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _wait_for_postgres(database_url: str, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(database_url, connect_timeout=1) as connection:
                connection.execute("SELECT 1")
            return True
        except psycopg.Error:
            time.sleep(0.2)
    return False


def _wait_for_url(url: str, *, timeout: float, expected_status: set[int]) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=1.0)
            if response.status_code in expected_status:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    return False


async def _temporal_namespace_ready(address: str, namespace: str) -> bool:
    try:
        client = await Client.connect(address, namespace=namespace)
        await client.service_client.workflow_service.describe_namespace(
            DescribeNamespaceRequest(namespace=namespace)
        )
    except (OSError, RPCError, RuntimeError):
        return False
    return True


def _wait_for_temporal_namespace(
    address: str, namespace: str, *, timeout: float
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if asyncio.run(_temporal_namespace_ready(address, namespace)):
            return True
        time.sleep(0.2)
    return False


def _port_is_free(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return False
    except OSError:
        return True


def _check_startup_ports() -> None:
    for port in (
        3000,
        8000,
        DEFAULT_POSTGRES_PORT,
        DEFAULT_TEMPORAL_PORT,
    ):
        if not _port_is_free(port):
            raise DemoScenarioError(f"required host port {port} is unavailable")


def _build_web_app(state_dir: Path) -> None:
    log_dir = _log_dir(state_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        with (log_dir / "web-build.log").open("wb") as log_file:
            result = subprocess.run(
                ["pnpm", "--filter", "@proxyloop/web", "build"],
                cwd=REPOSITORY_ROOT,
                env=build_demo_environment(),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=False,
            )
    except OSError as exc:
        error_type = exc.__class__.__name__
        raise DemoScenarioError(f"could not build Web app ({error_type})") from None
    if result.returncode != 0:
        raise DemoScenarioError("Web build failed; inspect logs/web-build.log")


def _spawn_host_services(state_dir: Path) -> dict[str, subprocess.Popen[bytes]]:
    log_dir = _log_dir(state_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    environment = build_demo_environment()
    commands = {
        "worker": [
            "uv",
            "run",
            "--project",
            "runtime",
            "--all-packages",
            "python",
            "-m",
            "proxyloop_workflow_worker.worker",
        ],
        "runtime": [
            "uv",
            "run",
            "--project",
            "runtime",
            "--all-packages",
            "python",
            "-m",
            "proxyloop_api.server",
            "--mode",
            "scripted",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        "web": [
            "pnpm",
            "--filter",
            "@proxyloop/web",
            "start",
            "--hostname",
            "127.0.0.1",
            "--port",
            "3000",
        ],
    }
    processes: dict[str, subprocess.Popen[bytes]] = {}
    try:
        for name, command in commands.items():
            log_file = (log_dir / f"{name}.log").open("ab")
            processes[name] = subprocess.Popen(
                command,
                cwd=REPOSITORY_ROOT,
                env=environment,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            log_file.close()
    except OSError as exc:
        _terminate_processes(processes)
        error_type = exc.__class__.__name__
        raise DemoScenarioError(
            f"could not start host service ({error_type})"
        ) from None
    _pid_file(state_dir).parent.mkdir(parents=True, exist_ok=True)
    _pid_file(state_dir).write_text(
        json.dumps(
            {name: process.pid for name, process in processes.items()},
            sort_keys=True,
        )
        + "\n"
    )
    return processes


def _assert_processes_alive(processes: Mapping[str, _ProcessHandle]) -> None:
    exited = [name for name, process in processes.items() if process.poll() is not None]
    if exited:
        raise DemoScenarioError(f"host service exited ({','.join(exited)})")


def _terminate_processes(processes: Mapping[str, _ProcessHandle]) -> None:
    for process in processes.values():
        if process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and any(
        process.poll() is None for process in processes.values()
    ):
        time.sleep(0.1)
    for process in processes.values():
        if process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)


def _running_processes(state_dir: Path) -> dict[str, _PidHandle]:
    try:
        pids = _read_pids(state_dir)
    except DemoScenarioError:
        return {}
    processes: dict[str, _PidHandle] = {}
    for name, pid in pids.items():
        if not _pid_is_running(pid):
            continue
        if not _pid_matches_expected_process(name, pid):
            raise DemoScenarioError(
                "portfolio demo process state is invalid; refusing to stop an "
                "unexpected process"
            )
        processes[name] = _process_from_pid(pid)
    return processes


def _pid_matches_expected_process(name: str, pid: int) -> bool:
    marker = HOST_PROCESS_MARKERS.get(name)
    if marker is None or pid <= 1:
        return False
    try:
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
        )
        group = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pgid="],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return (
        command.returncode == 0
        and marker in command.stdout
        and group.returncode == 0
        and group.stdout.strip() == str(pid)
    )


def _read_pids(state_dir: Path) -> dict[str, int]:
    try:
        raw = json.loads(_pid_file(state_dir).read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise DemoScenarioError("portfolio demo is not running") from exc
    if not isinstance(raw, dict) or any(
        name not in raw or not isinstance(raw[name], int) or isinstance(raw[name], bool)
        for name in HOST_SERVICE_NAMES
    ):
        raise DemoScenarioError("portfolio demo process state is invalid")
    return {name: raw[name] for name in HOST_SERVICE_NAMES}


def stop_demo(*, state_dir: Path | None = None, stop_compose: bool = True) -> None:
    selected = _state_dir(state_dir)
    with _lifecycle_command_guard(selected, blocking=True):
        _request_supervisor_stop(selected, reason="external stop requested\n")
        if stop_compose:
            result = _compose("stop", *COMPOSE_SERVICES, check=False)
            if result.returncode != 0:
                raise DemoScenarioError("could not stop local Compose dependencies")
        _stop_file(selected).unlink(missing_ok=True)
    print("Stopped local portfolio demo; PostgreSQL volume was preserved.")


def _process_from_pid(pid: int) -> _PidHandle:
    return _PidHandle(pid)


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def reset_demo() -> None:
    print(
        "Reset scope: stop and remove only the Compose volume "
        f"{COMPOSE_VOLUME_NAME}; no other Docker volumes or files will be "
        "touched."
    )
    with _lifecycle_command_guard(DEFAULT_STATE_DIR, blocking=True):
        _request_supervisor_stop(DEFAULT_STATE_DIR, reason="external reset requested\n")
        _stop_file(DEFAULT_STATE_DIR).unlink(missing_ok=True)
        result = _compose("stop", *COMPOSE_SERVICES, check=False)
        if result.returncode != 0:
            raise DemoScenarioError(
                "could not stop local Compose dependencies for reset"
            )
        # Stopping leaves containers attached to the volume. Remove only the
        # named demo service containers before removing the one named volume.
        removed = _compose("rm", "-sf", *COMPOSE_SERVICES, check=False)
        if removed.returncode != 0:
            raise DemoScenarioError(
                "could not remove the named demo Compose containers"
            )
        inspected = subprocess.run(
            ["docker", "volume", "inspect", COMPOSE_VOLUME_NAME],
            cwd=REPOSITORY_ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        if inspected.returncode not in {0, 1}:
            raise DemoScenarioError(
                "could not inspect the named demo PostgreSQL volume"
            )
        if inspected.returncode == 0:
            volume = subprocess.run(
                ["docker", "volume", "rm", COMPOSE_VOLUME_NAME],
                cwd=REPOSITORY_ROOT,
                check=False,
                text=True,
                capture_output=True,
            )
            if volume.returncode != 0:
                raise DemoScenarioError(
                    "could not remove the named demo PostgreSQL volume"
                )
        verified_absent = subprocess.run(
            ["docker", "volume", "inspect", COMPOSE_VOLUME_NAME],
            cwd=REPOSITORY_ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        if verified_absent.returncode == 0:
            raise DemoScenarioError("named demo PostgreSQL volume is still present")
        if verified_absent.returncode != 1:
            raise DemoScenarioError(
                "could not verify the named demo PostgreSQL volume reset"
            )
    print(
        "Reset complete. The next demo startup will create a fresh PostgreSQL volume."
    )


def _start_compose_dependencies() -> None:
    try:
        result = _compose("up", "-d", *COMPOSE_SERVICES)
        if result.returncode != 0:
            raise DemoScenarioError("could not start Compose dependencies")
        if not _wait_for_postgres(DEFAULT_DATABASE_URL, timeout=45):
            raise DemoScenarioError(
                "PostgreSQL did not become ready; inspect Compose status"
            )
        if not _wait_for_tcp("127.0.0.1", DEFAULT_TEMPORAL_PORT, timeout=45):
            raise DemoScenarioError(
                "Temporal did not become ready; inspect Compose status"
            )
        if not _wait_for_temporal_namespace(
            DEFAULT_TEMPORAL_ADDRESS, "default", timeout=45
        ):
            raise DemoScenarioError(
                "Temporal default namespace did not become ready; inspect Compose logs"
            )
    except (OSError, subprocess.CalledProcessError) as exc:
        _compose("stop", *COMPOSE_SERVICES, check=False)
        error_type = exc.__class__.__name__
        raise DemoScenarioError(
            f"could not start Compose dependencies ({error_type})"
        ) from None
    except DemoScenarioError:
        _compose("stop", *COMPOSE_SERVICES, check=False)
        raise


def start_demo(*, state_dir: Path | None = None) -> None:
    selected = _state_dir(state_dir)
    _initialize_startup_state(selected)
    processes: dict[str, subprocess.Popen[bytes]] = {}
    compose_started = False
    try:
        if _pid_file(selected).exists():
            raise DemoScenarioError(
                "portfolio demo already has a process state; run "
                "make portfolio-demo-stop"
            )
        _raise_if_stop_requested(selected)
        _check_startup_ports()
        _start_compose_dependencies()
        compose_started = True
        _raise_if_stop_requested(selected)
        _build_web_app(selected)
        _raise_if_stop_requested(selected)
        processes = _spawn_host_services(selected)
        _raise_if_stop_requested(selected)
        _assert_processes_alive(processes)
        if not _wait_for_url(
            f"{DEFAULT_RUNTIME_URL}/health/ready", timeout=45, expected_status={200}
        ):
            raise DemoScenarioError(
                "Runtime readiness did not pass; inspect logs/runtime.log"
            )
        _assert_processes_alive(processes)
        if not _wait_for_url(DEFAULT_WEB_URL, timeout=45, expected_status={200}):
            raise DemoScenarioError("Web did not become ready; inspect logs/web.log")
        _assert_processes_alive(processes)
        print(f"Web: {DEFAULT_WEB_URL}")
        print(f"Runtime readiness: {DEFAULT_RUNTIME_URL}/health/ready")
        print(f"Temporal server: {DEFAULT_TEMPORAL_ADDRESS}")
        print(
            "Scene order: Scene A Web Case, then reset, then Scene B synthetic "
            "local_mailbox."
        )
        print(
            f"Logs: {_log_dir(selected)}/web-build.log, "
            f"{_log_dir(selected)}/worker.log, "
            f"{_log_dir(selected)}/runtime.log, {_log_dir(selected)}/web.log"
        )
        print("Stop: make portfolio-demo-stop (or Ctrl-C in this command).")
        try:
            while True:
                _raise_if_stop_requested(selected)
                _assert_processes_alive(processes)
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    finally:
        _terminate_processes(processes)
        if compose_started:
            _compose("stop", *COMPOSE_SERVICES, check=False)
        _pid_file(selected).unlink(missing_ok=True)
        _stop_file(selected).unlink(missing_ok=True)
        _release_lifecycle_lock(selected)


def _post_fixture(
    client: httpx.Client,
    raw: bytes,
    *,
    expected_status: int,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    try:
        response = client.post(
            "/channels/local_mailbox/events",
            content=raw,
            headers=headers or build_fixture_headers(raw),
        )
    except httpx.HTTPError:
        raise DemoScenarioError("Runtime channel request was unavailable") from None
    if response.status_code != expected_status:
        status = response.status_code
        raise DemoScenarioError(f"Runtime channel request failed ({status})")
    try:
        value = response.json()
    except ValueError:
        raise DemoScenarioError("Runtime channel response was not JSON") from None
    if not isinstance(value, dict):
        raise DemoScenarioError("Runtime channel response shape was invalid")
    return value


def _count_rows(database_url: str, table: str, column: str, value: UUID) -> int:
    allowed = {
        "proxyloop_channel_inbox_receipts": "event_id",
        "proxyloop_channel_outbox_records": "delivery_id",
        "proxyloop_channel_delivery_receipts": "delivery_id",
    }
    if allowed.get(table) != column:
        raise DemoScenarioError("portfolio demo database assertion was not allowlisted")
    try:
        with psycopg.connect(database_url) as connection:
            row = connection.execute(
                f"SELECT count(*) FROM {table} WHERE {column} = %s", (value,)
            ).fetchone()
    except psycopg.Error:
        raise DemoScenarioError(
            "PostgreSQL channel assertion was unavailable"
        ) from None
    if row is None:
        raise DemoScenarioError("PostgreSQL channel assertion returned no row")
    return int(row[0])


def _wait_for_accepted(repository: PostgresCaseRepository, delivery_id: UUID) -> Any:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        outbox = repository.get_outbox_record(delivery_id)
        if outbox is not None and outbox.state == "accepted":
            return outbox
        time.sleep(0.2)
    raise DemoScenarioError("local mailbox delivery did not reach accepted state")


def run_channel_scene(
    *,
    runtime_url: str = DEFAULT_RUNTIME_URL,
    database_url: str = DEFAULT_DATABASE_URL,
) -> None:
    try:
        repository = PostgresCaseRepository(database_url)
        if repository.get(SCRIPTED_CASE_ID) is not None:
            raise DemoScenarioError(
                "demo state is not fresh; run make portfolio-demo-reset first"
            )
        with httpx.Client(base_url=runtime_url, timeout=10.0) as client:
            created = client.post(
                "/cases",
                json={
                    "current_monthly_total": {"amount_minor": 9200, "currency": "USD"},
                    "target_monthly_total": {"amount_minor": 7500, "currency": "USD"},
                    "mobile_hotspot_required": True,
                    "device_financing_change_forbidden": True,
                },
                headers={"Idempotency-Key": CREATE_IDEMPOTENCY_KEY},
            )
            if created.status_code != 201:
                status = created.status_code
                raise DemoScenarioError(f"Runtime Case creation failed ({status})")
            created_payload = created.json()
            case_id = UUID(str(created_payload.get("case_id")))
            if case_id != SCRIPTED_CASE_ID:
                raise DemoScenarioError("Runtime created an unexpected Case")

            occurred_at = datetime.now(UTC)
            inbound_raw = build_provider_message_body(occurred_at)
            inbound_headers = build_fixture_headers(inbound_raw)
            inbound = _post_fixture(
                client,
                inbound_raw,
                expected_status=200,
                headers=inbound_headers,
            )
            delivery_value = inbound.get("delivery_id")
            if not isinstance(delivery_value, str):
                raise DemoScenarioError(
                    "inbound event did not produce a delivery identity"
                )
            delivery_id = UUID(delivery_value)
            duplicate = _post_fixture(
                client,
                inbound_raw,
                expected_status=200,
                headers=inbound_headers,
            )
            if (
                duplicate.get("deduplicated") is not True
                or duplicate.get("delivery_id") != delivery_value
            ):
                raise DemoScenarioError("exact duplicate was not deduplicated")

            inbox = repository.get_inbox_receipt(INBOUND_EVENT_ID)
            if (
                inbox is None
                or inbox.case_id != case_id
                or inbox.processing_state != "applied"
            ):
                raise DemoScenarioError(
                    "inbound event was not server-correlated and applied"
                )
            outbox = _wait_for_accepted(repository, delivery_id)
            provider_message_id = outbox.provider_message_id
            if not provider_message_id or not provider_message_id.startswith(
                "local-provider-"
            ):
                raise DemoScenarioError(
                    "synthetic Provider acceptance reference was invalid"
                )
            inbound_count = _count_rows(
                database_url,
                "proxyloop_channel_inbox_receipts",
                "event_id",
                INBOUND_EVENT_ID,
            )
            if inbound_count != 1:
                raise DemoScenarioError("inbound inbox identity was not unique")
            outbox_count = _count_rows(
                database_url,
                "proxyloop_channel_outbox_records",
                "delivery_id",
                delivery_id,
            )
            if outbox_count != 1:
                raise DemoScenarioError("outbox delivery identity was not unique")

            callback_raw = build_delivery_body(
                delivery_id,
                provider_message_id,
                datetime.now(UTC),
            )
            callback = _post_fixture(client, callback_raw, expected_status=200)
            if callback.get("delivery_status") != "delivered":
                raise DemoScenarioError("synthetic delivery callback was not delivered")
            receipt = repository.get_delivery_receipt(delivery_id)
            if (
                receipt is None
                or receipt.observation_state != "delivered"
                or receipt.provider_message_id != provider_message_id
                or receipt.artifact_hash != sha256_hex(callback_raw)
            ):
                raise DemoScenarioError(
                    "authoritative delivery receipt was not recorded"
                )
            receipt_count = _count_rows(
                database_url,
                "proxyloop_channel_delivery_receipts",
                "delivery_id",
                delivery_id,
            )
            if receipt_count != 1:
                raise DemoScenarioError("delivery receipt identity was not unique")

            state = repository.get(case_id)
            if state is None:
                raise DemoScenarioError("authoritative Case state disappeared")
            evidence_refs = [
                (item.source_type.value, item.source_ref)
                for item in state.snapshot.evidence
            ]
            assert_authoritative_channel_evidence(
                evidence_refs, provider_message_id=provider_message_id
            )
            browser_response = client.get(f"/cases/{case_id}")
            if browser_response.status_code != 200:
                raise DemoScenarioError("browser Case projection could not be read")
            browser_payload = browser_response.json()
            assert_browser_projection_isolated(
                browser_payload,
                forbidden=(
                    INBOUND_CONTENT,
                    provider_message_id,
                    sha256_hex(callback_raw),
                    BINDING_REF,
                    str(INBOUND_EVENT_ID),
                    str(CALLBACK_EVENT_ID),
                    str(delivery_id),
                ),
            )
    except (httpx.HTTPError, ValueError, psycopg.Error):
        raise DemoScenarioError("local mailbox scene failed safely") from None
    print(
        f"Scene B passed: Case {case_id} has one verified inbound, one "
        "deduplicated replay, one accepted synthetic delivery, one delivered "
        "callback, and two authoritative channel Evidence records."
    )
    print(
        "Browser projection isolation passed; synthetic acceptance/delivery is "
        "not real-provider delivery or production exactly-once proof."
    )


def run_recovery_check() -> None:
    if not _wait_for_tcp("127.0.0.1", DEFAULT_TEMPORAL_PORT, timeout=2):
        raise DemoScenarioError("Temporal is not ready; run make portfolio-demo first")
    try:
        _compose("--profile", "postgres-test", "up", "-d", "postgres-test")
    except (OSError, subprocess.CalledProcessError):
        raise DemoScenarioError(
            "could not start the focused recovery database"
        ) from None
    try:
        if not _wait_for_postgres(RECOVERY_DATABASE_URL, timeout=30):
            raise DemoScenarioError("focused recovery database did not become ready")
        environment = build_demo_environment()
        environment.update(
            {
                "PROXYLOOP_TEST_DATABASE_URL": RECOVERY_DATABASE_URL,
                "PROXYLOOP_TEST_TEMPORAL_ADDRESS": DEFAULT_TEMPORAL_ADDRESS,
            }
        )
        result = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                "runtime",
                "--all-packages",
                "pytest",
                "-c",
                "runtime/pyproject.toml",
                "-q",
                "tests/integration/test_phase_06b1_temporal.py::test_live_temporal_local_mailbox_delivery_is_stable",
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            check=False,
        )
        if result.returncode != 0:
            raise DemoScenarioError(
                "focused worker-restart/lost-response recovery check failed"
            )
    finally:
        _compose("--profile", "postgres-test", "stop", "postgres-test", check=False)
    print(
        "Recovery check passed: the accepted Phase 06B1 lost-response retry "
        "preserved one logical local delivery."
    )


def _handle_signal(_signum: int, _frame: Any) -> NoReturn:
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Phase 07A local portfolio demo"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="start Compose and host demo processes")
    subparsers.add_parser("stop", help="stop host processes and Compose dependencies")
    subparsers.add_parser("reset", help="remove only the named demo PostgreSQL volume")
    channel = subparsers.add_parser(
        "scene-channel", help="run the isolated synthetic mailbox scene"
    )
    channel.add_argument("--runtime-url", default=DEFAULT_RUNTIME_URL)
    channel.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    subparsers.add_parser("recovery", help="run the focused real local recovery check")
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, _handle_signal)
    try:
        if args.command == "serve":
            start_demo()
        elif args.command == "stop":
            stop_demo()
        elif args.command == "reset":
            reset_demo()
        elif args.command == "scene-channel":
            run_channel_scene(
                runtime_url=args.runtime_url, database_url=args.database_url
            )
        elif args.command == "recovery":
            run_recovery_check()
        else:
            parser.error("unknown command")
    except DemoScenarioError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError):
        print("local demo dependency command failed safely", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CALLBACK_EVENT_ID",
    "CREATE_IDEMPOTENCY_KEY",
    "DEFAULT_DATABASE_URL",
    "INBOUND_CONTENT",
    "INBOUND_EVENT_ID",
    "DemoScenarioError",
    "assert_authoritative_channel_evidence",
    "assert_browser_projection_isolated",
    "build_delivery_body",
    "build_demo_environment",
    "build_fixture_headers",
    "build_provider_message_body",
    "main",
    "parse_utc",
    "reset_demo",
    "run_channel_scene",
    "run_recovery_check",
    "sha256_hex",
    "start_demo",
    "stop_demo",
]
