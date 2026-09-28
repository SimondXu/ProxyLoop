"""Suite-wide pytest configuration."""

from __future__ import annotations

import pytest
from hypothesis import settings

# Deterministic runs, and no example database written into the worktree.
settings.register_profile("deterministic", database=None, derandomize=True)
settings.load_profile("deterministic")

# The `serial` group (S1-ROOT-18): tests with a tight wall-clock budget, which
# `make test` runs in a pass of their own, without xdist, so parallel load
# never eats into the budget. Node-id prefixes; the tests themselves unchanged.
SERIAL = (
    # a 60 s wait_for around ~25 s of virtual-time work (flaked on CI)
    "tests/kernel/test_wake.py::test_a_rep_turn_every_2_s_for_720_s_stays_bounded",
    # _wait_for: a 5 s poll for a line from a live kernel (flaked on CI)
    "tests/kernel/test_web.py::test_serve_refuses_a_rep_line_before_the_call_opens",
    "tests/kernel/test_web.py::test_serve_starts_a_case_and_its_posts_reach_the_kernel",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.nodeid.startswith(SERIAL):
            item.add_marker(pytest.mark.serial)
