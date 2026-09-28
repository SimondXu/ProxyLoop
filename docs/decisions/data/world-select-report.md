# World-model selection report (S1-MOD-09, ADR-0024)

Internal instrument choice, not a claim; the user decides (ADR-0024).

- git_sha: 33ef3a6974b86306c3a09658737cf05c77dd7523
- git_dirty: False
- items_root_hash: 471a0a9151af0c85204b6d49d2977fc14fae50fdfcd77cc2c2401246d61a41cc
- codebook_sha256: 892c8f686dfcb27d6a4c81a0f672c44226e2e306f625cf895da427534b4b7a38
- gold_sha256: aec2f545fc4dbbb013ab4f09c2dc25f9a21cc75fe2923a9644eeda75a77e32e1
- incumbent: teamrouter:gemini-3.8-flash@low
- primary: Ear cc_accuracy

## ear: recorded

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| cc_accuracy | 0.875 [0.8415, 0.9023] (399/456) | 0.8662 [0.8319, 0.8944] (395/456) | 0.7895 [0.7497, 0.8244] (360/456) |
| arguments.facts | 1.0 [0.9434, 1.0] (64/64) | 1.0 [0.948, 1.0] (70/70) | 1.0 [0.8865, 1.0] (30/30) |
| arguments.offer_ref | 1.0 [0.9572, 1.0] (86/86) | 0.9828 [0.9086, 0.9969] (57/58) | 0.977 [0.92, 0.9937] (85/87) |
| arguments.price_usd | - | - | - |
| block_size_first_attempt | 0.8857 [0.7405, 0.9546] (31/35) | 0.7714 [0.6098, 0.8793] (27/35) | 1.0 [0.9011, 1.0] (35/35) |
| exact_accuracy | 0.8333 [0.7964, 0.8647] (380/456) | 0.8311 [0.794, 0.8627] (379/456) | 0.7193 [0.6764, 0.7586] (328/456) |
| excluded | 0 | 0 | 0 |
| exhausted | 9 | 5 | 40 |
| first_attempt_valid | 0.893 [0.859, 0.9196] (359/402) | 0.7935 [0.7513, 0.8302] (319/402) | 0.8358 [0.7965, 0.8688] (336/402) |
| harm.accept.fn | 0 | 0 | 0 |
| harm.accept.fp | 0 | 0 | 0 |
| harm.cancel_intent.fn | 0 | 0 | 0 |
| harm.cancel_intent.fp | 0 | 0 | 0 |
| harm.cite_competitor.fn | 0 | 0 | 0 |
| harm.cite_competitor.fp | 0 | 0 | 0 |
| items | 402 | 402 | 402 |
| per_class.accept.precision | - | - | - |
| per_class.accept.recall | - | - | - |
| per_class.ask_discount.precision | 0.8415 [0.7474, 0.9049] (69/82) | 0.8387 [0.7508, 0.8997] (78/93) | 0.66 [0.5628, 0.7454] (66/100) |
| per_class.ask_discount.recall | 0.7841 [0.6872, 0.8572] (69/88) | 0.8864 [0.8033, 0.9371] (78/88) | 0.75 [0.6504, 0.8287] (66/88) |
| per_class.ask_readback.precision | 0.8037 [0.7185, 0.8679] (86/107) | 0.8657 [0.764, 0.9277] (58/67) | 0.8365 [0.7537, 0.8954] (87/104) |
| per_class.ask_readback.recall | 0.9149 [0.841, 0.9562] (86/94) | 0.617 [0.516, 0.7089] (58/94) | 0.9255 [0.8542, 0.9635] (87/94) |
| per_class.ask_supervisor.precision | - | - | - |
| per_class.ask_supervisor.recall | - | - | - |
| per_class.cancel_intent.precision | - | - | - |
| per_class.cancel_intent.recall | - | - | - |
| per_class.cite_competitor.precision | - | - | - |
| per_class.cite_competitor.recall | - | - | - |
| per_class.decline.precision | 0.0 [0.0, 0.7935] (0/1) | 0.0 [0.0, 0.3903] (0/6) | 0.0 [0.0, 0.6576] (0/2) |
| per_class.decline.recall | - | - | - |
| per_class.hold_request.precision | 0.9298 [0.833, 0.9724] (53/57) | 0.9608 [0.8678, 0.9892] (49/51) | 0.9815 [0.9023, 0.9967] (53/54) |
| per_class.hold_request.recall | 0.9815 [0.9023, 0.9967] (53/54) | 0.9074 [0.8009, 0.9598] (49/54) | 0.9815 [0.9023, 0.9967] (53/54) |
| per_class.injection.precision | 0.0 [0.0, 0.5615] (0/3) | 0.0 [0.0, 0.4345] (0/5) | 0.0 [0.0, 0.1936] (0/16) |
| per_class.injection.recall | - | - | - |
| per_class.other.precision | 0.6429 [0.4583, 0.7929] (18/28) | 0.5682 [0.4222, 0.7032] (25/44) | 0.6364 [0.4887, 0.7622] (28/44) |
| per_class.other.recall | 0.4 [0.2702, 0.5455] (18/45) | 0.5556 [0.4118, 0.6906] (25/45) | 0.6222 [0.4763, 0.7489] (28/45) |
| per_class.provide_fact.precision | 1.0 [0.9434, 1.0] (64/64) | 0.9859 [0.9244, 0.9975] (70/71) | 1.0 [0.8865, 1.0] (30/30) |
| per_class.provide_fact.recall | 0.9143 [0.8253, 0.9601] (64/70) | 1.0 [0.948, 1.0] (70/70) | 0.4286 [0.3194, 0.5452] (30/70) |
| per_class.refuse_fact.precision | 0.9747 [0.9123, 0.993] (77/79) | 0.9762 [0.9173, 0.9934] (82/84) | 0.9841 [0.9154, 0.9972] (62/63) |
| per_class.refuse_fact.recall | 0.8851 [0.8012, 0.9364] (77/87) | 0.9425 [0.8724, 0.9752] (82/87) | 0.7126 [0.6102, 0.7971] (62/87) |
| per_class.smalltalk.precision | 0.5909 [0.3873, 0.7674] (13/22) | 0.6296 [0.4423, 0.7847] (17/27) | 1.0 [0.3424, 1.0] (2/2) |
| per_class.smalltalk.recall | 0.7222 [0.4913, 0.875] (13/18) | 0.9444 [0.7424, 0.9901] (17/18) | 0.1111 [0.031, 0.328] (2/18) |
| per_class.tenure.precision | - | - | - |
| per_class.tenure.recall | - | - | - |
| stability | 0.8438 [0.6825, 0.9314] (27/32) | 0.9062 [0.7578, 0.9676] (29/32) | 0.9062 [0.7578, 0.9676] (29/32) |
| timeout | 0 | 2 | 0 |
| utterances | 456 | 456 | 456 |
| weighted.cc_accuracy | 0.9077 | 0.903 | 0.8451 |
| weighted.exact | 0.8106 | 0.8153 | 0.6745 |

## ear: constructed

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| cc_accuracy | 0.9214 [0.8648, 0.9556] (129/140) | 0.9286 [0.8735, 0.9607] (130/140) | 0.8429 [0.7735, 0.8939] (118/140) |
| arguments.facts | 1.0 [0.8454, 1.0] (21/21) | 1.0 [0.8454, 1.0] (21/21) | 1.0 [0.8389, 1.0] (20/20) |
| arguments.offer_ref | 1.0 [0.7719, 1.0] (13/13) | 1.0 [0.7719, 1.0] (13/13) | 1.0 [0.7225, 1.0] (10/10) |
| arguments.price_usd | 1.0 [0.8897, 1.0] (31/31) | 1.0 [0.8928, 1.0] (32/32) | 1.0 [0.8794, 1.0] (28/28) |
| block_size_first_attempt | 0.8571 [0.4869, 0.9743] (6/7) | 0.8571 [0.4869, 0.9743] (6/7) | 1.0 [0.6457, 1.0] (7/7) |
| exact_accuracy | 0.9143 [0.8562, 0.9503] (128/140) | 0.9214 [0.8648, 0.9556] (129/140) | 0.8286 [0.7576, 0.882] (116/140) |
| excluded | 3 | 3 | 3 |
| exhausted | 4 | 3 | 11 |
| first_attempt_valid | 0.9333 [0.8782, 0.9645] (126/135) | 0.7926 [0.7166, 0.8524] (107/135) | 0.8963 [0.8334, 0.9372] (121/135) |
| harm.accept.fn | 0 | 0 | 4 |
| harm.accept.fp | 2 | 2 | 1 |
| harm.cancel_intent.fn | 1 | 1 | 2 |
| harm.cancel_intent.fp | 1 | 3 | 2 |
| harm.cite_competitor.fn | 1 | 0 | 0 |
| harm.cite_competitor.fp | 1 | 0 | 1 |
| items | 135 | 135 | 135 |
| per_class.accept.precision | 0.8571 [0.6006, 0.9599] (12/14) | 0.8571 [0.6006, 0.9599] (12/14) | 0.8889 [0.565, 0.9801] (8/9) |
| per_class.accept.recall | 1.0 [0.7575, 1.0] (12/12) | 1.0 [0.7575, 1.0] (12/12) | 0.6667 [0.3906, 0.8619] (8/12) |
| per_class.ask_discount.precision | 1.0 [0.7009, 1.0] (9/9) | 1.0 [0.7225, 1.0] (10/10) | 1.0 [0.6097, 1.0] (6/6) |
| per_class.ask_discount.recall | 0.9 [0.5958, 0.9821] (9/10) | 1.0 [0.7225, 1.0] (10/10) | 0.6 [0.3127, 0.8318] (6/10) |
| per_class.ask_readback.precision | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.3424, 1.0] (2/2) |
| per_class.ask_readback.recall | 0.5 [0.0945, 0.9055] (1/2) | 0.5 [0.0945, 0.9055] (1/2) | 1.0 [0.3424, 1.0] (2/2) |
| per_class.ask_supervisor.precision | 0.8947 [0.6861, 0.9706] (17/19) | 0.9444 [0.7424, 0.9901] (17/18) | 0.8947 [0.6861, 0.9706] (17/19) |
| per_class.ask_supervisor.recall | 0.9444 [0.7424, 0.9901] (17/18) | 0.9444 [0.7424, 0.9901] (17/18) | 0.9444 [0.7424, 0.9901] (17/18) |
| per_class.cancel_intent.precision | 0.9444 [0.7424, 0.9901] (17/18) | 0.85 [0.6396, 0.9476] (17/20) | 0.8889 [0.672, 0.969] (16/18) |
| per_class.cancel_intent.recall | 0.9444 [0.7424, 0.9901] (17/18) | 0.9444 [0.7424, 0.9901] (17/18) | 0.8889 [0.672, 0.969] (16/18) |
| per_class.cite_competitor.precision | 0.95 [0.7639, 0.9911] (19/20) | 1.0 [0.8389, 1.0] (20/20) | 0.9524 [0.7733, 0.9915] (20/21) |
| per_class.cite_competitor.recall | 0.95 [0.7639, 0.9911] (19/20) | 1.0 [0.8389, 1.0] (20/20) | 1.0 [0.8389, 1.0] (20/20) |
| per_class.decline.precision | 1.0 [0.4385, 1.0] (3/3) | 1.0 [0.4385, 1.0] (3/3) | 0.5 [0.15, 0.85] (2/4) |
| per_class.decline.recall | 1.0 [0.4385, 1.0] (3/3) | 1.0 [0.4385, 1.0] (3/3) | 0.6667 [0.2077, 0.9385] (2/3) |
| per_class.hold_request.precision | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.3424, 1.0] (2/2) | - |
| per_class.hold_request.recall | 0.5 [0.0945, 0.9055] (1/2) | 1.0 [0.3424, 1.0] (2/2) | 0.0 [0.0, 0.6576] (0/2) |
| per_class.injection.precision | - | - | 0.0 [0.0, 0.5615] (0/3) |
| per_class.injection.recall | - | - | - |
| per_class.other.precision | 0.8571 [0.4869, 0.9743] (6/7) | 0.8333 [0.4365, 0.9699] (5/6) | 0.8571 [0.4869, 0.9743] (6/7) |
| per_class.other.recall | 0.5455 [0.2801, 0.7873] (6/11) | 0.4545 [0.2127, 0.7199] (5/11) | 0.5455 [0.2801, 0.7873] (6/11) |
| per_class.provide_fact.precision | 1.0 [0.8454, 1.0] (21/21) | 0.913 [0.732, 0.9758] (21/23) | 1.0 [0.8389, 1.0] (20/20) |
| per_class.provide_fact.recall | 1.0 [0.8454, 1.0] (21/21) | 1.0 [0.8454, 1.0] (21/21) | 0.9524 [0.7733, 0.9915] (20/21) |
| per_class.refuse_fact.precision | 0.5 [0.15, 0.85] (2/4) | 0.6667 [0.2077, 0.9385] (2/3) | 0.5 [0.15, 0.85] (2/4) |
| per_class.refuse_fact.recall | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) |
| per_class.smalltalk.precision | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) | - |
| per_class.smalltalk.recall | 0.6667 [0.2077, 0.9385] (2/3) | 0.6667 [0.2077, 0.9385] (2/3) | 0.0 [0.0, 0.5615] (0/3) |
| per_class.tenure.precision | 0.9474 [0.7536, 0.9906] (18/19) | 0.9444 [0.7424, 0.9901] (17/18) | 0.8947 [0.6861, 0.9706] (17/19) |
| per_class.tenure.recall | 1.0 [0.8241, 1.0] (18/18) | 0.9444 [0.7424, 0.9901] (17/18) | 0.9444 [0.7424, 0.9901] (17/18) |
| stability | 0.8 [0.4902, 0.9433] (8/10) | 0.8 [0.4902, 0.9433] (8/10) | 0.8 [0.4902, 0.9433] (8/10) |
| timeout | 0 | 0 | 0 |
| utterances | 140 | 140 | 140 |
| weighted.cc_accuracy | 0.9214 | 0.9286 | 0.8429 |
| weighted.exact | 0.9143 | 0.9214 | 0.8286 |

## ear: off_distribution

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| cc_accuracy | 0.8889 [0.7469, 0.9559] (32/36) | 0.9722 [0.8583, 0.9951] (35/36) | 0.5278 [0.3701, 0.6801] (19/36) |
| arguments.facts | - | - | - |
| arguments.offer_ref | 1.0 [0.8389, 1.0] (20/20) | 1.0 [0.8389, 1.0] (20/20) | 1.0 [0.7412, 1.0] (11/11) |
| arguments.price_usd | 1.0 [0.7719, 1.0] (13/13) | 1.0 [0.7719, 1.0] (13/13) | 1.0 [0.6097, 1.0] (6/6) |
| block_size_first_attempt | 1.0 [0.6097, 1.0] (6/6) | 1.0 [0.6097, 1.0] (6/6) | 1.0 [0.6097, 1.0] (6/6) |
| exact_accuracy | 0.8889 [0.7469, 0.9559] (32/36) | 0.9722 [0.8583, 0.9951] (35/36) | 0.5 [0.3447, 0.6553] (18/36) |
| excluded | 0 | 0 | 0 |
| exhausted | 0 | 0 | 8 |
| first_attempt_valid | 0.931 [0.7804, 0.9809] (27/29) | 0.8621 [0.6944, 0.945] (25/29) | 0.6552 [0.4735, 0.8006] (19/29) |
| harm.accept.fn | 0 | 0 | 7 |
| harm.accept.fp | 0 | 0 | 0 |
| harm.cancel_intent.fn | 0 | 0 | 0 |
| harm.cancel_intent.fp | 0 | 0 | 0 |
| harm.cite_competitor.fn | 0 | 0 | 0 |
| harm.cite_competitor.fp | 1 | 0 | 2 |
| items | 29 | 29 | 29 |
| per_class.accept.precision | 1.0 [0.7719, 1.0] (13/13) | 1.0 [0.7719, 1.0] (13/13) | 1.0 [0.6097, 1.0] (6/6) |
| per_class.accept.recall | 1.0 [0.7719, 1.0] (13/13) | 1.0 [0.7719, 1.0] (13/13) | 0.4615 [0.2321, 0.7086] (6/13) |
| per_class.ask_discount.precision | 0.6667 [0.2077, 0.9385] (2/3) | 0.75 [0.3006, 0.9544] (3/4) | 1.0 [0.3424, 1.0] (2/2) |
| per_class.ask_discount.recall | 0.6667 [0.2077, 0.9385] (2/3) | 1.0 [0.4385, 1.0] (3/3) | 0.6667 [0.2077, 0.9385] (2/3) |
| per_class.ask_readback.precision | 0.875 [0.5291, 0.9776] (7/8) | 1.0 [0.6457, 1.0] (7/7) | 0.625 [0.3057, 0.8632] (5/8) |
| per_class.ask_readback.recall | 1.0 [0.6457, 1.0] (7/7) | 1.0 [0.6457, 1.0] (7/7) | 0.7143 [0.3589, 0.9178] (5/7) |
| per_class.ask_supervisor.precision | 0.0 [0.0, 0.7935] (0/1) | - | 0.0 [0.0, 0.6576] (0/2) |
| per_class.ask_supervisor.recall | - | - | - |
| per_class.cancel_intent.precision | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.2065, 1.0] (1/1) |
| per_class.cancel_intent.recall | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.2065, 1.0] (1/1) |
| per_class.cite_competitor.precision | 0.0 [0.0, 0.7935] (0/1) | - | 0.0 [0.0, 0.6576] (0/2) |
| per_class.cite_competitor.recall | - | - | - |
| per_class.decline.precision | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.2065, 1.0] (1/1) |
| per_class.decline.recall | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) | 0.5 [0.0945, 0.9055] (1/2) |
| per_class.hold_request.precision | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) |
| per_class.hold_request.recall | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) |
| per_class.injection.precision | - | - | 0.0 [0.0, 0.7935] (0/1) |
| per_class.injection.recall | - | - | - |
| per_class.other.precision | 1.0 [0.5655, 1.0] (5/5) | 1.0 [0.6457, 1.0] (7/7) | 1.0 [0.2065, 1.0] (1/1) |
| per_class.other.recall | 0.625 [0.3057, 0.8632] (5/8) | 0.875 [0.5291, 0.9776] (7/8) | 0.125 [0.0224, 0.4709] (1/8) |
| per_class.provide_fact.precision | - | - | - |
| per_class.provide_fact.recall | - | - | - |
| per_class.refuse_fact.precision | - | - | - |
| per_class.refuse_fact.recall | - | - | - |
| per_class.smalltalk.precision | - | - | - |
| per_class.smalltalk.recall | - | - | - |
| per_class.tenure.precision | - | - | - |
| per_class.tenure.recall | - | - | - |
| stability | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) | 0.5 [0.0945, 0.9055] (1/2) |
| timeout | 0 | 0 | 0 |
| utterances | 36 | 36 | 36 |
| weighted.cc_accuracy | 0.8889 | 0.9722 | 0.5278 |
| weighted.exact | 0.8889 | 0.9722 | 0.5 |

## mouth: recorded

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| exhausted | 0 | 0 | 0 |
| fallback | 0.1933 [0.1481, 0.2482] (46/238) | 0.0042 [0.0007, 0.0234] (1/238) | 0.105 [0.0722, 0.1505] (25/238) |
| fidelity_ok | 0.8067 [0.7518, 0.8519] (192/238) | 0.9958 [0.9766, 0.9993] (237/238) | 0.895 [0.8495, 0.9278] (213/238) |
| items | 238 | 238 | 238 |
| judged.M1 | 0.9948 [0.9711, 0.9991] (191/192) | 1.0 [0.984, 1.0] (237/237) | 0.9202 [0.8759, 0.9496] (196/213) |
| judged.M2 | 1.0 [0.9804, 1.0] (192/192) | 0.9747 [0.9459, 0.9883] (231/237) | 0.9953 [0.9739, 0.9992] (212/213) |
| judged.M3 | 1.0 [0.9804, 1.0] (192/192) | 1.0 [0.984, 1.0] (237/237) | 0.9014 [0.854, 0.9346] (192/213) |
| judged.M4 | 1.0 [0.9804, 1.0] (192/192) | 1.0 [0.984, 1.0] (237/237) | 0.9437 [0.9041, 0.9675] (201/213) |
| judged.M5 | 1.0 [0.9804, 1.0] (192/192) | 1.0 [0.984, 1.0] (237/237) | 1.0 [0.9823, 1.0] (213/213) |
| judged.no_violation | 0.9948 [0.9711, 0.9991] (191/192) | 0.9747 [0.9459, 0.9883] (231/237) | 0.831 [0.7749, 0.8753] (177/213) |
| timeout | 0 | 0 | 0 |

## mouth: constructed

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| exhausted | 0 | 0 | 0 |
| fallback | 0.1636 [0.0886, 0.2826] (9/55) | 0.0727 [0.0286, 0.1726] (4/55) | 0.1273 [0.063, 0.2402] (7/55) |
| fidelity_ok | 0.8364 [0.7174, 0.9114] (46/55) | 0.9273 [0.8274, 0.9714] (51/55) | 0.8727 [0.7598, 0.937] (48/55) |
| items | 55 | 55 | 55 |
| judged.M1 | 1.0 [0.9229, 1.0] (46/46) | 1.0 [0.93, 1.0] (51/51) | 1.0 [0.9259, 1.0] (48/48) |
| judged.M2 | 1.0 [0.9229, 1.0] (46/46) | 1.0 [0.93, 1.0] (51/51) | 1.0 [0.9259, 1.0] (48/48) |
| judged.M3 | 0.9783 [0.8866, 0.9962] (45/46) | 1.0 [0.93, 1.0] (51/51) | 1.0 [0.9259, 1.0] (48/48) |
| judged.M4 | 1.0 [0.9229, 1.0] (46/46) | 1.0 [0.93, 1.0] (51/51) | 1.0 [0.9259, 1.0] (48/48) |
| judged.M5 | 1.0 [0.9229, 1.0] (46/46) | 1.0 [0.93, 1.0] (51/51) | 1.0 [0.9259, 1.0] (48/48) |
| judged.no_violation | 0.9783 [0.8866, 0.9962] (45/46) | 1.0 [0.93, 1.0] (51/51) | 1.0 [0.9259, 1.0] (48/48) |
| timeout | 0 | 0 | 0 |

## simuser: recorded

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| exhausted | 1 | 2 | 49 |
| invented_numbers | 0.0 [0.0, 0.0897] (0/39) | 0.0 [0.0, 0.0989] (0/35) | 0.0 [0.0, 0.0857] (0/41) |
| items | 114 | 114 | 114 |
| not_replayable | 0 | 0 | 0 |
| partial_check | 0 | 0 | 0 |
| timeout | 0 | 1 | 0 |
| undeclared_reveals | - | - | - |
| valid_full_check | 0.9912 [0.952, 0.9984] (113/114) | 0.9737 [0.9255, 0.991] (111/114) | 0.5702 [0.4785, 0.6573] (65/114) |

## simuser: constructed

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| exhausted | 0 | 0 | 0 |
| invented_numbers | - | - | - |
| items | 13 | 13 | 13 |
| not_replayable | 13 | 13 | 13 |
| partial_check | 0 | 0 | 0 |
| timeout | 0 | 0 | 0 |
| undeclared_reveals | - | - | - |
| valid_full_check | - | - | - |

## paired: X - incumbent, 95 % CI (no decision rule)

| metric | teamrouter:deepseek-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|
| ear_cc_accuracy.constructed | -0.0071 [-0.0563, 0.0365] (132 clusters) | -0.0857 [-0.1522, -0.0217] (132 clusters) |
| ear_cc_accuracy.off_distribution | -0.0833 [-0.1842, 0.0] (29 clusters) | -0.4444 [-0.6316, -0.2571] (29 clusters) |
| ear_cc_accuracy.recorded | 0.0088 [-0.0805, 0.1053] (42 clusters) | -0.0768 [-0.196, 0.053] (42 clusters) |
| mouth_fidelity_ok.constructed | -0.0909 [-0.1818, 0.0] (55 clusters) | -0.0545 [-0.1455, 0.0182] (55 clusters) |
| mouth_fidelity_ok.recorded | -0.1891 [-0.2527, -0.1183] (35 clusters) | -0.1008 [-0.1417, -0.056] (35 clusters) |

## calls: latency, tokens, cost, served echoes

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| cost_usd | - | - | - |
| echoes | deepseek-v4-1-flash-260910 | gemini-3.8-flash | glm-5.3-flash |
| latency_ms.ear.n | 690 | 750 | 771 |
| latency_ms.ear.p50 | 2364 | 3691 | 5249 |
| latency_ms.ear.p95 | 4941 | 11134 | 11527 |
| latency_ms.mouth.n | 447 | 328 | 377 |
| latency_ms.mouth.p50 | 4036 | 4644 | 2293 |
| latency_ms.mouth.p95 | 5318 | 15666 | 5335 |
| latency_ms.simuser.n | 120 | 138 | 233 |
| latency_ms.simuser.p50 | 1947 | 3108 | 5909 |
| latency_ms.simuser.p95 | 3831 | 7865 | 11976 |
| not_final_rows.capped | 0 | 0 | 0 |
| not_final_rows.unavailable | 0 | 0 | 0 |
| tokens.ear.completion_tokens | 149960 | 360830 | 30389 |
| tokens.ear.prompt_tokens | 552149 | 399290 | 502676 |
| tokens.ear.reasoning_tokens | 116786 | 341613 | 7311 |
| tokens.mouth.completion_tokens | 179394 | 252383 | 15288 |
| tokens.mouth.prompt_tokens | 73528 | 63485 | 55250 |
| tokens.mouth.reasoning_tokens | 174755 | 245996 | 5518 |
| tokens.simuser.completion_tokens | 16832 | 31011 | 13292 |
| tokens.simuser.prompt_tokens | 95621 | 85854 | 155681 |
| tokens.simuser.reasoning_tokens | 8547 | 26803 | 102 |
| torn_lines | 0 | 0 | 0 |

