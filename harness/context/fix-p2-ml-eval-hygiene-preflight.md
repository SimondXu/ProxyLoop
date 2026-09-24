# Fix: P2 ML/evaluation hygiene batch (D3-7, D3-9, D2-6, D2-7, D2-8)

Bounded repository change delegated by the root orchestrator on 2026-09-23
under the audit-remediation authorization. Branch `fix/p2-ml-eval-hygiene`
from `origin/main` (`5bedcce`). Findings: `harness/code_review/repo-audit-D3.md`
(D3-7, D3-9) and `harness/code_review/repo-audit-D2.md` (D2-6, D2-7, D2-8).
D2-9 and D3-8 are out of scope.

## Hard constraints

- Frozen, never edited: `qwen_mlx.py`, `fast_output.py`, `fresh_fixtures.py`,
  `phase03b_experiment.py`, `hosted_rerun.py`, `openai_frontier.py`, and every
  path in `hosted_rerun._R4_EXECUTION_PATHS` (this includes `artifacts_v2.py`,
  `replay_v2.py`, `runner_v2.py`, `slow_output.py`, `ml/pyproject.toml`,
  `ml/uv.lock`, `scripts/run_phase_03a1_hosted_rerun.py`).
- No byte under `data/` changes; `git status --porcelain data/` stays empty and
  every `make test` evidence gate stays green.

## Per-item disposition (verified present on `5bedcce`)

| Item | Fix location | Frozen? | Disposition |
|---|---|---|---|
| D3-7 reason codes | `ml/data_pipeline/.../pipeline.py` `_intrinsic_rejection` | no | fix the mislabels (root-decided codes after review round 1) |
| D3-7 `rejection_reasons` | `models.py` field, emitted in `data/schemas/normalized-trajectory-v1.schema.json` | no, but committed schema | accept-gap fixed as `declared_rejection`; deleting the field deferred (committed schema bytes) |
| D3-9 model match / unbounded `str(exc)` | `openai_frontier.py:287-370, 587-590` | yes | known limit |
| D2-6 r2 labels not replayed once r3 exists | `artifacts_v2.check_r2_artifacts` | yes | non-frozen check in `ml/tests` |
| D2-7 `router_outcome_mismatch` on every Slow failure | `runner_v2.py:1142-1147`; label in committed r2-r5 reports | yes | known limit |
| D2-8 constant `policy_violation_count` / `leakage_violation_count` | `runner_v2.py:636, 746, 836, 1224`; `artifacts_v2.py:115-186` | yes | known limit |

## Frozen design

1. **D3-7.** In `_intrinsic_rejection` (codes as amended by the root
   orchestrator in review round 1):
   - an absent or `None` `source` returns `missing_provenance` (a null
     `source` previously fell through to schema validation);
   - `ValidationError` from `NormalizedTrajectory.model_validate` returns
     `schema_invalid` (was `missing_provenance`);
   - a non-empty `rejection_reasons`, checked after schema validation, returns
     `declared_rejection` (was accepted);
   - a `derivation_parent_id` that names no scenario returns
     `unknown_derivation_parent` (was `split_mismatch`);
   - `source`/`generation` present but different from the expected record
     returns `provenance_mismatch` (was `missing_provenance`);
   - `content_hash` or `semantic_fingerprint` disagreeing with the recomputed
     value returns `hash_mismatch` (was `invalid_verifier_outcome`).
   - No other branch changes; the `_matches_environment` fallback in
     `curate_candidates` (audit N1) is out of scope. None of the eight pilot
     probes reaches a changed branch, so the committed quarantine manifest and
     quality report are byte-identical (`data-pilot-check`).
2. **D2-6.** A test replays the committed r2 report through the public
   `replay_report_v2` and asserts the conditions with a semantic mismatch are
   exactly the conditions whose episode rows r3 corrected (today:
   `untuned_fast_frontier_slow_medium`). r2 cannot be replayed clean by design:
   r3 is the offline erratum that corrects that condition.

## Acceptance

- A failing test per fixed item before the change (D3-7); D2-6 is a new check.
- `uv run --project ml pytest -c ml/pyproject.toml ml/tests -q`, `make lint`,
  `make typecheck`, `make format-check`, `make preflight-fast`, `make test` pass;
  `git status --porcelain data/` is empty.
