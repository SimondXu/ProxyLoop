# Teacher selection report (S1-MOD-10, ADR-0025)

Internal instrument choice, not a claim; open-loop, 127 states from 5 train runs; the user decides (ADR-0025).

The exact kernel request (S1-MOD-08) except max_tokens: the candidates ran with a max_tokens override {'teamrouter:claude-sonnet-5-5@low': 16384, 'teamrouter:claude-sonnet-5-5@none': 16384, 'teamrouter:deepseek-flash@high': 16384, 'teamrouter:deepseek-flash@medium': 16384, 'teamrouter:deepseek-flash@none': 16384, 'teamrouter:glm-5.3-flash@none': 16384, 'openrouter:openai/gpt-6-luna@none': 16384}, read from the probe reports' max_tokens_override and every row's max_tokens_sent (they agree; refused otherwise); the reference was recorded at the session's [160].

- useful: USEFUL = D1 & D2 & D4 & D6 & D7 & judged T1..T6. Primary ('all', and USEFUL itself): k / every view of the lane; an errored row and a view an aborted arm never called (`not_run`) are not useful. 'over_rows_run': k / the arm's rows; 'answered' / 'judged': k / its non-error rows. Rates: Wilson 95 % CIs.
- timing: TTFT/latency: the candidates' TeamRouter-relay-measured by the probe, the reference's recorded live via OpenRouter in a session: not comparable. Percentiles: nearest rank.
- hold: hold_agreement: 'has a @hold' equals the reference's (cp lane, answered rows); the reference is the recorded Luna answer, not gold.
- numbers: Numbers (D3, D4, D5): digit runs with ,/. separators, commas and decimal trailing zeros dropped; unsupported: spoken, but not among the rendered messages' numbers; number words are not seen.
- D1: No error, no parse issue, some speech or directive (first attempt).
- D2: hold_for_decision needs @hold decision, hold_for_fact @hold fact_request, close_call @end_call; @end_call under any other guide or none fails; user lane: no @end_call or @hold (wrong_lane_directives).
- D3: Informational: each guide slot value (read from the rendered line) in the speech, as digits or a case-insensitive substring; numbers said naturally (as the profile asks) read as not stated.
- D4: Every number of the speech and of the relays' values and texts (not fact keys) is among the rendered user message's numbers (not the system text's).
- D5: Informational: on rep_spoke / user_msg whose last partner line has a number, a relay value or text carries one of its numbers.
- D6: Frozen phrase lists (CP_AUTHORITY; USER_COMPLETION unless VERIFIED_COMPLETE) in the speech, a negation/modality guard over the 6 words before it in its sentence (GUARDS: 'if', 'will', 'once', words ending in n't or 'll, 'no way', 'no sign', ...; not a bare 'no', 'once again' or 'after all'); lexical, not semantic (T3 is the backstop). Every hit is listed.
- D7: The raw output's pinned-Qwen token count (no special tokens) <= the recorded sessions' Fast max_tokens (the student's cap). finish_reason 'length' is a runaway: the candidates' max_tokens is a guard, not the length control.
- paired: Every candidate - the reference, the two arms of a model, the models at one level (none/minimal/low = low-end; medium); over every view (not run = not useful); run_id clusters resampled; few clusters, wide CI.
- judging: Blind batches, one fresh judge each; a batch never holds two views of one run, nor a view whose prompt carries another's reference sentence (>= 25 characters, whitespace and case normalised); errored outputs are not judged.
- cost: usd: the arm's actual spend (--costs): the sum of TeamRouter's billed amounts of its rows' request_ids, cross-checked against the account balance delta over the whole batch; else null, never 0; usd_per_useful = usd / useful rows (TRAINING §7 cpue sense).
- dash: A '-' cell is null: no denominator, or not known.
- profile: A row is checked and judged under its profile_rendered (else the view's recorded profile): one judge block per (view, profile); one profile per arm and lane; a pair of arms on different profiles is flagged different_prompts.

- git_sha: edf29e50646cd1e4dffe519a9d5a90e1f15f1292
- git_dirty: False
- export_id: 2ad161c83aa7147e76029d2ba5c6093d1f95b94552cb4da72c03c3dcb07b70ec
- views: 127
- runs: 5
- by_lane: {"user": 24, "cp": 103}
- bootstrap: {"seed": 0, "resamples": 10000}
- exclusions: {"errored_rows_not_judged": {"openrouter:openai/gpt-6-luna@none": 0, "teamrouter:claude-sonnet-5-5@low": 0, "teamrouter:claude-sonnet-5-5@none": 0, "teamrouter:deepseek-flash@high": 0, "teamrouter:deepseek-flash@medium": 0, "teamrouter:deepseek-flash@none": 0, "teamrouter:glm-5.3-flash@none": 0}}
- sha256.reports.claude-sonnet-5-5@low.json: 953bbe5e5d03a3665c35196ac2f855384cec538b830022b77d3439fc4d2f7e9f
- sha256.reports.claude-sonnet-5-5@none.json: 535464c2647a29888e88796a204222f69572b1c6feb8d6cc7ee79714331a2137
- sha256.reports.deepseek-flash@high.json: 17dfab20081005ac2a0eaa2e6becf4fcf8ce8d54f05f8d1feb987d0fb99be7e9
- sha256.reports.deepseek-flash@medium.json: dbe0deda5b56dbb28bee8dc1eadbb414cd99a82ead7c1554d3611abfd50f9656
- sha256.reports.deepseek-flash@none.json: c0ff1af3c4f5956f877c9f9a90813bbe57484317190193e51fe5a893ef264bdc
- sha256.reports.glm-5.3-flash@none.json: a4029dd5a2e8f9b412ae69aeccc3fe2bb07979c34fd76c7735d70b5088813e41
- sha256.reports.openrouter_openai_gpt-6-luna@none.json: 18a5e93e74c5799b8d6269229b4a7fe75ae44278b47c8e44e4327865bc5397b0
- sha256.key: a1975577b92bff3efbefa0619bdb3122c392e0a3b59d4571135349ee97527e7b
- sha256.labels.ts-2ad161c8-001.jsonl: fed6f89c7bc94cc2d5287940bbe85ed3fc43465c6212657dc171db1510d3b310
- sha256.labels.ts-2ad161c8-002.jsonl: e7960ae456ad7b810748e51ec88d63391632ac2ebae64199cec238110aeb0c7b
- sha256.labels.ts-2ad161c8-003.jsonl: 2064c9d8f7461aa62efd6f5d2cc5929fc2edde8b48a817c2c2caf70546056ec0
- sha256.labels.ts-2ad161c8-004.jsonl: 6508f844de35acca1d25024d43f154c535a6947d41aca2b1913e9ebca6164c70
- sha256.labels.ts-2ad161c8-005.jsonl: 9f57189ebf7405b9849db0be59368ece524ae63447c853d068241cd57aeaf39c
- sha256.labels.ts-2ad161c8-006.jsonl: 0f581e3ed8eb0c6f41698723e6d9957f65743f4fab9a2bd89fb3fc9af0c1fa0c
- sha256.labels.ts-2ad161c8-007.jsonl: 5e8f89a11609821c4b538d417ad6096b0ccbca3d701b55f2b53673e48d30b60a
- sha256.labels.ts-2ad161c8-008.jsonl: a83d1c7fa12963f5001e0816a96a81e9afd6e9a305e18dd5225fdc010c7e1948
- sha256.labels.ts-2ad161c8-009.jsonl: aaeae9ad0f2545985bbb9ebc842f46ccd7b4bbf63bbb0482cdc59cc5a32666ba
- sha256.labels.ts-2ad161c8-010.jsonl: 0cdc441a1a1ab91ab1fb87a07c0fe9870c8266df3f12cbe5aff9570e775d5732
- sha256.labels.ts-2ad161c8-011.jsonl: f2c302d74b0acbf2bd82bddc14408340adb072a614a54438680f577d02522b0a
- sha256.labels.ts-2ad161c8-012.jsonl: 668ad1baf7a2d71a9992d0b874e5fae1b864dc1f24a2d0d39af245ae8b84aacb
- sha256.labels.ts-2ad161c8-013.jsonl: 8730782f29d3ad3b3420a15a8acebacc08634d189268dde02f678500a798c6b8
- sha256.labels.ts-2ad161c8-014.jsonl: e51b5f01f360456865697540ef4070ea67838794ec2f94e4e52efc8c81db2783
- sha256.labels.ts-2ad161c8-015.jsonl: db3d1e89115f9db583f1bfd53355a245f99761ce713b95ace129db3b213c57b9
- sha256.labels.ts-2ad161c8-016.jsonl: 7679761a0e3d39695fdbdc1ac490637a1f71a9d881eba9b3f1ebc7dcb6b2b67d
- sha256.labels.ts-2ad161c8-017.jsonl: 451f17b15d3b6dfb5c4f546b25b4c72f4fb28e6b3ebaf033ba36aaf8c37213cb
- sha256.labels.ts-2ad161c8-018.jsonl: 4e8a734178e5acd96bd99939647b2960b92cedcac61f4901a8c352995a96aa6e
- sha256.labels.ts-2ad161c8-019.jsonl: 7976463f10ae0b4761a26979a13e573370bc4727471a28d687e10e6ee98c4da7
- sha256.labels.ts-2ad161c8-020.jsonl: 295f5686750d24821185f2b77307f1829ab7d5ae1b262e5ce275136039393639
- sha256.labels.ts-2ad161c8-021.jsonl: e0a43fb7354e5ee55ce81cf600babfcecbb21ee88ca210881fbf96d12baf785a
- sha256.labels.ts-2ad161c8-022.jsonl: 6329701e36ddce7d2879c2f07f9398a145d6e191c5fa42328f05048bc9cc116d
- sha256.labels.ts-2ad161c8-023.jsonl: 60056c646d68b140463a3f1ea6659bc7f48a1e82e2140bbf17ad927adeb13cee
- sha256.labels.ts-2ad161c8-024.jsonl: b5c3d1d6a2255bcc7b5e1baf39a32ff1a00bad0c451430569287c5c91c99dcec
- sha256.labels.ts-2ad161c8-025.jsonl: ccfd813a597c9f9bc4c1cfbcf530ad80071833c8880fcef24c4be21314082a53
- sha256.labels.ts-2ad161c8-026.jsonl: 585bf4bfd52ef6c50825b2e5f7ca3ef86c0f8c78ce6558aa8ae3c7c6860ac256
- sha256.labels.ts-2ad161c8-027.jsonl: 129b03d52f48ad752d6a3fbb4a8c16716169113e394f093019d609f2740e4bc9
- sha256.labels.ts-2ad161c8-028.jsonl: 8758b07a7a6887f438da134055e847f478fe50036a9d106d269b1b72e01a88cb
- sha256.labels.ts-2ad161c8-029.jsonl: 31c3d47519a7f2e31f9378dca216e3f21251bada3bcdeef74351e46fa38e8bcf
- sha256.labels.ts-2ad161c8-030.jsonl: ac4530e8d9b3a0b00ce368c342c40ebc65b5cf04a447958ff6cd52c668bb68a2
- sha256.labels.ts-2ad161c8-031.jsonl: dd851ac19e8ff432d79e2185603446f594897898be0d9da803547016cbb0d43b
- sha256.labels.ts-2ad161c8-032.jsonl: 6627a115e29a3aa2f2d63c68fafe29ff996f333ae14d84341360e4e93423f09f
- sha256.labels.ts-2ad161c8-033.jsonl: b1d423dc4b157c3585c940f6b73960f1a75707ebfbb7f090006d071167671c08
- sha256.labels.ts-2ad161c8-034.jsonl: d9c078daa1d8fa9d4d55389a8e7bc3b49d156732deb98fdff98bae2154177a09
- sha256.labels.ts-2ad161c8-035.jsonl: 177608e2b1b658574e6244351a44eb2ef7ef033cd3cc1b8218ead9979dfd6115
- sha256.costs: -
- sha256.evidence_funnel: 4f4d73b05dee91edcc4f862c4e8b440f8042e414aa77dcbd0a50448c800299be
- sha256.rubric: eac7fbfe1ae6c0b8d6169bca560d86633fd87b4561d47ee49f0e476931dba536

## arms

| metric | openrouter:openai/gpt-6-luna@none | teamrouter:claude-sonnet-5-5@low | teamrouter:claude-sonnet-5-5@none | teamrouter:deepseek-flash@high | teamrouter:deepseek-flash@medium | teamrouter:deepseek-flash@none | teamrouter:glm-5.3-flash@none |
|---|---|---|---|---|---|---|---|
| model_refs | [{"endpoint": "openrouter", "kind": "real_http", "model_id": "openai/gpt-6-luna", "reasoning_effort": "none"}] | [{"endpoint": "teamrouter", "kind": "real_http", "model_id": "claude-sonnet-5-5", "reasoning_effort": "low"}] | [{"endpoint": "teamrouter", "kind": "real_http", "model_id": "claude-sonnet-5-5", "reasoning_effort": "none"}] | [{"endpoint": "teamrouter", "kind": "real_http", "model_id": "deepseek-flash", "reasoning_effort": "high"}] | [{"endpoint": "teamrouter", "kind": "real_http", "model_id": "deepseek-flash", "reasoning_effort": "medium"}] | [{"endpoint": "teamrouter", "kind": "real_http", "model_id": "deepseek-flash", "reasoning_effort": "none"}] | [{"endpoint": "teamrouter", "kind": "real_http", "model_id": "glm-5.3-flash", "reasoning_effort": "none"}] |
| level | low-end | low-end | low-end | high | medium | low-end | low-end |
| served_echoes | ["openai/gpt-6-luna"] | ["claude-sonnet-5-5"] | ["claude-sonnet-5-5"] | ["deepseek-v4-1-flash-260910"] | ["deepseek-v4-1-flash-260910"] | ["deepseek-v4-1-flash-260910"] | ["glm-5.3-flash"] |
| max_tokens | {"values": [16384], "rows_without": 0} | {"values": [16384], "rows_without": 0} | {"values": [16384], "rows_without": 0} | {"values": [16384], "rows_without": 0} | {"values": [16384], "rows_without": 0} | {"values": [16384], "rows_without": 0} | {"values": [16384], "rows_without": 0} |
| rows | 127 | 127 | 127 | 127 | 127 | 127 | 127 |
| not_run | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| profiles | {"cp": "pl_cp_v4", "user": "pl_user_v2"} | {"cp": "pl_cp_v4", "user": "pl_user_v2"} | {"cp": "pl_cp_v4", "user": "pl_user_v2"} | {"cp": "pl_cp_v4", "user": "pl_user_v2"} | {"cp": "pl_cp_v4", "user": "pl_user_v2"} | {"cp": "pl_cp_v4", "user": "pl_user_v2"} | {"cp": "pl_cp_v4", "user": "pl_user_v2"} |
| aborted | - | - | - | - | - | - | - |
| usd | - | - | - | - | - | - | - |
| usd_per_useful | - | - | - | - | - | - | - |

## lane: all

| metric | openrouter:openai/gpt-6-luna@none | teamrouter:claude-sonnet-5-5@low | teamrouter:claude-sonnet-5-5@none | teamrouter:deepseek-flash@high | teamrouter:deepseek-flash@medium | teamrouter:deepseek-flash@none | teamrouter:glm-5.3-flash@none |
|---|---|---|---|---|---|---|---|
| views | 127 | 127 | 127 | 127 | 127 | 127 | 127 |
| n | 127 | 127 | 127 | 127 | 127 | 127 | 127 |
| not_run | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| errors | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| D1.answered | 0.9528 [0.9008, 0.9782] (121/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D1.all | 0.9528 [0.9008, 0.9782] (121/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D1.over_rows_run | 0.9528 [0.9008, 0.9782] (121/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D2.answered | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D2.all | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D2.over_rows_run | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D4.answered | 1.0 [0.9706, 1.0] (127/127) | 0.9921 [0.9567, 0.9986] (126/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D4.all | 1.0 [0.9706, 1.0] (127/127) | 0.9921 [0.9567, 0.9986] (126/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D4.over_rows_run | 1.0 [0.9706, 1.0] (127/127) | 0.9921 [0.9567, 0.9986] (126/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D6.answered | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D6.all | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D6.over_rows_run | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D7.answered | 0.9764 [0.9328, 0.9919] (124/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D7.all | 0.9764 [0.9328, 0.9919] (124/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D7.over_rows_run | 0.9764 [0.9328, 0.9919] (124/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| judged.T1 | 0.9528 [0.9008, 0.9782] (121/127) | 0.9921 [0.9567, 0.9986] (126/127) | 0.9843 [0.9444, 0.9957] (125/127) | 0.9843 [0.9444, 0.9957] (125/127) | 0.9764 [0.9328, 0.9919] (124/127) | 0.874 [0.8051, 0.9209] (111/127) | 0.9606 [0.9111, 0.9831] (122/127) |
| judged.T2 | 1.0 [0.9706, 1.0] (127/127) | 0.9685 [0.9218, 0.9877] (123/127) | 0.9685 [0.9218, 0.9877] (123/127) | 0.9764 [0.9328, 0.9919] (124/127) | 1.0 [0.9706, 1.0] (127/127) | 0.9921 [0.9567, 0.9986] (126/127) | 0.9685 [0.9218, 0.9877] (123/127) |
| judged.T3 | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| judged.T4 | 0.748 [0.666, 0.8155] (95/127) | 0.7559 [0.6744, 0.8224] (96/127) | 0.8031 [0.7255, 0.863] (102/127) | 0.811 [0.7342, 0.8696] (103/127) | 0.8425 [0.7692, 0.8957] (107/127) | 0.6929 [0.608, 0.7665] (88/127) | 0.7402 [0.6576, 0.8086] (94/127) |
| judged.T5 | 0.7008 [0.6162, 0.7736] (89/127) | 0.9921 [0.9567, 0.9986] (126/127) | 0.9528 [0.9008, 0.9782] (121/127) | 0.9449 [0.8906, 0.973] (120/127) | 0.9685 [0.9218, 0.9877] (123/127) | 0.9764 [0.9328, 0.9919] (124/127) | 0.9291 [0.8708, 0.9623] (118/127) |
| judged.T6 | 0.8268 [0.7516, 0.8827] (105/127) | 0.8976 [0.8327, 0.9392] (114/127) | 0.874 [0.8051, 0.9209] (111/127) | 0.9606 [0.9111, 0.9831] (122/127) | 0.9213 [0.8611, 0.9567] (117/127) | 0.937 [0.8806, 0.9677] (119/127) | 0.9764 [0.9328, 0.9919] (124/127) |
| judged_all_pass.judged | 0.5197 [0.4335, 0.6047] (66/127) | 0.6772 [0.5917, 0.7522] (86/127) | 0.6929 [0.608, 0.7665] (88/127) | 0.7244 [0.641, 0.7947] (92/127) | 0.7323 [0.6493, 0.8016] (93/127) | 0.6063 [0.5194, 0.687] (77/127) | 0.6614 [0.5755, 0.7379] (84/127) |
| judged_all_pass.all | 0.5197 [0.4335, 0.6047] (66/127) | 0.6772 [0.5917, 0.7522] (86/127) | 0.6929 [0.608, 0.7665] (88/127) | 0.7244 [0.641, 0.7947] (92/127) | 0.7323 [0.6493, 0.8016] (93/127) | 0.6063 [0.5194, 0.687] (77/127) | 0.6614 [0.5755, 0.7379] (84/127) |
| judged_all_pass.over_rows_run | 0.5197 [0.4335, 0.6047] (66/127) | 0.6772 [0.5917, 0.7522] (86/127) | 0.6929 [0.608, 0.7665] (88/127) | 0.7244 [0.641, 0.7947] (92/127) | 0.7323 [0.6493, 0.8016] (93/127) | 0.6063 [0.5194, 0.687] (77/127) | 0.6614 [0.5755, 0.7379] (84/127) |
| useful | 0.5197 [0.4335, 0.6047] (66/127) | 0.6772 [0.5917, 0.7522] (86/127) | 0.6929 [0.608, 0.7665] (88/127) | 0.7244 [0.641, 0.7947] (92/127) | 0.7323 [0.6493, 0.8016] (93/127) | 0.6063 [0.5194, 0.687] (77/127) | 0.6614 [0.5755, 0.7379] (84/127) |
| useful_over_rows_run | 0.5197 [0.4335, 0.6047] (66/127) | 0.6772 [0.5917, 0.7522] (86/127) | 0.6929 [0.608, 0.7665] (88/127) | 0.7244 [0.641, 0.7947] (92/127) | 0.7323 [0.6493, 0.8016] (93/127) | 0.6063 [0.5194, 0.687] (77/127) | 0.6614 [0.5755, 0.7379] (84/127) |
| failed_attempts | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| missing_echoes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| D3_slots_stated | 0.1429 [0.071, 0.2667] (7/49) | 0.0816 [0.0322, 0.1919] (4/49) | 0.1837 [0.0998, 0.3136] (9/49) | 0.2245 [0.1302, 0.3588] (11/49) | 0.2245 [0.1302, 0.3588] (11/49) | 0.1429 [0.071, 0.2667] (7/49) | 0.1837 [0.0998, 0.3136] (9/49) |
| D5_relay_expected | 0.4444 [0.3094, 0.5882] (20/45) | 0.7778 [0.6373, 0.8746] (35/45) | 0.7556 [0.6133, 0.8576] (34/45) | 0.7333 [0.5896, 0.8404] (33/45) | 0.7333 [0.5896, 0.8404] (33/45) | 0.7111 [0.5663, 0.8227] (32/45) | 0.7111 [0.5663, 0.8227] (32/45) |
| hold_agreement | - | - | - | - | - | - | - |
| wrong_lane_directives | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sentences_mean | 2.126 | 1.7165 | 1.7874 | 1.685 | 1.6535 | 1.5906 | 1.7323 |
| spoken_words_mean | 26.5512 | 26.9528 | 27.1181 | 21.6929 | 22.0315 | 19.0866 | 22.8189 |
| finish_reason | {"stop": 126, "length": 1} | {"stop": 127} | {"stop": 127} | {"stop": 127} | {"stop": 127} | {"stop": 127} | {"stop": 127} |
| length_stops | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| length_empty_speech | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| reasoning_tokens.p50 | 0 | 0 | 0 | 113 | 111 | 0 | 0 |
| reasoning_tokens.p95 | 0 | 0 | 0 | 819 | 654 | 0 | 19 |
| reasoning_tokens.n | 127 | 127 | 127 | 127 | 127 | 127 | 127 |
| reasoning_tokens.unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| qwen_tokens.p50 | 35 | 49 | 45 | 40 | 40 | 34 | 37 |
| qwen_tokens.p95 | 93 | 107 | 112 | 93 | 90 | 89 | 89 |
| qwen_tokens.n | 127 | 127 | 127 | 127 | 127 | 127 | 127 |
| qwen_tokens.max | 16390 | 130 | 123 | 121 | 128 | 113 | 121 |
| ttft_ms.p50 | 778 | 8178 | 3322 | 2317 | 2399 | 1319 | 2484 |
| ttft_ms.p95 | 2971 | 30442 | 7801 | 8160 | 6929 | 1917 | 4163 |
| ttft_ms.n | 127 | 127 | 127 | 127 | 127 | 127 | 127 |
| latency_ms.p50 | 1199 | 9566 | 4662 | 2591 | 2591 | 1656 | 3109 |
| latency_ms.p95 | 3706 | 33540 | 10009 | 8326 | 7338 | 2257 | 5137 |
| latency_ms.n | 127 | 127 | 127 | 127 | 127 | 127 | 127 |
| usage_unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| prompt_tokens | 155969 | 232813 | 232813 | 163130 | 163130 | 159955 | 154717 |
| completion_tokens | 22556 | 77390 | 9370 | 32111 | 30583 | 5200 | 6070 |

## lane: user

| metric | openrouter:openai/gpt-6-luna@none | teamrouter:claude-sonnet-5-5@low | teamrouter:claude-sonnet-5-5@none | teamrouter:deepseek-flash@high | teamrouter:deepseek-flash@medium | teamrouter:deepseek-flash@none | teamrouter:glm-5.3-flash@none |
|---|---|---|---|---|---|---|---|
| views | 24 | 24 | 24 | 24 | 24 | 24 | 24 |
| n | 24 | 24 | 24 | 24 | 24 | 24 | 24 |
| not_run | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| errors | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| D1.answered | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D1.all | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D1.over_rows_run | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D2.answered | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D2.all | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D2.over_rows_run | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D4.answered | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D4.all | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D4.over_rows_run | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D6.answered | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D6.all | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D6.over_rows_run | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D7.answered | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D7.all | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D7.over_rows_run | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| judged.T1 | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| judged.T2 | 1.0 [0.862, 1.0] (24/24) | 0.9583 [0.7976, 0.9926] (23/24) | 0.9167 [0.7415, 0.9768] (22/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 0.9167 [0.7415, 0.9768] (22/24) |
| judged.T3 | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| judged.T4 | 0.875 [0.69, 0.9566] (21/24) | 0.9583 [0.7976, 0.9926] (23/24) | 0.875 [0.69, 0.9566] (21/24) | 0.7917 [0.5953, 0.9076] (19/24) | 0.9167 [0.7415, 0.9768] (22/24) | 0.8333 [0.6415, 0.9332] (20/24) | 0.875 [0.69, 0.9566] (21/24) |
| judged.T5 | 0.9583 [0.7976, 0.9926] (23/24) | 1.0 [0.862, 1.0] (24/24) | 0.9583 [0.7976, 0.9926] (23/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| judged.T6 | 1.0 [0.862, 1.0] (24/24) | 0.7917 [0.5953, 0.9076] (19/24) | 0.875 [0.69, 0.9566] (21/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| judged_all_pass.judged | 0.875 [0.69, 0.9566] (21/24) | 0.75 [0.551, 0.88] (18/24) | 0.7917 [0.5953, 0.9076] (19/24) | 0.7917 [0.5953, 0.9076] (19/24) | 0.9167 [0.7415, 0.9768] (22/24) | 0.8333 [0.6415, 0.9332] (20/24) | 0.7917 [0.5953, 0.9076] (19/24) |
| judged_all_pass.all | 0.875 [0.69, 0.9566] (21/24) | 0.75 [0.551, 0.88] (18/24) | 0.7917 [0.5953, 0.9076] (19/24) | 0.7917 [0.5953, 0.9076] (19/24) | 0.9167 [0.7415, 0.9768] (22/24) | 0.8333 [0.6415, 0.9332] (20/24) | 0.7917 [0.5953, 0.9076] (19/24) |
| judged_all_pass.over_rows_run | 0.875 [0.69, 0.9566] (21/24) | 0.75 [0.551, 0.88] (18/24) | 0.7917 [0.5953, 0.9076] (19/24) | 0.7917 [0.5953, 0.9076] (19/24) | 0.9167 [0.7415, 0.9768] (22/24) | 0.8333 [0.6415, 0.9332] (20/24) | 0.7917 [0.5953, 0.9076] (19/24) |
| useful | 0.875 [0.69, 0.9566] (21/24) | 0.75 [0.551, 0.88] (18/24) | 0.7917 [0.5953, 0.9076] (19/24) | 0.7917 [0.5953, 0.9076] (19/24) | 0.9167 [0.7415, 0.9768] (22/24) | 0.8333 [0.6415, 0.9332] (20/24) | 0.7917 [0.5953, 0.9076] (19/24) |
| useful_over_rows_run | 0.875 [0.69, 0.9566] (21/24) | 0.75 [0.551, 0.88] (18/24) | 0.7917 [0.5953, 0.9076] (19/24) | 0.7917 [0.5953, 0.9076] (19/24) | 0.9167 [0.7415, 0.9768] (22/24) | 0.8333 [0.6415, 0.9332] (20/24) | 0.7917 [0.5953, 0.9076] (19/24) |
| failed_attempts | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| missing_echoes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| D3_slots_stated | - | - | - | - | - | - | - |
| D5_relay_expected | 1.0 [0.7575, 1.0] (12/12) | 1.0 [0.7575, 1.0] (12/12) | 1.0 [0.7575, 1.0] (12/12) | 1.0 [0.7575, 1.0] (12/12) | 1.0 [0.7575, 1.0] (12/12) | 1.0 [0.7575, 1.0] (12/12) | 1.0 [0.7575, 1.0] (12/12) |
| hold_agreement | - | - | - | - | - | - | - |
| wrong_lane_directives | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sentences_mean | 1.4583 | 1.4583 | 1.5 | 1.3333 | 1.3333 | 1.25 | 1.2917 |
| spoken_words_mean | 23.125 | 31.4583 | 32.2917 | 24.2083 | 25.8333 | 21.7083 | 29.0 |
| finish_reason | {"stop": 24} | {"stop": 24} | {"stop": 24} | {"stop": 24} | {"stop": 24} | {"stop": 24} | {"stop": 24} |
| length_stops | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| length_empty_speech | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| reasoning_tokens.p50 | 0 | 0 | 0 | 41 | 42 | 0 | 0 |
| reasoning_tokens.p95 | 0 | 0 | 0 | 159 | 108 | 0 | 0 |
| reasoning_tokens.n | 24 | 24 | 24 | 24 | 24 | 24 | 24 |
| reasoning_tokens.unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| qwen_tokens.p50 | 50 | 54 | 52 | 47 | 52 | 48 | 48 |
| qwen_tokens.p95 | 81 | 84 | 117 | 67 | 75 | 84 | 105 |
| qwen_tokens.n | 24 | 24 | 24 | 24 | 24 | 24 | 24 |
| qwen_tokens.max | 114 | 107 | 123 | 95 | 80 | 111 | 121 |
| ttft_ms.p50 | 681 | 5443 | 2970 | 1757 | 1834 | 1319 | 2541 |
| ttft_ms.p95 | 875 | 11558 | 4703 | 2748 | 2905 | 1699 | 4163 |
| ttft_ms.n | 24 | 24 | 24 | 24 | 24 | 24 | 24 |
| latency_ms.p50 | 1157 | 6798 | 4387 | 2042 | 2090 | 1668 | 3367 |
| latency_ms.p95 | 1748 | 12749 | 6174 | 3107 | 3323 | 2078 | 5586 |
| latency_ms.n | 24 | 24 | 24 | 24 | 24 | 24 | 24 |
| usage_unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| prompt_tokens | 19438 | 29568 | 29568 | 20484 | 20484 | 19884 | 19653 |
| completion_tokens | 1274 | 6982 | 1969 | 2686 | 2415 | 1104 | 1341 |

## lane: cp

| metric | openrouter:openai/gpt-6-luna@none | teamrouter:claude-sonnet-5-5@low | teamrouter:claude-sonnet-5-5@none | teamrouter:deepseek-flash@high | teamrouter:deepseek-flash@medium | teamrouter:deepseek-flash@none | teamrouter:glm-5.3-flash@none |
|---|---|---|---|---|---|---|---|
| views | 103 | 103 | 103 | 103 | 103 | 103 | 103 |
| n | 103 | 103 | 103 | 103 | 103 | 103 | 103 |
| not_run | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| errors | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| D1.answered | 0.9417 [0.8787, 0.973] (97/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D1.all | 0.9417 [0.8787, 0.973] (97/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D1.over_rows_run | 0.9417 [0.8787, 0.973] (97/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D2.answered | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D2.all | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D2.over_rows_run | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D4.answered | 1.0 [0.964, 1] (103/103) | 0.9903 [0.947, 0.9983] (102/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D4.all | 1.0 [0.964, 1] (103/103) | 0.9903 [0.947, 0.9983] (102/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D4.over_rows_run | 1.0 [0.964, 1] (103/103) | 0.9903 [0.947, 0.9983] (102/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D6.answered | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D6.all | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D6.over_rows_run | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D7.answered | 0.9709 [0.9178, 0.99] (100/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D7.all | 0.9709 [0.9178, 0.99] (100/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D7.over_rows_run | 0.9709 [0.9178, 0.99] (100/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| judged.T1 | 0.9417 [0.8787, 0.973] (97/103) | 0.9903 [0.947, 0.9983] (102/103) | 0.9806 [0.9319, 0.9947] (101/103) | 0.9806 [0.9319, 0.9947] (101/103) | 0.9709 [0.9178, 0.99] (100/103) | 0.8447 [0.7625, 0.9021] (87/103) | 0.9515 [0.8914, 0.9791] (98/103) |
| judged.T2 | 1.0 [0.964, 1] (103/103) | 0.9709 [0.9178, 0.99] (100/103) | 0.9806 [0.9319, 0.9947] (101/103) | 0.9709 [0.9178, 0.99] (100/103) | 1.0 [0.964, 1] (103/103) | 0.9903 [0.947, 0.9983] (102/103) | 0.9806 [0.9319, 0.9947] (101/103) |
| judged.T3 | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| judged.T4 | 0.7184 [0.6249, 0.7962] (74/103) | 0.7087 [0.6148, 0.7877] (73/103) | 0.7864 [0.6977, 0.8545] (81/103) | 0.8155 [0.7298, 0.8786] (84/103) | 0.8252 [0.7406, 0.8865] (85/103) | 0.6602 [0.5644, 0.7444] (68/103) | 0.7087 [0.6148, 0.7877] (73/103) |
| judged.T5 | 0.6408 [0.5446, 0.7268] (66/103) | 0.9903 [0.947, 0.9983] (102/103) | 0.9515 [0.8914, 0.9791] (98/103) | 0.932 [0.8663, 0.9667] (96/103) | 0.9612 [0.9044, 0.9848] (99/103) | 0.9709 [0.9178, 0.99] (100/103) | 0.9126 [0.8422, 0.9533] (94/103) |
| judged.T6 | 0.7864 [0.6977, 0.8545] (81/103) | 0.9223 [0.8542, 0.9601] (95/103) | 0.8738 [0.796, 0.9247] (90/103) | 0.9515 [0.8914, 0.9791] (98/103) | 0.9029 [0.8304, 0.9464] (93/103) | 0.9223 [0.8542, 0.9601] (95/103) | 0.9709 [0.9178, 0.99] (100/103) |
| judged_all_pass.judged | 0.4369 [0.3451, 0.5332] (45/103) | 0.6602 [0.5644, 0.7444] (68/103) | 0.6699 [0.5744, 0.7532] (69/103) | 0.7087 [0.6148, 0.7877] (73/103) | 0.6893 [0.5945, 0.7705] (71/103) | 0.5534 [0.4572, 0.6458] (57/103) | 0.6311 [0.5347, 0.718] (65/103) |
| judged_all_pass.all | 0.4369 [0.3451, 0.5332] (45/103) | 0.6602 [0.5644, 0.7444] (68/103) | 0.6699 [0.5744, 0.7532] (69/103) | 0.7087 [0.6148, 0.7877] (73/103) | 0.6893 [0.5945, 0.7705] (71/103) | 0.5534 [0.4572, 0.6458] (57/103) | 0.6311 [0.5347, 0.718] (65/103) |
| judged_all_pass.over_rows_run | 0.4369 [0.3451, 0.5332] (45/103) | 0.6602 [0.5644, 0.7444] (68/103) | 0.6699 [0.5744, 0.7532] (69/103) | 0.7087 [0.6148, 0.7877] (73/103) | 0.6893 [0.5945, 0.7705] (71/103) | 0.5534 [0.4572, 0.6458] (57/103) | 0.6311 [0.5347, 0.718] (65/103) |
| useful | 0.4369 [0.3451, 0.5332] (45/103) | 0.6602 [0.5644, 0.7444] (68/103) | 0.6699 [0.5744, 0.7532] (69/103) | 0.7087 [0.6148, 0.7877] (73/103) | 0.6893 [0.5945, 0.7705] (71/103) | 0.5534 [0.4572, 0.6458] (57/103) | 0.6311 [0.5347, 0.718] (65/103) |
| useful_over_rows_run | 0.4369 [0.3451, 0.5332] (45/103) | 0.6602 [0.5644, 0.7444] (68/103) | 0.6699 [0.5744, 0.7532] (69/103) | 0.7087 [0.6148, 0.7877] (73/103) | 0.6893 [0.5945, 0.7705] (71/103) | 0.5534 [0.4572, 0.6458] (57/103) | 0.6311 [0.5347, 0.718] (65/103) |
| failed_attempts | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| missing_echoes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| D3_slots_stated | 0.1429 [0.071, 0.2667] (7/49) | 0.0816 [0.0322, 0.1919] (4/49) | 0.1837 [0.0998, 0.3136] (9/49) | 0.2245 [0.1302, 0.3588] (11/49) | 0.2245 [0.1302, 0.3588] (11/49) | 0.1429 [0.071, 0.2667] (7/49) | 0.1837 [0.0998, 0.3136] (9/49) |
| D5_relay_expected | 0.2424 [0.1283, 0.4102] (8/33) | 0.697 [0.5266, 0.8262] (23/33) | 0.6667 [0.4961, 0.8025] (22/33) | 0.6364 [0.4662, 0.7781] (21/33) | 0.6364 [0.4662, 0.7781] (21/33) | 0.6061 [0.4368, 0.7532] (20/33) | 0.6061 [0.4368, 0.7532] (20/33) |
| hold_agreement | - | - | - | - | - | - | - |
| wrong_lane_directives | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sentences_mean | 2.2816 | 1.7767 | 1.8544 | 1.767 | 1.7282 | 1.6699 | 1.835 |
| spoken_words_mean | 27.3495 | 25.9029 | 25.9126 | 21.1068 | 21.1456 | 18.4757 | 21.3786 |
| finish_reason | {"stop": 102, "length": 1} | {"stop": 103} | {"stop": 103} | {"stop": 103} | {"stop": 103} | {"stop": 103} | {"stop": 103} |
| length_stops | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| length_empty_speech | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| reasoning_tokens.p50 | 0 | 0 | 0 | 126 | 146 | 0 | 0 |
| reasoning_tokens.p95 | 0 | 0 | 0 | 848 | 679 | 0 | 21 |
| reasoning_tokens.n | 103 | 103 | 103 | 103 | 103 | 103 | 103 |
| reasoning_tokens.unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| qwen_tokens.p50 | 33 | 46 | 42 | 36 | 37 | 31 | 36 |
| qwen_tokens.p95 | 93 | 109 | 111 | 93 | 94 | 89 | 81 |
| qwen_tokens.n | 103 | 103 | 103 | 103 | 103 | 103 | 103 |
| qwen_tokens.max | 16390 | 130 | 120 | 121 | 128 | 113 | 102 |
| ttft_ms.p50 | 797 | 9234 | 3460 | 2634 | 2558 | 1315 | 2478 |
| ttft_ms.p95 | 3385 | 30967 | 8196 | 8193 | 7036 | 1965 | 4139 |
| ttft_ms.n | 103 | 103 | 103 | 103 | 103 | 103 | 103 |
| latency_ms.p50 | 1223 | 10271 | 4747 | 2810 | 2813 | 1646 | 3028 |
| latency_ms.p95 | 3753 | 33828 | 11283 | 8569 | 7372 | 2352 | 4754 |
| latency_ms.n | 103 | 103 | 103 | 103 | 103 | 103 | 103 |
| usage_unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| prompt_tokens | 136531 | 203245 | 203245 | 142646 | 142646 | 140071 | 135064 |
| completion_tokens | 21282 | 70408 | 7401 | 29425 | 28168 | 4096 | 4729 |

## paired useful: difference, 95 % CI (no decision rule)

| metric | all | user | cp |
|---|---|---|---|
| openrouter:openai/gpt-6-luna@none - teamrouter:claude-sonnet-5-5@low | -0.1575 [-0.2069, -0.1081] (5 clusters) | 0.125 [0.0, 0.3462] (5 clusters) | -0.2233 [-0.2609, -0.1863] (5 clusters) |
| openrouter:openai/gpt-6-luna@none - teamrouter:claude-sonnet-5-5@none | -0.1732 [-0.1908, -0.1495] (5 clusters) | 0.0833 [0.0, 0.2] (5 clusters) | -0.233 [-0.2527, -0.2019] (5 clusters) |
| openrouter:openai/gpt-6-luna@none - teamrouter:deepseek-flash@none | -0.0866 [-0.1405, -0.0504] (5 clusters) | 0.0417 [0.0, 0.1154] (5 clusters) | -0.1165 [-0.18, -0.069] (5 clusters) |
| openrouter:openai/gpt-6-luna@none - teamrouter:glm-5.3-flash@none | -0.1417 [-0.1736, -0.1] (5 clusters) | 0.0833 [0.0, 0.1786] (5 clusters) | -0.1942 [-0.2432, -0.1333] (5 clusters) |
| teamrouter:claude-sonnet-5-5@low - teamrouter:deepseek-flash@none | 0.0709 [0.034, 0.1215] (5 clusters) | -0.0833 [-0.2308, 0.0] (5 clusters) | 0.1068 [0.0642, 0.1546] (5 clusters) |
| teamrouter:claude-sonnet-5-5@low - teamrouter:glm-5.3-flash@none | 0.0157 [-0.0461, 0.069] (5 clusters) | -0.0417 [-0.2143, 0.1364] (5 clusters) | 0.0291 [-0.0161, 0.0787] (5 clusters) |
| teamrouter:claude-sonnet-5-5@none - teamrouter:deepseek-flash@none | 0.0866 [0.0323, 0.1275] (5 clusters) | -0.0417 [-0.2, 0.0769] (5 clusters) | 0.1165 [0.0545, 0.1616] (5 clusters) |
| teamrouter:claude-sonnet-5-5@none - teamrouter:glm-5.3-flash@none | 0.0315 [0.0078, 0.0593] (5 clusters) | 0.0 [-0.1364, 0.1071] (5 clusters) | 0.0388 [0.0, 0.1011] (5 clusters) |
| teamrouter:deepseek-flash@high - teamrouter:deepseek-flash@medium | -0.0079 [-0.0577, 0.0397] (5 clusters) | -0.125 [-0.2273, -0.0385] (5 clusters) | 0.0194 [-0.0455, 0.0661] (5 clusters) |
| teamrouter:deepseek-flash@high - teamrouter:deepseek-flash@none | 0.1181 [0.0442, 0.1774] (5 clusters) | -0.0417 [-0.1364, 0.0] (5 clusters) | 0.1553 [0.0769, 0.2255] (5 clusters) |
| teamrouter:deepseek-flash@medium - teamrouter:deepseek-flash@none | 0.126 [0.0667, 0.1855] (5 clusters) | 0.0833 [0.0, 0.1818] (5 clusters) | 0.1359 [0.0833, 0.1863] (5 clusters) |
| teamrouter:deepseek-flash@none - teamrouter:glm-5.3-flash@none | -0.0551 [-0.0985, -0.0082] (5 clusters) | 0.0417 [0.0, 0.1364] (5 clusters) | -0.0777 [-0.1389, -0.0102] (5 clusters) |

## paired judged_all_pass: difference, 95 % CI (no decision rule)

| metric | all | user | cp |
|---|---|---|---|
| openrouter:openai/gpt-6-luna@none - teamrouter:claude-sonnet-5-5@low | -0.1575 [-0.2069, -0.1081] (5 clusters) | 0.125 [0.0, 0.3462] (5 clusters) | -0.2233 [-0.2609, -0.1863] (5 clusters) |
| openrouter:openai/gpt-6-luna@none - teamrouter:claude-sonnet-5-5@none | -0.1732 [-0.1908, -0.1495] (5 clusters) | 0.0833 [0.0, 0.2] (5 clusters) | -0.233 [-0.2527, -0.2019] (5 clusters) |
| openrouter:openai/gpt-6-luna@none - teamrouter:deepseek-flash@none | -0.0866 [-0.1405, -0.0504] (5 clusters) | 0.0417 [0.0, 0.1154] (5 clusters) | -0.1165 [-0.18, -0.069] (5 clusters) |
| openrouter:openai/gpt-6-luna@none - teamrouter:glm-5.3-flash@none | -0.1417 [-0.1736, -0.1] (5 clusters) | 0.0833 [0.0, 0.1786] (5 clusters) | -0.1942 [-0.2432, -0.1333] (5 clusters) |
| teamrouter:claude-sonnet-5-5@low - teamrouter:deepseek-flash@none | 0.0709 [0.034, 0.1215] (5 clusters) | -0.0833 [-0.2308, 0.0] (5 clusters) | 0.1068 [0.0642, 0.1546] (5 clusters) |
| teamrouter:claude-sonnet-5-5@low - teamrouter:glm-5.3-flash@none | 0.0157 [-0.0461, 0.069] (5 clusters) | -0.0417 [-0.2143, 0.1364] (5 clusters) | 0.0291 [-0.0161, 0.0787] (5 clusters) |
| teamrouter:claude-sonnet-5-5@none - teamrouter:deepseek-flash@none | 0.0866 [0.0323, 0.1275] (5 clusters) | -0.0417 [-0.2, 0.0769] (5 clusters) | 0.1165 [0.0545, 0.1616] (5 clusters) |
| teamrouter:claude-sonnet-5-5@none - teamrouter:glm-5.3-flash@none | 0.0315 [0.0078, 0.0593] (5 clusters) | 0.0 [-0.1364, 0.1071] (5 clusters) | 0.0388 [0.0, 0.1011] (5 clusters) |
| teamrouter:deepseek-flash@high - teamrouter:deepseek-flash@medium | -0.0079 [-0.0577, 0.0397] (5 clusters) | -0.125 [-0.2273, -0.0385] (5 clusters) | 0.0194 [-0.0455, 0.0661] (5 clusters) |
| teamrouter:deepseek-flash@high - teamrouter:deepseek-flash@none | 0.1181 [0.0442, 0.1774] (5 clusters) | -0.0417 [-0.1364, 0.0] (5 clusters) | 0.1553 [0.0769, 0.2255] (5 clusters) |
| teamrouter:deepseek-flash@medium - teamrouter:deepseek-flash@none | 0.126 [0.0667, 0.1855] (5 clusters) | 0.0833 [0.0, 0.1818] (5 clusters) | 0.1359 [0.0833, 0.1863] (5 clusters) |
| teamrouter:deepseek-flash@none - teamrouter:glm-5.3-flash@none | -0.0551 [-0.0985, -0.0082] (5 clusters) | 0.0417 [0.0, 0.1364] (5 clusters) | -0.0777 [-0.1389, -0.0102] (5 clusters) |

## D6 lexical hits

- none
