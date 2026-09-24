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
