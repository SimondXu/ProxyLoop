"""Lazy exports for the fictional ProxyLoop Case Workflow adapter.

The package is imported before a Workflow submodule is loaded.  Keep this
module free of Runtime/PostgreSQL imports so Temporal's Workflow sandbox only
loads deterministic command/reference models and Temporal APIs.
"""

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "ACTIVITY_NAME": ".workflow",
    "ACTIVITY_RETRY_POLICY": ".workflow",
    "ACTIVITY_SCHEDULE_TO_CLOSE": ".workflow",
    "ACTIVITY_START_TO_CLOSE": ".workflow",
    "CHANNEL_DELIVERY_ACTIVITY_NAME": ".workflow",
    "UPDATE_NAME": ".workflow",
    "WORKFLOW_SCHEMA_VERSION": ".models",
    "CaseCommandActivityAdapter": ".activities",
    "CaseCommandRequest": ".models",
    "ChannelDeliveryRequest": ".models",
    "CaseWorkflow": ".workflow",
    "CaseWorkflowInput": ".models",
    "TemporalCaseClient": ".client",
    "TemporalDispatchError": ".client",
    "TemporalReadinessResult": ".readiness",
    "TemporalSettings": ".config",
    "activity_for_adapter": ".activities",
    "channel_activity_for_adapter": ".activities",
    "activity_id_for_command": ".workflow",
    "apply_case_command_activity": ".activities",
    "check_readiness": ".readiness",
    "check_temporal_readiness": ".readiness",
    "expiry_command_id": ".workflow",
    "readiness_payload": ".readiness",
    "temporal_settings_from_environment": ".config",
    "update_id_for_command": ".workflow",
    "workflow_id_for_case": ".workflow",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


__all__ = [
    "ACTIVITY_NAME",
    "ACTIVITY_RETRY_POLICY",
    "ACTIVITY_SCHEDULE_TO_CLOSE",
    "ACTIVITY_START_TO_CLOSE",
    "CHANNEL_DELIVERY_ACTIVITY_NAME",
    "UPDATE_NAME",
    "WORKFLOW_SCHEMA_VERSION",
    "CaseCommandActivityAdapter",
    "CaseCommandRequest",
    "CaseWorkflow",
    "CaseWorkflowInput",
    "ChannelDeliveryRequest",
    "TemporalCaseClient",
    "TemporalDispatchError",
    "TemporalReadinessResult",
    "TemporalSettings",
    "activity_for_adapter",
    "activity_id_for_command",
    "apply_case_command_activity",
    "channel_activity_for_adapter",
    "check_readiness",
    "check_temporal_readiness",
    "expiry_command_id",
    "readiness_payload",
    "temporal_settings_from_environment",
    "update_id_for_command",
    "workflow_id_for_case",
]
