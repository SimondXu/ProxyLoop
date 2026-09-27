"""The fixture corpus the run index and the spend report are checked against.

Layout (``tmp_path``):
- ``runs/rA``: live; slow priced twice, fast_cp on vLLM, ear unpriced,
  simuser unpriced with no usage;
- ``runs/live/case-1/rB``: live layout; slow priced, ear unpriced, one mouth
  ``llm.call`` with no ``spend.charged``;
- ``runs/rC`` and ``evidence/s1/rC``: the same run twice; slow priced, ear
  unpriced, one mouth ``spend.charged`` with no ``llm.call``;
- ``runs/rD``: non-live (slow ``recorded_replay``, fast_cp ``baseline``);
- ``runs/rE``: events without a manifest (incomplete), one priced call;
- ``runs/rF``: a manifest that is not JSON (invalid);
- ``runs/rG``: a ``split == "test"`` manifest outside ``evidence/`` (sealed),
  with events that would not parse;
- ``evidence/s4/test/rH``: never entered (AGENTS rule 11).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.contract.samples import GEMINI, QWEN, SONNET
from tests.obs.bundles import LIVE_REFS, Log, manifest, write

from proxyloop.contract.bundle import EVENTS, MANIFEST
from proxyloop.contract.llm import AdapterKind, LLMRole, ModelRef, Usage


def _usage(prompt: int, completion: int, reasoning: int | None = None) -> Usage:
    return Usage(
        prompt_tokens=prompt, completion_tokens=completion, reasoning_tokens=reasoning
    )


def _run_c(root: Path) -> None:
    log = Log("rC")
    log.call("slow", SONNET, _usage(200, 0), "tokens", 600)
    log.call("ear", GEMINI, _usage(50, 5, 5), "unpriced")
    log.charge("ghost:rC:0", "mouth", GEMINI, "unpriced", None)
    log.end("done")
    write(root, log, manifest("rC"))


@pytest.fixture
def corpus(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    runs, evidence = tmp_path / "runs", tmp_path / "evidence"

    a = Log("rA")
    a.call("slow", SONNET, _usage(1000, 100), "tokens", 4500)
    a.call("slow", SONNET, _usage(100, 100, 20), "tokens", 1800)
    a.call("fast_cp", QWEN, _usage(50, 10), "gpu_time")
    a.call("ear", GEMINI, _usage(200, 30, 25), "unpriced")
    a.call("simuser", GEMINI, None, "unpriced")
    a.end("done")
    write(runs / "rA", a, manifest("rA"))

    b = Log("rB")
    b.call("slow", SONNET, _usage(1000, 0), "tokens", 3000)
    b.call("ear", GEMINI, _usage(100, 20), "unpriced")
    b.call("mouth", GEMINI, _usage(7, 7), None)
    b.end("abandoned")
    write(runs / "live" / "case-1" / "rB", b, manifest("rB"))

    _run_c(runs / "rC")
    _run_c(evidence / "s1" / "rC")

    replay = ModelRef(
        kind=AdapterKind.RECORDED_REPLAY, endpoint="relay", model_id="claude-sonnet-5"
    )
    fsm = ModelRef(kind=AdapterKind.BASELINE, endpoint=None, model_id="fsm")
    refs: dict[LLMRole, ModelRef] = {**LIVE_REFS, "slow": replay, "fast_cp": fsm}
    d = Log("rD")
    d.call("slow", replay, _usage(3000, 0), "tokens", 9000)
    d.end("done")
    write(runs / "rD", d, manifest("rD", refs))

    e = Log("rE")
    e.call("ear", GEMINI, _usage(1, 1), "unpriced")
    e.call("slow", SONNET, _usage(10000, 0), "tokens", 30000)  # a crashed run's $
    write(runs / "rE", e, None)

    (write(runs / "rF", None, None) / MANIFEST).write_text("{", "utf-8")

    g = write(runs / "rG", None, manifest("rG", split="test"))
    (g / EVENTS).write_text("not json\n", "utf-8")

    sealed = evidence / "s4" / "test"
    (write(sealed / "rH", None, None) / MANIFEST).write_text("{", "utf-8")
    sealed.chmod(0)  # listing it, or anything under it, raises
    try:
        yield runs, evidence
    finally:
        sealed.chmod(0o755)
