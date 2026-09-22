# Repo audit — Lane E: Web and projection boundary

Reviewer: `reviewer` (Opus, high), read-only; 77 tool uses, ~230K tokens.
Recorded by the root orchestrator from the lane's report; root verification
at the end. Reproductions under the session scratchpad `laneE/`
(`laneE.repro.tsx` R1–R6, `drive.py`, `parse.mjs`).

Scope: `apps/web/**` on `main` @ `aaae134`, `docs/ui/*.md`,
`api/app.py:770-856`, the three Web phase contracts and their log/review
records.

## 1. Module verdicts

| Module | Verdict | Why |
|---|---|---|
| `apps/web/lib/runtime-client.ts` | keep | Narrow, strictly validated envelope; defects are copy and untested error branches. |
| `apps/web/app/components/conversation-workspace.tsx` | **refactor** | 1287-line component; 409 on event/approval swallowed with no message (E-1); Finalizing polling goes silent after 5 reads (E-2); pending-approval retry discarded exactly when needed (E-3); a "blocked" response re-offers the mutating confirm action (E-5). |
| `layout.tsx`, `page.tsx`, `app-shell.tsx`, `status-badge.tsx`, `next.config.ts` | keep | Trivial. |
| `docs/ui/*.md` | **refactor** | `state-matrix.md` rows 13, 15, 18 do not describe the implementation; `research.md` audits a commit that exists only on a local, unpushed branch. |
| `app.py:770-856` browser projection | refactor (policy) | Ships the full `CaseContextSnapshot` (~300 leaf keys); the Web reads ~25 and renders ~16. Confirms B2-N1. |
| Web tests (47) | keep, extend | Load-bearing on happy/fail-closed paths; zero coverage of 409-after-POST, poll exhaustion, direct-mode gate, 404/422, readiness-not-ready, Temporal copy, rejected USD inputs. |

## 2. Findings

### E-1 — Important — 409 on the event or approval POST is swallowed: no message, action re-enabled, stale pending command kept
- `conversation-workspace.tsx:1046-1053` and `:1107-1114`: on `status === 409` the code calls `readAuthoritativeCase` and returns without `setError`; an unchanged GET puts the UI back in `confirm`/`approval`, `busy` clears, the button re-enables; `pendingResolved` (`:663`) keeps the stale `append_event` command.
- Claims: `docs/ui/state-matrix.md:18` ("never … continues silently"); `phase-06a:87-89`; `docs/ui/user-flows.md:50-51`.
- This is the user-visible face of B2-3: 31 minutes after creation every click gets 409 `model_result_rejected`, adds a user bubble, and silently re-enables the button — forever.
- Repro: R1 (no `role="alert"`, confirm button enabled, pending command retained); live `POST /events` with stale `expected_revision` → 409 (`drive.py`).
- Direction: after a 409 reconcile that did not advance the revision, show the stable category and clear/mark the stale command.

### E-2 — Important — Finalizing polling stops after 5 reads (7.5 s) and goes silent: no error, no reconnect control
- `:938-950` `if (pollCount.current >= 5) return;` with no state change; the reconnect button renders only when `error !== null` (`:1247`); the Progress artifact keeps "Waiting for the authoritative response."
- Claims: `docs/ui/state-matrix.md:13`; 06A `:102-103`, AC 11/12.
- With B2-1 this is the permanent screen: reload → restore → `pending_execution=true` → 5 polls → silence. The user is never told the Provider side effect already happened.
- Repro: R2 (exactly 5 GETs, heading still "Finalizing…", no reconnect, no error).

### E-3 — Important — the exact pending-approval retry is discarded when the approval is `approved` but execution is still pending
- `:660-666` `pendingResolved`: the `append_event` branch checks `pending_execution`; the `decide_approval` branch returns true as soon as `approval.decision !== "pending"`. The runtime writes exactly `approved + pending_execution=true` at `runtime.py:1086-1119` before executing, so the stored command is cleared and the documented exact retry is never sent.
- Claims: 06A `:85-86`, AC 6; `docs/ui/user-flows.md:20-22`.
- Fixing B2-1 alone does not restore the recovery path; the Web must also change.
- Repro: R3.

### E-4 — Important — direct mode (the documented iterative setup) dead-ends after any reload, network blip, or second run, with false copy
- `runtime-client.ts:570-572` `statusMessage("case_conflict")` says "I will read its current authoritative state before continuing"; `conversation-workspace.tsx:854-857` performs no read. `restorePersisted` (`:710-721`) refuses any non-Temporal/Postgres profile; direct-mode readiness emits no `orchestration_mode`, so every reload lands on "Recovery requires the durable … profile". One Case per process (B2-N6) → every later `POST /cases` is 409.
- Observed live: direct Runtime on :8000 + `next dev` on :3000 → `POST /api/runtime/cases` → 409 `case already exists`; UI shows the false copy; "Reconnect" → profile block; "Restart local demo" → 409 again. Nothing says "restart the Runtime process".
- Claims: `docs/ui/user-flows.md:50-51`, `state-matrix.md:18`, `apps/README.md:12-16`.
- Repro: R4 + live curl.

### E-5 — Important — a "blocked" event response re-offers the confirm action and allows a second consumer event
- `readAuthoritativeCase` (`:675-687`) accepts the payload before the `blocked` check and throws; `confirmConstraint`'s catch (`:1054`) sets `phase = "confirm"`, so `TaskBriefArtifact` renders with `onConfirm` enabled and "Needs input". Clicking sends another `POST /events`.
- Claims: `phase-minimal-local-web-demo.md:38-39` ("never expose a confirm or approval action"); `state-matrix.md:15`.
- Reachability: needs a projection the Web predicates reject; the scripted runtime never produces one today. Still the fail-closed guarantee the docs sell.
- Repro: R6; the existing test at `conversation-workspace.test.tsx:343` asserts only that the approval button is absent.

### E-6 — Important — required tests recorded as present do not exist
- `phase-local-conversation-intake-ux.md:122-123` requires "strict USD parsing" tests; `harness/code_review/phase-06a-durable-web-resume.md:36-39` states the Temporal-unavailable copy, deadline backoff, and polling budget "each … has focused coverage"; 06A AC 5/14 require direct-mode and 404/422 coverage.
- Grep of both test files: no rejected USD input, no `temporal_unavailable` string, no `ready:false`, no non-Temporal readiness profile, no 404/422, no restore-409 message, no double-click suppression, no "Blocked"/"Connecting"/"Working" label. `runtime-client.test.ts:73-80` checks 409/503 by `kind`/`status` only.

### E-7 — Minor — a poll during the in-flight event POST regresses the display (`:938-950` polls in `working`; an unchanged GET flips to `confirm` mid-request). Repro R5.
### E-8 — Minor — the Progress artifact renders hardcoded "done" steps (`:396-413`) before any response; `state-matrix.md:12` claims "observable local work".
### E-9 — Minor — the context rail "Usage" row reads `bill_snapshot.usage.data_gb` (`:1275`); the projection emits `data_megabytes`; the row always shows the literal "Runtime fact".
### E-10 — Minor — USD parser edge cases contradict its own prompt (`:96-110`): `"$92.00."` and `"$92."` → null; `"$1,50"` → $1.00; `"$12345"` rejected. Repro `parse.mjs`.
### E-11 — Minor — direct mode never expires an approval (`EXPIRE_APPROVAL` is issued only by the Temporal timer, `workflow.py:290`); the Web parks on "Approval deadline reached" forever; `state-matrix.md:17` promises the Runtime will label it.

### Notes
- N1 (answers B2-N1): the browser receives the whole `StrategyPacket`, `action_intents[].idempotency_key`, `material_terms_hash`, `planning_basis.*_fingerprint`, `pins`, `capability_manifest`, `delegated_authority`, `visible_events`, `fact_ledger`. The Web renders: bill total, target, required/forbidden labels, offer provider/price/term/features, computed savings, approval pins, `material_terms_hash` (inside `<details>`), evidence count, `execution_count`. It never reads `route`, `fast`, `visible_events`, strategy text, or evidence bodies. Nothing the docs say must be excluded is rendered; the exposure is a policy question.
- N2 Monotonic guard is keyed on the fixed `case_id`, so it cannot distinguish a reset Case from a regressed one; after `portfolio-demo-reset` an open tab rejects the new Case as "stale" until reload. B2-7 is invisible because the Web never reads `route`.
- N3 `docs/ui/research.md:11` audits snapshot `b8d7ee5` on `feat/pine-inspired-ui-prototype`; the branch is not on the remote. Nothing from the snapshot is on `main`.
- N4 The real offer has `term_months: 0` (rendered "0 months"); every test fixture uses `1`.
- N5 `ApprovalCommand` accepts `"rejected"` but the Web has no reject control; the only way to decline is inaction.
- N6 The "Verified snapshot" Task Brief omits fixture facts the Case contains (`premium_data` add-on, 420 voice minutes, 24 576 MB, `consumer_id`, strategy). By contract; relevant to §5.
- N7 `next dev` rewrote the tracked `apps/web/next-env.d.ts`; the lane restored it with `git checkout --`.

## 3. Acceptance-criteria table (T test / M manual only / ✗ contradicted or missing)

| Contract / AC | Evidence |
|---|---|
| minimal-web-demo 1, 2, 3 | T (`conversation-workspace.test.tsx:100-116, 224-269`; `runtime-client.test.ts:357`); responsiveness M |
| minimal-web-demo 4 (409/503/network/malformed/stale/evidence) | T for all except **✗ UI-level 409** (E-1, E-5) |
| minimal-web-demo 5 | present; `research.md` unverifiable (N3) |
| intake-ux 1, 2, 3, 7 | T (`:100-171`, `runtime-client.test.ts:91, 304`) |
| intake-ux 4 (422 classes, Web side) | **✗ no rejected-input test** (E-6) |
| intake-ux 6 drift blocks confirm/approval/receipt | T for approval/receipt; **✗ confirm re-exposed** (E-5) |
| intake-ux 8, 9, 11 | code only / M / recorded |
| 06A 1, 2, 9, 13 | T |
| 06A 3, 4 | T mocked / M only |
| 06A 5 durable UX only with Temporal/Postgres | code `:710-721`; **✗ non-durable branch untested** |
| 06A 6 exact retry | T for network loss; **✗ approval retry discarded in pending-execution** (E-3) |
| 06A 7 | Runtime scope (B2-4: false in direct mode) |
| 06A 8 duplicate clicks | `busy` guard; **✗ no test** |
| 06A 10 | T; direct mode never labels expired (E-11) |
| 06A 11 truthful states | **✗** E-1, E-2, E-4; `temporal_unavailable` copy untested |
| 06A 12 bounded polling | T; exhaustion silent (E-2) |
| 06A 14 404/409/422/503/network/malformed | T for 503/network/malformed/storage; **✗ 404, 422, UI-level 409** |
| 06A 15 | T except readiness-not-ready and command mismatch |
| 06A 16, 17, 18 | M / recorded (E-2 is the same class as the "swallowed finalizing poll failure" Terra found; the fix covered the failure branch, not the exhaustion branch) / status |

## 4. Test quality
Load-bearing: intent gate, intake edits, happy path, evidence mismatch, malformed brief, incomplete offer, lost brief, drift, restart races, restore/retry, poll failure/visibility/finalizing/expired/deadline/cursor, envelope validation, readiness, task brief, receipt. Shallow or tautological: `runtime-client.test.ts` 409/503 by kind only; "sends the returned approval pins" and "reads a Case through the narrow GET" assert pass-through of their own inputs. Untested: `errorCategory`, `statusMessage` copy, 404/422, `checkReadiness` rethrow, invalid idempotency key, storage quota swallow, "New task" clearing storage, `working`/`blocked`/`Connecting` labels, double-click, restore-409 discard message, non-durable readiness gate, rejected USD/boolean inputs, R1–R6.

## 5. "Agent or form" — user-action trace (empty page → receipt)
1. Type a sentence matching three regexes (`mobile|cell|phone` + `bill|cost|price|plan|monthly` + `lower|reduce|save|…`); text stays local; the thread title is always "Lower my mobile bill".
2. Type current bill (`$92`; must be > $72).
3. Type target (`$75`; must be in `[$72, current)`).
4. Type `yes` for hotspot (only `yes|true|required|keep it` accepted).
5. Type `yes` for financing (only `yes|true|unchanged|no change(s)|keep (it) unchanged`).
6. Click "Create fictional Case" → `POST /cases` with the four fields.
7. Click "Keep both unchanged and continue" → `POST /events` with the hardcoded `CONFIRMATION_EVENT` string (`:60-61`); the user's words are never sent.
8. Click "Approve exact terms" → `POST /approvals/{id}` with the returned pins (the one consequential decision; no reject control).

Eight actions, two free-value inputs, one real decision. Every assistant bubble is a string literal in the component; no model-generated text is ever displayed — in model mode the Web would look identical because it never reads `fast`, strategy, or `visible_events`. The Provider "dialogue" is one scripted event the Web does not render. A reviewer sees a four-field wizard inside a chat textarea, three confirmation buttons, and three Runtime-derived cards.

## 6. Checks run / not run
Run: `pnpm --filter @proxyloop/web test` → 47 passed; `typecheck` clean; R1–R6 → 6/6 reproduce; direct Runtime :8000 driven by `drive.py` (create 201 → same-key create 409 → event 200 → exact retry 409 stale → approve 200 → retry 409 → new-key create 409 → post-terminal event 409); `next dev` :3000 rewrite → 409 live; `parse.mjs`. Servers stopped; `lsof` clean; worktree restored. Not run: `make web-check` (lint + build; passed in root baseline), Temporal/PostgreSQL profile, model mode, Browser/375px smoke.

## 7. Open questions
1. E-1/E-3: is the intended reaction to a 409 "read and explain" (docs) or "read and silently re-offer" (code)?
2. E-4: is direct mode still a supported demo path? If yes, document one-Case-per-process and no-reload; if no, route `apps/README.md` to `make portfolio-demo` only.
3. N1: is shipping the full `StrategyPacket`, `idempotency_key`, fingerprints, and manifest to the browser acceptable? An allow-list would also shrink the Web's validation surface.
4. N3: keep citing an unpushed branch in `docs/ui/research.md`?
5. §5: whether the "agent demo" framing in `README.md` is acceptable when the browser path shows no agent output is a product decision.

## Root verification (2026-09-21)

Root read `conversation-workspace.tsx:938-950` (silent poll cap),
`:1044-1056` (409 → read → return, no `setError`), `:658-667`
(`decide_approval` branch ignores `pending_execution`), and confirmed the
worktree is clean apart from the audit files.

| Id | Verdict | Root note |
|---|---|---|
| E-1, E-2, E-3 | confirmed, Important | Together with B2-1/B2-3 they define what a user actually experiences when the runtime sticks: silence. |
| E-4 | confirmed, Important | Live 409 reproduced by the lane; direct mode is the setup `apps/README.md` documents. |
| E-5 | confirmed, Important (not reachable with the scripted runtime today) | Fail-closed guarantee the contracts promise. |
| E-6 | confirmed, Important (doc/process) | Recorded review text claims tests that do not exist. |
| E-7 … E-11, N1–N7 | accepted as reported | — |

§5 is the most important non-defect output of this lane for the user's
"runnable Pine-style demo" question: the demo is a four-field wizard with
three confirmation buttons; no model text, no Provider dialogue, and no
negotiation is ever shown.
