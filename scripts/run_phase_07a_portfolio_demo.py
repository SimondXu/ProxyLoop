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
from uuid import UUID, uuid4

import httpx
import psycopg
from proxyloop_agent_core import SCRIPTED_DIALOGUE_LINES
from proxyloop_case_runtime import (
    FAST_FALLBACK_TEXT,
    SCRIPTED_CASE_ID,
    PostgresCaseRepository,
)
from proxyloop_connectors import (
    BINDING_REF,
    SCHEMA_VERSION,
    build_fixture_headers,
)
from proxyloop_local_fast import (
    FAST_BACKEND_VARIABLE,
    LocalFastStartupError,
    fast_adapter_from_environment,
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
# The focused recovery check's temporary `postgres-test` service.
RECOVERY_POSTGRES_PORT = 55434
# Phase 07 D2: the Runtime and Web ports may be overridden explicitly
# (`--runtime-port`/`--web-port`); the launcher never picks a port on its own.
DEFAULT_RUNTIME_PORT = 8000
DEFAULT_WEB_PORT = 3000
DEFAULT_RUNTIME_URL = f"http://127.0.0.1:{DEFAULT_RUNTIME_PORT}"
DEFAULT_WEB_URL = f"http://127.0.0.1:{DEFAULT_WEB_PORT}"
# Read by apps/web/next.config.ts at build and start: where the Web's
# `/api/runtime/*` rewrite sends requests. Always set from the Runtime port.
RUNTIME_ORIGIN_VARIABLE = "PROXYLOOP_RUNTIME_ORIGIN"
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
# PR-11: the FAST_BACKEND flag; the two local backends need PR-9b's gateway.
FAST_BACKENDS = ("scripted", "distilled", "untuned")
FAST_BACKEND_LABELS = {
    "local_distilled_candidate": "local opt-in candidate",
    "local_untuned_baseline": "untuned local baseline",
}
INBOUND_EVENT_ID = UUID("77777777-7777-4777-8777-777777777777")
CALLBACK_EVENT_ID = UUID("88888888-8888-4888-8888-888888888888")
CREATE_IDEMPOTENCY_KEY = "33333333-3333-4333-8333-333333333333"
INBOUND_CONTENT = "Synthetic Provider message for the local portfolio demo."
RECOVERY_DATABASE_URL = f"postgresql://proxyloop:proxyloop@127.0.0.1:{RECOVERY_POSTGRES_PORT}/proxyloop_test"


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


def runtime_origin(runtime_port: int) -> str:
    """The loopback origin the Web's Runtime rewrite targets (D2)."""

    return f"http://127.0.0.1:{runtime_port}"


def validate_demo_ports(runtime_port: int, web_port: int) -> None:
    """Refuse an out-of-range or colliding port before anything starts (D2)."""

    for name, port in (("Runtime", runtime_port), ("Web", web_port)):
        if not 1 <= port <= 65535:
            raise DemoScenarioError(f"{name} port {port} is out of range")
    reserved = {
        DEFAULT_POSTGRES_PORT: "the demo PostgreSQL",
        DEFAULT_TEMPORAL_PORT: "the demo Temporal server",
        RECOVERY_POSTGRES_PORT: "the recovery PostgreSQL",
    }
    for name, port in (("Runtime", runtime_port), ("Web", web_port)):
        if port in reserved:
            raise DemoScenarioError(
                f"{name} port {port} is reserved for {reserved[port]}"
            )
    if runtime_port == web_port:
        raise DemoScenarioError("Runtime and Web port must differ")


def build_demo_environment(
    environ: Mapping[str, str] | None = None,
    *,
    fast_backend: str = "scripted",
    runtime_port: int = DEFAULT_RUNTIME_PORT,
) -> dict[str, str]:
    """Return explicit demo settings without inheriting model credentials.

    ``PROXYLOOP_FAST_BACKEND`` is always set explicitly, overriding an
    inherited value. ``serve`` passes the ``FAST_BACKEND`` flag here for the
    host worker and API, so both read the same selection; the Web build and
    the recovery check call it with the ``scripted`` default.
    ``PROXYLOOP_RUNTIME_ORIGIN`` is always derived from ``runtime_port``, so
    an inherited value never redirects the Web's Runtime rewrite.
    """

    if fast_backend not in FAST_BACKENDS:
        raise ValueError("unknown fast backend")
    values = dict(os.environ if environ is None else environ)
    for key in MODEL_ENVIRONMENT_KEYS:
        values.pop(key, None)
    values.update(
        {
            "PROXYLOOP_FAST_BACKEND": fast_backend,
            "PROXYLOOP_RUNTIME_MODE": "scripted",
            "PROXYLOOP_STORAGE_MODE": "postgres",
            "PROXYLOOP_ORCHESTRATION_MODE": "temporal",
            "PROXYLOOP_DATABASE_URL": DEFAULT_DATABASE_URL,
            "PROXYLOOP_TEMPORAL_ADDRESS": DEFAULT_TEMPORAL_ADDRESS,
            "PROXYLOOP_TEMPORAL_NAMESPACE": "default",
            "PROXYLOOP_TEMPORAL_TASK_QUEUE": "proxyloop-case-workflow",
            "PROXYLOOP_TEMPORAL_CONTINUE_AS_NEW_AFTER": "32",
            RUNTIME_ORIGIN_VARIABLE: runtime_origin(runtime_port),
        }
    )
    return values


def check_fast_backend(environment: Mapping[str, str]) -> str | None:
    """Probe the local Fast gateway the demo expects; ``None`` for scripted.

    The same parse and identity probe the worker and API run at start. The
    launcher never starts the gateway (PR-9b's ``make local-fast-gateway``).
    """

    backend = environment.get(FAST_BACKEND_VARIABLE, "scripted")
    if backend == "scripted":
        return None
    try:
        adapter = fast_adapter_from_environment(environment)
    except (ValueError, LocalFastStartupError) as exc:
        raise DemoScenarioError(
            f"FAST_BACKEND={backend} needs its local Fast gateway ({exc}); "
            f"start it with make local-fast-gateway BACKEND={backend}, then retry"
        ) from None
    assert adapter is not None  # a local backend connects or raises
    return FAST_BACKEND_LABELS[adapter.fast_backend_label]


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
    # The browser projection carries no source_ref and needs neither type, so
    # any Provider message or event Evidence reaching it is channel material.
    return item.get("source_type") in {"provider_message", "provider_event"}


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
            "POSTGRES_TEST_PORT": str(RECOVERY_POSTGRES_PORT),
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


def _check_startup_ports(
    *, runtime_port: int = DEFAULT_RUNTIME_PORT, web_port: int = DEFAULT_WEB_PORT
) -> None:
    for port in (
        web_port,
        runtime_port,
        DEFAULT_POSTGRES_PORT,
        DEFAULT_TEMPORAL_PORT,
    ):
        if not _port_is_free(port):
            raise DemoScenarioError(f"required host port {port} is unavailable")


def _build_web_app(
    state_dir: Path, *, runtime_port: int = DEFAULT_RUNTIME_PORT
) -> None:
    log_dir = _log_dir(state_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        with (log_dir / "web-build.log").open("wb") as log_file:
            result = subprocess.run(
                ["pnpm", "--filter", "@proxyloop/web", "build"],
                cwd=REPOSITORY_ROOT,
                env=build_demo_environment(runtime_port=runtime_port),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=False,
            )
    except OSError as exc:
        error_type = exc.__class__.__name__
        raise DemoScenarioError(f"could not build Web app ({error_type})") from None
    if result.returncode != 0:
        raise DemoScenarioError("Web build failed; inspect logs/web-build.log")


def _spawn_host_services(
    state_dir: Path,
    *,
    fast_backend: str = "scripted",
    runtime_port: int = DEFAULT_RUNTIME_PORT,
    web_port: int = DEFAULT_WEB_PORT,
) -> dict[str, subprocess.Popen[bytes]]:
    log_dir = _log_dir(state_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    environment = build_demo_environment(
        fast_backend=fast_backend, runtime_port=runtime_port
    )
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
            str(runtime_port),
        ],
        "web": [
            "pnpm",
            "--filter",
            "@proxyloop/web",
            "start",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(web_port),
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


def start_demo(
    *,
    state_dir: Path | None = None,
    fast_backend: str = "scripted",
    runtime_port: int = DEFAULT_RUNTIME_PORT,
    web_port: int = DEFAULT_WEB_PORT,
) -> None:
    validate_demo_ports(runtime_port, web_port)
    runtime_url = f"http://127.0.0.1:{runtime_port}"
    web_url = f"http://127.0.0.1:{web_port}"
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
        # Before anything starts: a local backend needs its gateway running.
        fast_label = check_fast_backend(
            build_demo_environment(fast_backend=fast_backend)
        )
        _check_startup_ports(runtime_port=runtime_port, web_port=web_port)
        _start_compose_dependencies()
        compose_started = True
        _raise_if_stop_requested(selected)
        _build_web_app(selected, runtime_port=runtime_port)
        _raise_if_stop_requested(selected)
        processes = _spawn_host_services(
            selected,
            fast_backend=fast_backend,
            runtime_port=runtime_port,
            web_port=web_port,
        )
        _raise_if_stop_requested(selected)
        _assert_processes_alive(processes)
        if not _wait_for_url(
            f"{runtime_url}/health/ready", timeout=45, expected_status={200}
        ):
            raise DemoScenarioError(
                "Runtime readiness did not pass; inspect logs/runtime.log"
            )
        _assert_processes_alive(processes)
        if not _wait_for_url(web_url, timeout=45, expected_status={200}):
            raise DemoScenarioError("Web did not become ready; inspect logs/web.log")
        _assert_processes_alive(processes)
        print(f"Web: {web_url}")
        print(f"Runtime readiness: {runtime_url}/health/ready")
        print(f"Temporal server: {DEFAULT_TEMPORAL_ADDRESS}")
        print(
            "Fast backend: scripted"
            if fast_label is None
            else f"Fast backend: {fast_backend} ({fast_label}; the gateway is "
            "not supervised by this demo)"
        )
        print(
            "Scene order (stop and reset between scenes): Scene A Web journey, "
            "Scene J make portfolio-demo-journey, Scene B make "
            "portfolio-demo-channel, then make portfolio-demo-recovery."
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
        # Only the invocation that spawned the host services wrote pids.json.
        # A refused start must keep another supervisor's file so
        # portfolio-demo-stop can still find those processes.
        if processes:
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


# Phase 07 Scene J: the journey the Web drives, over the same HTTP routes.
# The message carries a marker that must never reach a log or a response.
JOURNEY_MARKER = "zebra-7731"
JOURNEY_MESSAGE = (
    "My mobile bill is $92 and I want to get it under $75. Keep my hotspot. "
    f"({JOURNEY_MARKER})"
)
# Must equal CONFIRMATION_EVENT in apps/web/app/components/conversation-workspace.tsx.
CONFIRMATION_EVENT = (
    "Keep mobile hotspot and device financing unchanged. "
    "Continue with the fictional offer."
)
JOURNEY_LOG_FILES = ("runtime.log", "web.log", "worker.log")
JOURNEY_EVIDENCE_PATH = (
    REPOSITORY_ROOT / "data" / "evaluation" / "phase-07-demo-journey-scripted.json"
)
JOURNEY_SCHEMA_VERSION = "phase-07-demo-journey-v1"
JOURNEY_CLAIM_BOUNDARY = (
    "One local run of the credential-free 07A demo on the scripted Fast, "
    "scripted Slow and scripted Judge (decision 17), through the Web's HTTP "
    "routes against PostgreSQL and Temporal. Content-free: no ids, timestamps, "
    "latencies, text, or host identity. It is not a model-quality, latency, "
    "capacity, or production claim."
)
INTAKE_READ_FIELDS = (
    "current_monthly_total",
    "target_monthly_total",
    "mobile_hotspot_required",
)
# The Web's financing question, answered "no change": the device-financing
# change is forbidden (the Draft Task Brief row reads "Confirmed · unchanged").
INTAKE_CLARIFIED_FIELD = "device_financing_change_forbidden"
TRACE_ROLES = ("fast", "judge", "slow")
TRACE_RESULTS = ("failed", "rejected", "succeeded")
# From the split report's demo_path and PR-14 §5: one Slow result at create,
# judged once and accepted (no retry), then one Fast turn on the confirmation.
EXPECTED_SCRIPTED_TRACE_COUNTS = {
    "fast": {"failed": 0, "rejected": 0, "succeeded": 1},
    "judge": {"failed": 0, "rejected": 0, "succeeded": 1},
    "slow": {"failed": 0, "rejected": 0, "succeeded": 1},
}
CONFIRM_EVENT_TYPES = (
    ("provider", "provider_offer"),
    ("consumer", "consumer_message"),
    ("system", "assistant_message"),
)
REFERENCE_REVISIONS = {"create": 2, "confirm": 4, "approve": 6}


class _JourneyRepository(Protocol):
    def get(self, case_id: UUID) -> Any: ...

    def list_model_traces(self, case_id: UUID) -> Sequence[Any]: ...


def completion_has_verified_evidence(payload: Mapping[str, Any]) -> bool:
    """The Web's receipt predicate (``completionHasVerifiedEvidence``)."""

    completion = payload.get("completion")
    evidence = payload.get("evidence")
    if not isinstance(completion, Mapping) or not isinstance(evidence, list):
        return False
    evidence_ids = completion.get("evidence_ids")
    known = {
        item.get("evidence_id")
        for item in evidence
        if isinstance(item, Mapping)
        and isinstance(item.get("evidence_id"), str)
        and item.get("evidence_id", "").strip()
    }
    return (
        completion.get("decision") == "complete"
        and payload.get("execution_count") == 1
        and isinstance(evidence_ids, list)
        and len(evidence_ids) > 0
        and all(
            isinstance(item, str) and item.strip() and item in known
            for item in evidence_ids
        )
    )


def _journey_json(
    response: httpx.Response, *, expected_status: int, step: str
) -> dict[str, Any]:
    if response.status_code != expected_status:
        raise DemoScenarioError(f"journey step {step} failed ({response.status_code})")
    try:
        value = response.json()
    except ValueError:
        raise DemoScenarioError(f"journey step {step} was not JSON") from None
    if not isinstance(value, dict):
        raise DemoScenarioError(f"journey step {step} shape was invalid")
    return value


def _visible_events(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    snapshot = payload.get("snapshot")
    events = snapshot.get("visible_events") if isinstance(snapshot, Mapping) else None
    if not isinstance(events, list):
        raise DemoScenarioError("journey payload has no visible events")
    return [item for item in events if isinstance(item, Mapping)]


def _trace_counts(traces: Sequence[Any]) -> dict[str, dict[str, int]]:
    counts = {role: dict.fromkeys(TRACE_RESULTS, 0) for role in TRACE_ROLES}
    for trace in traces:
        role = str(trace.role)
        result = str(getattr(trace.result, "value", trace.result))
        if role not in counts or result not in counts[role]:
            raise DemoScenarioError("unexpected model trace role or result")
        counts[role][result] += 1
    return counts


def _intake_create_request(proposal: Mapping[str, Any]) -> dict[str, Any]:
    facts = proposal.get("proposal")
    clarifications = proposal.get("clarifications")
    if not isinstance(facts, Mapping) or not isinstance(clarifications, list):
        raise DemoScenarioError("intake proposal shape was invalid")
    read = sorted(key for key, value in facts.items() if value is not None)
    clarified = sorted(
        str(item.get("field")) for item in clarifications if isinstance(item, Mapping)
    )
    if read != sorted(INTAKE_READ_FIELDS) or clarified != [INTAKE_CLARIFIED_FIELD]:
        raise DemoScenarioError("intake did not read the expected facts")
    request = {key: facts[key] for key in INTAKE_READ_FIELDS}
    request[INTAKE_CLARIFIED_FIELD] = True
    return request


def run_journey(
    *,
    client: httpx.Client,
    repository: _JourneyRepository,
    log_dir: Path,
    evidence_path: Path | None = None,
) -> dict[str, Any]:
    """Drive Scene J and return its content-free evidence; raise on a deviation."""

    try:
        if repository.get(SCRIPTED_CASE_ID) is not None:
            raise DemoScenarioError(
                "demo state is not fresh; run make portfolio-demo-reset first"
            )
        ready = _journey_json(
            client.get("/health/ready"), expected_status=200, step="readiness"
        )
        readiness = {
            key: str(ready.get(key))
            for key in ("adapter_mode", "storage_mode", "orchestration_mode")
        }
        if readiness["storage_mode"] != "postgres" or (
            readiness["orchestration_mode"] != "temporal"
        ):
            raise DemoScenarioError("journey needs the PostgreSQL/Temporal demo")
        scripted = readiness["adapter_mode"] == "scripted"
        if evidence_path is not None and not scripted:
            raise DemoScenarioError(
                "journey evidence is committed for the scripted backend only"
            )

        proposal_response = client.post(
            "/intake/proposals", json={"text": JOURNEY_MESSAGE}
        )
        if JOURNEY_MARKER in proposal_response.text:
            raise DemoScenarioError("intake marker was echoed by the proposal")
        proposal = _journey_json(proposal_response, expected_status=200, step="intake")
        create_body = _intake_create_request(proposal)

        created = _journey_json(
            client.post(
                "/cases",
                json=create_body,
                headers={"Idempotency-Key": str(uuid4())},
            ),
            expected_status=201,
            step="create",
        )
        if created.get("case_id") != str(SCRIPTED_CASE_ID):
            raise DemoScenarioError("Runtime created an unexpected Case")
        case_path = f"/cases/{SCRIPTED_CASE_ID}"

        confirmed = _journey_json(
            client.post(
                f"{case_path}/events",
                json={
                    "content": CONFIRMATION_EVENT,
                    "event_type": "consumer_message",
                    "expected_revision": created.get("revision"),
                },
                headers={"Idempotency-Key": str(uuid4())},
            ),
            expected_status=200,
            step="confirm",
        )
        events = _visible_events(confirmed)
        event_types = [(item.get("actor"), item.get("event_type")) for item in events]
        if tuple(event_types) != CONFIRM_EVENT_TYPES:
            raise DemoScenarioError("confirmation events were not offer, turn, line")
        line = events[-1].get("content")
        if line == FAST_FALLBACK_TEXT:
            line_class = "fallback"
        elif isinstance(line, str) and line.strip():
            line_class = "model"
        else:
            raise DemoScenarioError("assistant line was missing")
        if scripted and line != SCRIPTED_DIALOGUE_LINES[0]:
            raise DemoScenarioError(
                "assistant line was not the first scripted dialogue line"
            )
        approval = confirmed.get("approval")
        if not isinstance(approval, Mapping) or approval.get("decision") != "pending":
            raise DemoScenarioError("confirmation did not open a pending approval")

        approval_path = f"{case_path}/approvals/{approval.get('approval_id')}"
        approval_body = {
            "decision": "approved",
            "expected_action_intent_revision": approval.get("action_intent_revision"),
            "expected_case_revision": approval.get("case_revision"),
            "expected_revision": confirmed.get("revision"),
        }
        approval_headers = {"Idempotency-Key": str(uuid4())}
        approved = _journey_json(
            client.post(approval_path, json=approval_body, headers=approval_headers),
            expected_status=200,
            step="approve",
        )
        if approved.get("execution_count") != 1:
            raise DemoScenarioError("execution count was not 1 after approval")
        replayed = _journey_json(
            client.post(approval_path, json=approval_body, headers=approval_headers),
            expected_status=200,
            step="approve-replay",
        )
        final = _journey_json(
            client.get(case_path), expected_status=200, step="final-read"
        )
        if replayed.get("execution_count") != 1 or final.get("execution_count") != 1:
            raise DemoScenarioError("replayed approval executed again")
        if not completion_has_verified_evidence(final):
            raise DemoScenarioError("receipt predicate did not hold")

        trace_counts = _trace_counts(repository.list_model_traces(SCRIPTED_CASE_ID))
        if scripted:
            if trace_counts != EXPECTED_SCRIPTED_TRACE_COUNTS:
                raise DemoScenarioError("unexpected model trace counts")
        elif (
            trace_counts["slow"] != EXPECTED_SCRIPTED_TRACE_COUNTS["slow"]
            or trace_counts["judge"] != EXPECTED_SCRIPTED_TRACE_COUNTS["judge"]
            or sum(trace_counts["fast"].values()) != 1
        ):
            raise DemoScenarioError("unexpected model trace counts")

        marker_absent: dict[str, bool] = {"proposal_response": True}
        for name in JOURNEY_LOG_FILES:
            path = log_dir / name
            if not path.is_file():
                raise DemoScenarioError(f"journey log {name} is missing")
            if JOURNEY_MARKER.encode() in path.read_bytes():
                raise DemoScenarioError(f"intake marker was found in {name}")
            marker_absent[name] = True
    except (httpx.HTTPError, psycopg.Error):
        raise DemoScenarioError("journey failed safely") from None

    evidence: dict[str, Any] = {
        "schema_version": JOURNEY_SCHEMA_VERSION,
        "claim_boundary": JOURNEY_CLAIM_BOUNDARY,
        "readiness": readiness,
        "intake": {
            "parser": str(proposal.get("parser")),
            "read_fields": sorted(INTAKE_READ_FIELDS),
            "clarified_fields": [INTAKE_CLARIFIED_FIELD],
        },
        "revisions": {
            "create": created.get("revision"),
            "confirm": confirmed.get("revision"),
            "approve": approved.get("revision"),
        },
        "replay_revision_unchanged": replayed.get("revision")
        == approved.get("revision")
        == final.get("revision"),
        "event_types_after_confirm": [kind for _, kind in event_types],
        "assistant_line": line_class,
        "approval_after_confirm": "pending",
        "execution_count": {
            "after_approve": approved.get("execution_count"),
            "after_replay": replayed.get("execution_count"),
        },
        "completion_decision": "complete",
        "receipt_predicate": True,
        "trace_counts": trace_counts,
        "marker_absent": marker_absent,
    }
    if not evidence["replay_revision_unchanged"]:
        raise DemoScenarioError("replayed approval changed the Case revision")
    if evidence_path is not None:
        evidence_path.write_text(render_journey_evidence(evidence))
    return evidence


def render_journey_evidence(evidence: Mapping[str, Any]) -> str:
    return json.dumps(evidence, indent=2, sort_keys=True) + "\n"


def run_journey_command(
    *,
    runtime_url: str,
    database_url: str = DEFAULT_DATABASE_URL,
    log_dir: Path | None = None,
    write_evidence: bool = False,
) -> None:
    selected_logs = log_dir if log_dir is not None else _log_dir()
    try:
        repository = PostgresCaseRepository(database_url)
    except (psycopg.Error, ValueError):
        raise DemoScenarioError("journey database was unavailable") from None
    with httpx.Client(base_url=runtime_url, timeout=45.0) as client:
        evidence = run_journey(
            client=client,
            repository=repository,
            log_dir=selected_logs,
            evidence_path=JOURNEY_EVIDENCE_PATH if write_evidence else None,
        )
    revisions = evidence["revisions"]
    print(
        "Scene J passed: intake read three facts and asked one; the Case was "
        "created; the confirmation turn got one "
        f"{evidence['assistant_line']} line and a pending approval; one "
        "execution, unchanged by an exact approval replay; the receipt predicate "
        "holds."
    )
    counts = evidence["trace_counts"]
    print(
        "Model traces (PostgreSQL): "
        + "; ".join(
            f"{role} "
            + ", ".join(f"{result} {count}" for result, count in results.items())
            for role, results in counts.items()
        )
        + ". The intake marker is absent from the proposal and the demo logs."
    )
    if revisions != REFERENCE_REVISIONS:
        print(
            f"Note: Case revisions {revisions} differ from the reference "
            f"{REFERENCE_REVISIONS}; record and explain this in the phase log."
        )
    if write_evidence:
        print(f"Evidence written: {JOURNEY_EVIDENCE_PATH.relative_to(REPOSITORY_ROOT)}")


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
    serve = subparsers.add_parser("serve", help="start Compose and host demo processes")
    serve.add_argument(
        "--fast-backend",
        choices=FAST_BACKENDS,
        default="scripted",
        help="distilled/untuned expect a running local Fast gateway",
    )
    serve.add_argument("--runtime-port", type=int, default=DEFAULT_RUNTIME_PORT)
    serve.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT)
    subparsers.add_parser("stop", help="stop host processes and Compose dependencies")
    subparsers.add_parser("reset", help="remove only the named demo PostgreSQL volume")
    channel = subparsers.add_parser(
        "scene-channel", help="run the isolated synthetic mailbox scene"
    )
    channel.add_argument("--runtime-url", default=DEFAULT_RUNTIME_URL)
    channel.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    journey = subparsers.add_parser(
        "journey", help="drive the Scene J journey through the Web's HTTP routes"
    )
    journey.add_argument("--runtime-url", default=DEFAULT_RUNTIME_URL)
    journey.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    journey.add_argument(
        "--write-evidence",
        action="store_true",
        help="write the committed content-free evidence (scripted backend only)",
    )
    subparsers.add_parser("recovery", help="run the focused real local recovery check")
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, _handle_signal)
    try:
        if args.command == "serve":
            start_demo(
                fast_backend=args.fast_backend,
                runtime_port=args.runtime_port,
                web_port=args.web_port,
            )
        elif args.command == "stop":
            stop_demo()
        elif args.command == "reset":
            reset_demo()
        elif args.command == "scene-channel":
            run_channel_scene(
                runtime_url=args.runtime_url, database_url=args.database_url
            )
        elif args.command == "journey":
            run_journey_command(
                runtime_url=args.runtime_url,
                database_url=args.database_url,
                write_evidence=args.write_evidence,
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
    "CONFIRMATION_EVENT",
    "CREATE_IDEMPOTENCY_KEY",
    "DEFAULT_DATABASE_URL",
    "DEFAULT_RUNTIME_PORT",
    "DEFAULT_WEB_PORT",
    "FAST_BACKENDS",
    "INBOUND_CONTENT",
    "INBOUND_EVENT_ID",
    "JOURNEY_EVIDENCE_PATH",
    "JOURNEY_LOG_FILES",
    "RECOVERY_POSTGRES_PORT",
    "DemoScenarioError",
    "assert_authoritative_channel_evidence",
    "assert_browser_projection_isolated",
    "build_delivery_body",
    "build_demo_environment",
    "build_fixture_headers",
    "build_provider_message_body",
    "check_fast_backend",
    "completion_has_verified_evidence",
    "main",
    "parse_utc",
    "render_journey_evidence",
    "reset_demo",
    "run_channel_scene",
    "run_journey",
    "run_journey_command",
    "run_recovery_check",
    "runtime_origin",
    "sha256_hex",
    "start_demo",
    "stop_demo",
    "validate_demo_ports",
]
