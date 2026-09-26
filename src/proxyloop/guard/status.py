"""The status machine (ARCHITECTURE §9.5): ``status.changed`` is emitted only
for a legal transition. Only verifier outcomes (``completion_ok``,
``no_deal_verified``) reach a ``VERIFIED_*`` status."""

from __future__ import annotations

from proxyloop.contract.state import Blackboard, CaseStatus

# from | trigger | to
_TABLE = """
INTAKE             mandate_granted     MANDATED
INTAKE             call_opened         IN_CALL
MANDATED           call_opened         IN_CALL
IN_CALL            approval_requested  AWAITING_APPROVAL
AWAITING_APPROVAL  approval_decided    IN_CALL
IN_CALL            accept_authorized   COMMIT_AUTHORIZED
COMMIT_AUTHORIZED  accept_heard        COMMITTED
COMMIT_AUTHORIZED  accept_revoked      NEEDS_REPLAN
COMMIT_AUTHORIZED  accept_truncated    NEEDS_REPLAN
COMMITTED          evidence_recorded   EVIDENCE_PENDING
EVIDENCE_PENDING   completion_ok       VERIFIED_COMPLETE
EVIDENCE_PENDING   completion_fail     NEEDS_REPLAN
NEEDS_REPLAN       replan              IN_CALL
NEEDS_REPLAN       escalate            ESCALATED
IN_CALL            no_deal_verified    VERIFIED_NO_DEAL
IN_CALL            info_only           CLOSED_NO_ACTION
"""
TRANSITIONS: dict[tuple[CaseStatus, str], CaseStatus] = {
    (CaseStatus(a), t): CaseStatus(b)
    for a, t, b in (row.split() for row in _TABLE.strip().splitlines())
}
S = CaseStatus
TERMINAL = frozenset(
    {
        S.VERIFIED_COMPLETE,
        S.VERIFIED_NO_DEAL,
        S.ESCALATED,
        S.ABANDONED,
        S.CLOSED_NO_ACTION,
    }
)


def next_status(status: CaseStatus, trigger: str) -> CaseStatus | None:
    """The status after ``trigger``, or ``None`` if it is not a transition.
    ``hang_up`` (strikes >= 3) abandons any case that is not closed."""
    if trigger == "hang_up":
        return None if status in TERMINAL else S.ABANDONED
    return TRANSITIONS.get((status, trigger))


def status_change(bb: Blackboard, trigger: str) -> dict[str, object] | None:
    """The ``status.changed`` payload for ``trigger``, if it moves the case."""
    previous = bb.public.status
    status = next_status(previous, trigger)
    return (
        None if status is None else {"previous": previous.value, "status": status.value}
    )
