# PR-9b Review: local distilled Fast gateway and M1 stack parity (first half)

**Target**: `feat/pr9b-local-fast-gateway` @ `31edadb` (base `main` @ `1573a42`)

**Spec**: `harness/context/pr9-local-distilled-fast-design.md`

**Reviewer**: independent read-only `reviewer` subagent. The root orchestrator
relayed the findings and its decisions; the implementer wrote this artifact.
The reviewer's forgery repro was `scratchpad/rev-pr9b/subset_demo.py`.

**Decision**: Request Changes, with no Blocking findings. The root accepted
I1 and M1–M7 for this PR, and added one decision: PR-9a's default Fast timeout
is 25 s (the cap). The PR merges after PR-9a, once the gateway has switched to
the shared wire module.

## Findings and disposition

### I1: `--check` accepted a self-consistent rewrite of the report

**Severity**: Important (evidence integrity). **Disposition**: fixed.

`--check` rebuilt the derived fields from the report's own observed fields.
So a report that dropped the four distilled rows the model got wrong (236/236),
duplicated rows, or carried a zeroed `decoding_fingerprint` still passed. Both
`--write` and `--check` now run `validate_observed` first. Each arm must hold
exactly the cloud arm's prompt ids in cloud order. Its identity must equal
`GatewayIdentity(backend, attested adapter fingerprint, recorded MLX versions)`,
`identity_fingerprint` included. Tests cover dropped, duplicated and reordered
rows, a zeroed decoding fingerprint, a swapped label, an edit with a
re-computed fingerprint, and the reviewer's forgery through `main(["--check"])`.
The inherent limits are stated in the report's `claim_boundary` and in the
README: raw outputs cannot be verified without the model, and
`report_fingerprint` is self-computed, not a signature.

### M1: the LoRA guard missed a partial load and the verify/load gap

**Severity**: Minor. **Disposition**: fixed.

After load, `check_loaded_lora_weights` fingerprints every loaded
`lora_a`/`lora_b` with the attestation formula and requires the committed
`content_fingerprint`. Implementation choice: the root's wording was to compare
against `mx.load(adapters.safetensors)`. But a file swapped after the check
would be read identically by `mlx_lm.load` and by that re-read. Comparing the
tensors in memory with the committed hash closes both gaps with one check.
Real MLX: a copy with one `lora_a` renamed passed the layer guard and was
refused by the new check. The attested adapter passes both.

### M2: M1 ran on uncommitted working-tree code

**Severity**: Minor. **Disposition**: recorded, no rerun.

The distilled arm started at `5429076` before any PR-9b code commit. The
untuned arm started at `afeec4d` with the parity runner uncommitted. Both
predate `f148362`. Finding: the generation path is byte-identical in
behaviour, with this evidence:

- `prompt_fingerprint_matches` is 240/240 against the bundle rows.
- The frozen decoding and parsing modules are base-commit bytes.
- At `31edadb` with a clean tree, 10 distilled rows (the first of each family
  plus all 4 oracle-disagreeing rows) and 6 untuned rows regenerated
  byte-identical raw outputs and token counts, under identical identities.

The distilled arm's pre-commit files are known to differ from the committed
ones only by formatting, import mechanics and a `wire.py` change off the
generation path. That rests on the session record, not on preserved bytes.
Each arm's `code_state` in the report records this. Future runs capture it in
the run header. The post-hoc rule for two unparseable outputs decided 0 rows.

### M3: `--run` did not require `HF_HUB_OFFLINE=1`

**Severity**: Minor. **Disposition**: fixed. `--run` now refuses without it.

### M4: the loopback gateway accepted browser simple POSTs and rebinding Hosts

**Severity**: Minor. **Disposition**: fixed.

Requests need `Host: 127.0.0.1:<port>` (400 `host_not_allowed`). Decide
calls need `Content-Type: application/json` (415). Socket reads time out after
10 s (408). Tests cover each. Note for PR-9a: the client must address
`127.0.0.1`, not `localhost`.

### M5: no test that load and decide share the model thread

**Severity**: Minor. **Disposition**: fixed.
`test_load_and_decide_run_on_the_same_model_thread`.

### M6: `mlx_config_sha256` was not CI-verifiable

**Severity**: Minor. **Disposition**: fixed. `render_mlx_config` derives the
config from the committed PEFT `adapter_config.json`, and a test recomputes the
attested hash.

### M7: latency measured under concurrent load

**Severity**: Minor. **Disposition**: documented in the README and the log.

## Root decision recorded with this review

PR-9a's default Fast timeout is 25 s. MLX cannot cancel, so after a client
timeout the gateway stays busy until the generation ends. The next Fast call
in that window gets `503 busy` and falls back. This is recorded in
`ml/serving/README.md` and the log.

---

# PR-9b Review, second half: wire switch, M2, local split reports, docs

**Target**: `feat/pr9b-local-fast-gateway` @ `93bf266` (after the merge of
`main` @ `e10443d`, #98)

**Reviewer**: independent read-only `reviewer` subagent (scratch
`scratchpad/rev-pr9b2/`: branch patch, a merged-tree copy, and its check logs).
The root orchestrator relayed the findings and its decisions; the implementer
wrote this section.

**Decision**: Request Changes, with no Blocking findings. The root accepted I1,
M1–M5 and the nits for this PR.

## Findings and disposition

### I1: the per-family explanation of the M2 drop was wrong

**Severity**: Important (docs correctness). **Disposition**: fixed.

The README, the log and `docs/architecture.md` said the distilled model
"follows its input" on promotion-credit and unsupported-action, and called D4
the main cause. The committed report says otherwise:
- promotion-credit: 40/40 against the true oracle, 0/40 against the product
  oracle (the model keeps confirm);
- unsupported-action: 0/40 true and 40/40 product.

The 236 → 157 drop breaks down as:
- refusal-transfer −40 (no offer, refused before the model, not D4);
- unsupported-action −40 (D4);
- required-feature-loss +1.

The implementer re-derived these from `product-path-report.json` and the M1
report. All four places are corrected (the status row included). D4 is about
half of the drop.

### M1: the timeout expectations in `docs/architecture.md` disagreed

**Severity**: Minor. **Disposition**: fixed. The relevant figure is now the
product path: 64/200 over 25 s by `generation_ms`, 65/200 by `wall_ms`,
roughly a third. The trained-path 15/240 is context only, and the split runs
saw 0/16.

### M2: Host and IPv6 wording

**Severity**: Minor. **Disposition**: fixed. The README Host rule accepts
`127.0.0.1:<port>` and `localhost:<port>`. `docs/development.md` says the
gateway listens on IPv4 only, so `http://[::1]:<port>` fails at startup.

### M3: the local split check trusted its own identity and measured block

**Severity**: Minor (evidence integrity). **Disposition**: fixed.
`check_local_report` requires `gateway_identity` to equal the M1 report's
recorded identity for the backend. The distilled adapter fingerprint must also
equal the committed attestation's `content_fingerprint`
(`gateway_identity_not_attested`). The check then cross-checks
`measured.fast_calls` against the per-turn records:
- the call count;
- the token entries;
- the recomputed p50 and max;
- the per-turn outcome, set against `fast_result`, `fallback_cause` and
  `delivered`.

Tamper tests cover a self-consistent re-identified report, a call rewritten as
a timeout, a dropped call, an edited max, and a call moved to another turn.
They failed against the previous script.

### M4: M2 could not be regenerated without the git-ignored runs

**Severity**: Minor. **Disposition**: fixed.
`run_phase03c_product_parity.py --rebuild-from-report` re-derives every
delivery stage, gate code and aggregate from the committed per-row raw outputs.
It refuses when a generated row's product prompt no longer matches the
recomputed one (`validate_observed` now checks `prompt_fingerprint`), because
then the model must run again. The `--check` failure message names it, and the
README documents it. Tests: a rebuild with no code change gives identical
bytes; a derivation change is caught and then rebuilt; a changed prompt is
refused.

### M5: no `main(["--check"])` test for an edited raw output or reordered rows

**Severity**: Minor. **Disposition**: fixed (both, on the M2 script).

### Nits

**Disposition**: all three fixed.
- The make variable is `LOCAL_FAST_PORT`, and `FAST_GATEWAY_URL` follows it.
- The M2 `CLAIM_BOUNDARY` now says "not p95 or capacity". The report was
  regenerated with `--rebuild-from-report`; only `claim_boundary` and
  `report_fingerprint` changed.
- The stale "Pending (after PR-9a lands)" log section was replaced.

## Known limit recorded with this review

The Web does not restore a Case on a local Fast backend after a reload, because
restore requires `adapter_mode=scripted` (see the Browser check in the log).
This is on the follow-up list and is outside PR-9b.

Closed by `fix/followup-web-restore-flaky`: the Web now restores under
temporal + postgres with `adapter_mode` `scripted`, `local_distilled_candidate`
or `local_untuned_baseline` (log `harness/log/fix-followup-web-restore-flaky.md`).
