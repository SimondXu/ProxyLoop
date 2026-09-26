import subprocess
import threading

import pytest

from serving import modal_vllm


class Exited(BaseException):
    """Stands in for os._exit, which never returns."""


def patch_exit(monkeypatch, *, raises: bool) -> tuple[list, threading.Event]:
    codes, done = [], threading.Event()

    def fake_exit(code):
        codes.append(code)
        done.set()
        if raises:
            raise Exited

    monkeypatch.setattr(modal_vllm.os, "_exit", fake_exit)
    return codes, done


def test_container_exits_when_vllm_exits(monkeypatch):
    codes, done = patch_exit(monkeypatch, raises=False)
    monkeypatch.setattr(modal_vllm, "_start_vllm", lambda started_at: subprocess.Popen(["true"]))
    modal_vllm._serve()  # returns at once; the watcher thread waits on the child
    assert done.wait(10)
    assert codes == [1]


def test_a_failure_before_popen_exits_non_zero_at_once(monkeypatch, capsys):
    codes, _ = patch_exit(monkeypatch, raises=True)

    def boom(started_at):
        raise FileNotFoundError("attestation inputs missing")

    monkeypatch.setattr(modal_vllm, "_start_vllm", boom)
    with pytest.raises(Exited):
        modal_vllm._serve()
    assert codes == [1]
    assert "attestation inputs missing" in capsys.readouterr().err
