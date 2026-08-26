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
    ChannelConflictError,
    ChannelDependencyUnavailableError,
    ModelRuntimeError,
    PostgresCaseRepository,
    StorageUnavailableError,
    ThinAgentRuntime,
)
from proxyloop_connectors import (
    DeliveryAdapter,
    DeliveryAttempt,
    DeliveryObservation,
    LocalMailboxAdapter,
)
from pydantic import ValidationError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from .models import ChannelDeliveryRequest
from .workflow import ACTIVITY_NAME, CHANNEL_DELIVERY_ACTIVITY_NAME


class CaseCommandActivityAdapter:
    """Adapt one Runtime instance to the Temporal activity contract."""

    def __init__(
        self,
        runtime: ThinAgentRuntime,
        local_mailbox: DeliveryAdapter | None = None,
    ) -> None:
        self.runtime = runtime
        self.local_mailbox = local_mailbox or LocalMailboxAdapter()

    def apply_command(self, command: CaseCommand) -> Any:
        """Apply a command while converting failures to redacted categories."""

        parsed: CaseCommand | None = None
        try:
            parsed = _coerce_command(command)
            return self.runtime.apply_command(parsed)
        except ApplicationError:
            raise
        except ChannelDependencyUnavailableError as exc:
            raise ApplicationError(
                "channel dependency unavailable",
                type="channel_dependency_unavailable",
            ) from exc
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
        except ChannelConflictError as exc:
            category = _channel_conflict_category(exc)
            raise ApplicationError(
                "channel conflict",
                type=category,
                non_retryable=True,
            ) from exc
        except CaseConflictError as exc:
            category = (
                "approval_expired"
                if "approval expired" in str(exc).lower()
                else "case_conflict"
            )
            if parsed is not None and _is_channel_command(parsed):
                category = "channel_conflict"
            raise ApplicationError(
                (
                    "channel conflict"
                    if category == "channel_conflict"
                    else "approval expired"
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

    def dispatch_channel_delivery(
        self, request: ChannelDeliveryRequest, *, activity_attempt: int = 1
    ) -> Any:
        """Send one exact persisted Outbox attempt and reconcile lost replies."""

        try:
            parsed = (
                request
                if isinstance(request, ChannelDeliveryRequest)
                else ChannelDeliveryRequest.model_validate(request)
            )
            repository = self.runtime.repository
            get_outbox = getattr(repository, "get_outbox_record", None)
            record_observation = getattr(
                repository, "record_delivery_observation", None
            )
            if not callable(get_outbox) or not callable(record_observation):
                raise ChannelDependencyUnavailableError(
                    "channel persistence is unavailable"
                )
            outbox = get_outbox(parsed.delivery_id)
            if (
                outbox is None
                or outbox.case_id != parsed.case_id
                or outbox.idempotency_key != parsed.idempotency_key
            ):
                raise CaseNotFoundError("outbox delivery not found")
            if outbox.state in {"accepted", "delivered", "bounced"}:
                if outbox.provider_message_id is None:
                    raise ChannelConflictError("delivery provider message is missing")
                return outbox
            if outbox.state == "failed_terminal":
                raise ChannelConflictError("terminal delivery has no accepted truth")
            if outbox.state not in {"pending", "failed_retryable", "unknown"}:
                raise ChannelConflictError("stored delivery state is invalid")
            attempt = DeliveryAttempt(
                delivery_id=outbox.delivery_id,
                idempotency_key=outbox.idempotency_key,
                binding_ref=outbox.binding_ref,
                body=outbox.body,
                body_hash=outbox.body_hash,
            )
            observation: DeliveryObservation | None = None
            if activity_attempt > 1:
                lookup_result = self.local_mailbox.lookup(attempt)
                if isinstance(lookup_result, DeliveryObservation):
                    observation = lookup_result
            if observation is None:
                try:
                    observation = self.local_mailbox.send(attempt)
                except TimeoutError:
                    lookup_result = self.local_mailbox.lookup(attempt)
                    if isinstance(lookup_result, DeliveryObservation):
                        observation = lookup_result
                    else:
                        observation = self.local_mailbox.send(attempt)
            if not isinstance(observation, DeliveryObservation):
                raise RuntimeError("local adapter returned an invalid observation")
            return record_observation(
                parsed.delivery_id,
                idempotency_key=parsed.idempotency_key,
                state=observation.state.value,
                provider_message_id=observation.provider_message_id,
                failure_category=observation.failure_category,
            )
        except ApplicationError:
            raise
        except ChannelDependencyUnavailableError as exc:
            raise ApplicationError(
                "channel dependency unavailable",
                type="channel_dependency_unavailable",
            ) from exc
        except StorageUnavailableError as exc:
            raise ApplicationError(
                "channel storage unavailable", type="storage_unavailable"
            ) from exc
        except CaseNotFoundError as exc:
            raise ApplicationError(
                "outbox delivery not found", type="case_not_found", non_retryable=True
            ) from exc
        except ChannelConflictError as exc:
            raise ApplicationError(
                "channel conflict",
                type=_channel_conflict_category(exc),
                non_retryable=True,
            ) from exc
        except CaseConflictError as exc:
            raise ApplicationError(
                "channel conflict", type="channel_conflict", non_retryable=True
            ) from exc
        except RuntimeError as exc:
            category = str(exc)
            if category != "channel_dependency_unavailable":
                category = "channel_dependency_unavailable"
            raise ApplicationError(
                "channel dependency unavailable", type=category
            ) from exc
        except Exception as exc:
            raise ApplicationError(
                "channel activity failed", type="activity_failed"
            ) from exc


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


def _is_channel_command(command: CaseCommand) -> bool:
    return command.command_type.value in {
        "ingest_channel_event",
        "record_channel_delivery",
    }


def _channel_conflict_category(exc: BaseException) -> str:
    """Convert known channel conflict details to one redacted category."""

    value = str(exc).lower()
    if "channel_replay_mismatch" in value or "replay mismatch" in value:
        return "channel_replay_mismatch"
    if "stale_unknown_event" in value or "stale unknown event" in value:
        return "stale_unknown_event"
    if "unknown_binding" in value or "unknown binding" in value:
        return "unknown_binding"
    return "channel_conflict"


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


def channel_activity_for_adapter(adapter: CaseCommandActivityAdapter) -> Any:
    """Return the separate delivery activity while preserving the old helper."""

    @activity.defn(name=CHANNEL_DELIVERY_ACTIVITY_NAME)
    async def dispatch_channel_delivery_activity(
        request: ChannelDeliveryRequest,
    ) -> Any:
        return await asyncio.to_thread(
            adapter.dispatch_channel_delivery,
            request,
            activity_attempt=activity.info().attempt,
        )

    return dispatch_channel_delivery_activity


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


@activity.defn(name=CHANNEL_DELIVERY_ACTIVITY_NAME)
async def dispatch_channel_delivery_activity(request: ChannelDeliveryRequest) -> Any:
    return await asyncio.to_thread(
        _get_default_adapter().dispatch_channel_delivery,
        request,
        activity_attempt=activity.info().attempt,
    )


__all__ = [
    "CaseCommandActivityAdapter",
    "activity_for_adapter",
    "apply_case_command_activity",
    "channel_activity_for_adapter",
    "dispatch_channel_delivery_activity",
    "runtime_from_environment",
]
