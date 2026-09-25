"""Executable localhost server command for the Phase 04B Runtime."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import TextIO

import uvicorn

from .app import create_app
from .config import runtime_from_environment, services_from_environment

app = create_app()

OPERATION_LOGGER_NAME = "proxyloop_api.operations"


class _OperationRecordHandler(logging.StreamHandler[TextIO]):
    """Marks the one handler this module attaches."""


def configure_operation_logging(stream: TextIO | None = None) -> logging.Handler:
    """Emit the allowlisted operation records to stderr, one line each.

    ``JsonLoggingOperationRecorder`` already renders each record as one
    allowlisted JSON message at INFO; this only attaches the handler that the
    server lacked (Phase 07 F1), with the message as the whole line. Calling
    it again returns the handler already attached.
    """

    logger = logging.getLogger(OPERATION_LOGGER_NAME)
    for existing in logger.handlers:
        if isinstance(existing, _OperationRecordHandler):
            return existing
    handler = _OperationRecordHandler(stream if stream is not None else sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return handler


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
    configure_operation_logging()
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


__all__ = ["app", "configure_operation_logging", "main"]
