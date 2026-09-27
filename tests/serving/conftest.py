# Until the root pyproject gives pytest a pythonpath, make the top-level `serving`
# package importable.
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(autouse=True)
def _no_stray_serving_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A shell's deploy-time variables never reach these tests."""
    for name in ("PL_SERVE_MODEL", "PL_TRAINED_ADAPTER"):
        monkeypatch.delenv(name, raising=False)
