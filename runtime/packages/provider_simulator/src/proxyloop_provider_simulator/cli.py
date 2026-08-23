from __future__ import annotations

from .episode import run_success_episode


def main() -> int:
    print(run_success_episode().to_json(), end="")
    return 0
