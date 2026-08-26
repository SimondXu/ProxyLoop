"""Small, transport-neutral seam for the synthetic local mailbox.

The package deliberately knows nothing about Cases, persistence, workflows, or
the Web.  Raw request verification and the fake delivery adapter are kept here
so callers cannot accidentally use transport details as business authority.
"""

from .local_mailbox import (
    BINDING_REF,
    CHANNEL_KIND,
    FRESHNESS_WINDOW,
    SCHEMA_VERSION,
    DeliveryAdapter,
    DeliveryAdapterConflict,
    DeliveryAttempt,
    DeliveryObservation,
    DeliveryObservationState,
    FaultInjectingLocalMailboxAdapter,
    LocalMailboxAdapter,
    LocalMailboxEventKind,
    LocalMailboxVerificationError,
    UnknownDelivery,
    VerifiedLocalMailboxEvent,
    build_fixture_headers,
    verify_local_mailbox_event,
)

__all__ = [
    "BINDING_REF",
    "CHANNEL_KIND",
    "FRESHNESS_WINDOW",
    "SCHEMA_VERSION",
    "DeliveryAdapter",
    "DeliveryAdapterConflict",
    "DeliveryAttempt",
    "DeliveryObservation",
    "DeliveryObservationState",
    "FaultInjectingLocalMailboxAdapter",
    "LocalMailboxAdapter",
    "LocalMailboxEventKind",
    "LocalMailboxVerificationError",
    "UnknownDelivery",
    "VerifiedLocalMailboxEvent",
    "build_fixture_headers",
    "verify_local_mailbox_event",
]
