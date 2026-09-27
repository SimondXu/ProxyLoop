"""Metrics resolve a bundle's full task_ref, ``family@version[:mode][#seed]``
(S1-SYS-17): the instance it names is the one whose hash is checked."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.contract.samples import session_config
from tests.eval.streams import INSTANCE, Stream

from proxyloop.env.tasks.loader import instance_hash, resolve
from proxyloop.eval.benchmark import build, load_spec
from proxyloop.eval.matrix import Cell, cell_dir
from proxyloop.eval.metrics import metrics

MODED = ("cp-direct-discount@1:full", "cp-direct-discount@1#3")
REFS = (*MODED, "cp-direct-discount@1:full#3")


def _outcome(task_ref: str, instance: str) -> tuple[str, str | None]:
    out = metrics(Stream(task_ref=task_ref, instance=instance).end("info_only"))
    return out["outcome"], out["not_computable"].get("outcome")


@pytest.mark.parametrize("ref", REFS)
def test_a_moded_or_seeded_ref_resolves_to_its_own_instance(ref: str) -> None:
    task = resolve(ref)
    assert task.ref == ref and instance_hash(task) != INSTANCE  # a real instance
    assert _outcome(ref, instance_hash(task)) == ("ok", None)


@pytest.mark.parametrize("ref", REFS)
def test_the_plain_family_hash_under_a_moded_ref_is_a_mismatch(ref: str) -> None:
    result, why = _outcome(ref, INSTANCE)  # the hash of cp-direct-discount@1
    assert result == "infra_error" and why is not None and "hash mismatch" in why


def test_another_instance_hash_under_the_plain_ref_is_a_mismatch() -> None:
    result, why = _outcome("cp-direct-discount@1", instance_hash(resolve(MODED[1])))
    assert result == "infra_error" and why is not None and "hash mismatch" in why


@pytest.mark.parametrize(
    ("ref", "reason"),
    [
        ("cp-direct-discount@1#0", "bad task_ref"),  # #0 is never written
        ("cp-direct-discount@1:info_only", "not canonical"),  # the default mode
        ("cp-direct-discount@1:nope", "has no 'nope' mode"),
        ("cp-direct-discount@2", "is version 1"),
        ("cp-direct-discount", "bad task_ref"),
        ("no-such-family@1", "No such file"),
    ],
)
def test_a_ref_that_does_not_resolve_is_an_infra_error(ref: str, reason: str) -> None:
    result, why = _outcome(ref, INSTANCE)
    assert result == "infra_error" and why is not None
    assert why.startswith(f"task {ref} does not load: ") and reason in why


def test_a_benchmark_cell_refuses_a_seeded_instance_bundle(tmp_path: Path) -> None:
    """A spec cell is the family file's task: a ``#seed`` instance of it is
    another task, even under the cell's family and session seed."""
    bench = load_spec()
    (instance,) = bench.tasks
    seeded = resolve(f"{bench.tasks[instance].ref}#3")
    runs = tmp_path / "runs"
    s = Stream(
        session_config(seed=1), task_ref=seeded.ref, instance=instance_hash(seeded)
    )
    s.write(cell_dir(runs, 0, Cell("C2", instance, 1)) / "run-s")
    with pytest.raises(ValueError, match="not its cell"):
        build(bench, [runs], git_sha="g")


def test_the_benchmark_metrics_loader_serves_only_spec_task_refs() -> None:
    bench = load_spec()
    (task,) = bench.tasks.values()
    assert bench.load(task.ref) is task
    with pytest.raises(ValueError, match="not a task of this benchmark spec"):
        bench.load(f"{task.ref}#3")
