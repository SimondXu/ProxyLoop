"""Capture v0 behaviour once as JSON fixtures for the ported pure functions.

It runs only against a checkout of tag ``v0-legacy`` (``V0_REF``): after
S0-SYS-02 the v0 packages no longer exist on ``main``. From this repo, with
the v0 tree extracted to ``$V0`` (e.g. ``git archive v0-legacy runtime | tar
-x -C $V0``):

    uv sync --project $V0/runtime --all-packages
    uv run --project $V0/runtime python scripts/sys/capture_v0_fixtures.py

It writes ``tests/fixtures/v0/*.json``. The tests under ``tests/port`` read
only these files, never the v0 packages. The script stays as provenance.
"""

# pyright: basic, reportMissingImports=false

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from proxyloop_provider_simulator import negotiation_splits
from proxyloop_provider_simulator.episode import build_case
from proxyloop_provider_simulator.negotiation import NegotiationEnvironment
from proxyloop_provider_simulator.negotiation_catalog import (
    NEGOTIATION_SCENARIOS,
    ConfirmationMode,
    compliance_context,
    offer_terms_hash,
    offer_violations,
)
from proxyloop_provider_simulator.scenarios import BENCHMARK_SCENARIOS, PublicOffer
from proxyloop_telecom_domain import OfferComplianceContext, unsupported_applied_changes

OUT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "v0"
V0_REF = "v0-legacy@514fe317a23b2aa4b97a69f61daa568f5d791ca6"
SPLIT_SALTS = ("negotiation-split-v2", "port-fixture-1", "port-fixture-2")
PLUS_2H = timezone(timedelta(hours=2))
BASE_SCENARIO = NEGOTIATION_SCENARIOS[0]
BASE_OFFER = BASE_SCENARIO.final_offer
PRICE = BASE_OFFER.monthly_price_minor
NO_TARGET = {"target_monthly_minor": None, "target_currency": None}
FORBIDDEN = str(BASE_SCENARIO.case.goal.forbidden_changes[0])

# (name, offer overrides) around one clean catalogue offer.
HASH_VARIANTS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("unsorted-features", {"features": ("zeta", "alpha", "mid")}),
    ("no-features", {"features": ()}),
    ("padded-features", {"features": (" mobile", "hotspot ")}),
    ("padded-currency", {"currency": " USD"}),
    ("over-long-features", {"features": ("x" * 4001,)}),
    ("non-ascii-feature", {"features": ("café_wifi", "mobile")}),
    ("eur-24-months", {"currency": "EUR", "term_months": 24}),
    ("microsecond-expiry", {"expires_at": BASE_OFFER.expires_at + timedelta(0, 0, 7)}),
    ("offset-expiry", {"expires_at": BASE_OFFER.expires_at.astimezone(PLUS_2H)}),
)

# (name, context overrides, offer overrides): every v0 reason code and check.
POLICY_VARIANTS: tuple[tuple[str, dict[str, Any], dict[str, Any]], ...] = (
    ("currency-mismatch", {}, {"currency": "EUR"}),
    ("target-currency-mismatch", {"target_currency": "EUR"}, {}),
    ("no-target-total-below-current", NO_TARGET, {}),
    (
        "no-target-total-exceeds-current",
        {**NO_TARGET, "current_monthly_minor": PRICE + 1},
        {"fees_minor": 12, "total_cost_12_months_minor": PRICE * 12 + 12},
    ),
    ("price-not-reduced", {"current_monthly_minor": PRICE}, {}),
    ("fee-total-mismatch", {}, {"total_cost_12_months_minor": PRICE * 12 - 1}),
    (
        "known-promotion-credit",
        {},
        {
            "applied_changes": ("plan_change", "predefined_promotion_credit"),
            "total_cost_12_months_minor": PRICE * 12 - 5_000,
        },
    ),
    (
        "unknown-credit-token",
        {},
        {
            "applied_changes": ("plan_change", "loyalty_credit"),
            "total_cost_12_months_minor": PRICE * 12 - 5_000,
        },
    ),
    ("remove-add-on", {}, {"applied_changes": ("remove_add_on:x", "remove_add_on:")}),
    ("required-feature-missing", {}, {"features": ("unlimited_talk_text",)}),
    ("forbidden-change-present", {}, {"applied_changes": ("plan_change", FORBIDDEN)}),
    ("expired", {"evaluated_at": BASE_OFFER.expires_at + timedelta(seconds=1)}, {}),
    ("error-negative-price", {}, {"monthly_price_minor": -1}),
    ("error-bool-fees", {}, {"fees_minor": True}),
    ("error-lowercase-currency", {}, {"currency": "usd"}),
    ("error-duplicate-feature", {}, {"features": ("mobile_hotspot",) * 2}),
    ("error-blank-change", {}, {"applied_changes": ("plan_change", " ")}),
    (
        "error-non-utc-expiry",
        {},
        {"expires_at": BASE_OFFER.expires_at.astimezone(PLUS_2H)},
    ),
    ("error-naive-evaluated-at", {"evaluated_at": datetime(2026, 8, 23, 12)}, {}),
    ("error-negative-target", {"target_monthly_minor": -1}, {}),
    ("error-bad-target-currency", {"target_currency": "US"}, {}),
    ("error-duplicate-forbidden", {"forbidden_changes": ("x", "x")}, {}),
)

UNSUPPORTED_CHANGES = (
    (),
    ("plan_change", "revised_plan_change", "predefined_promotion_credit"),
    ("account_cancellation", "plan_change", "account_cancellation"),
    ("remove_add_on:", "remove_add_on:x", "b", "a", "b"),
    ("Plan_Change", "plan_change "),
)


def _write(name: str, body: dict[str, Any]) -> None:
    path = OUT / name
    body = {"v0_ref": V0_REF, **body}
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", "utf-8")
    print(f"wrote {path.relative_to(OUT.parents[2])}")


def _hash_row(catalogue: str, scenario_id: str, role: str, offer: PublicOffer) -> dict:
    row: dict[str, Any] = {
        "catalogue": catalogue,
        "scenario_id": scenario_id,
        "offer": role,
        "inputs": {
            "monthly_price_minor": offer.monthly_price_minor,
            "total_cost_12_months_minor": offer.total_cost_12_months_minor,
            "currency": offer.currency,
            "term_months": offer.term_months,
            "features": list(offer.features),
            "offer_expires_at": offer.expires_at.isoformat(),
        },
    }
    try:
        row["material_terms_hash"] = offer_terms_hash(offer)
    except ValueError as exc:  # pydantic's ValidationError is a ValueError
        row["error"] = type(exc).__name__
    return row


def capture_terms_hash() -> None:
    rows = [
        _hash_row("negotiation-v1", scenario.scenario_id, role, offer)
        for scenario in NEGOTIATION_SCENARIOS
        for role, offer in (
            ("opening", scenario.opening_offer),
            ("final", scenario.final_offer),
        )
    ]
    rows += [
        _hash_row("benchmark-v1", scenario.scenario_id, f"offer-{index}", offer)
        for scenario in BENCHMARK_SCENARIOS
        for index, offer in enumerate(scenario.provider_turn.offers)
    ]
    rows += [
        _hash_row("synthetic", name, "variant", replace(BASE_OFFER, **overrides))
        for name, overrides in HASH_VARIANTS
    ]
    with_offer = sum(1 for item in BENCHMARK_SCENARIOS if item.provider_turn.offers)
    _write(
        "terms_hash_v1.json",
        {
            "source": "negotiation_catalog.offer_terms_hash (material_terms_hash)",
            # Scenarios that carry at least one offer, so have material terms.
            "scenario_counts": {
                "negotiation-v1": len(NEGOTIATION_SCENARIOS),
                "benchmark-v1": with_offer,
            },
            "benchmark_v1_scenarios_without_offer": len(BENCHMARK_SCENARIOS)
            - with_offer,
            "rows": rows,
        },
    )


def _policy_row(name: str, context: dict[str, Any], offer: PublicOffer) -> dict:
    row: dict[str, Any] = {
        "name": name,
        "context": {**context, "evaluated_at": context["evaluated_at"].isoformat()},
        "offer": offer.to_dict(),
        "unsupported_applied_changes": list(
            unsupported_applied_changes(offer.applied_changes)
        ),
    }
    try:
        built = OfferComplianceContext(**context)
        row["offer_violations"] = list(offer_violations(offer, built))
    except ValueError as exc:
        row["error"] = str(exc)
    return row


def _context(case: Any, at: datetime) -> dict[str, Any]:
    return asdict(compliance_context(case, at))


def capture_offer_policy() -> None:
    cases = [
        _policy_row(
            f"{scenario.scenario_id}/{role}/{at_name}",
            _context(scenario.case, at),
            offer,
        )
        for scenario in NEGOTIATION_SCENARIOS
        for role, offer in (
            ("opening", scenario.opening_offer),
            ("final", scenario.final_offer),
        )
        for at_name, at in (
            ("start", scenario.started_at),
            ("expiry", offer.expires_at),
        )
    ]
    for scenario in BENCHMARK_SCENARIOS:
        context = _context(build_case(scenario.parameters), scenario.observed_at)
        for index, offer in enumerate(scenario.provider_turn.offers):
            cases.append(
                _policy_row(f"{scenario.scenario_id}/offer-{index}", context, offer)
            )
    base = _context(BASE_SCENARIO.case, BASE_SCENARIO.started_at)
    for name, context_overrides, offer_overrides in POLICY_VARIANTS:
        offer = replace(BASE_OFFER, **offer_overrides)
        cases.append(
            _policy_row(f"synthetic/{name}", {**base, **context_overrides}, offer)
        )
    _write(
        "offer_policy.json",
        {
            "source": "negotiation_catalog.offer_violations "
            "(offer_compliance_violations + unsupported_applied_changes)",
            "cases": cases,
            "unsupported_applied_changes": [
                {
                    "changes": list(item),
                    "unsupported": list(unsupported_applied_changes(item)),
                }
                for item in UNSUPPORTED_CHANGES
            ],
        },
    )


def capture_ledger() -> None:
    modes = {
        "honest": ConfirmationMode.HONEST,
        "misquote": ConfirmationMode.LEDGER_BINDS_OTHER,
        "absent": ConfirmationMode.ABSENT,
    }
    rows = []
    for scenario in NEGOTIATION_SCENARIOS:
        for name, mode in modes.items():
            env = NegotiationEnvironment(replace(scenario, confirmation_mode=mode))
            env._issue_confirmation(scenario.final_offer, scenario.started_at)
            rows.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "mode": name,
                    "v0_mode": mode.value,
                    "confirmation_ref": f"{scenario.episode_ref}::confirmation-1",
                    "heard_offer": scenario.final_offer.to_dict(),
                    "ledger": {
                        ref: entry.to_dict() for ref, entry in env._ledger.items()
                    },
                }
            )
    _write(
        "ledger.json",
        {
            "source": "NegotiationEnvironment._issue_confirmation (ledger side)",
            "rows": rows,
        },
    )


def capture_split() -> None:
    runs = []
    for salt in SPLIT_SALTS:
        # v0 reads its salt from this module global at call time.
        negotiation_splits.NEGOTIATION_SPLIT_VERSION = salt
        manifest = negotiation_splits.generate_negotiation_split(NEGOTIATION_SCENARIOS)
        runs.append(
            {
                "salt": salt,
                "family_assignments": manifest.to_dict()["family_assignments"],
            }
        )
    negotiation_splits.NEGOTIATION_SPLIT_VERSION = SPLIT_SALTS[0]
    _write(
        "split.json",
        {"source": "negotiation_splits.generate_negotiation_split", "runs": runs},
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    capture_terms_hash()
    capture_offer_policy()
    capture_ledger()
    capture_split()


if __name__ == "__main__":
    main()
