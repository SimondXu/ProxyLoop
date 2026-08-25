#!/usr/bin/env python3
"""Write or verify the deterministic Phase 03B Gate 0 review packet."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from proxyloop_evaluation.phase03b_readiness import (
        PACKET_PATH,
        check_packet_artifact,
        packet_json,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write:
        PACKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        PACKET_PATH.write_text(packet_json(), encoding="utf-8")
        return 0
    if args.check:
        failures = check_packet_artifact()
        if failures:
            print("Phase 03B readiness packet check failed:", *failures, sep="\n- ")
            return 1
        print("Phase 03B readiness packet is valid.")
        return 0
    print(packet_json(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
