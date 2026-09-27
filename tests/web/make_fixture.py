"""The web replay fixture: one whole ``run_session`` on scripted fakes
(``test_fake``, tests/support/sessions.py), so the viewer has a real bundle to
play before any evidence bundle exists. Synthetic only (I11).

``uv run python -m tests.web.make_fixture`` writes ``tests/web/fixtures/<run_id>/``.
It refuses to run while a fixture exists: ``git rm`` the old one first.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from tests.support.sessions import act, ear, only_bundle, reply, run

from proxyloop.contract.bundle import EVENTS, MANIFEST, PROMPTS

FIXTURES = Path(__file__).parent / "fixtures"
NAME = "Dana Reyes"  # the synthetic principal of the S0 family
SCRIPTS = {
    "simuser": [
        reply(
            f"Please get me a lower price. I am {NAME}.",
            **{"account.holder_name": NAME},
        )
    ],
    "fast_user": [
        f"Sure, I will call them now.\n@slow: fact account.holder_name={NAME}"
    ],
    "ear": [ear("other"), ear("ask_discount")],
    "mouth": ["Okay."],
    "fast_cp": ["Could you lower the monthly price?\n@slow: fact monthly_price=75.00"],
    "slow": [
        act(
            "The user wants a lower price.",
            {"tool": "tell_user", "text": "I am calling them now."},
            {"tool": "record_fact", "key": "account.holder_name", "value": NAME},
            public=f"Calling for {NAME}, who pays at most 70 a month.",
        ),
        act("Waiting for the call.", {"tool": "wait", "seconds": 5}),
    ],
}
FINISH = act("Done.", {"tool": "finish", "outcome": "info_only", "summary": "ok"})
UNTIL = {"slow": ("] cp_update", FINISH)}  # Slow ends once the call relayed


def generate(scratch: Path) -> Path:
    """Run the scripted session under ``scratch``; return its bundle directory."""

    result = run(scratch, SCRIPTS, until=UNTIL)
    only_bundle(scratch)  # exactly one bundle, and it reads
    return result.path


def main() -> int:
    if FIXTURES.exists() and any(FIXTURES.iterdir()):
        print(f"{FIXTURES} is not empty: git rm the old fixture first", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as scratch:
        run_dir = generate(Path(scratch))
        target = FIXTURES / run_dir.name
        target.mkdir(parents=True)
        for name in (MANIFEST, EVENTS, PROMPTS):
            shutil.copyfile(run_dir / name, target / name)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
