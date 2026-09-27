# ADR-0008: An offline OTel exporter instead of a live bus subscriber

- **Status:** accepted (root decision under §0.5a, 2026-09-27)
- **Date:** 2026-09-27
- **Task:** S1-ROOT-09 (records it); S1-SYS-11 (P-OBS) implements it and supersedes S1-SYS-06

## Context
- ARCHITECTURE planned `OTelExporter(bus)`: a live subscriber inside each session's TaskGroup whose crash is logged and isolated (S1-SYS-06). That puts exporter code, and failure-isolation code for it, on the session path of every run, and the trace it produces depends on the exporter being up while the session runs.
- Everything a trace needs is already in the bundle: `events.jsonl` carries `event_id`, `t_ms`, `actor`, `stream` and `cause_ids` (I2), and each `llm.call` record carries the model, endpoint, token usage and `t_start`/`t_first_token`/`t_end`. Prompts and responses are content-addressed in `prompts.jsonl`.
- Options: the live subscriber (rejected: session-path risk, and a trace cannot be rebuilt after the fact); an offline exporter over the bundle (chosen); both (rejected: two span mappings for one event log).

## Decision
- **Input.** `events.jsonl` of a finished bundle, or one being written, tailed from disk read-only. The exporter reads events only (AGENTS rule 7). It is not a bus subscriber, and nothing in `kernel/` knows it exists.
- **Spans.** One span per event, keyed by `event_id`. The first of `cause_ids` is the parent; the others are span links. Exogenous events (no causes) are roots.
- **Resources.** Each lane is an OTel resource (`service.name`): `user`, `cp`, `slow`, `world` and `guard`/`kernel`.
- **Timing.** From `t_ms` on the session clock; an `llm.call` span runs from its `t_start` to its `t_end`, so the latency is the recorded one.
- **Attributes.** `gen_ai.*` from `llm.call` records: model id, endpoint and token usage. No prompt or response text by default; the exporter may attach content from `prompts.jsonl`, by sha, only behind an explicit flag. Private-state values are never exported, flag or not.
- **Held-out data (rule 11).** The exporter refuses a sealed bundle (`serve.bundles.sealed`, any path through `evidence/s4/test`) and any bundle whose split is `test`.
- **Viewer and CLI.** Phoenix through a P-OBS-owned `compose.yaml`, bound to 127.0.0.1; the CLI is `python -m proxyloop.obs.trace RUN [--endpoint]`. The OTLP dependencies are granted in the S1-SYS-11 packet.

## Evidence
None measured; this is a design decision. S1-SYS-11's acceptance produces the evidence: span parent/child against `cause_ids` on fixture bundles, and an exported real S0 bundle with overlapping Fast and Slow spans (span JSON and a screenshot in its PR).

## Consequences
- **Contract / fingerprint impact:** none. The exporter reads the existing envelope and `LLMCallRecord`.
- **Data invalidated:** none.
- **Migration:** S1-SYS-06 stays superseded. ARCHITECTURE's `obs` row, the per-session task list and the §14 OTel bullet change with this ADR. No kernel change: the session gains no subscriber.
- **Gains.** Zero session-path risk; replayable (the same bundle always gives the same trace); the same path serves `evidence/` and `runs/`.
- **Risks and what would make us revisit this.** There is no trace during a live session; the web live view covers that. A live trace mode would need its own ADR. If the tail mode ever needs a write or a lock on the bundle, revisit.
