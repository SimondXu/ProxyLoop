"""Fixtures for the agent-scoped hook tests (S1-ROOT-24); helpers in hooks_layout."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.harness.hooks_layout import Layout, make_layout


@pytest.fixture(scope="module")
def layout(tmp_path_factory: pytest.TempPathFactory) -> Layout:
    """A read-only layout shared by one test module."""
    return make_layout(tmp_path_factory.mktemp("hooks"))


@pytest.fixture
def fresh_layout(tmp_path: Path) -> Layout:
    """A layout a test may mutate (commits, dirty files)."""
    return make_layout(tmp_path)
