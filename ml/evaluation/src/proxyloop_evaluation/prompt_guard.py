"""Value-level leakage guard for the Phase 03C / relay prompt path.

The frozen Fast prompt guards (``openai_frontier._assert_prompt_allowlist``,
``qwen_mlx._assert_safe_keys``) are key-name-only and stop at ``str`` values,
so JSON encoded inside an event ``content`` string passed them (audit D3-2).
They stay untouched under the r4 execution contract; this wrapper adds the
string-value scan of ``proxyloop_provider_simulator.leakage`` on top, for the
view a prompt is built from and for the rendered ``system``/``user`` text.

The label tier of ``PrivateTokens`` (hazard, outcome, reason-code words,
matched as whole string values) cannot apply to a rendered prompt section,
which is one prose string; the rendered sections are effectively checked for
the identifier tier only.

Known residual, not scanned: ``pins.provider_config_ref`` carries
``"<configuration_id>@2.0"`` in the frozen r2 views and the 03C pins; it is
handled with the next catalogue version (see ``docs/ml-evidence.md``).
"""

from __future__ import annotations

from proxyloop_contracts import FastModelView
from proxyloop_provider_simulator.leakage import (
    PrivateTokens,
    leaked_private_values,
    private_tokens,
)
from proxyloop_provider_simulator.scenarios import BENCHMARK_SCENARIOS

from proxyloop_evaluation.qwen_mlx import QwenPrompt

PRIVATE_TOKENS: PrivateTokens = private_tokens(BENCHMARK_SCENARIOS)


class PrivateValueLeakError(ValueError):
    """A model-facing payload carries a family, configuration, scenario id, or
    private label as a string value."""


def view_scan_payload(view: FastModelView) -> dict[str, object]:
    """The view as JSON, minus the ``pins.provider_config_ref`` residual."""

    payload = view.model_dump(mode="json")
    pins = dict(payload["pins"])
    pins.pop("provider_config_ref", None)
    payload["pins"] = pins
    return payload


def assert_view_private_value_free(view: FastModelView) -> None:
    leaked = leaked_private_values(view_scan_payload(view), PRIVATE_TOKENS)
    if leaked:
        raise PrivateValueLeakError(f"private value in Fast view: {', '.join(leaked)}")


def assert_prompt_private_value_free(prompt: QwenPrompt) -> None:
    for section in ("system", "user"):
        leaked = leaked_private_values(getattr(prompt, section), PRIVATE_TOKENS)
        if leaked:
            raise PrivateValueLeakError(
                f"private value in Fast prompt {section}: {', '.join(leaked)}"
            )


__all__ = [
    "PRIVATE_TOKENS",
    "PrivateValueLeakError",
    "assert_prompt_private_value_free",
    "assert_view_private_value_free",
    "view_scan_payload",
]
