# As tests/serving/conftest.py: until the root pyproject gives pytest a pythonpath,
# make the top-level `scripts` and `serving` packages importable (llm_smoke's goldens).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
