"""``make pull-through MODE=full|verify`` (TRAINING §9): plumbing only, claim "none".

Root-run (L+G), driven by ``mk/mod.mk``. One subcommand per step group:

- ``select`` (steps 1-2): up to 60 real Fast turns from one explicit label source
  (``base_9b``: base-9B turns, S0 labels, §9 E1; ``hosted``: one hosted model's turns,
  ``--label-model <endpoint>:<model_id>``, the user's decision of 2026-09-28) in
  evidence bundles whose renderer fingerprints equal the current ones (the lane
  profiles in ``kernel.lanes.PROFILE``, exactly), built into rows
  through ``training.dataset`` (``render_prompt`` only) with P5 on every row, and
  each row's provenance next to them.
- ``slot`` (step 4): ``<name>=<path>`` for serving's ``PL_TRAINED_ADAPTER``.
- ``check`` (steps 5-8): liveness through the slot, then one product-path session with
  both lanes on the adapter (``proxyloop.cli session --claim``: ``run_session`` and
  evidence-check), the served echoes and adapter shas, and the result JSON.
- ``liveness``: step 5 alone, for any trained slot (the S0-MOD-02 smoke adapter).

The session is a subprocess of the CLI: nothing here runs the kernel or imports
evidence-check (PLAN §0.2); only the ``kernel.lanes.PROFILE`` constant is read. A dead
endpoint fails the run; nothing is retried.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

import httpx

from proxyloop.contract.base import Lane, canonical_json, sha256_text
from proxyloop.contract.bundle import Bundle, read_bundle
from proxyloop.contract.events import Event
from proxyloop.contract.llm import (
    AdapterKind,
    Endpoint,
    LLMCallRecord,
    TextRequest,
    request_content,
)
from proxyloop.contract.protocol import (
    ParseIssue,
    fingerprint,
    parse_turn,
    render_messages,
)
from proxyloop.contract.views import FastView
from proxyloop.kernel.lanes import PROFILE  # the live lane profiles, read only
from proxyloop.training.dataset import build_row, tokenize_row
from proxyloop.training.masking import verify_trained_span
from serving import config, liveness  # top-level MOD package: run from the repo root

Json = dict[str, Any]
MAX_TURNS = 60
FAST_ROLES = ("fast_user", "fast_cp")
RESULT = Path("docs/results/pull-through.json")


def current_fingerprints() -> dict[str, str]:
    """The profiles the product path renders with now (I3), not every one the contract
    keeps: a bundle or card on a frozen profile is stale, its fingerprint unchanged."""
    return {p: fingerprint(p) for p in sorted(set(PROFILE.values()))}


def fp8(fps: dict[str, str]) -> str:
    return sha256_text(canonical_json(fps))[:8]


def adapter_name(fps: dict[str, str]) -> str:
    return f"{config.TRAINED_PREFIX}pt-{fp8(fps)}"


@dataclass(frozen=True)
class Source:
    """Where the labels come from: a closed choice (TRAINING §3 provenance)."""

    kind: Literal["base_9b", "hosted"]
    endpoint: str
    model_id: str

    @property
    def label(self) -> str:  # rows.json ``source``, copied into the training card
        if self.kind == "base_9b":
            return "base-9B turns (S0 labels, TRAINING §9 E1)"
        return f"hosted {self.endpoint}:{self.model_id} (teacher_exec)"


BASE_9B = Source("base_9b", "vllm", config.SERVED_NAME)
HOSTED_ENDPOINTS = tuple(e for e in get_args(Endpoint) if e != "vllm")


def label_source(kind: str, label_model: str | None) -> Source:
    """``base_9b`` takes no label model; ``hosted`` needs ``<endpoint>:<model_id>``
    on a hosted endpoint (the vLLM base is ``base_9b``)."""
    if kind == "base_9b" and label_model is None:
        return BASE_9B
    if kind == "base_9b":
        raise ValueError("--source base_9b takes no --label-model")
    if kind != "hosted":
        raise ValueError(f"unknown label source {kind!r}: base_9b or hosted")
    endpoint, _, model_id = (label_model or "").partition(":")
    if endpoint not in HOSTED_ENDPOINTS or not model_id:
        raise ValueError(
            f"--source hosted needs --label-model <endpoint>:<model_id> with an "
            f"endpoint in {HOSTED_ENDPOINTS}, got {label_model!r}"
        )
    return Source("hosted", endpoint, model_id)


@dataclass(frozen=True)
class Turn:
    event_id: str  # the fast.turn event
    profile: str
    view: str  # the stored FastView JSON
    raw: str  # the model's response text, as streamed
    prompt_sha: str  # what the model was sent (fast.request): a prompt or messages
    provenance: Json  # rows.json ``provenance``, one per row


def fast_calls(bundle: Bundle) -> list[LLMCallRecord]:
    return [
        LLMCallRecord.model_validate(e.payload)
        for e in bundle.events
        if e.type == "llm.call" and e.payload["role"] in FAST_ROLES
    ]


def unqualified(rec: LLMCallRecord, source: Source) -> str | None:
    """Why ``rec`` is not ``source``'s turn (a funnel key), or None."""
    if source.kind == "base_9b":
        real = rec.adapter_kind is AdapterKind.REAL_HTTP
        ok = real and rec.served_model_echo == config.SERVED_NAME
        return None if ok else "not_base_real_http"
    real = rec.adapter_kind is AdapterKind.REAL_HTTP
    served_by = (rec.model_ref.endpoint, rec.model_ref.model_id)
    if not real or served_by != (source.endpoint, source.model_id):
        return "not_label_model"
    return None if rec.served_model_echo == source.model_id else "echo_mismatch"


def messages_sha(view: FastView, profile: str, rec: LLMCallRecord) -> str:
    """The sha the kernel records for a non-vLLM Fast request (kernel/lanes.py)."""
    messages = render_messages(view, profile)
    request = TextRequest(
        call_id=rec.call_id,
        role=rec.role,
        messages=messages,
        max_tokens=1,  # neither is part of the hashed content
        temperature=0,
    )
    return sha256_text(request_content(request))


def provenance(
    run_id: str, turn: Event, lane: str, profile: str, rec: LLMCallRecord
) -> Json:
    """One row's provenance: ``resamples`` is the fast.turn's (a TeacherRepair turn;
    None when it has none), ``attempt`` the record's HTTP attempt."""
    ref = rec.model_ref
    return {
        "run_id": run_id,
        "event_id": turn.event_id,
        "lane": lane,
        "profile": profile,
        "model_ref": {
            "endpoint": ref.endpoint,
            "model_id": ref.model_id,
            "reasoning_effort": ref.reasoning_effort,
        },
        "served_model_echo": rec.served_model_echo,
        "request_id": rec.request_id,
        "sampling_sent": rec.sampling_sent,
        "resamples": turn.payload.get("resamples"),
        "attempt": rec.attempt,
    }


def label_turns(
    bundle: Bundle, source: Source = BASE_9B
) -> tuple[list[Turn], Counter[str]]:
    """Complete Fast turns ``source`` served over real HTTP; skips are counted. A hosted
    turn's record must hash the request's messages, which must re-render from the
    stored view and profile (its identity check); a base-9B turn's prompt is checked
    in ``p5_rows``, under the tokenizer."""
    events, skipped = bundle.events, Counter[str]()
    asked = {e.payload["gen_id"]: e.payload for e in events if e.type == "fast.request"}
    cancelled = {e.payload["gen_id"] for e in events if e.type == "fast.cancelled"}
    calls = {c.call_id: c for c in fast_calls(bundle) if c.error is None}
    turns: list[Turn] = []
    for e in (e for e in events if e.type == "fast.turn"):
        req, rec = asked[e.payload["gen_id"]], calls.get(str(e.payload["call_id"]))
        if e.payload["gen_id"] in cancelled or rec is None or not rec.response_sha:
            skipped["cancelled_or_no_response"] += 1
            continue
        if reason := unqualified(rec, source):
            skipped[reason] += 1
            continue
        if source.kind == "hosted" and rec.prompt_sha != req["prompt_sha"]:
            skipped["call_prompt_mismatch"] += 1  # the record answered another request
            continue
        if rec.finish_reason != "stop":
            skipped[f"finish_{rec.finish_reason}"] += 1
            continue
        raw = bundle.prompts[rec.response_sha].content
        lane: Lane = "user" if req["lane"] == "user" else "cp"
        profile = str(req["profile"])  # the grammar the turn was served under
        items = parse_turn(raw, lane, profile)
        if not items or any(isinstance(i, ParseIssue) for i in items):
            skipped["empty_or_parse_issue"] += 1
            continue
        view = bundle.prompts[str(req["view_sha"])].content
        sha = str(req["prompt_sha"])
        if source.kind == "hosted":
            fast_view = FastView.model_validate_json(view)
            if messages_sha(fast_view, profile, rec) != sha:
                skipped["messages_sha_mismatch"] += 1
                continue
        prov = provenance(bundle.manifest.run_id, e, lane, profile, rec)
        turns.append(Turn(e.event_id, profile, view, raw, sha, prov))
    return turns, skipped


def load_bundles(root: Path) -> list[Bundle]:
    """Bundles under ``root``; never opens a resolved path with a ``test`` part, the
    root's own included (I9, AGENTS rule 11)."""
    if "test" in root.resolve().parts:
        raise SystemExit(f"{root} is inside a sealed test dir: never a label source")
    dirs = sorted(m.parent.resolve() for m in root.rglob("manifest.json"))
    return [read_bundle(d) for d in dirs if "test" not in d.parts]


def select(
    bundles: Sequence[Bundle], fps: dict[str, str], source: Source = BASE_9B
) -> tuple[list[Turn], Json]:
    """Up to MAX_TURNS turns, newest bundle first; the funnel counts what was left."""
    funnel, chosen = Counter[str](), list[Turn]()
    newest = sorted(bundles, key=lambda b: (b.events[0].wall, b.manifest.run_id))
    for b in reversed(newest):
        if b.manifest.split != "train":
            funnel["bundle_not_train"] += 1
        elif b.manifest.fingerprints != fps:
            funnel["bundle_stale_fingerprint"] += 1
        else:
            turns, skipped = label_turns(b, source)
            funnel.update(skipped)
            chosen += turns
    kept = chosen[:MAX_TURNS]
    counts = {"bundles": len(bundles), "turns": len(chosen), "selected": len(kept)}
    return kept, counts | {"dropped_over_cap": len(chosen) - len(kept), **funnel}


def p5_rows(
    turns: Sequence[Turn], tok: Any, source: Source = BASE_9B
) -> tuple[list[Turn], Json]:
    """Rows as training builds them. A base-9B turn whose re-rendered prompt is not the
    one served is dropped (counted); a hosted turn was sent messages, not this prompt,
    and passed its own identity check in ``label_turns``. P5 on every kept row, and
    not ok aborts the run."""
    kept, failed, drift = list[Turn](), list[Json](), 0
    for t in turns:
        row = build_row(FastView.model_validate_json(t.view), t.profile, t.raw, tok)
        if source.kind == "base_9b" and sha256_text(row.prompt) != t.prompt_sha:
            drift += 1
            continue
        kept.append(t)
        data = tokenize_row(row, tok)
        ids, labels = data["input_ids"], data["labels"]
        if not (report := verify_trained_span(ids, labels, tok, row.completion))["ok"]:
            failed.append({"turn": t.event_id} | report)
    p5 = {"ok": bool(kept) and not failed, "rows": len(kept), "failed": failed}
    return kept, p5 | {"dropped_prompt_mismatch": drift}


def rows_doc(
    turns: Sequence[Turn],
    funnel: Json,
    fps: dict[str, str],
    tok: Any,
    source: Source = BASE_9B,
) -> Json:
    """The rows JSON ``training_jobs.modal_train::pull_through`` trains on; training
    reads ``rows`` and the card keys, never ``provenance``."""
    turns, p5 = p5_rows(turns, tok, source)
    rows = [[t.profile, t.view, t.raw] for t in turns]
    return {
        "fingerprint": fps,
        "fp8": fp8(fps),
        "adapter_name": adapter_name(fps),
        "source": source.label,
        "dataset_hash": sha256_text(canonical_json(rows)),
        "turns": [t.event_id for t in turns],
        "funnel": funnel,
        "p5": p5,
        "rows": rows,
        "provenance": [t.provenance for t in turns],
    }


def provenance_summary(rows: Json) -> Json:
    """The label models (with their reasoning effort), row count and runs behind a
    rows.json (the result card)."""
    prov = rows["provenance"]
    refs = {canonical_json(p["model_ref"]): p["model_ref"] for p in prov}
    models = [refs[k] for k in sorted(refs)]
    runs = sorted({p["run_id"] for p in prov})
    return {"label_models": models, "rows": len(prov), "run_ids": runs}


def echo_failures(bundle: Bundle, name: str) -> list[str]:
    """Both lanes ran on ``name`` and every served Fast response echoes it (I8)."""
    cfg = bundle.manifest.cfg
    refs = {"fast_user": cfg.fast_user, "fast_cp": cfg.fast_cp}
    out = [f"{r} ran {ref.model_id}" for r, ref in refs.items() if ref.model_id != name]
    calls = fast_calls(bundle)  # every echo counts, a cancelled call's too
    echoes = [(c.call_id, c.served_model_echo) for c in calls]
    out += [f"{i} echoed {m!r}" for i, m in echoes if m is not None and m != name]
    roles = {c.role for c in calls if c.error is None}
    return out + [f"no served {r} call" for r in FAST_ROLES if r not in roles]


def shard_failures(
    card: dict[str, str], seen: dict[str, str] | None, where: str
) -> list[str]:
    """The adapter card's shas equal ``seen`` file for file (evidence-check's own
    adapter-card comparison is vacuous while the kernel records no adapter_shards)."""
    return [] if seen == card else [f"{where}: {seen} != the card's {card}"]


def bundle_shards(bundle: Bundle, name: str) -> dict[str, str]:
    prefix = f"adapters/{name}/"
    files = (bundle.manifest.attestation or {}).items()
    return {f.removeprefix(prefix): s for f, s in files if f.startswith(prefix)}


def load_tokenizer() -> Any:  # the pinned tokenizer vLLM serves
    transformers: Any = importlib.import_module("transformers")
    return transformers.AutoTokenizer.from_pretrained(
        config.MODEL_ID, revision=config.MODEL_REVISION
    )


def vllm_client() -> httpx.Client:
    url, key = os.environ.get("PL_VLLM_BASE_URL"), os.environ.get("PL_VLLM_API_KEY")
    if not url or not key:
        raise SystemExit("PL_VLLM_BASE_URL and PL_VLLM_API_KEY must be exported")
    auth = {"Authorization": f"Bearer {key}"}
    return httpx.Client(base_url=url.rstrip("/"), headers=auth, timeout=300)


def probe_slot(name: str) -> Json:
    """Step 5: the slot's /pl/attest shas and prompt_logprobs liveness vs base."""
    pairs = [config.pair_ids(load_tokenizer(), p) for p in config.PAIRS]
    with vllm_client() as client:
        attest: Json = client.get("/pl/attest").raise_for_status().json()
        live = liveness.compare(client, pairs, name)
    live |= {"ok": liveness.live_ok(live), "min_mean": config.LIVE_MIN_MEAN_DIFF}
    return {"attested": attest["adapters"].get(name), "liveness": live}


def read_json(path: Path) -> Json:
    doc: Json = json.loads(path.read_text("utf-8"))
    return doc


def adapter_card(mode: str, run_dir: Path) -> Json:
    """The adapter under test: this run's training (full) or the last result."""
    if mode == "verify":
        prev = read_json(RESULT)
        if prev["fingerprint"] != current_fingerprints():
            raise SystemExit("the renderer fingerprint changed: run MODE=full")
        keys = ("fingerprint", "dataset_hash", "adapter", "adapter_shards", "p5")
        return {k: prev[k] for k in (*keys, "training", "source", "provenance")}
    rows, train = read_json(run_dir / "rows.json"), read_json(run_dir / "train.json")
    p5 = {"ok": rows["p5"]["ok"] and train["p5"]["ok"], "rows": rows["p5"]["rows"]}
    return {
        "fingerprint": rows["fingerprint"],
        "dataset_hash": rows["dataset_hash"],
        "adapter": {
            "name": rows["adapter_name"],
            "path": f"train/{train['run_id']}/adapter",
        },
        "adapter_shards": train["adapter_sha256"],
        "p5": p5 | {"on": "every row locally and the first real training batch"},
        "training": {k: train[k] for k in ("run_id", "recipe", "lora", "batch_note")},
        "source": rows["source"],
        "provenance": provenance_summary(rows),
    }


def check(mode: str, run_dir: Path, family: str) -> int:
    """Steps 5-8. The result reaches docs/results only if every check passed."""
    card = adapter_card(mode, run_dir)
    name, shards = card["adapter"]["name"], card["adapter_shards"]
    probe = probe_slot(name)
    fps = current_fingerprints()
    checks = {"fingerprint_current": card["fingerprint"] == fps, "p5": card["p5"]["ok"]}
    checks["liveness"] = probe["liveness"]["ok"]
    failures = shard_failures(shards, probe["attested"], "/pl/attest")
    doc = {"mode": mode, "claim": "none", **card, "liveness": probe["liveness"]}
    if all(checks.values()) and not failures:  # else no product session is paid for
        write(run_dir / "pull-through.json", doc)  # the probe survives a CLI crash
        runs = run_dir / "sessions"
        cli = [sys.executable, "-m", "proxyloop.cli", "session", "--family", family]
        cli += ["--fast-model", name, "--runs", str(runs), "--claim"]
        code = subprocess.run(cli, check=False).returncode  # --claim: evidence-check
        (bundle_dir,) = [d for d in runs.iterdir() if d.is_dir()]
        bundle = read_bundle(bundle_dir)
        failures += echo_failures(bundle, name)
        failures += shard_failures(shards, bundle_shards(bundle, name), "bundle")
        checks["bundle_fingerprint"] = bundle.manifest.fingerprints == fps
        checks["evidence_check_claim"] = code == 0
        doc |= {"run_id": bundle.manifest.run_id, "bundle": str(bundle_dir)}
        doc["cli_exit"] = code
    checks["echoes_and_shards"] = not failures and "evidence_check_claim" in checks
    doc |= {"checks": checks, "failures": failures, "passed": all(checks.values())}
    write(run_dir / "pull-through.json", doc)  # a paid run is never lost
    if doc["passed"]:
        write(RESULT, doc)
    print(json.dumps({"checks": checks, "failures": failures}, indent=1))
    return 0 if doc["passed"] else 1


def write(path: Path, doc: Json) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", "utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="proxyloop.training.pull_through")
    sub = parser.add_subparsers(dest="cmd", required=True)
    select_p, slot_p, check_p = (sub.add_parser(c) for c in ("select", "slot", "check"))
    for p in (select_p, slot_p, check_p):
        p.add_argument("--dir", required=True, help="this pull-through run's dir")
    for p in (slot_p, check_p):
        p.add_argument("--mode", choices=("full", "verify"), required=True)
    select_p.add_argument("--evidence", default="evidence/s0")
    select_p.add_argument("--source", choices=("base_9b", "hosted"), required=True)
    select_p.add_argument("--label-model", help="hosted only: <endpoint>:<model_id>")
    check_p.add_argument("--family", default="cp-direct-discount")
    live_p = sub.add_parser("liveness")
    live_p.add_argument("--name", required=True)
    live_p.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "select":
        try:
            source = label_source(args.source, args.label_model)
        except ValueError as e:
            parser.error(str(e))
        fps = current_fingerprints()
        turns, funnel = select(load_bundles(Path(args.evidence)), fps, source)
        doc = rows_doc(turns, funnel, fps, load_tokenizer(), source)
        write(Path(args.dir) / "rows.json", doc)
        print(json.dumps({"funnel": funnel, "p5": doc["p5"]["ok"]}))
        return 0 if doc["p5"]["ok"] else 1
    if args.cmd == "slot":
        adapter = adapter_card(args.mode, Path(args.dir))["adapter"]
        print(f"{adapter['name']}={adapter['path']}")
        return 0
    if args.cmd == "liveness":
        probe = probe_slot(args.name)
        write(Path(args.out), {"name": args.name, **probe})
        print(json.dumps({"liveness_ok": probe["liveness"]["ok"]}))
        return 0 if probe["liveness"]["ok"] else 1
    return check(args.mode, Path(args.dir), args.family)


if __name__ == "__main__":
    sys.exit(main())
