"""Temporal activity adapter around the shared scripted Case Runtime."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import Any

from proxyloop_case_runtime import (
    CaseCommand,
    CaseConflictError,
    CaseNotFoundError,
    ModelRuntimeError,
    PostgresCaseRepository,
    StorageUnavailableError,
    ThinAgentRuntime,
)
from pydantic import ValidationError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from .workflow import ACTIVITY_NAME


class CaseCommandActivityAdapter:
    """Adapt one Runtime instance to the Temporal activity contract."""

    def __init__(self, runtime: ThinAgentRuntime) -> None:
        self.runtime = runtime

    def apply_command(self, command: CaseCommand) -> Any:
        """Apply a command while converting failures to redacted categories."""

        try:
            parsed = _coerce_command(command)
            return self.runtime.apply_command(parsed)
        except ApplicationError:
            raise
        except StorageUnavailableError as exc:
            raise ApplicationError(
                "storage dependency unavailable",
                type="storage_unavailable",
            ) from exc
        except CaseNotFoundError as exc:
            raise ApplicationError(
                "Case or approval not found",
                type="case_not_found",
                non_retryable=True,
            ) from exc
        except CaseConflictError as exc:
            category = (
                "approval_expired"
                if "approval expired" in str(exc).lower()
                else "case_conflict"
            )
            raise ApplicationError(
                (
                    "approval expired"
                    if category == "approval_expired"
                    else "Case conflict"
                ),
                type=category,
                non_retryable=True,
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise ApplicationError(
                "invalid command",
                type="invalid_command",
                non_retryable=True,
            ) from exc
        except ModelRuntimeError as exc:
            raise ApplicationError(
                "model execution is not available in Temporal mode",
                type="model_path",
                non_retryable=True,
            ) from exc
        except RuntimeError as exc:
            raise ApplicationError(
                "stored Case state is invalid",
                type="state_invalid",
                non_retryable=True,
            ) from exc
        except Exception as exc:
            # The retry policy bounds unexpected defects without exposing the
            # driver, stack, or arbitrary exception body to callers.
            raise ApplicationError("activity failed", type="activity_failed") from exc


def _coerce_command(value: object) -> CaseCommand:
    if isinstance(value, CaseCommand):
        return value
    try:
        return CaseCommand.model_validate(value)
    except Exception as exc:
        raise ApplicationError(
            "invalid command",
            type="invalid_command",
            non_retryable=True,
        ) from exc


def runtime_from_environment(
    environ: Mapping[str, str] | None = None,
) -> ThinAgentRuntime:
    """Build the explicit scripted/PostgreSQL Runtime used by the worker."""

    values = os.environ if environ is None else environ
    if values.get("PROXYLOOP_RUNTIME_MODE", "scripted") != "scripted":
        raise ValueError("Temporal worker requires scripted Runtime mode")
    if values.get("PROXYLOOP_STORAGE_MODE", "postgres") != "postgres":
        raise ValueError("Temporal worker requires PostgreSQL storage")
    database_url = values.get("PROXYLOOP_DATABASE_URL")
    if not database_url or not database_url.strip():
        raise ValueError("Temporal worker requires PROXYLOOP_DATABASE_URL")
    return ThinAgentRuntime(PostgresCaseRepository(database_url))


def activity_for_adapter(adapter: CaseCommandActivityAdapter) -> Any:
    """Return a Worker-registration function bound to an adapter instance."""

    @activity.defn(name=ACTIVITY_NAME)
    async def apply_case_command_activity(command: CaseCommand) -> Any:
        return await asyncio.to_thread(adapter.apply_command, command)

    return apply_case_command_activity


_default_adapter: CaseCommandActivityAdapter | None = None


def _get_default_adapter() -> CaseCommandActivityAdapter:
    global _default_adapter
    if _default_adapter is None:
        _default_adapter = CaseCommandActivityAdapter(runtime_from_environment())
    return _default_adapter


@activity.defn(name=ACTIVITY_NAME)
async def apply_case_command_activity(command: CaseCommand) -> Any:
    """Apply one command using the lazily initialized process Runtime."""

    return await asyncio.to_thread(_get_default_adapter().apply_command, command)


__all__ = [
    "CaseCommandActivityAdapter",
    "activity_for_adapter",
    "apply_case_command_activity",
    "runtime_from_environment",
]
