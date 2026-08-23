"""Pure deterministic telecom authorization and completion interface."""

from .domain import (
    AppliedOfferConfirmation,
    ApprovalBindingError,
    ApprovalExpiredError,
    ApprovalUseError,
    CompletionVerification,
    ConfirmationAuthority,
    confirmation_hash,
    material_terms_hash,
    offer_material_terms,
    validate_approval_use,
    verify_completion,
)

__all__ = [
    "AppliedOfferConfirmation",
    "ApprovalBindingError",
    "ApprovalExpiredError",
    "ApprovalUseError",
    "CompletionVerification",
    "ConfirmationAuthority",
    "confirmation_hash",
    "material_terms_hash",
    "offer_material_terms",
    "validate_approval_use",
    "verify_completion",
]
