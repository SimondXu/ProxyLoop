# Runtime-backed UI state matrix

| State | Conversation presentation | Allowed user action | Truthfulness boundary |
|---|---|---|---|
| Runtime connecting | Draft Task Brief remains visible while the explicit create request is in flight | Wait | No Case facts or success state are shown before `POST /cases` returns |
| Blank conversation ready | Welcome and composer | Describe lowering the bill | The first message remains conversation-local; it is not silently sent as a Runtime event |
| Unsupported initial intent | User message plus local scope explanation | Rephrase with a clear mobile-bill outcome | No Runtime Case is created; the lexical gate does not claim general language understanding |
| Local intake draft | Draft Task Brief with four missing/confirmed rows and Edit actions | Supply or edit one fact; create only when all are valid | Strict USD parsing and fixed constraints stay local; no Runtime call occurs before explicit create |
| Constraint confirmation | Runtime-derived Task Brief and proactive question | Confirm hotspot and device financing stay unchanged | Root Case and `snapshot.case` must match the confirmed draft; missing or mismatched facts block the journey |
| Malformed Task Brief | Blocked Runtime error in the conversation | Restart | Missing Case facts, nonempty string constraints, or valid nonnegative Money prevent confirmation and event submission |
| Runtime working | Confirmed message plus Progress artifact | Wait | Progress describes observable local work, not hidden reasoning |
| Approval pending | Runtime-derived Offer and exact Approval artifact | Approve exact terms or add a local note | Approval uses returned `revision`, `approval.case_revision`, `approval.action_intent_revision`, and `approval_id` |
| Incomplete pending offer/approval | Blocked Runtime error; no approval button | Restart | Pending approval, exact pins, material hash/expiry, offer Money, provider, term, and feature facts must all validate |
| Completion verified | Evidence receipt inline in the conversation | Inspect or start a new local demo | Verified requires `complete`, execution count `1`, non-empty Evidence IDs, and matching Evidence items |
| HTTP/network/malformed failure | Red error state inside the conversation | Refresh the page or restart the local demo | The UI never displays success or continues silently |
| Unsupported correction after Case creation | Local note plus Runtime-restart/New-task explanation | Restart local Runtime, then choose New task | The UI does not pretend a chat note mutated the Case; no PATCH or second Case is sent |
| Restart during a Runtime request | Fresh blank conversation | Start a new supported request | A monotonic session id makes late create/event/approval responses unable to restore stale UI |
| Terminal but unverified | Blocked state | Restart or refresh | A terminal route alone is insufficient for a receipt |
