#!/usr/bin/env python3
"""Generate or verify the deterministic Phase 02 trajectory pilot artifacts."""

from __future__ import annotations

import argparse

from proxyloop_data_pipeline import artifact_payloads, build_pilot


def write_artifacts() -> None:
    for path, content in artifact_payloads().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def check_artifacts() -> tuple[bool, tuple[str, ...]]:
    failures: list[str] = []
    for path, expected in artifact_payloads().items():
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            failures.append(f"artifact_drift:{path.name}")
    report = build_pilot().report
    if report["automated_audit_status"] != "passed":
        failures.append("automated_audit_failed")
    return not failures, tuple(failures)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write:
        write_artifacts()
        return 0
    if args.check:
        passed, failures = check_artifacts()
        if not passed:
            print("Phase 02 data pilot check failed:", *failures, sep="\n- ")
            return 1
        print("Phase 02 data pilot artifacts and audit gate are valid.")
        return 0
    from proxyloop_data_pipeline.pipeline import pretty_json

    print(pretty_json(build_pilot().report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
