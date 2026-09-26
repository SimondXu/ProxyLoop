"""Suite-wide pytest configuration."""

from __future__ import annotations

from hypothesis import settings

# Deterministic runs, and no example database written into the worktree.
settings.register_profile("deterministic", database=None, derandomize=True)
settings.load_profile("deterministic")
