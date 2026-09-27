# ADR-0007: Contract: a decided approval keeps its card's expiry

- **Status:** accepted (root decision under §0.5a, 2026-09-26)
- **Date:** 2026-09-26
- **Task:** S1-CON-01

## Context
ARCHITECTURE §9.3 lets `accept_offer` rest on `approval.decided{granted}` only with an equal `terms_hash`, the same `authority_epoch` and **an unexpired card**. The card (`ApprovalCard`, with `expires_ms`) lives in `PrivateState.pending_approval` only until it is decided. The fold then replaces it with an `Approval` record (`approval_id, decision, by, terms_hash, authority_epoch`) and clears the pending card, so the expiry is lost. Guard (S1-SYS-01, PR #126) mints a capability at `accept_offer` with `expires_ms = min(offer expiry, now + CAP_TTL_MS, mandate expiry when the mandate is the grant)`. When the grant is an approval, it has no expiry to add, and nothing stops a stale approval from minting a capability. The options were:
- copy the card's expiry into the `Approval` record at decide time (chosen);
- keep decided cards in private state beside the approvals (rejected: two records of one decision, and Guard would have to join them);
- put the expiry in the `approval.decided` payload (rejected: the fold already holds the card, and a payload value would be a second source that could disagree with it).

## Decision
- `contract.state.Approval` gains `expires_ms: int | None = None`, in ms on the session clock like `ApprovalCard.expires_ms`.
- **Source.** The fold's `approval.decided` handler (`core/fold.py`, SYS) sets `Approval.expires_ms = card.expires_ms` from the pending card it is already checking. That card is Guard-written with `expires_ms = min(offer expiry, now + CARD_TTL_MS)`. No producer takes it from a model or a UI post (I6).
- **No new event key.** The `approval.decided` payload stays `approval_id, decision, by` (`tests/contract/snapshots/event_registry.json` is unchanged). The value is derived in the fold from `approval.requested`, which already carries `expires_ms`, so replay reproduces it (I2).
- **Private.** `Approval` lives only in `PrivateState.approvals` and `SlowView.approvals`. It is in no `FastView` (the user lane shows the pending card, not decided approvals) and in no Fast render. `view_cp` does not read private state at all (I4). `tests/contract/test_validators.py::test_approval_expiry_is_optional_private_and_absent_from_fast_views` checks that `FastView` names no `Approval`, and the counterfactual strategy in `tests/contract/test_views.py` now varies `expires_ms`.
- **Semantics of `None`.** `None` means "no expiry recorded". Only a record folded before this field existed can have it; S0 wrote none (no `approval.decided` exists in `evidence/s0`). Guard treats `None` as **expired**: an approval without a recorded expiry mints no capability. It is never read as unbounded (fail closed, I6).
- **Use.** When the grant is an approval, Guard (S1-SYS-01) requires `approval.expires_ms > t_now`, and adds it to the capability's `min(...)`. Revalidation at release then enforces the capability's expiry as today (ARCHITECTURE §9.4).

## Evidence
- The fingerprints computed on the branch with `proxyloop.contract.protocol.fingerprint` are unchanged: `pl_user_v1` = `796d2843…9cfb`, `pl_cp_v1` = `76a01858…b490` (PLAN header). The fingerprint hashes only the profile text and the P2 golden ids, and no Fast view gains a field.
- `uv run pytest tests/contract tests/golden -q` passes with the goldens untouched. The four `evidence/s0` bundles still pass `check_path(…, "offline")`.

## Consequences
- **Contract / fingerprint impact:** none. It is an additive private field with a default. `make pull-through MODE=verify` runs when #125 provides it.
- **Data invalidated:** none.
- **Migration:** S1-SYS-01 (#126) sets the field in `_approval_decided` and uses it in `accept_offer`'s grant check and capability expiry. Existing bundles fold unchanged. Other worktrees need no action beyond the usual merge of `main`.
- **Risks and what would make us revisit this.** If a later producer builds an `Approval` without a card (e.g. S4 `submit_transaction` over `action_hash`), it must supply its own expiry, or its approvals mint nothing under the `None` rule. Revisit the default then, and make the field required once no pre-field records need to fold.
