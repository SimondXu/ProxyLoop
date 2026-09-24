# PR-10 preflight: Agent Status Bar (Stage 4)

Bounded change under decisions 16–20 (`harness/context/audit-remediation-decisions.md`),
build plan row PR-10 (`harness/context/build-plan-to-complete.md`). Branch
`feat/pr10-agent-status-bar` from `origin/main` @ `c018390` (#95, PR-8b merged).
Written 2026-09-24. Tags: **[O]** observed in code, **[P]** proposed here.

## Sources

- Build plan PR-10 row: "Stage 4: Agent Status Bar, `render_status_block(snapshot)`;
  it must not become the distilled Fast prompt"; DoD item 2 "… → Status Bar → …".
- `audit-remediation-status.md` §5 item 4: "Agent Status Bar = rendering
  `CaseContextSnapshot` in the Web".
- Target architecture proposal §2 and §7 (a Python `agent_core/status_block.py`
  feeding the Fast and Slow prompts) and §9 (Web renders from the projection only).
- `pr8-fast-dialogue-design.md` I12: "The gate reads contract fields directly and
  imports no status-block renderer (PR-10: the Status Bar must not become the Fast
  prompt)."
- [O] `runtime/services/api/src/proxyloop_api/app.py` `_result_payload`,
  `_browser_snapshot`, `_browser_case`, `_browser_offer`, `_browser_approval`,
  `_browser_completion`; pinned by `tests/integration/test_browser_projection_allowlist.py`.
- [O] `apps/web/lib/runtime-client.ts`, `apps/web/app/components/conversation-workspace.tsx`.

## Decision 1 — where the renderer lives [P]

**A pure TypeScript function in the Web, `renderStatusBlock(payload)` in the new
module `apps/web/lib/status-block.ts`.** It is the TS spelling of the plan's
`render_status_block(snapshot)`; its input is the allow-listed browser projection
(`RuntimePayload`), which is the snapshot as the browser is allowed to see it. It is
the only place the Status Bar's text is built; the component only maps its rows to
markup.

Rejected: a Python renderer in `case_runtime` or `agent_core` whose output the API
exposes. It would (a) add a field to the browser envelope, a projection/security
boundary change the root owns; and (b) put a renderer next to the Fast prompt and
observation builders, which is exactly the coupling I12 forbids. The proposal §7
idea of one renderer shared by the prompts is **not** adopted here: the distilled
03C Fast adapter was trained and measured on its frozen observation prompt
(`qwen_mlx.py` is frozen by r4), so a prompt-side status block for Fast is out of
scope. Whether Slow ever gets a status block is a later, separate decision.

## Decision 2 — no API or projection change [P]

Every value comes from fields already in the allow-list [O]:

| Row | Source (browser projection) |
|---|---|
| Doing now | `snapshot.phase`, `approval.decision`, `snapshot.pending_execution`, `completion` + `evidence` + `execution_count` |
| Phase | `snapshot.phase` (Case phase) |
| Goal | `snapshot.case.goal.target_monthly_total`, `.deadline`; `snapshot.case.bill_snapshot.monthly_total` |
| Constraints | `snapshot.case.goal.required_features`, `.forbidden_changes`, `snapshot.case.constraints[].{classification,statement}` |
| Current offer | `snapshot.offers[0].{provider_id,monthly_price,total_cost,term_months,features,expires_at,revision}` |
| Approval | `approval.{decision,expires_at}` |
| Execution | `snapshot.pending_execution`, `execution_count` |
| Completion | `completion.{decision,reason_codes}`, `completionHasVerifiedEvidence(payload)` |

Interpretations the brief left open, decided here:

- **"Best current offer"** is shown as **"Current offer"**. The Runtime keeps one
  current offer (`runtime.py` builds `offers=(offer,)`) and the other artifacts
  read `offers[0]`; the Web does not rank offers or compute compliance (that is
  `offer_policy`'s authority, and no compliance verdict is projected).
- **"Delivery status"** is rendered as **execution status** (`pending_execution`,
  `execution_count`). Channel delivery status is deliberately not projected
  (`_is_channel_visible_event` filters channel events; the Fast gate verdict lives
  only in the trace log), so the Status Bar does not show it. Showing either would
  be a projection change: not done, recorded as a limit.
- **Receipt** is the existing Web rule: a verified completion is
  `completionHasVerifiedEvidence(payload)`; the canonical `CompletionReceipt` is not
  projected and is not needed.
- **Expiry** is rendered verbatim (the ISO string the Runtime returned), with no
  countdown: the renderer reads no clock, so it is deterministic.
- Excluded on purpose: `fast` (never read), ids other than revisions,
  `material_terms_hash` (the approval card already shows it), evidence ids.

"Doing now" precedence (first match wins; derived from the phase with the approval,
execution and completion overlays, because the Runtime keeps `negotiating` both while
executing and after an expiry [O]):

1. `completion.decision == complete`: verified → "Done: the Runtime verified
   completion against Provider Evidence."; not verified → "Stopped: the completion is
   not backed by matching Evidence."
2. `approval.decision == expired` → "Stopped: the approval expired and nothing was
   accepted."; `rejected` → "Stopped: the approval was rejected and nothing was
   accepted."
3. `pending_execution` → "Executing the approved fictional transition; waiting for a
   verified result."
4. `approval.decision == pending` → "Waiting for your approval of the exact terms."
5. by phase: `initiated`/`strategy` → "Planning from your confirmed goal.";
   `negotiating` → "Negotiating with the fictional Provider.";
   `awaiting_approval` → "Waiting for your approval of the exact terms.";
   `candidate_complete` → "Checking the Provider's confirmation before any receipt.";
   `complete`/`closed` → "The Case is closed."; otherwise → "Waiting for the Runtime
   to report the Case phase."

## Decision 3 — I12 enforcement [P]

1. Python, new `tests/contract/test_status_block_boundary.py`:
   - `agent_core/disclosure_gate.py` imports only the standard library and
     `proxyloop_contracts` (it reads contract fields directly).
   - No Python source in `runtime/packages/agent_core/src`,
     `runtime/packages/openai_adapter/src` (the Fast prompt builder), or `ml/` (the
     03C prompt/observation builders, the data pipeline, and PR-9's `ml/serving`)
     mentions `status_block`, `render_status_block`, `status-block`, or
     `renderStatusBlock`, so none can import or re-create the renderer silently.
2. Web, in `apps/web/lib/status-block.test.ts`:
   - Only `app/components/conversation-workspace.tsx` imports `status-block` among
     the Web's non-test sources.
   - `status-block.ts` source never mentions `fast`; behaviourally, a payload whose
     `fast.response_text` carries a sentinel renders no row containing it.

## Placement [P]

The Status Bar is a new first section, `aria-label="Agent status"`, in the existing
right-hand context rail (`aria-label="Current task context"`), shown once a Case
payload exists. Existing rail sections, the conversation artifacts, and the phase
machine are unchanged. Existing Web style (`context-section`, `context-label`, `dl`);
no new CSS unless the rows need it. No redesign.

## Red tests and acceptance criteria

Red on `origin/main` (module absent), green on the branch:

1. `renderStatusBlock` per phase: `strategy` (no approval) → planning line and
   "No offer yet"; `awaiting_approval` with a pending approval → waiting line and
   "Pending · expires <ISO>"; `negotiating` + `pending_execution` → executing line
   and "In progress"; `complete` with matching Evidence → done line and verified
   completion; `complete` without matching Evidence → stopped line; expired approval
   → stopped line; missing phase → fallback line.
2. Goal and constraints rows render the projected target, bill, required features,
   forbidden changes, and hard constraint statements.
3. Current offer row renders provider, monthly price, total cost, term, features,
   expiry, and offer revision.
4. Determinism: the same payload renders identical rows under two different system
   times.
5. No `fast`: sentinel test above; source test above.
6. Workspace: after Case creation the rail's "Agent status" region shows the rows;
   after approval completes it shows the verified completion; the `fast` sentinel
   never appears.
7. Python boundary test green (it is green on `main` too: it pins today's state).

Checks: `make web-check`, `make preflight`. Browser check against a real Runtime
only after the root grants the DB lane (it uses Compose).

## Docs

`docs/architecture.md` Experience Layer; `audit-remediation-status.md` §0 row and §5
item 4; log `harness/log/feat-pr10-agent-status-bar.md`.

## Limits

- No channel delivery status and no Fast gate verdict in the Status Bar (not projected).
- No compliance verdict for the offer (not projected; the Web does not compute it).
- The Status Bar is a rendering for the person, not a prompt. A prompt-side status
  block (proposal §7) is not built; if one is ever wanted for Slow, it is a separate
  root decision, and I12 keeps it away from Fast.

## Amendment 2026-09-24 — independent review (Request Changes, I-1..I-3)

The root accepted the two interpretations above ("Current offer"; execution status
instead of delivery status) as recorded limits. The review fixes supersede the
"Doing now" precedence in Decision 2:

- **I-1.** The workspace's `phaseForPayload` moved to `runtime-client.ts` as the
  single pure classifier, and both the workspace and `renderStatusBlock` use it.
  `blocked` (either the payload's classification or the workspace's own Blocked
  state, passed as `renderStatusBlock(payload, { blocked })`) renders "Stopped —
  state not verified. Reconnect or restart the local demo." This covers an invalid
  pending approval, an approved or rejected approval that is neither pending
  execution nor complete (including `candidate_complete` after execution), an
  unverified completion, and a stale payload kept after a rejected read. `receipt`,
  `expired`, `finalizing`, and `approval` map to their lines. `confirm` falls back
  to the Case phase: initiated/strategy is planning, negotiating is negotiating,
  a missing phase is "report the Case phase", and any other phase is "Waiting for
  the Runtime." The block also carries "as of Case revision N".
- **I-2.** Finalizing names an approved transition only when
  `approval.decision === "approved"`, the Progress artifact's M-4 condition.
  Otherwise it reads "Finalizing the fictional transition; …".
- **I-3.** The Python tripwire scans every `runtime/*/*/src` and `ml/`, asserts
  each root has sources, and keeps the gate-imports check. I12 is enforced by
  placement; the test is a tripwire.
- Minors: an empty decision renders "Not reported"; an unnamed Provider reads
  "Fictional Provider" (the Offer artifact's wording); money uses the shared
  `apps/web/lib/format.ts`; the Web importer test also catches dynamic `import()`;
  the section uses `aria-labelledby`.
- New limit: the workspace's local deadline timer can disable Approve before the
  Runtime has expired the approval. In that window the bar still shows the Runtime's
  "Pending · expires …" and the approval line until an authoritative read reports
  `expired`.
