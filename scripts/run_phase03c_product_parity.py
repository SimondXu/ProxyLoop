#!/usr/bin/env python
"""M2 input parity (E1) and the gate pass rate on the product rendering path.

The same 240 Phase 03C held-out rows as M1, rendered the way the product does
it: the latest Provider event is the plain Provider message (not the trained
marker), the observation is ``fast_public_observation(snapshot)`` (PR-9a), and
the gateway's ``trained_view`` puts it into the v6 prompt.  Rows whose
product-path prompt is byte-identical to the trained prompt reuse the M1
outputs; the others are generated again.  Every output is then replayed
through the runtime's delivery rules: a succeeded output with no fact updates
is compiled against the product view, validated with
``CaseCoordinator.validate_fast_result``, and checked with PR-8's
``fast_disclosure_violations``; only a line that passes all of them is
delivered.  The same gate is also applied to the M1 outputs on the trained
snapshots.

Modes, as in ``run_phase03c_local_parity``:

``--plan``      print the deterministic divergence summary; no model.
``--run``       generate the diverging rows for one backend (resumable,
                git-ignored JSONL; needs MLX and ``HF_HUB_OFFLINE=1``).
``--write``     combine both arms' runs, the M1 report and the plan into the
                committed ``product-path-report.json``.
``--check``     validate the row sets and identities, recompute every derived
                field, and require the committed bytes.  No model.
``--rebuild-from-report``
                re-derive every delivery stage, gate code and aggregate from
                the committed per-row raw outputs and rewrite the report.  No
                model and no git-ignored run files: after a change to the gate,
                validation, compile or the observation, this regenerates the
                report, as long as every generated row's product prompt is
                unchanged (otherwise the model must run again).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_phase03c_local_parity  # noqa: E402
from proxyloop_agent_core import (  # noqa: E402
    CaseCoordinator,
    FastAdapterResult,
    SafeObservation,
)
from proxyloop_agent_core.disclosure_gate import (  # noqa: E402
    FAST_GATE_VERSION,
    fast_disclosure_violations,
)
from proxyloop_agent_core.fast_observation import (  # noqa: E402
    FAST_OBSERVATION_VERSION,
    ObservationRefusal,
    fast_public_observation,
)
from proxyloop_contracts import CaseContextSnapshot, FastModelView  # noqa: E402
from proxyloop_evaluation.fast_output import (  # noqa: E402
    FastModelOutput,
    compile_fast_output,
)
from proxyloop_evaluation.fast_parse import extract_fast_json  # noqa: E402
from proxyloop_evaluation.local_fast.identity import (  # noqa: E402
    BACKENDS,
    GatewayIdentity,
)
from proxyloop_evaluation.local_fast.parity import parsed_act  # noqa: E402
from proxyloop_evaluation.local_fast.trained_view import trained_view  # noqa: E402
from proxyloop_evaluation.phase03b_readiness import (  # noqa: E402
    TARGET_DIALOGUE_ACTS,
)
from proxyloop_evaluation.phase03c_prompt_set import (  # noqa: E402
    build_parameterised_snapshot,
    render_prompt,
    render_prompt_view,
)
from proxyloop_evaluation.phase03c_scenarios import _oracle  # noqa: E402
from rescore_phase03c_heldout import build_index, oracle_act, wilson  # noqa: E402
from run_phase03c_local_parity import (  # noqa: E402
    ATTESTATION,
    CLOUD_REPORT,
    CODE_STATE_KEYS,
    DEFAULT_ADAPTER,
    OBSERVED_ROW_KEYS,
    PARITY_DIR,
    PROMPT_VERSION,
    RUNS_DIR,
    _cloud_prompt_ids,
    _render,
    current_code_state,
    host_facts,
)

M1_REPORT = run_phase03c_local_parity.REPORT
SCHEMA_VERSION = "phase-03c-product-path-v1"
REPORT = PARITY_DIR / "product-path-report.json"
OBSERVED_ARM_KEYS = ("identity", "host", "load_ms", "code_state")
FLAG_FIELDS = frozenset(
    {
        "needs_clarification",
        "transfer_available",
        "approval_current",
        "confirmation_evidence_available",
    }
)
CLAIM_BOUNDARY = (
    "M2 input parity (E1) and the gate pass rate: the 240 Phase 03C held-out "
    "rows rendered through the product path (plain Provider message, "
    "fast_public_observation with its declared Provider-state defaults and no "
    "applied changes), generated locally with MLX on one Apple-silicon machine, "
    "and replayed through the runtime delivery rules offline (compile, "
    "validate_fast_result with bounded=False, fast-gate-v1). The strategy text "
    "is the training fixture's, not the product Slow's (D6), and the prompt "
    "never contains the consumer's words (D5): neither is measured here. "
    "Integrity limits as in M1: --check cannot verify that raw outputs came "
    "from the model, and report_fingerprint is not a signature. Latencies are "
    "descriptive (one machine, sequential, uncontrolled load), not p95 or "
    "capacity. A local opt-in candidate, never promoted; the four Phase 03C "
    "caveats and E1-E5 apply."
)


def _display(path: Path) -> Path:
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


REBUILD_HINT = (
    "if a gate, validation, compile or observation change made it stale, run "
    "`python -m scripts.run_phase03c_product_parity --rebuild-from-report` "
    "(model-free; refuses if a product prompt changed) and review the diff"
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ("plan", "run", "write", "check", "rebuild-from-report"):
        mode.add_argument(f"--{name}", action="store_true")
    parser.add_argument("--backend", choices=BACKENDS)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--adapter-path", type=Path, default=DEFAULT_ADAPTER)
    return parser.parse_args(argv)


def product_snapshot(scenario: Any, position: Any) -> CaseContextSnapshot:
    """The held-out snapshot with the latest Provider event as plain text."""

    snapshot = build_parameterised_snapshot(scenario, position)
    events = list(snapshot.visible_events)
    events[-1] = events[-1].model_copy(
        update={"content": position.provider_turn.message}
    )
    data = snapshot.model_dump(mode="python")
    data["visible_events"] = tuple(event.model_dump(mode="python") for event in events)
    return CaseContextSnapshot.model_validate(data)


def _diverging_fields(product: SafeObservation, true: SafeObservation) -> list[str]:
    left, right = product.to_dict(), true.to_dict()
    fields: set[str] = set()
    for key in left:
        if key == "offers":
            continue
        if left[key] != right[key]:
            fields.add(key)
    offers_left = cast(list[dict[str, Any]], left["offers"])
    offers_right = cast(list[dict[str, Any]], right["offers"])
    if len(offers_left) != len(offers_right):
        fields.add("offers")
    else:
        for a, b in zip(offers_left, offers_right, strict=True):
            fields.update(f"offers[].{key}" for key in a if a[key] != b[key])
    return sorted(fields)


def _divergence_class(fields: Sequence[str]) -> str:
    classes: set[str] = set()
    for field in fields:
        if field == "requested_disclosures":
            classes.add("requested_disclosures_dropped")
        elif field in FLAG_FIELDS:
            classes.add("provider_flags_defaulted")
        elif field == "offers[].applied_changes":
            classes.add("applied_changes_dropped")
        else:
            classes.add(f"other:{field}")
    return "+".join(sorted(classes)) or "none"


def _product_oracle_act(observation: SafeObservation) -> str:
    return TARGET_DIALOGUE_ACTS[_oracle().decide(observation).action.value][0]


def plan_rows() -> list[dict[str, Any]]:
    """Deterministic, per held-out row, in the cloud A3 order."""

    cloud = json.loads(CLOUD_REPORT.read_text(encoding="utf-8"))
    index = build_index(PROMPT_VERSION)
    rows: list[dict[str, Any]] = []
    for prompt_id in _cloud_prompt_ids(cloud, "distilled"):
        scenario, position, rendered = index[prompt_id]
        snapshot = product_snapshot(scenario, position)
        view = CaseCoordinator.project_fast_view(snapshot)
        observation = fast_public_observation(snapshot)
        row: dict[str, Any] = {
            "prompt_id": prompt_id,
            "family_id": str(rendered["family_id"]),
            "split": str(rendered["split"]),
            "oracle_act": oracle_act(rendered),
            "trained_prompt_fingerprint": str(rendered["prompt_fingerprint"]),
        }
        if isinstance(observation, ObservationRefusal):
            row.update(
                refusal_codes=list(observation.reason_codes),
                diverging_fields=None,
                divergence_class="observation_refused",
                product_oracle_act=None,
                product_prompt_fingerprint=None,
                prompt_identical=False,
            )
        else:
            fields = _diverging_fields(observation, position.observation)
            try:
                fingerprint: str | None = render_prompt(
                    trained_view(view, observation)
                ).fingerprint
            except (ValueError, KeyError, TypeError):
                fingerprint = None
            row.update(
                refusal_codes=None,
                diverging_fields=fields,
                divergence_class=_divergence_class(fields),
                product_oracle_act=_product_oracle_act(observation),
                product_prompt_fingerprint=fingerprint,
                prompt_identical=fingerprint == row["trained_prompt_fingerprint"],
            )
        rows.append(row)
    return rows


def _needs_generation(row: dict[str, Any]) -> bool:
    return (
        not row["prompt_identical"]
        and row["refusal_codes"] is None
        and row["product_prompt_fingerprint"] is not None
    )


def run(args: argparse.Namespace) -> int:
    from proxyloop_evaluation.local_fast.gateway_core import LocalFastGatewayCore

    if args.backend is None or args.model_path is None:
        raise SystemExit("--run needs --backend and --model-path")
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        raise SystemExit("set HF_HUB_OFFLINE=1: the parity run never downloads")
    targets = [row for row in plan_rows() if _needs_generation(row)]
    index = build_index(PROMPT_VERSION)
    distilled = args.backend == "distilled"
    code_state = current_code_state()
    started = time.monotonic()
    core = LocalFastGatewayCore.load(
        backend=args.backend,
        model_path=args.model_path,
        adapter_path=args.adapter_path if distilled else None,
        attestation=_attestation() if distilled else None,
    )
    load_ms = round((time.monotonic() - started) * 1000)
    identity = core.identity.to_dict()
    print(f"loaded {args.backend} in {load_ms} ms; {len(targets)} rows", flush=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"product-{args.backend}.jsonl"
    done: set[str] = set()
    if path.exists():
        lines = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        if not lines or lines[0].get("identity") != identity:
            raise SystemExit(f"{path.name} was produced by a different identity")
        done = {str(line["prompt_id"]) for line in lines[1:]}
    else:
        header = {
            "kind": "header",
            "identity": identity,
            "host": host_facts(),
            "load_ms": load_ms,
            "code_state": code_state,
        }
        path.write_text(json.dumps(header, sort_keys=True) + "\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as stream:
        for number, row in enumerate(targets, start=1):
            if row["prompt_id"] in done:
                continue
            scenario, position, _ = index[row["prompt_id"]]
            snapshot = product_snapshot(scenario, position)
            observation = fast_public_observation(snapshot)
            assert isinstance(observation, SafeObservation)
            began = time.monotonic()
            result = core.decide(
                CaseCoordinator.project_fast_view(snapshot), observation
            )
            wall_ms = round((time.monotonic() - began) * 1000)
            record = {
                "kind": "row",
                "prompt_id": row["prompt_id"],
                "raw_output": result.raw_output,
                "status": result.status,
                "detail_code": result.detail_code,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "generation_ms": result.generation_ms,
                "wall_ms": wall_ms,
                "prompt_fingerprint": result.prompt_fingerprint,
            }
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            print(
                f"{number}/{len(targets)} {result.status} "
                f"act={parsed_act(result.raw_output)} {wall_ms} ms",
                flush=True,
            )
    return 0


def _attestation() -> Any:
    from proxyloop_evaluation.local_fast.mlx_adapter_conversion import (
        load_attestation,
    )

    return load_attestation(ATTESTATION)


def _delivery(
    raw: str | None,
    status: str,
    view: FastModelView,
    snapshot: CaseContextSnapshot,
) -> dict[str, Any]:
    """The runtime delivery rules replayed offline for one output."""

    if status != "succeeded" or raw is None:
        return {"stage": f"gateway_{status}", "codes": [], "delivered": False}
    text, _ = extract_fast_json(raw)
    output = FastModelOutput.model_validate_json(text)
    if output.fact_updates:
        return {"stage": "fact_updates_not_empty", "codes": [], "delivered": False}
    try:
        decision = compile_fast_output(view, output)
    except ValueError:
        return {"stage": "output_compile_refused", "codes": [], "delivered": False}
    audit = CaseCoordinator.validate_fast_result(
        FastAdapterResult(pins=view.pins, decision=decision), snapshot
    )
    if not audit.accepted:
        return {
            "stage": "validation_rejected",
            "codes": list(audit.reason_codes),
            "delivered": False,
        }
    codes = list(fast_disclosure_violations(decision, snapshot))
    return {
        "stage": "gate_rejected" if codes else "delivered",
        "codes": codes,
        "delivered": not codes,
    }


def _observed_from_runs(plan: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    targets = [row["prompt_id"] for row in plan if _needs_generation(row)]
    observed: dict[str, dict[str, Any]] = {}
    for backend in BACKENDS:
        path = RUNS_DIR / f"product-{backend}.jsonl"
        lines = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        header, rows = lines[0], {str(row["prompt_id"]): row for row in lines[1:]}
        if set(rows) != set(targets) or len(lines) - 1 != len(targets):
            raise SystemExit(f"{path.name} has {len(lines) - 1}/{len(targets)} rows")
        observed[backend] = {
            **{key: header[key] for key in OBSERVED_ARM_KEYS},
            "rows": [
                {key: rows[pid][key] for key in OBSERVED_ROW_KEYS} for pid in targets
            ],
        }
    return observed


def _observed_from_report(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        backend: {
            **{key: arm[key] for key in OBSERVED_ARM_KEYS},
            "rows": arm["generated_rows"],
        }
        for backend, arm in report["arms"].items()
    }


def validate_observed(
    observed: dict[str, dict[str, Any]], plan: list[dict[str, Any]]
) -> None:
    """Exactly the diverging rows in plan order, under the served identity."""

    attestation = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    targets = [row["prompt_id"] for row in plan if _needs_generation(row)]
    if set(observed) != set(BACKENDS):
        raise SystemExit("the report needs both the distilled and untuned arms")
    for backend in BACKENDS:
        arm = observed[backend]
        if [row["prompt_id"] for row in arm["rows"]] != targets:
            raise SystemExit(
                f"{backend} generated rows differ from the diverging product rows"
            )
        recorded = arm["identity"]
        expected = GatewayIdentity(
            backend=backend,
            adapter_fingerprint=(
                str(attestation["output"]["content_fingerprint"])
                if backend == "distilled"
                else None
            ),
            mlx_versions=dict(recorded.get("mlx_versions", {})),
        ).to_dict()
        if recorded != expected:
            raise SystemExit(f"{backend} identity differs from the served identity")
        if set(arm["code_state"]) != CODE_STATE_KEYS:
            raise SystemExit(f"{backend} code_state is malformed")
        prompts = {row["prompt_id"]: row["product_prompt_fingerprint"] for row in plan}
        changed = sum(
            1
            for row in arm["rows"]
            if row["prompt_fingerprint"] != prompts[row["prompt_id"]]
        )
        if changed:
            raise SystemExit(
                f"{backend}: {changed} generated rows answer a product prompt that "
                "is no longer the recomputed one; the model must run again "
                "(--run, then --write)"
            )


def _rate(rows: list[dict[str, Any]], key: str) -> dict[str, float | int]:
    count = sum(1 for row in rows if row[key])
    return {"count": count, **wilson(count, len(rows))}


def build_report(
    observed: dict[str, dict[str, Any]], plan: list[dict[str, Any]]
) -> dict[str, object]:
    m1 = json.loads(M1_REPORT.read_text(encoding="utf-8"))
    index = build_index(PROMPT_VERSION)
    arms: dict[str, object] = {}
    for backend in BACKENDS:
        m1_rows = {row["prompt_id"]: row for row in m1["arms"][backend]["rows"]}
        generated = {row["prompt_id"]: row for row in observed[backend]["rows"]}
        rows: list[dict[str, Any]] = []
        for planned in plan:
            prompt_id = planned["prompt_id"]
            scenario, position, _ = index[prompt_id]
            m1_row = m1_rows[prompt_id]
            trained_snapshot = build_parameterised_snapshot(scenario, position)
            trained_delivery = _delivery(
                m1_row["raw_output"],
                m1_row["status"],
                render_prompt_view(scenario, position),
                trained_snapshot,
            )
            if planned["refusal_codes"] is not None:
                source, raw, status = "observation_refused", None, "unrenderable"
            elif planned["product_prompt_fingerprint"] is None:
                source, raw, status = "prompt_render_refused", None, "unrenderable"
            elif planned["prompt_identical"]:
                source, raw, status = (
                    "m1_reused",
                    m1_row["raw_output"],
                    m1_row["status"],
                )
            else:
                item = generated[prompt_id]
                if item["prompt_fingerprint"] != planned["product_prompt_fingerprint"]:
                    raise SystemExit(f"{prompt_id}: generated from another prompt")
                source, raw, status = "m2_generated", item["raw_output"], item["status"]
            snapshot = product_snapshot(scenario, position)
            delivery = _delivery(
                raw, status, CaseCoordinator.project_fast_view(snapshot), snapshot
            )
            act = parsed_act(raw) if status == "succeeded" else None
            rows.append(
                {
                    "prompt_id": prompt_id,
                    "source": source,
                    "local_act": act,
                    "agrees_true_oracle": act == planned["oracle_act"],
                    "agrees_product_oracle": (
                        act is not None and act == planned["product_oracle_act"]
                    ),
                    "delivery": delivery,
                    "trained_path_delivery": trained_delivery,
                }
            )
        stages = Counter(row["delivery"]["stage"] for row in rows)
        trained_stages = Counter(row["trained_path_delivery"]["stage"] for row in rows)
        gate_codes = Counter(
            code
            for row in rows
            for code in row["delivery"]["codes"]
            if row["delivery"]["stage"] == "gate_rejected"
        )
        reached_gate = [
            row
            for row in rows
            if row["delivery"]["stage"] in ("delivered", "gate_rejected")
        ]
        trained_reached = [
            row
            for row in rows
            if row["trained_path_delivery"]["stage"] in ("delivered", "gate_rejected")
        ]
        for row in rows:
            row["delivered"] = row["delivery"]["delivered"]
            row["trained_delivered"] = row["trained_path_delivery"]["delivered"]
        by_source = Counter(row["source"] for row in rows)
        generation = [int(row["generation_ms"]) for row in observed[backend]["rows"]]
        arms[backend] = {
            **{key: observed[backend][key] for key in OBSERVED_ARM_KEYS},
            "generated_rows": observed[backend]["rows"],
            "rows": rows,
            "summary": {
                "rows": len(rows),
                "sources": dict(sorted(by_source.items())),
                "act_agreement_true_oracle": _rate(rows, "agrees_true_oracle"),
                "act_agreement_product_oracle": _rate(rows, "agrees_product_oracle"),
                "delivered_line": _rate(rows, "delivered"),
                "delivery_stages": dict(sorted(stages.items())),
                "gate_pass_among_gated": {
                    "passed": stages["delivered"],
                    "gated": len(reached_gate),
                },
                "gate_rejection_codes": dict(sorted(gate_codes.items())),
                "trained_path_delivered_line": _rate(rows, "trained_delivered"),
                "trained_path_delivery_stages": dict(sorted(trained_stages.items())),
                "trained_path_gate_pass_among_gated": {
                    "passed": trained_stages["delivered"],
                    "gated": len(trained_reached),
                },
                "generation_ms_generated_rows": {
                    "total": sum(generation),
                    "max": max(generation, default=0),
                },
            },
        }
    classes = Counter(row["divergence_class"] for row in plan)
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "result_role": "local_measurement",
        "measurement": "M2 input parity (E1) and the delivered-line (gate) rate",
        "labels": {
            "distilled": "local opt-in candidate",
            "untuned": "untuned local baseline",
        },
        "source_m1_report": {
            "path": str(M1_REPORT.relative_to(ROOT)),
            "sha256": hashlib.sha256(M1_REPORT.read_bytes()).hexdigest(),
        },
        "versions": {
            "fast_observation": FAST_OBSERVATION_VERSION,
            "fast_gate": FAST_GATE_VERSION,
            "prompt": PROMPT_VERSION,
        },
        "definitions": {
            "act_agreement_true_oracle": (
                "the gateway succeeded and its dialogue_act equals the oracle act "
                "of the row's true observation"
            ),
            "act_agreement_product_oracle": (
                "the same, against the oracle's act for the product-rendered "
                "observation; the difference is renderer information loss"
            ),
            "delivered_line": (
                "succeeded, no fact updates, compiles against the product view, "
                "accepted by validate_fast_result (bounded=False), and no "
                "fast-gate-v1 code: the line the runtime would show"
            ),
            "gate_pass_among_gated": "delivered / outputs that reached the gate",
            "compile": (
                "ml's frozen compile_fast_output copy; the runtime compiles with "
                "proxyloop_openai_adapter's"
            ),
        },
        "divergence": {
            "classes": dict(sorted(classes.items())),
            "prompt_identical_rows": sum(1 for row in plan if row["prompt_identical"]),
            "generated_rows": sum(1 for row in plan if _needs_generation(row)),
        },
        "plan": plan,
        "claim_boundary": CLAIM_BOUNDARY,
        "arms": arms,
    }
    document["report_fingerprint"] = hashlib.sha256(
        json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return document


def _print_summary(document: dict[str, Any]) -> None:
    print("divergence:", json.dumps(document["divergence"], sort_keys=True))
    for backend, arm in document["arms"].items():
        summary = arm["summary"]
        true_agree = summary["act_agreement_true_oracle"]["count"]
        product_agree = summary["act_agreement_product_oracle"]["count"]
        delivered = summary["delivered_line"]["count"]
        trained = summary["trained_path_delivered_line"]["count"]
        print(
            f"{backend}: agree(true) {true_agree}/240 "
            f"agree(product) {product_agree}/240 delivered {delivered}/240 "
            f"(trained path {trained}/240) stages {summary['delivery_stages']}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.run:
        return run(args)
    plan = plan_rows()
    if args.plan:
        classes = Counter(row["divergence_class"] for row in plan)
        print("classes:", dict(sorted(classes.items())))
        print("prompt identical:", sum(1 for row in plan if row["prompt_identical"]))
        print("to generate:", sum(1 for row in plan if _needs_generation(row)))
        agree = sum(1 for row in plan if row["oracle_act"] == row["product_oracle_act"])
        print("true oracle act == product oracle act:", agree, "/", len(plan))
        return 0
    if args.write:
        observed = _observed_from_runs(plan)
        validate_observed(observed, plan)
        rendered = _render(build_report(observed, plan))
        REPORT.write_text(rendered, encoding="utf-8")
        print(f"wrote {_display(REPORT)}")
    elif args.rebuild_from_report:
        committed = REPORT.read_text(encoding="utf-8")
        observed = _observed_from_report(json.loads(committed))
        validate_observed(observed, plan)
        rendered = _render(build_report(observed, plan))
        REPORT.write_text(rendered, encoding="utf-8")
        state = "unchanged" if rendered == committed else "changed"
        print(f"rebuilt {_display(REPORT)} from its raw outputs ({state})")
    else:
        committed = REPORT.read_text(encoding="utf-8")
        report = json.loads(committed)
        if report["plan"] != plan:
            raise SystemExit(
                f"the committed plan differs from the recomputed one; {REBUILD_HINT}"
            )
        observed = _observed_from_report(report)
        validate_observed(observed, plan)
        rendered = _render(build_report(observed, plan))
        if committed != rendered:
            raise SystemExit(
                f"{_display(REPORT)} is stale or was edited; {REBUILD_HINT}"
            )
        print(f"checked {_display(REPORT)}")
    _print_summary(json.loads(rendered))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
