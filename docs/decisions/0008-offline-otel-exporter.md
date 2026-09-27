# ADR-0008: An offline OTel exporter instead of a live bus subscriber

- **Status:** accepted (root decision under §0.5a, 2026-09-27)
- **Date:** 2026-09-27
- **Task:** S1-ROOT-09 (records it); S1-SYS-11 (P-OBS) implements it and supersedes S1-SYS-06

## Context
- ARCHITECTURE planned `OTelExporter(bus)`: a live subscriber inside each session's TaskGroup whose crash is logged and isolated (S1-SYS-06). That puts exporter code, and failure-isolation code for it, on the session path of every run, and the trace it produces depends on the exporter being up while the session runs.
- Everything a trace needs is already in the bundle: `events.jsonl` carries `event_id`, `t_ms`, `actor`, `stream` and `cause_ids` (I2), and each `llm.call` record carries the model, endpoint, token usage and `t_start`/`t_first_token`/`t_end`. Prompts and responses are content-addressed in `prompts.jsonl`.
- Options: the live subscriber (rejected: session-path risk, and a trace cannot be rebuilt after the fact); an offline exporter over the bundle (chosen); both (rejected: two span mappings for one event log).

## Decision
- **Input.** `events.jsonl` of a finished bundle, or one being written, tailed from disk read-only. The exporter reads events only (AGENTS rule 7). It is not a bus subscriber, and nothing in `kernel/` knows it exists. Tail mode tolerates a partial last line (it waits for the newline) and checks `session.started`'s split before it emits any span.
- **Trace and spans.** All spans of a run share one trace id, derived from `run_id`. One span per event, keyed by `event_id`. `session.started` is the root span, exogenous events (no causes) are its children, and otherwise the first of `cause_ids` is the parent and the others are span links.
- **Services.** `service.name` by actor: `fast.user` → `user`, `fast.cp` → `cp`, `slow` → `slow`, `world.*` → `world`, and `guard`, `kernel`, `ui`, `sim_approver` as themselves. An `llm.call` span takes its record's `role` instead.
- **Timing.** Absolute time is `session.started`'s `wall` plus `t_ms`. An `llm.call` span runs from its `t_start` to its `t_end`, so the latency is the recorded one.
- **`llm.call` attributes.** `gen_ai.request.model` is `requested_model`, `gen_ai.response.model` is `served_model_echo`, plus the endpoint and token usage. Every HTTP attempt is its own span, and a record with `error` gets an ERROR span status.
- **Privacy: default deny.** A span carries the envelope (`event_id`, `t_ms`, `actor`, `stream`, `cause_ids`, `type`) and a named allow-list of non-content payload keys: `lane`, `gen_id`, `utt_id`, `call_id`, `trigger`, `reason`, `basis_seq`, `ttft_ms`/`ttfs_ms`, `slow.tool`'s `name`/`ok`, `offer_ref`/`revision`, `scope`, `status`/`previous`, `move`. Nothing else, by default. An explicit content flag may add only what I4 already makes public: cp-lane text (the rep's lines and the agent's delivered cp lines) and `fast_cp` prompts from `prompts.jsonl`. No flag ever exports private-scope payloads, mandate or approval payloads, `declass.denied`, the user lane's text, or `fast_user`/`slow` prompts.
- **Held-out data (rule 11).** The exporter refuses a sealed path (`serve.bundles.sealed`, any path through `evidence/s4/test`) and any bundle whose split is `test`, before it emits any span.
- **Viewer and CLI.** Phoenix through a P-OBS-owned `compose.yaml`, bound to 127.0.0.1; the CLI is `python -m proxyloop.obs.trace RUN [--endpoint]`. The OTLP dependencies go in an optional dependency group, which the root adds at S1-SYS-11's merge.

## Evidence
None measured; this is a design decision. S1-SYS-11's acceptance produces the evidence: span parent/child against `cause_ids` on fixture bundles; a fixture with private values whose spans contain none of them, with and without the flag; a refused sealed or `test` bundle with no span emitted; and an exported real S0 bundle with overlapping Fast and Slow spans (span JSON and a screenshot in its PR).

## Consequences
- **Contract / fingerprint impact:** none. The exporter reads the existing envelope and `LLMCallRecord`.
- **Data invalidated:** none.
- **Migration:** S1-SYS-06 stays superseded. ARCHITECTURE's `obs` row, the per-session task list and the §14 OTel bullet change with this ADR. No kernel change: the session gains no subscriber.
- **Gains.** Zero session-path risk; replayable (the same bundle always gives the same trace); the same path serves `evidence/` and `runs/`.
- **Risks and what would make us revisit this.** There is no trace during a live session; the web live view covers that. A live trace mode would need its own ADR. If the tail mode ever needs a write or a lock on the bundle, revisit.
