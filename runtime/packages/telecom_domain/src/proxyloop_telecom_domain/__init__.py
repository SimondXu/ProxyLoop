"""Pure deterministic telecom authorization and completion interface."""

from .domain import (
    AppliedOfferConfirmation,
    ApprovalBindingError,
    ApprovalExpiredError,
    ApprovalUseError,
    CompletionVerification,
    ConfirmationAuthority,
    case_offer_violations,
    confirmation_hash,
    material_terms_hash,
    offer_material_terms,
    validate_approval_use,
    verify_completion,
)
from .offer_policy import (
    REMOVE_ADD_ON_PREFIX,
    SUPPORTED_APPLIED_CHANGES,
    OfferComplianceContext,
    OfferComplianceTerms,
    is_supported_applied_change,
    offer_compliance_violations,
    unsupported_applied_changes,
)

__all__ = [
    "REMOVE_ADD_ON_PREFIX",
    "SUPPORTED_APPLIED_CHANGES",
    "AppliedOfferConfirmation",
    "ApprovalBindingError",
    "ApprovalExpiredError",
    "ApprovalUseError",
    "CompletionVerification",
    "ConfirmationAuthority",
    "OfferComplianceContext",
    "OfferComplianceTerms",
    "case_offer_violations",
    "confirmation_hash",
    "is_supported_applied_change",
    "material_terms_hash",
    "offer_compliance_violations",
    "offer_material_terms",
    "unsupported_applied_changes",
    "validate_approval_use",
    "verify_completion",
]
