"""Phase 07 F1: the Runtime server writes one operation record per request.

`JsonLoggingOperationRecorder` logs each allowlisted record at INFO to
`proxyloop_api.operations`. Before F1, `proxyloop_api.server` attached no
handler to that logger, so no record reached the process output. This test
runs the real server command and reads its stderr.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from proxyloop_api import OPERATION_RECORD_FIELDS

ROOT = Path(__file__).resolve().parents[2]
MARKER = "zebra-7731"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_socket(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("local Runtime server exited")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("local Runtime server did not start")


def test_one_request_writes_exactly_one_content_free_operation_record(
    tmp_path: Path,
) -> None:
    port = _free_port()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PROXYLOOP_")
    }
    environment.update(
        {
            "PROXYLOOP_RUNTIME_MODE": "scripted",
            "PROXYLOOP_STORAGE_MODE": "memory",
            "PROXYLOOP_ORCHESTRATION_MODE": "direct",
        }
    )
    stderr_path = tmp_path / "runtime.log"
    with stderr_path.open("wb") as stderr:
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
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
        )
        try:
            _wait_for_socket(port, process)
            response = httpx.post(
                f"http://127.0.0.1:{port}/intake/proposals",
                json={"text": f"My mobile bill is $92. ({MARKER})"},
                timeout=5,
            )
            assert response.status_code == 200
            time.sleep(0.3)
        finally:
            process.terminate()
            process.wait(timeout=5)

    output = stderr_path.read_text()
    assert MARKER not in output
    records = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "correlation_id" in value:
            records.append(value)
    assert len(records) == 1
    record = records[0]
    assert set(record) == OPERATION_RECORD_FIELDS
    assert record["operation"] == "intake_proposal"
    assert record["status"] == 200
    assert record["error_category"] == "none"
