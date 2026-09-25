# Fix log: Web restore on local Fast backends, and a deterministic concurrency test

Branch `fix/followup-web-restore-flaky` from `origin/main` @ `eee47a3`.
Two independent follow-up items. No service change: `runtime.py`,
`postgres_repository.py` and `turn_split.py` (owned by PR-14) are untouched,
and so are `qwen_mlx.py`, `fast_output.py`, `ml/pyproject.toml` and
`ml/uv.lock`.

## Item 1: the Web restores a Case on a local Fast backend

Root decision: restore after a reload when readiness reports
`orchestration_mode=temporal`, `storage_mode=postgres` and `adapter_mode` in
{`scripted`, `local_distilled_candidate`, `local_untuned_baseline`}. Direct
mode stays excluded (not durable); the hosted `model` stays excluded.

- Rule: `restorePersisted` in `apps/web/app/components/conversation-workspace.tsx`
  now checks `RESTORABLE_ADAPTER_MODES` instead of `adapter_mode !== "scripted"`.
  The blocked-profile copy now reads "Recovery requires the durable
  Temporal/PostgreSQL Runtime in scripted Runtime mode" (root decision after
  review), so it no longer suggests switching `PROXYLOOP_FAST_BACKEND`.
- Tests (`conversation-workspace.test.tsx`): a restore succeeds for each local
  label under temporal + postgres (authoritative GET, Task Brief shown, no
  alert); the non-durable `it.each` gains hosted `model`, direct +
  PostgreSQL with each local label, and (after review) temporal + PostgreSQL
  with no `adapter_mode`.
- Red on `eee47a3`'s rule: the two restore cases failed (`findByRole` for the
  Task Brief heading timed out); the three new blocked rows passed (they guard
  the exclusions). Green after the change: 9/9 of the selected cases.
- Docs: `docs/architecture.md` (Fast Backend paragraph) and
  `docs/ui/state-matrix.md` ("Restoring Case") state the new rule. The PR-9b
  known limit is marked closed in its log, its review and its status row.
- Not run: a Browser check of the reload against a real Temporal + PostgreSQL
  Runtime on a local backend (needs the gateway and the DB/Temporal lane).

## Item 2: `test_concurrent_sampling_matches_the_sequential_run`

The test asserted `elapsed < 0.6` over 80 fake calls of 10 ms on eight
workers, and failed once on a loaded machine with `0.605`
(`harness/log/feat-pr12-stateless-intake.md`). Following R-15
(`harness/log/fix-gate-honesty-r15-g1.md`), the wall-clock bound is replaced
by deterministic evidence of overlap; only the test file changed.

- New fake `_OverlapCompletions`: the first eight calls wait at a
  `threading.Barrier(8, timeout=10.0)` whose action sets `overlapped`; it
  opens only when eight calls are in flight at once. A worker's calls are
  sequential, so these are eight distinct workers. Later calls sleep 10 ms so
  the writes still interleave. The test asserts `completions.overlapped is True`;
  every other assertion is unchanged. `_SlowCompletions` stays for the resume
  check and `_HardErrorCompletions`.
- Old flake: not reproduced here (10 runs beside 42 busy-loop processes on 14
  cores, 10 passed); the recorded failure is the red evidence.
- Scratch mutation (reverted with `git checkout`, `git diff` empty after):
  `ThreadPoolExecutor(max_workers=concurrency)` → `max_workers=1` in
  `teacher_pipeline.py`. The test failed: `assert False is True` on
  `overlapped` (`_entered=5`: the barrier broke on its timeout and the
  teacher's breaker stopped after five failed calls), `1 failed in 10.53s`.
- Repeat runs, fresh pytest process each: 100/100 passed with no other load;
  20/20 passed beside 42 busy-loop processes.

## Review

Independent review: Approve. Root decisions applied afterwards: the rule is
also stated in `docs/ui/README.md`; `docs/architecture.md` says `adapter_mode`
is opaque to the Web outside the allow-list; the new blocking copy (above);
a deny row for temporal + PostgreSQL with no `adapter_mode`; the PR-9b log and
status row now record the #100 merge. `main` was merged in afterwards.

## Checks

- `make lint` exit 0; `make typecheck` exit 0 (mypy: no issues in 70 files).
- `make test` exit 0: runtime pytest 2016 passed, 66 skipped; ML pytest 498
  passed, 1 skipped; every `*-check` current.
- `make web-check` exit 0: vitest 255 passed, `next build` compiled.
- `make preflight`: the first run failed at `format-check` (ruff would join
  the `threading.Barrier(...)` call in the new fake onto one line). After
  `ruff format` on that file (layout only), the second run exited 0: runtime
  2016 passed / 66 skipped, ML 498 passed / 1 skipped, vitest 255, build,
  both `uv lock --check`, gated skips match the pin of 66. The concurrency
  test passed again after the reformat; the 100x and mutation runs above were
  on the pre-format text (same code).

Not run: the DB gates (`postgres-check`, `phase05a-check`, `phase06b1-check`)
and no `PROXYLOOP_TEST_*` variable set (no service change); the Browser check
above; independent review.
