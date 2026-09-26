# Until the root pyproject gives pytest a pythonpath, make the top-level `serving`
# package importable.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
