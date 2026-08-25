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
from .offer_policy import (
    OfferComplianceContext,
    OfferComplianceTerms,
    offer_compliance_violations,
)

__all__ = [
    "AppliedOfferConfirmation",
    "ApprovalBindingError",
    "ApprovalExpiredError",
    "ApprovalUseError",
    "CompletionVerification",
    "ConfirmationAuthority",
    "OfferComplianceContext",
    "OfferComplianceTerms",
    "confirmation_hash",
    "material_terms_hash",
    "offer_compliance_violations",
    "offer_material_terms",
    "validate_approval_use",
    "verify_completion",
]
