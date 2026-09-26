"""evidence_check: the offline integrity rules and the claim rules (§14)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.contract.samples import QWEN
from tests.support.fakes import fake_ref
from tests.support.recorded import RUN_ID, write_fast_bundle

from proxyloop.contract.bundle import (
    EVENTS,
    MANIFEST,
    PROMPTS,
    Bundle,
    Manifest,
    read_bundle,
)
from proxyloop.contract.events import Event
from proxyloop.contract.llm import AdapterKind
from proxyloop.evidence.check import check_path, evidence_check

RESPONSE = "Thanks, that helps. Could you read the full offer back to me?\n@hold offer"


def _lines(run: Path, name: str) -> list[str]:
    return (run / name).read_text("utf-8").splitlines()


def _rewrite(run: Path, name: str, lines: list[str]) -> None:
    (run / name).write_text("".join(f"{line}\n" for line in lines), "utf-8")


def _edit_manifest(run: Path, **update: object) -> None:
    body = json.loads((run / MANIFEST).read_text("utf-8")) | update
    (run / MANIFEST).write_text(
        Manifest.model_validate(body).model_dump_json(), "utf-8"
    )


@pytest.fixture
def recorded(tmp_path: Path) -> Path:
    return write_fast_bundle(tmp_path / "run", RESPONSE)


@pytest.fixture
def real(tmp_path: Path) -> Path:
    """Scripted, but labelled real_http: exercises the claim rules, never a claim."""

    run = write_fast_bundle(tmp_path / "real", RESPONSE, ref=QWEN, live=True)
    _edit_manifest(run, p3="pass")
    return run


def _types(run: Path) -> list[str]:
    return [json.loads(line)["type"] for line in _lines(run, EVENTS)]


def test_a_recorded_bundle_passes_offline_and_fails_a_claim(recorded: Path) -> None:
    offline = check_path(recorded)
    assert offline.ok, offline.failures
    assert offline.reality == {"fast_cp": "recorded_replay"}
    claim = check_path(recorded, "claim")
    assert "claimed role fast_cp ran recorded_replay" in claim.failures
    assert any("own call is not real_http" in f for f in claim.failures)


def test_a_well_formed_real_bundle_passes_the_claim(real: Path) -> None:
    report = check_path(real, "claim")
    assert report.ok, report.failures
    assert report.reality == {"fast_cp": "vllm"}


def test_rejects_a_missing_cause(recorded: Path) -> None:
    call = _types(recorded).index("llm.call")
    lines = _lines(recorded, EVENTS)
    _rewrite(recorded, EVENTS, lines[:call] + lines[call + 1 :])
    via_path = check_path(recorded)
    assert not via_path.ok and "cites unknown events" in via_path.failures[0]
    # The same log handed over already parsed (read_bundle would refuse it):
    manifest = Manifest.model_validate_json((recorded / MANIFEST).read_text("utf-8"))
    events = tuple(Event.model_validate_json(line) for line in _lines(recorded, EVENTS))
    report = evidence_check(Bundle(manifest, events, {}))
    assert any(
        f.startswith("causes:") and "cites unknown" in f for f in report.failures
    )


def test_rejects_a_seq_gap(recorded: Path) -> None:
    delivered = _types(recorded).index("utt.delivered")  # nothing cites it
    lines = _lines(recorded, EVENTS)
    _rewrite(recorded, EVENTS, lines[:delivered] + lines[delivered + 1 :])
    report = check_path(recorded)
    assert report.failures == (
        f"seq is not dense: position {delivered} holds seq {delivered + 1}",
    )


def test_rejects_a_response_sha_mismatch(recorded: Path) -> None:
    lines = _lines(recorded, PROMPTS)
    records = [json.loads(line) for line in lines]
    i = next(n for n, r in enumerate(records) if r["kind"] == "response")
    records[i]["content"] = records[i]["content"].replace("offer", "offet")
    _rewrite(recorded, PROMPTS, [json.dumps(r) for r in records])
    report = check_path(recorded)
    assert any("response" in f and "does not hash" in f for f in report.failures)
    assert any("not the parse of the recorded response" in f for f in report.failures)


def test_rejects_test_fake_in_a_claimed_role(tmp_path: Path) -> None:
    run = write_fast_bundle(tmp_path / "fake", RESPONSE, ref=fake_ref())
    assert check_path(run).ok
    report = check_path(run, "claim", roles={"fast_cp"})
    assert "claimed role fast_cp ran test_fake" in report.failures
    assert "claimed role fast_cp has no successful real_http call" in report.failures
    assert check_path(run, "claim", roles=()).failures == (
        "utt.delivered run-test:6: its turn's own call is not real_http",
        "utt.delivered run-test:8: its turn's own call is not real_http",
    )


def test_a_live_bundle_cannot_contain_test_fake(real: Path) -> None:
    _edit_manifest(real, reality={"fast_cp": AdapterKind.TEST_FAKE})
    failures = check_path(real).failures
    assert "a live bundle contains test_fake or recorded_replay" in failures
    assert any(f.startswith("reality says fast_cp ran test_fake") for f in failures)


def test_claim_rules_on_served_model_fingerprint_and_p3(real: Path) -> None:
    manifest = json.loads((real / MANIFEST).read_text("utf-8"))
    served = manifest["models"]["fast_cp"] | {"served_model": "Qwen3.5-9B-lora-a"}
    _edit_manifest(
        real, models={"fast_cp": served}, fingerprints={"pl_cp_v1": "0" * 64}, p3="fail"
    )
    failures = check_path(real, "claim").failures
    assert any(
        "served 'Qwen3.5-9B', configured 'Qwen3.5-9B-lora-a'" in f for f in failures
    )
    assert "fingerprint of pl_cp_v1 is not the current contract's" in failures
    assert "P3 is fail" in failures
    assert check_path(real).ok  # none of these is an offline rule


def test_rejects_another_run_in_the_log(real: Path) -> None:
    _edit_manifest(real, run_id="other")
    assert f"events of runs ['{RUN_ID}'] in bundle other" in check_path(real).failures


def _append(
    bundle: Bundle, type_: str, actor: str, payload: Mapping[str, object], cause: str
) -> Bundle:
    """Add an event just before the closing ``session.ended``."""

    *body, end = bundle.events
    seq = len(body)
    event = Event(
        run_id=RUN_ID,
        seq=seq,
        event_id=f"{RUN_ID}:{seq}",
        t_ms=end.t_ms,
        wall=datetime(2026, 9, 26, tzinfo=UTC),
        type=type_,
        actor=actor,
        stream="agent",
        cause_ids=(cause,),
        epoch=0,
        payload=dict(payload),
    )
    moved = end.model_copy(update={"seq": seq + 1, "event_id": f"{RUN_ID}:{seq + 1}"})
    return Bundle(bundle.manifest, (*body, event, moved), bundle.prompts)


def _last_id(bundle: Bundle) -> str:
    return bundle.events[-2].event_id  # the event before session.ended


def test_a_guard_verbatim_line_has_a_chain(recorded: Path) -> None:
    text = "I am an AI assistant calling for my customer."
    bundle = read_bundle(recorded)
    rep = next(e.event_id for e in bundle.events if e.type == "utt.final")
    verbatim = {"lane": "cp", "kind": "disclosure", "text": text}
    bundle = _append(bundle, "speak.verbatim", "guard", verbatim, rep)
    bundle = _append(bundle, "speak.released", "kernel", {}, _last_id(bundle))
    released = _last_id(bundle)
    heard = {"lane": "cp", "utt_id": "v1", "text_generated": text, "text_heard": text}
    delivered = heard | {"interrupted": False}
    ok = _append(bundle, "utt.delivered", "kernel", delivered, released)
    assert evidence_check(ok).ok, evidence_check(ok).failures
    twice = _append(ok, "utt.delivered", "kernel", delivered, released)
    assert (
        evidence_check(twice).failures[-1].endswith(f"{released} is already delivered")
    )
    orphan = _append(bundle, "utt.delivered", "kernel", delivered, rep)
    assert (
        evidence_check(orphan)
        .failures[-1]
        .endswith("no chain to a fast.sentence or a released speak.verbatim")
    )
    other_lane = _append(
        bundle, "utt.delivered", "kernel", delivered | {"lane": "user"}, released
    )
    assert evidence_check(other_lane).failures[-1].endswith("is for the other lane")
    wrong = heard | {"text_heard": "I am a human.", "interrupted": True}
    cut = _append(bundle, "utt.delivered", "kernel", wrong, released)
    assert "neither the generated text" in evidence_check(cut).failures[-1]
