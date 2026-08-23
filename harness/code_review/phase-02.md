# Phase 02 Independent Review

Date: 2026-08-23

Reviewer role: independent, read-only reviewer. Sol retains the final integration and merge decision.

## Initial Decision

Request Changes.

### P1 — Cross-split fingerprint was not a frozen lexical check

The initial fingerprint removed selected identifiers but did not normalize case, whitespace, or punctuation, and it omitted assistant response text. The cross-split probe therefore did not prove a lexical collision detector.

Resolution: the fingerprint now normalizes relevant public content with Unicode normalization, case-folding, whitespace collapse, and punctuation normalization after opaque case, offer, and timestamp identifiers are removed. It includes assistant response text consistently. A non-byte-identical cross-split probe differs only in case, whitespace, and punctuation, normalizes to an existing train fingerprint, and is quarantined. Documentation calls this a lexical heuristic, not embedding or semantic equivalence.

### P2 — Audit report values were hard-coded

The initial report declared provenance completeness, accepted-safety counts, external usage, and passed status with literals, so it could not expose corrupted accepted evidence or non-zero external usage.

Resolution: report accounting now derives provenance, accepted PII/forbidden/dedup/leakage counts, quarantine reason counts, external calls/tokens/cost, and audit status from accepted and quarantined records plus generator snapshots. A regression mutates source and external-usage evidence and proves the report becomes incomplete and `failed` with non-zero usage.

### P2 — Scratch planning files

The run-created `findings.md`, `task_plan.md`, and `progress.md` were outside Phase 02 deliverables.

Resolution: those three root scratch files were deleted. No product or phase evidence was removed.

## Second Rereview Decision

Request Changes.

### P1 — Invalid provenance discarded quarantined external-usage evidence

Quarantine usage accounting initially parsed the complete normalized trajectory. A candidate with missing `source` therefore failed full validation before its valid raw `generation.snapshots` could contribute external calls, tokens, or cost to the report.

Resolution: raw usage accounting now defensively parses only `generation.snapshots`, retaining correctly typed non-negative usage even when the rest of the candidate is invalid. Malformed generation or snapshot values remain zero and are not trusted. A regression deletes source provenance while setting one snapshot to an external call, nine input tokens, and non-zero cost; the candidate remains `missing_provenance`, but quarantine audit and aggregate report retain the usage and set `automated_audit_status=failed`.

## Final Rereview Decision

Approve. No unresolved blocking findings remain in the local Phase 02 implementation.

The final rereview confirmed that:

- the lexical cross-split check is frozen, includes response text, and is described honestly as a lexical heuristic;
- report accounting derives safety, provenance, quarantine, and external-usage evidence rather than declaring it;
- malformed surrounding provenance cannot erase valid, typed raw snapshot usage from quarantine accounting;
- the pilot remains `pending_human` and `training_ready=false`.

## Remaining Integration Gate

This approval covers the local implementation and review only. Pull-request publication, CI, GitGuardian, Sol integration review, and squash merge have not run. Phase 03 remains inactive until that integration completes and the user explicitly authorizes a new phase.
