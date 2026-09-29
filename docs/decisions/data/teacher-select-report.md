# Teacher selection report (S1-MOD-10, ADR-0025)

Internal instrument choice, not a claim; open-loop, 127 states from 5 train runs; the user decides (ADR-0025).

The exact kernel request (S1-MOD-08) except max_tokens: the candidates ran with a max_tokens override {'teamrouter:glm-5.3-flash@none': 16384, 'teamrouter:glm-5.3-flash@medium': 16384, 'teamrouter:deepseek-flash@none': 16384, 'teamrouter:deepseek-flash@medium': 16384, 'teamrouter:gemini-3.8-flash@none': 16384, 'teamrouter:gemini-3.8-flash@medium': 16384}, read from the probe reports' max_tokens_override and every row's max_tokens_sent (they agree; refused otherwise); the reference was recorded at the session's [160].

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

- git_sha: 64e56a3d4ad66f37c3a99def2d6713aa286c6259
- git_dirty: False
- export_id: 41fd630b3a8869a2245f605761f55fd76e98ea40c88603fc1cdc131e8e6a4a88
- views: 127
- runs: 5
- by_lane: {"user": 24, "cp": 103}
- bootstrap: {"seed": 0, "resamples": 10000}
- exclusions: {"errored_rows_not_judged": {"reference": 0, "teamrouter:deepseek-flash@medium": 0, "teamrouter:deepseek-flash@none": 0, "teamrouter:gemini-3.8-flash@medium": 1, "teamrouter:gemini-3.8-flash@none": 1, "teamrouter:glm-5.3-flash@medium": 0, "teamrouter:glm-5.3-flash@none": 0}}
- sha256.reports.glm-5.3-flash@none.json: 146edd1d1fe5b7a0db3f7958e8dfe70be4482ad92e3af685cd43be3cfb53f5f6
- sha256.reports.glm-5.3-flash@medium.json: 4c9c505eafd586c77b98770978f46999003c711e0ec791447340378f566cfa5a
- sha256.reports.deepseek-flash@none.json: eb7fbe4fa64243aba6242c791a2a302b1b6fed3e41ab5e5d779deab56bbb062d
- sha256.reports.deepseek-flash@medium.json: edc75d8d23bba55b28d64af5fee32cb25d82be93337e6cacffc92133f3c3c352
- sha256.reports.gemini-3.8-flash@none.json: 6a31588c38bd9c9818cc0c9164ae8c433e9c9d65828d989b5359607edeb9b018
- sha256.reports.gemini-3.8-flash@medium.json: 2b3a2356f4c20ea7b16fc2a1dea238fcf67b38f5c2d1d066d49c0c091d31dc12
- sha256.key: 9e7d4d8040d3018828aa4648db7195b62b00c1a1028bad081b6d0c50e0047e27
- sha256.labels.ts-41fd630b-001.jsonl: 09f4de769242481a50791d423bf670d3394992d3adc617bc5d0da43e96d2fc08
- sha256.labels.ts-41fd630b-002.jsonl: 4f8523467b774895c152d30e51c8202e180e1114e23639279e46a0289fe4aedb
- sha256.labels.ts-41fd630b-003.jsonl: 5c0b291f222ff5ce2705bd509ea6c2717de4d709875976cb5dad513c9c00254e
- sha256.labels.ts-41fd630b-004.jsonl: 1e3bd7e14f7f7fb21694e78c41c460a1bd7ee4a96fa58214d49f92a694e8ef78
- sha256.labels.ts-41fd630b-005.jsonl: b26557a1aef1aa516d9e88a1afed235baf9e6fd7fb04d665ae00d5774c36dc9b
- sha256.labels.ts-41fd630b-006.jsonl: 46b358824a867c8ada1bae650f503dc11406f0f5a9110511c33f6a739dd81e4f
- sha256.labels.ts-41fd630b-007.jsonl: f6542e7ae3800478de5c939f0e06ddf1c06f73be134451dc6f8e3a1fc48da170
- sha256.labels.ts-41fd630b-008.jsonl: 4ff46a724227de48ac7f8139459e35fa47ac8ac3b646cbd120c4889457b21995
- sha256.labels.ts-41fd630b-009.jsonl: d9f58312e7ada3f81e3d8a495c92c10839e47a18c405bfa57e68f220b248e7d7
- sha256.labels.ts-41fd630b-010.jsonl: 88796b1356b01af6a0c5a5f3d7013736c9d12666ff52545986d919b9053d64da
- sha256.labels.ts-41fd630b-011.jsonl: 45e740e95616d8ebf2b88465372488fe72bb51b4da6e442aa9fa172735183ef5
- sha256.labels.ts-41fd630b-012.jsonl: 44a33a44313f45d98477652b051bde5ceea4bf3548a767dcee03ee5d53fa9ae4
- sha256.labels.ts-41fd630b-013.jsonl: 6443db87d72d39d7ae68994b127daff6db213fc480d743ac157a0d5c7d4ad3d1
- sha256.labels.ts-41fd630b-014.jsonl: a7a41a44e69f0746ffcf2f14d11655337f2f635f9e75190f89f1511384b9a62c
- sha256.labels.ts-41fd630b-015.jsonl: 2241fd0ce31b8e82c5ec0266065619406247bd87c8bbd776d78c44e708cbddc8
- sha256.labels.ts-41fd630b-016.jsonl: 0b8f768d408554d20a498a634f20ebf4e4e88d9e2ca1362a8c8773c42cdf9fa2
- sha256.labels.ts-41fd630b-017.jsonl: cc6bebd1a69d72df0ad9590df51a9367fd1ff17afb0234d64b42da90fc3feb92
- sha256.labels.ts-41fd630b-018.jsonl: dcce01c24d40d69046b4e9e6aaa836dedb85421ce117f05e91fe61654de683bd
- sha256.labels.ts-41fd630b-019.jsonl: 7ca8aacd7c62e83222995ff512d3909e02a26becaf9edaeab5f0569e6d7fe8c4
- sha256.labels.ts-41fd630b-020.jsonl: 4cf2b301a9a350d72d832f3707328844ba121ec559c6a4ad9e9ff17e4bfc6d60
- sha256.labels.ts-41fd630b-021.jsonl: f78e7979a04c0ad07e38b532fbb381210a2b3c6113d5f561e588444562f07cd6
- sha256.labels.ts-41fd630b-022.jsonl: 28eac0a0bdff8a7072bea55d1fd322fe03baca47daf032d832e5967571877899
- sha256.labels.ts-41fd630b-023.jsonl: 4847f710ad60593706f84718b805c07e2cc3b37bb31da6ae256a70c54167f8ff
- sha256.labels.ts-41fd630b-024.jsonl: 18441c428ca022b44a0f42bdebc230cf7eb4085268bd496217291c8974ad182a
- sha256.labels.ts-41fd630b-025.jsonl: b13acb2e10e7c45c18fc92f7d1d8083496bfb1169124e68fd7c0f0753d88155b
- sha256.labels.ts-41fd630b-026.jsonl: 48852a8f36151cc4803fcafd9bd052554b4934b004d1fa9216b3e23d56bab05d
- sha256.labels.ts-41fd630b-027.jsonl: b9f5e109b657d58941013ae8b45bc666445e490bc576c56d017af276aca36a85
- sha256.labels.ts-41fd630b-028.jsonl: 29e0dcb776ca1f1e59c251df5257485379559b8eb7e2a84e1479150e4ab949fd
- sha256.labels.ts-41fd630b-029.jsonl: 3aa87c6659167aee484bc2c294de8025fb808b103e3ce873aa152be2f36f8644
- sha256.labels.ts-41fd630b-030.jsonl: b989d7b5af36a5702206f9c1da81e944f48ae78a60a8f4fc01d48b13c83d126c
- sha256.labels.ts-41fd630b-031.jsonl: 0c9e1b0e287969625ba3936620347294d6f6a53fb48984f4004199557155c93b
- sha256.labels.ts-41fd630b-032.jsonl: d31ec330a70dac31baa63539f5b561acd2f685620f3615889996198de4261520
- sha256.labels.ts-41fd630b-033.jsonl: 0de02cafc6299d3396b339b4ca479b0e64ecbd90038e923cc23a5b3d4dfc8ec2
- sha256.labels.ts-41fd630b-034.jsonl: 4e171eb27b5083a17efdf6fd52dad3d427eebb5595c9cece668628b245bb21bf
- sha256.labels.ts-41fd630b-035.jsonl: 4f276c1793e4b692a73cb46c1df6fe5f7e1f815805c2ad549e88a4f26e42c380
- sha256.costs: 9edfb446c9cefda77360490718056f61b41bfba6bef4850bac0e3eeaed848c4e
- sha256.evidence_funnel: 49386572221f15a58323b12151eb57d94e58882310f306d02da6d94c1b4d43a6
- sha256.rubric: eac7fbfe1ae6c0b8d6169bca560d86633fd87b4561d47ee49f0e476931dba536

## arms

| metric | reference | teamrouter:deepseek-flash@medium | teamrouter:deepseek-flash@none | teamrouter:gemini-3.8-flash@medium | teamrouter:gemini-3.8-flash@none | teamrouter:glm-5.3-flash@medium | teamrouter:glm-5.3-flash@none |
|---|---|---|---|---|---|---|---|
| model_refs | [{"endpoint": "openrouter", "kind": "real_http", "model_id": "openai/gpt-6-luna", "reasoning_effort": "none"}] | [{"endpoint": "teamrouter", "kind": "real_http", "model_id": "deepseek-flash", "reasoning_effort": "medium"}] | [{"endpoint": "teamrouter", "kind": "real_http", "model_id": "deepseek-flash", "reasoning_effort": "none"}] | [{"endpoint": "teamrouter", "kind": "real_http", "model_id": "gemini-3.8-flash", "reasoning_effort": "medium"}] | [{"endpoint": "teamrouter", "kind": "real_http", "model_id": "gemini-3.8-flash", "reasoning_effort": "none"}] | [{"endpoint": "teamrouter", "kind": "real_http", "model_id": "glm-5.3-flash", "reasoning_effort": "medium"}] | [{"endpoint": "teamrouter", "kind": "real_http", "model_id": "glm-5.3-flash", "reasoning_effort": "none"}] |
| level | - | medium | low-end | medium | low-end | medium | low-end |
| served_echoes | ["openai/gpt-6-luna"] | ["deepseek-v4-1-flash-260910"] | ["deepseek-v4-1-flash-260910"] | ["gemini-3.8-flash"] | ["gemini-3.8-flash"] | ["glm-5.3-flash"] | ["glm-5.3-flash"] |
| max_tokens | {"values": [160], "rows_without": 0} | {"values": [16384], "rows_without": 0} | {"values": [16384], "rows_without": 0} | {"values": [16384], "rows_without": 0} | {"values": [16384], "rows_without": 0} | {"values": [16384], "rows_without": 0} | {"values": [16384], "rows_without": 0} |
| rows | 127 | 127 | 127 | 1 | 118 | 127 | 127 |
| not_run | 0 | 0 | 0 | 126 | 9 | 0 | 0 |
| aborted | - | - | - | gemini-3.8-flash unavailable: RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read) | gemini-3.8-flash unavailable: RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read) | - | - |
| usd | - | 0.03269923 | 0.01641249 | - | - | 0.00873268 | 0.00774488 |
| usd_per_useful | - | 0.0005 | 0.0003 | - | - | 0.0001 | 0.0001 |

## lane: all

| metric | reference | teamrouter:deepseek-flash@medium | teamrouter:deepseek-flash@none | teamrouter:gemini-3.8-flash@medium | teamrouter:gemini-3.8-flash@none | teamrouter:glm-5.3-flash@medium | teamrouter:glm-5.3-flash@none |
|---|---|---|---|---|---|---|---|
| views | 127 | 127 | 127 | 127 | 127 | 127 | 127 |
| n | 127 | 127 | 127 | 1 | 118 | 127 | 127 |
| not_run | 0 | 0 | 0 | 126 | 9 | 0 | 0 |
| errors | 0 | 0 | 0 | 1 | 1 | 0 | 0 |
| D1.answered | 0.874 [0.8051, 0.9209] (111/127) | 0.9291 [0.8708, 0.9623] (118/127) | 0.8976 [0.8327, 0.9392] (114/127) | - | 0.3761 [0.2936, 0.4665] (44/117) | 0.7244 [0.641, 0.7947] (92/127) | 0.811 [0.7342, 0.8696] (103/127) |
| D1.all | 0.874 [0.8051, 0.9209] (111/127) | 0.9291 [0.8708, 0.9623] (118/127) | 0.8976 [0.8327, 0.9392] (114/127) | 0.0 [0.0, 0.0294] (0/127) | 0.3465 [0.2693, 0.4326] (44/127) | 0.7244 [0.641, 0.7947] (92/127) | 0.811 [0.7342, 0.8696] (103/127) |
| D1.over_rows_run | 0.874 [0.8051, 0.9209] (111/127) | 0.9291 [0.8708, 0.9623] (118/127) | 0.8976 [0.8327, 0.9392] (114/127) | 0.0 [0.0, 0.7935] (0/1) | 0.3729 [0.2909, 0.4628] (44/118) | 0.7244 [0.641, 0.7947] (92/127) | 0.811 [0.7342, 0.8696] (103/127) |
| D2.answered | 0.937 [0.8806, 0.9677] (119/127) | 0.9606 [0.9111, 0.9831] (122/127) | 1.0 [0.9706, 1.0] (127/127) | - | 0.9316 [0.8709, 0.9649] (109/117) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D2.all | 0.937 [0.8806, 0.9677] (119/127) | 0.9606 [0.9111, 0.9831] (122/127) | 1.0 [0.9706, 1.0] (127/127) | 0.0 [0.0, 0.0294] (0/127) | 0.8583 [0.7871, 0.9084] (109/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D2.over_rows_run | 0.937 [0.8806, 0.9677] (119/127) | 0.9606 [0.9111, 0.9831] (122/127) | 1.0 [0.9706, 1.0] (127/127) | 0.0 [0.0, 0.7935] (0/1) | 0.9237 [0.8614, 0.9594] (109/118) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D4.answered | 1.0 [0.9706, 1.0] (127/127) | 0.9843 [0.9444, 0.9957] (125/127) | 1.0 [0.9706, 1.0] (127/127) | - | 1.0 [0.9682, 1.0] (117/117) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D4.all | 1.0 [0.9706, 1.0] (127/127) | 0.9843 [0.9444, 0.9957] (125/127) | 1.0 [0.9706, 1.0] (127/127) | 0.0 [0.0, 0.0294] (0/127) | 0.9213 [0.8611, 0.9567] (117/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D4.over_rows_run | 1.0 [0.9706, 1.0] (127/127) | 0.9843 [0.9444, 0.9957] (125/127) | 1.0 [0.9706, 1.0] (127/127) | 0.0 [0.0, 0.7935] (0/1) | 0.9915 [0.9536, 0.9985] (117/118) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D6.answered | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | - | 1.0 [0.9682, 1.0] (117/117) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D6.all | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 0.0 [0.0, 0.0294] (0/127) | 0.9213 [0.8611, 0.9567] (117/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D6.over_rows_run | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 0.0 [0.0, 0.7935] (0/1) | 0.9915 [0.9536, 0.9985] (117/118) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D7.answered | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | - | 1.0 [0.9682, 1.0] (117/117) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D7.all | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 0.0 [0.0, 0.0294] (0/127) | 0.9213 [0.8611, 0.9567] (117/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| D7.over_rows_run | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 0.0 [0.0, 0.7935] (0/1) | 0.9915 [0.9536, 0.9985] (117/118) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| judged.T1 | 0.9843 [0.9444, 0.9957] (125/127) | 0.9134 [0.8515, 0.9509] (116/127) | 0.9213 [0.8611, 0.9567] (117/127) | - | 0.3846 [0.3015, 0.4751] (45/117) | 0.9685 [0.9218, 0.9877] (123/127) | 0.8661 [0.7961, 0.9147] (110/127) |
| judged.T2 | 1.0 [0.9706, 1.0] (127/127) | 0.9685 [0.9218, 0.9877] (123/127) | 0.9528 [0.9008, 0.9782] (121/127) | - | 1.0 [0.9682, 1.0] (117/117) | 0.9606 [0.9111, 0.9831] (122/127) | 0.9764 [0.9328, 0.9919] (124/127) |
| judged.T3 | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) | - | 1.0 [0.9682, 1.0] (117/117) | 1.0 [0.9706, 1.0] (127/127) | 1.0 [0.9706, 1.0] (127/127) |
| judged.T4 | 0.8268 [0.7516, 0.8827] (105/127) | 0.7087 [0.6244, 0.7806] (90/127) | 0.6142 [0.5273, 0.6943] (78/127) | - | 0.7607 [0.6759, 0.8289] (89/117) | 0.8268 [0.7516, 0.8827] (105/127) | 0.8268 [0.7516, 0.8827] (105/127) |
| judged.T5 | 0.748 [0.666, 0.8155] (95/127) | 0.9843 [0.9444, 0.9957] (125/127) | 1.0 [0.9706, 1.0] (127/127) | - | 1.0 [0.9682, 1.0] (117/117) | 0.9764 [0.9328, 0.9919] (124/127) | 0.937 [0.8806, 0.9677] (119/127) |
| judged.T6 | 0.8819 [0.8143, 0.9271] (112/127) | 0.937 [0.8806, 0.9677] (119/127) | 0.9134 [0.8515, 0.9509] (116/127) | - | 0.9829 [0.9398, 0.9953] (115/117) | 0.9528 [0.9008, 0.9782] (121/127) | 0.9291 [0.8708, 0.9623] (118/127) |
| judged_all_pass.judged | 0.5433 [0.4567, 0.6274] (69/127) | 0.6063 [0.5194, 0.687] (77/127) | 0.5118 [0.4258, 0.5971] (65/127) | - | 0.359 [0.2778, 0.4491] (42/117) | 0.7165 [0.6327, 0.7877] (91/127) | 0.6378 [0.5513, 0.7162] (81/127) |
| judged_all_pass.all | 0.5433 [0.4567, 0.6274] (69/127) | 0.6063 [0.5194, 0.687] (77/127) | 0.5118 [0.4258, 0.5971] (65/127) | 0.0 [0.0, 0.0294] (0/127) | 0.3307 [0.2549, 0.4164] (42/127) | 0.7165 [0.6327, 0.7877] (91/127) | 0.6378 [0.5513, 0.7162] (81/127) |
| judged_all_pass.over_rows_run | 0.5433 [0.4567, 0.6274] (69/127) | 0.6063 [0.5194, 0.687] (77/127) | 0.5118 [0.4258, 0.5971] (65/127) | 0.0 [0.0, 0.7935] (0/1) | 0.3559 [0.2753, 0.4456] (42/118) | 0.7165 [0.6327, 0.7877] (91/127) | 0.6378 [0.5513, 0.7162] (81/127) |
| useful | 0.5433 [0.4567, 0.6274] (69/127) | 0.5669 [0.48, 0.6499] (72/127) | 0.4567 [0.3726, 0.5433] (58/127) | 0.0 [0.0, 0.0294] (0/127) | 0.3228 [0.2478, 0.4083] (41/127) | 0.5433 [0.4567, 0.6274] (69/127) | 0.5354 [0.4489, 0.6199] (68/127) |
| useful_over_rows_run | 0.5433 [0.4567, 0.6274] (69/127) | 0.5669 [0.48, 0.6499] (72/127) | 0.4567 [0.3726, 0.5433] (58/127) | 0.0 [0.0, 0.7935] (0/1) | 0.3475 [0.2676, 0.437] (41/118) | 0.5433 [0.4567, 0.6274] (69/127) | 0.5354 [0.4489, 0.6199] (68/127) |
| failed_attempts | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| missing_echoes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| D3_slots_stated | 0.1224 [0.0573, 0.2424] (6/49) | 0.1633 [0.0851, 0.2904] (8/49) | 0.102 [0.0444, 0.2176] (5/49) | - | 0.0 [0.0, 0.0727] (0/49) | 0.1633 [0.0851, 0.2904] (8/49) | 0.2245 [0.1302, 0.3588] (11/49) |
| D5_relay_expected | 0.5556 [0.4118, 0.6906] (25/45) | 0.7556 [0.6133, 0.8576] (34/45) | 0.8222 [0.6867, 0.9071] (37/45) | - | 0.225 [0.1232, 0.375] (9/40) | 0.8 [0.6618, 0.891] (36/45) | 0.7111 [0.5663, 0.8227] (32/45) |
| hold_agreement | - | 0.6602 [0.5644, 0.7444] (68/103) | 0.5631 [0.4668, 0.6549] (58/103) | - | 0.7447 [0.6481, 0.822] (70/94) | 0.767 [0.6767, 0.8381] (79/103) | 0.767 [0.6767, 0.8381] (79/103) |
| wrong_lane_directives | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sentences_mean | 1.9291 | 1.7638 | 1.8425 | - | 0.6068 | 1.8425 | 1.7795 |
| spoken_words_mean | 25.6614 | 28.6142 | 25.5118 | - | 8.6154 | 29.4882 | 25.7559 |
| finish_reason | {"stop": 127} | {"stop": 127} | {"stop": 127} | {} | {"stop": 45, "None": 72} | {"stop": 127} | {"stop": 127} |
| length_stops | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| length_empty_speech | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| reasoning_tokens.p50 | 0 | 103 | 0 | - | 0 | 20 | 0 |
| reasoning_tokens.p95 | 0 | 276 | 0 | - | 1065 | 79 | 0 |
| reasoning_tokens.n | 127 | 127 | 127 | 0 | 117 | 127 | 127 |
| reasoning_tokens.unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| qwen_tokens.p50 | 37 | 56 | 55 | - | 0 | 53 | 45 |
| qwen_tokens.p95 | 91 | 102 | 88 | - | 70 | 106 | 88 |
| qwen_tokens.n | 127 | 127 | 127 | 0 | 117 | 127 | 127 |
| qwen_tokens.max | 143 | 127 | 129 | - | 96 | 150 | 123 |
| ttft_ms.p50 | 577 | 2627 | 1523 | - | 3758 | 4188 | 3244 |
| ttft_ms.p95 | 814 | 4533 | 2232 | - | 8541 | 7632 | 5117 |
| ttft_ms.n | 127 | 127 | 127 | 0 | 45 | 127 | 127 |
| latency_ms.p50 | 926 | 2959 | 1965 | - | 4063 | 5597 | 4232 |
| latency_ms.p95 | 1382 | 4893 | 2811 | - | 13351 | 9376 | 6432 |
| latency_ms.n | 127 | 127 | 127 | 0 | 117 | 127 | 127 |
| usage_unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| prompt_tokens | 125531 | 132002 | 128827 | - | 62753 | 124152 | 124152 |
| completion_tokens | 5919 | 22874 | 6726 | - | 22527 | 10469 | 5979 |

## lane: user

| metric | reference | teamrouter:deepseek-flash@medium | teamrouter:deepseek-flash@none | teamrouter:gemini-3.8-flash@medium | teamrouter:gemini-3.8-flash@none | teamrouter:glm-5.3-flash@medium | teamrouter:glm-5.3-flash@none |
|---|---|---|---|---|---|---|---|
| views | 24 | 24 | 24 | 24 | 24 | 24 | 24 |
| n | 24 | 24 | 24 | 1 | 23 | 24 | 24 |
| not_run | 0 | 0 | 0 | 23 | 1 | 0 | 0 |
| errors | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| D1.answered | 0.9583 [0.7976, 0.9926] (23/24) | 0.875 [0.69, 0.9566] (21/24) | 0.9167 [0.7415, 0.9768] (22/24) | - | 0.4783 [0.2924, 0.6704] (11/23) | 0.5833 [0.3883, 0.7553] (14/24) | 0.7083 [0.5083, 0.8509] (17/24) |
| D1.all | 0.9583 [0.7976, 0.9926] (23/24) | 0.875 [0.69, 0.9566] (21/24) | 0.9167 [0.7415, 0.9768] (22/24) | 0.0 [0.0, 0.138] (0/24) | 0.4583 [0.2789, 0.6493] (11/24) | 0.5833 [0.3883, 0.7553] (14/24) | 0.7083 [0.5083, 0.8509] (17/24) |
| D1.over_rows_run | 0.9583 [0.7976, 0.9926] (23/24) | 0.875 [0.69, 0.9566] (21/24) | 0.9167 [0.7415, 0.9768] (22/24) | 0.0 [0.0, 0.7935] (0/1) | 0.4783 [0.2924, 0.6704] (11/23) | 0.5833 [0.3883, 0.7553] (14/24) | 0.7083 [0.5083, 0.8509] (17/24) |
| D2.answered | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | - | 1.0 [0.8569, 1.0] (23/23) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D2.all | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 0.0 [0.0, 0.138] (0/24) | 0.9583 [0.7976, 0.9926] (23/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D2.over_rows_run | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 0.0 [0.0, 0.7935] (0/1) | 1.0 [0.8569, 1.0] (23/23) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D4.answered | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | - | 1.0 [0.8569, 1.0] (23/23) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D4.all | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 0.0 [0.0, 0.138] (0/24) | 0.9583 [0.7976, 0.9926] (23/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D4.over_rows_run | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 0.0 [0.0, 0.7935] (0/1) | 1.0 [0.8569, 1.0] (23/23) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D6.answered | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | - | 1.0 [0.8569, 1.0] (23/23) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D6.all | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 0.0 [0.0, 0.138] (0/24) | 0.9583 [0.7976, 0.9926] (23/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D6.over_rows_run | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 0.0 [0.0, 0.7935] (0/1) | 1.0 [0.8569, 1.0] (23/23) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D7.answered | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | - | 1.0 [0.8569, 1.0] (23/23) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D7.all | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 0.0 [0.0, 0.138] (0/24) | 0.9583 [0.7976, 0.9926] (23/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| D7.over_rows_run | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 0.0 [0.0, 0.7935] (0/1) | 1.0 [0.8569, 1.0] (23/23) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| judged.T1 | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | - | 0.4783 [0.2924, 0.6704] (11/23) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| judged.T2 | 1.0 [0.862, 1.0] (24/24) | 0.9167 [0.7415, 0.9768] (22/24) | 0.8333 [0.6415, 0.9332] (20/24) | - | 1.0 [0.8569, 1.0] (23/23) | 0.9583 [0.7976, 0.9926] (23/24) | 1.0 [0.862, 1.0] (24/24) |
| judged.T3 | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | - | 1.0 [0.8569, 1.0] (23/23) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) |
| judged.T4 | 0.9167 [0.7415, 0.9768] (22/24) | 0.9583 [0.7976, 0.9926] (23/24) | 0.7917 [0.5953, 0.9076] (19/24) | - | 0.7826 [0.581, 0.9034] (18/23) | 0.7917 [0.5953, 0.9076] (19/24) | 0.7917 [0.5953, 0.9076] (19/24) |
| judged.T5 | 0.9167 [0.7415, 0.9768] (22/24) | 1.0 [0.862, 1.0] (24/24) | 1.0 [0.862, 1.0] (24/24) | - | 1.0 [0.8569, 1.0] (23/23) | 1.0 [0.862, 1.0] (24/24) | 0.875 [0.69, 0.9566] (21/24) |
| judged.T6 | 1.0 [0.862, 1.0] (24/24) | 0.8333 [0.6415, 0.9332] (20/24) | 0.8333 [0.6415, 0.9332] (20/24) | - | 1.0 [0.8569, 1.0] (23/23) | 0.9167 [0.7415, 0.9768] (22/24) | 0.9583 [0.7976, 0.9926] (23/24) |
| judged_all_pass.judged | 0.8333 [0.6415, 0.9332] (20/24) | 0.75 [0.551, 0.88] (18/24) | 0.625 [0.4271, 0.7884] (15/24) | - | 0.4783 [0.2924, 0.6704] (11/23) | 0.7083 [0.5083, 0.8509] (17/24) | 0.7083 [0.5083, 0.8509] (17/24) |
| judged_all_pass.all | 0.8333 [0.6415, 0.9332] (20/24) | 0.75 [0.551, 0.88] (18/24) | 0.625 [0.4271, 0.7884] (15/24) | 0.0 [0.0, 0.138] (0/24) | 0.4583 [0.2789, 0.6493] (11/24) | 0.7083 [0.5083, 0.8509] (17/24) | 0.7083 [0.5083, 0.8509] (17/24) |
| judged_all_pass.over_rows_run | 0.8333 [0.6415, 0.9332] (20/24) | 0.75 [0.551, 0.88] (18/24) | 0.625 [0.4271, 0.7884] (15/24) | 0.0 [0.0, 0.7935] (0/1) | 0.4783 [0.2924, 0.6704] (11/23) | 0.7083 [0.5083, 0.8509] (17/24) | 0.7083 [0.5083, 0.8509] (17/24) |
| useful | 0.8333 [0.6415, 0.9332] (20/24) | 0.6667 [0.4671, 0.8203] (16/24) | 0.5417 [0.3507, 0.7211] (13/24) | 0.0 [0.0, 0.138] (0/24) | 0.4583 [0.2789, 0.6493] (11/24) | 0.3333 [0.1797, 0.5329] (8/24) | 0.4583 [0.2789, 0.6493] (11/24) |
| useful_over_rows_run | 0.8333 [0.6415, 0.9332] (20/24) | 0.6667 [0.4671, 0.8203] (16/24) | 0.5417 [0.3507, 0.7211] (13/24) | 0.0 [0.0, 0.7935] (0/1) | 0.4783 [0.2924, 0.6704] (11/23) | 0.3333 [0.1797, 0.5329] (8/24) | 0.4583 [0.2789, 0.6493] (11/24) |
| failed_attempts | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| missing_echoes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| D3_slots_stated | - | - | - | - | - | - | - |
| D5_relay_expected | 0.9167 [0.6461, 0.9851] (11/12) | 1.0 [0.7575, 1.0] (12/12) | 1.0 [0.7575, 1.0] (12/12) | - | 0.5833 [0.3195, 0.8067] (7/12) | 1.0 [0.7575, 1.0] (12/12) | 1.0 [0.7575, 1.0] (12/12) |
| hold_agreement | - | - | - | - | - | - | - |
| wrong_lane_directives | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sentences_mean | 1.6667 | 1.625 | 1.8333 | - | 0.8696 | 1.6667 | 1.5417 |
| spoken_words_mean | 26.9167 | 36.5833 | 33.375 | - | 15.3913 | 36.3333 | 32.5 |
| finish_reason | {"stop": 24} | {"stop": 24} | {"stop": 24} | {} | {"stop": 11, "None": 12} | {"stop": 24} | {"stop": 24} |
| length_stops | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| length_empty_speech | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| reasoning_tokens.p50 | 0 | 49 | 0 | - | 0 | 0 | 0 |
| reasoning_tokens.p95 | 0 | 113 | 0 | - | 811 | 32 | 0 |
| reasoning_tokens.n | 24 | 24 | 24 | 0 | 23 | 24 | 24 |
| reasoning_tokens.unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| qwen_tokens.p50 | 48 | 61 | 58 | - | 0 | 63 | 57 |
| qwen_tokens.p95 | 80 | 105 | 119 | - | 89 | 144 | 107 |
| qwen_tokens.n | 24 | 24 | 24 | 0 | 23 | 24 | 24 |
| qwen_tokens.max | 107 | 115 | 129 | - | 96 | 150 | 123 |
| ttft_ms.p50 | 637 | 1868 | 1409 | - | 3756 | 2844 | 3169 |
| ttft_ms.p95 | 796 | 2738 | 2232 | - | 8541 | 73465 | 4950 |
| ttft_ms.n | 24 | 24 | 24 | 0 | 11 | 24 | 24 |
| latency_ms.p50 | 1026 | 2253 | 1921 | - | 4504 | 4105 | 4087 |
| latency_ms.p95 | 1363 | 3620 | 2822 | - | 11595 | 74739 | 6534 |
| latency_ms.n | 24 | 24 | 24 | 0 | 23 | 24 | 24 |
| usage_unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| prompt_tokens | 18934 | 19908 | 19308 | - | 10233 | 19125 | 19125 |
| completion_tokens | 1226 | 2987 | 1561 | - | 5860 | 1896 | 1454 |

## lane: cp

| metric | reference | teamrouter:deepseek-flash@medium | teamrouter:deepseek-flash@none | teamrouter:gemini-3.8-flash@medium | teamrouter:gemini-3.8-flash@none | teamrouter:glm-5.3-flash@medium | teamrouter:glm-5.3-flash@none |
|---|---|---|---|---|---|---|---|
| views | 103 | 103 | 103 | 103 | 103 | 103 | 103 |
| n | 103 | 103 | 103 | 0 | 95 | 103 | 103 |
| not_run | 0 | 0 | 0 | 103 | 8 | 0 | 0 |
| errors | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| D1.answered | 0.8544 [0.7735, 0.9097] (88/103) | 0.9417 [0.8787, 0.973] (97/103) | 0.8932 [0.8188, 0.9393] (92/103) | - | 0.3511 [0.2622, 0.4517] (33/94) | 0.7573 [0.6662, 0.8298] (78/103) | 0.835 [0.7515, 0.8943] (86/103) |
| D1.all | 0.8544 [0.7735, 0.9097] (88/103) | 0.9417 [0.8787, 0.973] (97/103) | 0.8932 [0.8188, 0.9393] (92/103) | 0.0 [0.0, 0.036] (0/103) | 0.3204 [0.2381, 0.4156] (33/103) | 0.7573 [0.6662, 0.8298] (78/103) | 0.835 [0.7515, 0.8943] (86/103) |
| D1.over_rows_run | 0.8544 [0.7735, 0.9097] (88/103) | 0.9417 [0.8787, 0.973] (97/103) | 0.8932 [0.8188, 0.9393] (92/103) | - | 0.3474 [0.2592, 0.4474] (33/95) | 0.7573 [0.6662, 0.8298] (78/103) | 0.835 [0.7515, 0.8943] (86/103) |
| D2.answered | 0.9223 [0.8542, 0.9601] (95/103) | 0.9515 [0.8914, 0.9791] (98/103) | 1.0 [0.964, 1] (103/103) | - | 0.9149 [0.841, 0.9562] (86/94) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D2.all | 0.9223 [0.8542, 0.9601] (95/103) | 0.9515 [0.8914, 0.9791] (98/103) | 1.0 [0.964, 1] (103/103) | 0.0 [0.0, 0.036] (0/103) | 0.835 [0.7515, 0.8943] (86/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D2.over_rows_run | 0.9223 [0.8542, 0.9601] (95/103) | 0.9515 [0.8914, 0.9791] (98/103) | 1.0 [0.964, 1] (103/103) | - | 0.9053 [0.8297, 0.9494] (86/95) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D4.answered | 1.0 [0.964, 1] (103/103) | 0.9806 [0.9319, 0.9947] (101/103) | 1.0 [0.964, 1] (103/103) | - | 1.0 [0.9607, 1.0] (94/94) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D4.all | 1.0 [0.964, 1] (103/103) | 0.9806 [0.9319, 0.9947] (101/103) | 1.0 [0.964, 1] (103/103) | 0.0 [0.0, 0.036] (0/103) | 0.9126 [0.8422, 0.9533] (94/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D4.over_rows_run | 1.0 [0.964, 1] (103/103) | 0.9806 [0.9319, 0.9947] (101/103) | 1.0 [0.964, 1] (103/103) | - | 0.9895 [0.9428, 0.9981] (94/95) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D6.answered | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | - | 1.0 [0.9607, 1.0] (94/94) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D6.all | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 0.0 [0.0, 0.036] (0/103) | 0.9126 [0.8422, 0.9533] (94/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D6.over_rows_run | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | - | 0.9895 [0.9428, 0.9981] (94/95) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D7.answered | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | - | 1.0 [0.9607, 1.0] (94/94) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D7.all | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 0.0 [0.0, 0.036] (0/103) | 0.9126 [0.8422, 0.9533] (94/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| D7.over_rows_run | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | - | 0.9895 [0.9428, 0.9981] (94/95) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| judged.T1 | 0.9806 [0.9319, 0.9947] (101/103) | 0.8932 [0.8188, 0.9393] (92/103) | 0.9029 [0.8304, 0.9464] (93/103) | - | 0.3617 [0.2718, 0.4625] (34/94) | 0.9612 [0.9044, 0.9848] (99/103) | 0.835 [0.7515, 0.8943] (86/103) |
| judged.T2 | 1.0 [0.964, 1] (103/103) | 0.9806 [0.9319, 0.9947] (101/103) | 0.9806 [0.9319, 0.9947] (101/103) | - | 1.0 [0.9607, 1.0] (94/94) | 0.9612 [0.9044, 0.9848] (99/103) | 0.9709 [0.9178, 0.99] (100/103) |
| judged.T3 | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) | - | 1.0 [0.9607, 1.0] (94/94) | 1.0 [0.964, 1] (103/103) | 1.0 [0.964, 1] (103/103) |
| judged.T4 | 0.8058 [0.719, 0.8706] (83/103) | 0.6505 [0.5545, 0.7356] (67/103) | 0.5728 [0.4764, 0.664] (59/103) | - | 0.7553 [0.6595, 0.8311] (71/94) | 0.835 [0.7515, 0.8943] (86/103) | 0.835 [0.7515, 0.8943] (86/103) |
| judged.T5 | 0.7087 [0.6148, 0.7877] (73/103) | 0.9806 [0.9319, 0.9947] (101/103) | 1.0 [0.964, 1] (103/103) | - | 1.0 [0.9607, 1.0] (94/94) | 0.9709 [0.9178, 0.99] (100/103) | 0.9515 [0.8914, 0.9791] (98/103) |
| judged.T6 | 0.8544 [0.7735, 0.9097] (88/103) | 0.9612 [0.9044, 0.9848] (99/103) | 0.932 [0.8663, 0.9667] (96/103) | - | 0.9787 [0.9257, 0.9941] (92/94) | 0.9612 [0.9044, 0.9848] (99/103) | 0.9223 [0.8542, 0.9601] (95/103) |
| judged_all_pass.judged | 0.4757 [0.3819, 0.5713] (49/103) | 0.5728 [0.4764, 0.664] (59/103) | 0.4854 [0.3912, 0.5807] (50/103) | - | 0.3298 [0.2431, 0.4299] (31/94) | 0.7184 [0.6249, 0.7962] (74/103) | 0.6214 [0.5249, 0.7091] (64/103) |
| judged_all_pass.all | 0.4757 [0.3819, 0.5713] (49/103) | 0.5728 [0.4764, 0.664] (59/103) | 0.4854 [0.3912, 0.5807] (50/103) | 0.0 [0.0, 0.036] (0/103) | 0.301 [0.2209, 0.3954] (31/103) | 0.7184 [0.6249, 0.7962] (74/103) | 0.6214 [0.5249, 0.7091] (64/103) |
| judged_all_pass.over_rows_run | 0.4757 [0.3819, 0.5713] (49/103) | 0.5728 [0.4764, 0.664] (59/103) | 0.4854 [0.3912, 0.5807] (50/103) | - | 0.3263 [0.2404, 0.4257] (31/95) | 0.7184 [0.6249, 0.7962] (74/103) | 0.6214 [0.5249, 0.7091] (64/103) |
| useful | 0.4757 [0.3819, 0.5713] (49/103) | 0.5437 [0.4477, 0.6366] (56/103) | 0.4369 [0.3451, 0.5332] (45/103) | 0.0 [0.0, 0.036] (0/103) | 0.2913 [0.2123, 0.3852] (30/103) | 0.5922 [0.4957, 0.6822] (61/103) | 0.5534 [0.4572, 0.6458] (57/103) |
| useful_over_rows_run | 0.4757 [0.3819, 0.5713] (49/103) | 0.5437 [0.4477, 0.6366] (56/103) | 0.4369 [0.3451, 0.5332] (45/103) | - | 0.3158 [0.231, 0.4149] (30/95) | 0.5922 [0.4957, 0.6822] (61/103) | 0.5534 [0.4572, 0.6458] (57/103) |
| failed_attempts | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| missing_echoes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| D3_slots_stated | 0.1224 [0.0573, 0.2424] (6/49) | 0.1633 [0.0851, 0.2904] (8/49) | 0.102 [0.0444, 0.2176] (5/49) | - | 0.0 [0.0, 0.0727] (0/49) | 0.1633 [0.0851, 0.2904] (8/49) | 0.2245 [0.1302, 0.3588] (11/49) |
| D5_relay_expected | 0.4242 [0.2724, 0.5919] (14/33) | 0.6667 [0.4961, 0.8025] (22/33) | 0.7576 [0.5898, 0.8717] (25/33) | - | 0.0714 [0.0198, 0.2265] (2/28) | 0.7273 [0.5578, 0.8493] (24/33) | 0.6061 [0.4368, 0.7532] (20/33) |
| hold_agreement | - | 0.6602 [0.5644, 0.7444] (68/103) | 0.5631 [0.4668, 0.6549] (58/103) | - | 0.7447 [0.6481, 0.822] (70/94) | 0.767 [0.6767, 0.8381] (79/103) | 0.767 [0.6767, 0.8381] (79/103) |
| wrong_lane_directives | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sentences_mean | 1.9903 | 1.7961 | 1.8447 | - | 0.5426 | 1.8835 | 1.835 |
| spoken_words_mean | 25.3689 | 26.7573 | 23.6796 | - | 6.9574 | 27.8932 | 24.1845 |
| finish_reason | {"stop": 103} | {"stop": 103} | {"stop": 103} | {} | {"None": 60, "stop": 34} | {"stop": 103} | {"stop": 103} |
| length_stops | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| length_empty_speech | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| reasoning_tokens.p50 | 0 | 118 | 0 | - | 0 | 23 | 0 |
| reasoning_tokens.p95 | 0 | 288 | 0 | - | 1065 | 81 | 0 |
| reasoning_tokens.n | 103 | 103 | 103 | 0 | 94 | 103 | 103 |
| reasoning_tokens.unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| qwen_tokens.p50 | 33 | 55 | 54 | - | 0 | 52 | 39 |
| qwen_tokens.p95 | 91 | 96 | 81 | - | 39 | 93 | 78 |
| qwen_tokens.n | 103 | 103 | 103 | 0 | 94 | 103 | 103 |
| qwen_tokens.max | 143 | 127 | 90 | - | 74 | 107 | 96 |
| ttft_ms.p50 | 569 | 2772 | 1555 | - | 3880 | 4442 | 3283 |
| ttft_ms.p95 | 849 | 4680 | 2126 | - | 11206 | 7558 | 5125 |
| ttft_ms.n | 103 | 103 | 103 | 0 | 34 | 103 | 103 |
| latency_ms.p50 | 896 | 3232 | 1970 | - | 4022 | 5781 | 4256 |
| latency_ms.p95 | 1445 | 5002 | 2757 | - | 13882 | 8795 | 6207 |
| latency_ms.n | 103 | 103 | 103 | 0 | 94 | 103 | 103 |
| usage_unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| prompt_tokens | 106597 | 112094 | 109519 | - | 52520 | 105027 | 105027 |
| completion_tokens | 4693 | 19887 | 5165 | - | 16667 | 8573 | 4525 |

## paired useful: difference, 95 % CI (no decision rule)

| metric | all | user | cp |
|---|---|---|---|
| teamrouter:deepseek-flash@medium - teamrouter:deepseek-flash@none | 0.1102 [0.0169, 0.1938] (5 clusters) | 0.125 [0.0, 0.25] (5 clusters) | 0.1068 [0.0097, 0.2045] (5 clusters) |
| teamrouter:deepseek-flash@medium - teamrouter:gemini-3.8-flash@medium | 0.5669 [0.3707, 0.7083] (5 clusters) | 0.6667 [0.5, 0.7857] (5 clusters) | 0.5437 [0.3226, 0.6937] (5 clusters) |
| teamrouter:deepseek-flash@medium - teamrouter:glm-5.3-flash@medium | 0.0236 [-0.1284, 0.1241] (5 clusters) | 0.3333 [0.15, 0.4615] (5 clusters) | -0.0485 [-0.191, 0.0465] (5 clusters) |
| teamrouter:deepseek-flash@none - teamrouter:gemini-3.8-flash@none | 0.1339 [-0.045, 0.2903] (5 clusters) | 0.0833 [0.0, 0.1818] (5 clusters) | 0.1456 [-0.0674, 0.3235] (5 clusters) |
| teamrouter:deepseek-flash@none - teamrouter:glm-5.3-flash@none | -0.0787 [-0.115, -0.0345] (5 clusters) | 0.0833 [0.0, 0.1786] (5 clusters) | -0.1165 [-0.1518, -0.0588] (5 clusters) |
| teamrouter:gemini-3.8-flash@medium - teamrouter:gemini-3.8-flash@none | -0.3228 [-0.3894, -0.2097] (5 clusters) | -0.4583 [-0.5, -0.3636] (5 clusters) | -0.2913 [-0.3636, -0.1717] (5 clusters) |
| teamrouter:gemini-3.8-flash@medium - teamrouter:glm-5.3-flash@medium | -0.5433 [-0.6233, -0.4352] (5 clusters) | -0.3333 [-0.4615, -0.1667] (5 clusters) | -0.5922 [-0.6814, -0.4886] (5 clusters) |
| teamrouter:gemini-3.8-flash@none - teamrouter:glm-5.3-flash@none | -0.2126 [-0.3357, -0.0541] (5 clusters) | 0.0 [-0.1667, 0.1667] (5 clusters) | -0.2621 [-0.4017, -0.0787] (5 clusters) |
| teamrouter:glm-5.3-flash@medium - teamrouter:glm-5.3-flash@none | 0.0079 [-0.0441, 0.0776] (5 clusters) | -0.125 [-0.2273, -0.0385] (5 clusters) | 0.0388 [-0.0315, 0.117] (5 clusters) |
| teamrouter:deepseek-flash@medium - reference | 0.0236 [-0.2661, 0.2117] (5 clusters) | -0.1667 [-0.35, -0.0357] (5 clusters) | 0.068 [-0.236, 0.2793] (5 clusters) |
| teamrouter:deepseek-flash@none - reference | -0.0866 [-0.3028, 0.0376] (5 clusters) | -0.2917 [-0.4, -0.2083] (5 clusters) | -0.0388 [-0.2857, 0.1101] (5 clusters) |
| teamrouter:gemini-3.8-flash@medium - reference | -0.5433 [-0.6466, -0.4344] (5 clusters) | -0.8333 [-0.9091, -0.7727] (5 clusters) | -0.4757 [-0.5865, -0.3469] (5 clusters) |
| teamrouter:gemini-3.8-flash@none - reference | -0.2205 [-0.3482, -0.094] (5 clusters) | -0.375 [-0.4545, -0.3077] (5 clusters) | -0.1845 [-0.3261, -0.0421] (5 clusters) |
| teamrouter:glm-5.3-flash@medium - reference | 0.0 [-0.1293, 0.0876] (5 clusters) | -0.5 [-0.6364, -0.3929] (5 clusters) | 0.1165 [-0.0449, 0.2342] (5 clusters) |
| teamrouter:glm-5.3-flash@none - reference | -0.0079 [-0.2069, 0.1095] (5 clusters) | -0.375 [-0.5, -0.2308] (5 clusters) | 0.0777 [-0.1573, 0.2342] (5 clusters) |

## paired judged_all_pass: difference, 95 % CI (no decision rule)

| metric | all | user | cp |
|---|---|---|---|
| teamrouter:deepseek-flash@medium - teamrouter:deepseek-flash@none | 0.0945 [0.0182, 0.1528] (5 clusters) | 0.125 [0.0, 0.25] (5 clusters) | 0.0874 [0.0222, 0.1456] (5 clusters) |
| teamrouter:deepseek-flash@medium - teamrouter:gemini-3.8-flash@medium | 0.6063 [0.3966, 0.7431] (5 clusters) | 0.75 [0.55, 0.8929] (5 clusters) | 0.5728 [0.3511, 0.7087] (5 clusters) |
| teamrouter:deepseek-flash@medium - teamrouter:glm-5.3-flash@medium | -0.1102 [-0.2936, 0.0219] (5 clusters) | 0.0417 [-0.2727, 0.2692] (5 clusters) | -0.1456 [-0.2967, -0.0275] (5 clusters) |
| teamrouter:deepseek-flash@none - teamrouter:gemini-3.8-flash@none | 0.1811 [0.0078, 0.3276] (5 clusters) | 0.1667 [0.0909, 0.2273] (5 clusters) | 0.1845 [-0.0101, 0.3511] (5 clusters) |
| teamrouter:deepseek-flash@none - teamrouter:glm-5.3-flash@none | -0.126 [-0.2101, -0.0385] (5 clusters) | -0.0833 [-0.1818, 0.0] (5 clusters) | -0.1359 [-0.23, -0.0326] (5 clusters) |
| teamrouter:gemini-3.8-flash@medium - teamrouter:gemini-3.8-flash@none | -0.3307 [-0.3972, -0.2114] (5 clusters) | -0.4583 [-0.5, -0.3636] (5 clusters) | -0.301 [-0.3739, -0.1717] (5 clusters) |
| teamrouter:gemini-3.8-flash@medium - teamrouter:glm-5.3-flash@medium | -0.7165 [-0.7755, -0.6355] (5 clusters) | -0.7083 [-0.8636, -0.5909] (5 clusters) | -0.7184 [-0.7983, -0.6092] (5 clusters) |
| teamrouter:gemini-3.8-flash@none - teamrouter:glm-5.3-flash@none | -0.3071 [-0.437, -0.1322] (5 clusters) | -0.25 [-0.375, -0.125] (5 clusters) | -0.3204 [-0.4587, -0.1348] (5 clusters) |
| teamrouter:glm-5.3-flash@medium - teamrouter:glm-5.3-flash@none | 0.0787 [0.0194, 0.181] (5 clusters) | 0.0 [-0.1667, 0.25] (5 clusters) | 0.0971 [0.0323, 0.1702] (5 clusters) |
| teamrouter:deepseek-flash@medium - reference | 0.063 [-0.2385, 0.2482] (5 clusters) | -0.0833 [-0.3182, 0.0769] (5 clusters) | 0.0971 [-0.2135, 0.2955] (5 clusters) |
| teamrouter:deepseek-flash@none - reference | -0.0315 [-0.2569, 0.131] (5 clusters) | -0.2083 [-0.3636, -0.0909] (5 clusters) | 0.0097 [-0.2418, 0.1849] (5 clusters) |
| teamrouter:gemini-3.8-flash@medium - reference | -0.5433 [-0.6466, -0.4344] (5 clusters) | -0.8333 [-0.9091, -0.7727] (5 clusters) | -0.4757 [-0.5865, -0.3469] (5 clusters) |
| teamrouter:gemini-3.8-flash@none - reference | -0.2126 [-0.3413, -0.0855] (5 clusters) | -0.375 [-0.4545, -0.3077] (5 clusters) | -0.1748 [-0.3173, -0.0316] (5 clusters) |
| teamrouter:glm-5.3-flash@medium - reference | 0.1732 [0.066, 0.2419] (5 clusters) | -0.125 [-0.1923, -0.0455] (5 clusters) | 0.2427 [0.0957, 0.3495] (5 clusters) |
| teamrouter:glm-5.3-flash@none - reference | 0.0945 [-0.1121, 0.2093] (5 clusters) | -0.125 [-0.3, 0.0] (5 clusters) | 0.1456 [-0.0745, 0.2759] (5 clusters) |

## D6 lexical hits

- none
