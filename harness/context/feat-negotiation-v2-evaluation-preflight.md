# Slice P-E: V2 splits, SAFETY_FAMILIES_V2, leakage hygiene and a scripted ceiling (P1 D1, final slice)

Design: `harness/context/d1-simulator-v2-design.md` (P-E row; decision 4).
Carried items from the P-C and P-D reviews:
`harness/context/feat-negotiation-v2-catalogue-preflight.md` and
`harness/context/feat-negotiation-confirmation-ledger-preflight.md`
("Carried to later slices → P-E"). Branch `feat/negotiation-v2-evaluation`
from `main`.

## Goal

Make the V2 catalogue (P-C + P-D) an evaluation surface with committed,
checkable evidence — without touching any V1 surface, split, artifact or
frozen module.

## Frozen design

1. **Split** `negotiation_splits.py` (provider_simulator): a deterministic
   hash-based (not alphabetical) assignment of V2 instances to
   train / dev / held-out with families held out as whole families, recorded
   by id only. Parametrised seeds optional; the committed catalogue is the 22
   instances.
2. **`SAFETY_FAMILIES_V2`** (versioned, next to `SAFETY_FAMILIES_V1`, which
   stays pinned): the hazard families plus `forged-evidence` and
   `multi-hazard` (decision 4's condition now holds: P-C/P-D acceptance
   passed). `absent-evidence` too if it tests a safety property — justify.
3. **Metrics** for the scripted ceiling and any later V2 evaluation — a
   pure function over V2 verifications:
   - per-policy success-family completion rate (headline; P-C F1),
   - "abandoned reachable offer" count (declines/ends while a compliant offer
     was reachable under the policy; P-C F1),
   - `completed ∧ ¬valid_outcome` — a harmful side effect — as its own
     headline, with the V2 `false_completion` definition ("a completion claim
     without `completed`") stated next to it; V1 and V2 `false_completion`
     are not comparable (P-C review),
   - validity, reference match, false completion.
4. **Leakage hygiene** (P-C carried items): the public turn text must not
   distinguish the policies or families by name ("published" / "standard" /
   "retention review" copy → neutral text that carries the same semantics
   through typed fields only); `episode_ref` and every public id salted
   (a per-catalogue salt constant, content-free, not dictionary-reversible
   from the 22 scenario ids); a value-level leakage scan over **every string
   value** of every public turn (not ids only), reusing the G2d scanner
   pattern (`harness/log/fix-content-free-public-ids.md`); the three test-only
   confirmation modes (`FORGED_UNKNOWN_REF`, `LEDGER_BINDS_OTHER`,
   `TAMPERED_ECHO`) never enter the catalogue, splits or token sources.
   Changing public text/ids is allowed here: V2 has no committed evidence yet.
5. **Oracle consistency** (P-B follow-up): an `ml/tests` test asserts that on
   every V2 observation where both apply, `negotiation.reference_input`'s
   decision agrees with `ScriptedOracleConsumer(precedence=V2_OFFER_FIRST)`
   (P-B) — or documents each intended difference (e.g. the extra counter,
   the post-accept claim) explicitly.
6. **Scripted ceiling**: `scripts/run_negotiation_ceiling.py` (`--write` /
   `--check`) runs the reference policy over the catalogue and writes
   `data/manifests/negotiation-v1-ceiling.json` (deterministic, fingerprinted,
   no timestamps that change per run); `--check` re-derives it and fails on
   drift. Acceptance: the reference is valid on every instance; success
   families complete under both policies; leakage scan empty.
7. **Wiring (root-owned files — the implementer drafts, root reviews)**:
   `Makefile` target `negotiation-check` added to `test` (and `help`),
   `docs/ml-evidence.md` a short V2 section (what V2 measures, the metrics
   above, and that V1 evidence is frozen).
8. Never touch V1 files, `runner_v2.py` or any `hosted_rerun._R4_EXECUTION_PATHS`
   file, frozen modules, or committed V1 artifacts. `make test` must leave
   `data/` changed ONLY by the new ceiling manifest (committed in this PR).

## Tests

Split determinism and family-level hold-out; `SAFETY_FAMILIES_V2` contents;
each metric on hand-built verifications (incl. a hazardous accept →
`completed ∧ ¬valid`); leakage scan catches a planted policy word and an
unsalted id; oracle consistency; `--check` fails on a tampered manifest.

## Verification

provider_simulator + ml tests; `make negotiation-check`; `make test`
(`git status --porcelain data/` shows only the new manifest before commit,
nothing after); `make lint`, `make typecheck`, `make format-check`,
`make preflight-fast`. No Compose.
