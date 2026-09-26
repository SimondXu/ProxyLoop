# Until the root pyproject gives pytest a pythonpath, make the top-level `serving` and
# `training_jobs` packages importable (as tests/serving/conftest.py does).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
