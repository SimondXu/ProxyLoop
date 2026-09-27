"""A session of a seeded full-mode instance names it in its task_ref, and the
ref resolves back to the instance the bundle ran (S1-SYS-17)."""

from __future__ import annotations

from pathlib import Path

from tests.kernel.test_session import SCRIPTS, UNTIL
from tests.support.sessions import only_bundle, run

from proxyloop.env.tasks.loader import instance_hash, resolve

REF = "cp-direct-discount@1:full#7"


def test_a_seeded_full_mode_session_writes_its_extended_task_ref(
    tmp_path: Path,
) -> None:
    task = resolve(REF)
    run(tmp_path, SCRIPTS, until=UNTIL, task=task)
    bundle = only_bundle(tmp_path)
    started = next(e for e in bundle.events if e.type == "session.started")
    assert bundle.manifest.task_ref == started.payload["task_ref"] == REF
    assert bundle.manifest.instance_hash == started.payload["instance_hash"]
    assert instance_hash(resolve(bundle.manifest.task_ref)) == instance_hash(task)
    assert bundle.manifest.instance_hash == instance_hash(task)
