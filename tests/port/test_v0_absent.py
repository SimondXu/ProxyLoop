from __future__ import annotations

import importlib.util

import pytest


@pytest.mark.parametrize(
    "module",
    ["proxyloop_contracts", "proxyloop_provider_simulator", "proxyloop_telecom_domain"],
)
def test_v0_packages_are_not_importable(module: str) -> None:
    assert importlib.util.find_spec(module) is None
