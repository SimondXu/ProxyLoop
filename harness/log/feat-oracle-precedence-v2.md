# Feat log: versioned scripted-oracle precedence, V2 offer-first (P1 D1-8, slice P-B)

Spec: `harness/context/feat-oracle-precedence-v2-preflight.md`.
Design: D1 simulator-v2 root decision 3 (precedence is versioned, default V1).
Branch `feat/oracle-precedence-v2` from `main` @ `383d1fa`.

## What changed

- `runtime/packages/agent_core/src/proxyloop_agent_core/observation.py`: new
  `OraclePrecedence` `StrEnum` (`V1 = "v1"`, `V2_OFFER_FIRST =
  "v2_offer_first"`); `ScriptedOracleConsumer` takes keyword
  `precedence=OraclePrecedence.V1`, coerced through `OraclePrecedence(...)`
  (unknown values raise `ValueError`). After the shared clarify → disclosure →
  approval gates, V2 goes to `_decide_offer_first` (accept a compliant offer
  when evidence is available → escalate on transfer → replan without
  evidence → decline). Offer selection moved into `_best_valid_offer`, used by
  both orders; the V1 branch order and reason codes are unchanged.
- `runtime/packages/agent_core/src/proxyloop_agent_core/__init__.py`: exports
  `OraclePrecedence`.
- `ml/tests/test_oracle_precedence_v2.py` (new, 7 tests). It lives under
  `ml/tests` because the invariance probe uses the 03C builders
  (`proxyloop_evaluation.phase03c_scenarios.harvest_positions`), which exist
  only in the ML environment.

No caller switches to V2; no scenario, environment, manifest, verifier or
artifact file is touched.

## Red → green

- Red (before the source change): `uv run --project ml pytest -c
  ml/pyproject.toml ml/tests/test_oracle_precedence_v2.py -q` → collection
  error `ImportError: cannot import name 'OraclePrecedence' from
  'proxyloop_agent_core'`.
- Pre-change snapshot, measured on unmodified `main` @ `383d1fa` with a
  scratch probe (catalogue 32 instances + seeds 1–1010 × 32 instances, both
  harvested positions): 64,704 observations, default-oracle digest
  `21c81841a5f9c207a7f2c5dd17c8d6687060bae307556f0b06a7ea20e69bed22`
  (accept 20,220; decline 16,176; replan 12,132; escalate 8,088; clarify
  4,044; refuse_disclosure 4,044; every escalate has transfer set).
- Green: same command → `7 passed in 7.17s` (full 64,704 space, ~5.7 s).

## Invariance result

- Default, explicit `V1` and `V2_OFFER_FIRST` all reproduce digest
  `21c81841…bed22` over the 64,704 observations (scratch probe after the
  change); the test pins this digest and asserts default == explicit V1 and
  V2 == V1 per observation (0 differences).
- Forcing `transfer_available=True` on the 56,616 non-transfer observations:
  V2 ≠ V1 on exactly the 20,220 whose original V1 decision was
  `accept_offer` (V1 escalates, V2 returns the original accept); identical
  elsewhere.
- Probe E (catalogue `direct-success` opening + transfer): V2 →
  `accept_offer` on the expected offer, `("valid_offer",)`; default and V1 →
  `escalate`, `("transfer_available",)`.

## Verification (this worktree)

Passed:
- `make lint` → exit 0 (both ruff runs "All checks passed!").
- `make typecheck` → exit 0 ("Success: no issues found in 59 source files").
- `ruff format --check` on the changed files → already formatted.
- `make harness-check`, `make benchmark-check`,
  `make phase03c-invariants-check`, `make phase03c-rescore-check`
  (cloud disagreements: 0 on held-out and dev) → exit 0.
- `make preflight-fast` → exit 0.
- `make test` → exit 0 (runtime 705 passed, 42 skipped; ml 388 passed,
  1 skipped; every artifact check valid). `git status --porcelain data/`
  afterwards: empty.

Environment note: the first `make test` in the fresh worktree failed two
`runtime/test_generated_contracts.py` tests because the worktree had no
`node_modules` (`Command "json2ts" not found`). `pnpm install
--frozen-lockfile --offline` fixed it without changing tracked files; the
rerun above is the reported result.

Not run: `make preflight` (final gate, root's call), Compose gates (no
runtime/worker/connector/API change).

## Review

Independent review (`reviewer`, Opus): **Approve**, no Blocking/Important.
A 200,000-observation differential fuzz outside the catalogue (ties broken
by offer_id, `expires_at == observed_at`, currency mismatch, unsupported
changes, an injected raising policy) found 0 differences between `main` and
the default/explicit V1 in action, offer, reason codes, exceptions and the
order of policy calls; V2 matched an independent model of the frozen order
with 0 violations, and every V2 accept had confirmation evidence. The
pinned digest was recomputed from `main`'s `observation.py` and matches; it
is stable across `PYTHONHASHSEED`. Minor 1 applied (docstring: V2 evaluates
the offer policy on the transfer path). Minor 2 (a hand-built tie-break
test) not applied: the existing 01B observation tests and this fuzz cover it.
