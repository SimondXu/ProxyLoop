# Runtime-backed UI state matrix

| State | Conversation presentation | Allowed user action | Truthfulness boundary |
|---|---|---|---|
| Runtime connecting | Draft Task Brief remains visible while the explicit create request is in flight | Wait | No Case facts or success state are shown before `POST /cases` returns |
| Restoring Case | Saved locator checks readiness, then reads the authoritative Case | Wait or reconnect | Only explicit Temporal/PostgreSQL/scripted readiness enables a durable-recovery claim; `orchestration_mode: direct` with memory storage shows the one-Case-per-process limit and asks for a Runtime process restart instead; any other non-durable profile shows the generic durable-profile notice |
| Blank conversation ready | Welcome and composer | Describe lowering the bill | The first message remains conversation-local; it is not silently sent as a Runtime event |
| Unsupported initial intent | User message plus local scope explanation | Rephrase with a clear mobile-bill outcome | No Runtime Case is created; the lexical gate does not claim general language understanding |
| Local intake draft | Draft Task Brief with four missing/confirmed rows and Edit actions | Supply or edit one fact; create only when all are valid | Strict USD parsing (exactly one `$` or `USD` amount candidate, validated as comma-grouped or plain digits with at most two decimals; one trailing sentence period or a trailing comma before whitespace is allowed; a decimal comma, third decimal, second amount, letter-prefixed `$` such as `A$`/`US$`, following non-USD ISO code such as `AUD`, or range dash is rejected) and fixed constraints stay local; no Runtime call occurs before explicit create |
| Constraint confirmation | Runtime-derived Task Brief and proactive question | Confirm hotspot and device financing stay unchanged | Root Case and `snapshot.case` must match the confirmed draft; missing or mismatched facts block the journey |
| Malformed Task Brief | Blocked Runtime error in the conversation | Restart | Missing Case facts, nonempty string constraints, or valid nonnegative Money prevent confirmation and event submission |
| Runtime working | Confirmed message plus Progress artifact | Wait | Progress shows only steps the accepted payload backs (the Case revision read and validated against the confirmed facts) plus the awaited Runtime decision; no hard-coded completed steps. A poll during the in-flight event POST may advance or block the Case but never steps back to the confirm state |
| Finalizing / pending execution | Approved terms remain visible with a Finalizing Progress artifact; after 5 authoritative reads still show `pending_execution`, an explicit "still waiting" error with `Reconnect and read Case` appears alongside it | Wait, or reconnect after the bounded polling reports it is still waiting | `pending_execution` is recoverable; polling never stops silently; no receipt is shown until a final GET verifies completion |
| Approval pending | Runtime-derived Offer and exact Approval artifact | Approve exact terms or add a local note | Approval uses returned `revision`, `approval.case_revision`, `approval.action_intent_revision`, and `approval_id` |
| Incomplete pending offer/approval | Blocked Runtime error; no approval button | Restart | Pending approval, exact pins, material hash/expiry, offer Money, provider, term, and feature facts must all validate |
| Completion verified | Evidence receipt inline in the conversation | Inspect or start a new local demo | Verified requires `complete`, execution count `1`, non-empty Evidence IDs, and matching Evidence items |
| Authoritative approval expired | Expired state with approval action removed | Start a new local demo | Browser time may disable approval and trigger a read, but only the Runtime labels `Expired` (a Temporal timer in the durable profile, an in-process timer in direct mode that a process restart loses) |
| HTTP/network/malformed failure | Red error state inside the conversation; a 409 after the event or approval request first reads the Case, and if that read did not advance the revision the error shows the Runtime category message, the stale retry is dropped, and the primary action reads `Reconnect to continue` until a fresh read; a 409 on create performs no read and its message promises none (retry only if still offered, or restart the Runtime process to start over) | Reconnect and read Case, refresh the page, or restart the local demo | The UI never displays success or continues silently; a 409 that reconciles to a newer revision adopts that state, one that does not is surfaced |
| Unsupported correction after Case creation | Local note plus Runtime-restart/New-task explanation | Restart local Runtime, then choose New task | The UI does not pretend a chat note mutated the Case; no PATCH or second Case is sent |
| Explicit `New task` during a Runtime request | Fresh blank conversation | Start a new supported request | A monotonic session id makes late create/event/approval responses unable to restore stale UI; page refresh instead preserves an exact uncertain retry |
| Terminal but unverified | Blocked state | Restart or refresh | A terminal route alone is insufficient for a receipt |

Projection note: when the Runtime has no `CompletionDecision` yet, the browser
projection's `completion` (top level and `snapshot.completion`, built by
`_browser_completion` in `proxyloop_api/app.py`) is a synthetic placeholder
`{decision: "not_done", evidence_ids: [], missing_evidence:
["verified_provider_confirmation"], reason_codes: [...]}`, not a canonical
`CompletionDecision`. The Web treats only `decision: "complete"` with matching
Evidence as completion, so the placeholder never renders a receipt.
