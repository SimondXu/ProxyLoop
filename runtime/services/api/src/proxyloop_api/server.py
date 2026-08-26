"""Executable localhost server command for the Phase 04B Runtime."""

from __future__ import annotations

import argparse
import asyncio
import os

import uvicorn

from .app import create_app
from .config import runtime_from_environment, services_from_environment

app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ProxyLoop local Runtime")
    parser.add_argument("--mode", choices=("scripted", "model"), default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    orchestration_mode = os.environ.get("PROXYLOOP_ORCHESTRATION_MODE", "direct")
    try:
        if orchestration_mode == "direct":
            runtime = runtime_from_environment(mode=args.mode)
            temporal_client = None
        else:
            services = asyncio.run(services_from_environment(mode=args.mode))
            runtime = services.runtime
            temporal_client = services.temporal_client
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    uvicorn.run(
        create_app(
            runtime,
            temporal_client=temporal_client,
        ),
        host=args.host,
        port=args.port,
        log_level="error",
    )


if __name__ == "__main__":
    main()


__all__ = ["app", "main"]
