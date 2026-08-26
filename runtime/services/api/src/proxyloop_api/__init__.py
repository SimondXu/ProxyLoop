"""FastAPI entry point for ProxyLoop's Phase 04A thin runtime."""

from .app import app, create_app
from .config import runtime_from_environment
from .operations import (
    CORRELATION_ID_HEADER,
    OPERATION_RECORD_FIELDS,
    InMemoryOperationRecorder,
    JsonLoggingOperationRecorder,
    OperationRecord,
    OperationRecorder,
)
from .postgres_repository import PostgresCaseRepository
from .readiness import ReadinessResult, check_readiness
from .repository import (
    CaseConflictError,
    CaseNotFoundError,
    CaseRepository,
    CaseRuntimeState,
    InMemoryCaseRepository,
    StorageUnavailableError,
)
from .runtime import (
    AdapterMode,
    ModelRuntimeError,
    RuntimeProfile,
    RuntimeResult,
    StorageMode,
    ThinAgentRuntime,
)

__all__ = [
    "CORRELATION_ID_HEADER",
    "OPERATION_RECORD_FIELDS",
    "AdapterMode",
    "CaseConflictError",
    "CaseNotFoundError",
    "CaseRepository",
    "CaseRuntimeState",
    "InMemoryCaseRepository",
    "InMemoryOperationRecorder",
    "JsonLoggingOperationRecorder",
    "ModelRuntimeError",
    "OperationRecord",
    "OperationRecorder",
    "PostgresCaseRepository",
    "ReadinessResult",
    "RuntimeProfile",
    "RuntimeResult",
    "StorageMode",
    "StorageUnavailableError",
    "ThinAgentRuntime",
    "app",
    "check_readiness",
    "create_app",
    "runtime_from_environment",
]
