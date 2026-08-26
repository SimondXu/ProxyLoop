"""Executable Temporal Worker entry point for the scripted Case Workflow."""

from __future__ import annotations

import argparse
import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from .activities import (
    CaseCommandActivityAdapter,
    activity_for_adapter,
    channel_activity_for_adapter,
    runtime_from_environment,
)
from .client import TemporalCaseClient
from .config import TemporalSettings, temporal_settings_from_environment
from .workflow import CaseWorkflow


def create_worker(
    client: Client,
    settings: TemporalSettings,
    *,
    adapter: CaseCommandActivityAdapter | None = None,
) -> Worker:
    """Construct a Worker with exactly the Case Workflow and activity."""

    selected_adapter = adapter or CaseCommandActivityAdapter(runtime_from_environment())
    return Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[CaseWorkflow],
        activities=[
            activity_for_adapter(selected_adapter),
            channel_activity_for_adapter(selected_adapter),
        ],
    )


async def run_worker(settings: TemporalSettings | None = None) -> None:
    selected = settings or temporal_settings_from_environment()
    temporal_client = await TemporalCaseClient.connect(selected)
    worker = create_worker(temporal_client.client, selected)
    await worker.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ProxyLoop Case Workflow")
    parser.add_argument("--address", dest="address", default=None)
    parser.add_argument("--namespace", dest="namespace", default=None)
    parser.add_argument("--task-queue", dest="task_queue", default=None)
    args = parser.parse_args()
    if args.address is None and args.namespace is None and args.task_queue is None:
        asyncio.run(run_worker())
        return

    values = dict(os.environ)
    if args.address is not None:
        values["PROXYLOOP_TEMPORAL_ADDRESS"] = args.address
    if args.namespace is not None:
        values["PROXYLOOP_TEMPORAL_NAMESPACE"] = args.namespace
    if args.task_queue is not None:
        values["PROXYLOOP_TEMPORAL_TASK_QUEUE"] = args.task_queue
    settings = temporal_settings_from_environment(values)
    asyncio.run(run_worker(settings))


if __name__ == "__main__":
    main()


__all__ = ["create_worker", "main", "run_worker"]
