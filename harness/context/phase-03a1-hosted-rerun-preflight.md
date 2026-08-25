# Phase 03A1-R Hosted Rerun Preflight

Date: 2026-08-24

## Human Gate

The user reviewed the merged Phase 03A1-E outcome and explicitly asked to begin
the recommended next operation: a reliable, versioned Terra hosted baseline
rerun before any training decision.

## Integrated Base

- clean synchronized `main` at `a91943c`;
- active branch: `experiment/phase-03a1-hosted-rerun`;
- r2 report fingerprint:
  `499b62b7e0a6e1148652dcaf1bdc6538a6893c1aaa4d2476b5680b603770afa6`;
- r2 file SHA-256:
  `dbfb88c72317046b587ca63142adf71cf0f9b27d4b8f6bcb56e071bf290506b3`;
- r3 report fingerprint:
  `a80e9f2677753c6efb7286706a60703d4d56472941ee88189b88833504477e6c`;
- r3 file SHA-256:
  `c5ed4955bf598db2807a30aa1795fdf886f5b2cf6de2d27ec17541dc10bbcd72`;
- r3 is a zero-dispatch offline correction and remains immutable;
- the attested local Qwen checkpoint exists at revision
  `50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b`;
- Phase 03B and every product/training phase remain inactive.

## Provider Reliability Defect

The first r2 hosted call started but returned no auditable response or usage.
The existing evidence retained only a generic failed-call status and exception
class; it did not retain sanitized HTTP status, request ID, or provider
code/type. A new run must prove transport/usage observability before the matrix
and must never overwrite the failed source evidence.

## Frozen Rerun Shape

- two tiny non-evaluation structured probes, medium then high;
- zero retries and a dedicated probe cost cap;
- exact original four-condition order and r2 token/call caps;
- the three deterministic conditions are copied from r3, not recomputed;
- one new r4 report binds both source fingerprints/timestamps and reconciles
  probe plus matrix external dispatches;
- the probe report also binds all adapter/evaluator/replay/Qwen/dependency-lock
  and command files that can affect the matrix; any post-probe drift blocks it;
- any probe failure blocks all four matrix conditions; any unknown-cost matrix
  failure globally blocks later conditions.

## External and Secret Boundary

The approved endpoint remains `https://29qg.com/v1` with process-only
credentials from the ignored local environment. Provider messages,
credentials, headers, raw request bodies, and consumer PII are never printed or persisted. The probe
contains only a fixed synthetic label and no evaluation payload.

Current observation: `.env` has mode `0600`, but neither it nor the active
process contains `PROXYLOOP_FRONTIER_API_KEY`. No probe or hosted matrix call
has been dispatched in Phase 03A1-R. Work stops at this truthful credential
gate until the user makes the approved endpoint credential available again.

## Non-Goals

No prompt tuning, SFT, QLoRA, DPO, RL, teacher generation, data expansion,
serving, product Agent, database, real tool/Provider, channel, UI, deployment,
release, or Phase 03B activation.
