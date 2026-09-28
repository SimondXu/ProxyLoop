# World-model selection report (S1-MOD-09, ADR-0024)

Internal instrument choice, not a claim; the user decides (ADR-0024). POST HOC / EXPLORATORY: re-run after the user saw the pre-registered result (world-select-report.md). world.MAX_TOKENS raised 512 -> 2048 (S1-ROOT-21, #267) because 512 counted reasoning on DeepSeek; Ear + Mouth only (SimUser is in the pre-registered report); same items, gold, rubric, seeds; fresh calls; fresh blind judge. Not pre-registered.

- git_sha: bfc90cf77b97492c69c6e284d8934ea961c8cf5e
- git_dirty: False
- items_root_hash: 471a0a9151af0c85204b6d49d2977fc14fae50fdfcd77cc2c2401246d61a41cc
- codebook_sha256: 892c8f686dfcb27d6a4c81a0f672c44226e2e306f625cf895da427534b4b7a38
- gold_sha256: aec2f545fc4dbbb013ab4f09c2dc25f9a21cc75fe2923a9644eeda75a77e32e1
- world_max_tokens: 2048
- inputs_sha256.judge_export_id: 6c0d4d37ef6d8a2409b810065ddfb2ef6481893a67fc1d38675cb106afb0f3bc
- inputs_sha256.judge_key: 4b412e36c693678975dd6fc25fa95a0d15fb1a23dfb74a18c27d7296694cfdc4
- inputs_sha256.judge_labels.judge-6c0d4d37-001.json: 908d0d6f232f6e3d8787cdf31d9553810771e2c64468eaca45067f1737901018
- inputs_sha256.judge_labels.judge-6c0d4d37-002.json: 519a4214f668e786cd4878df9015057c2dbf66f0674c1226bff2833114f0967a
- inputs_sha256.judge_labels.judge-6c0d4d37-003.json: 8eec994a4e49f3ba54865d0f7a2ef6c31bda59ab80290dd2221335148d4ba7ee
- inputs_sha256.judge_labels.judge-6c0d4d37-004.json: be23f0cb82ee5ee99eda084d07a41cebb285396e67d2edcdbbb5e71cc28fd41d
- inputs_sha256.judge_labels.judge-6c0d4d37-005.json: 97b343dc6673c4241142d4467a13c9088c46b8be7ba9c79128d4d3bd44e33ffe
- inputs_sha256.judge_labels.judge-6c0d4d37-006.json: ad8295a543f0a8969bb620beb711af648bf08b5e432a9f85ae6182a80681f19d
- inputs_sha256.judge_labels.judge-6c0d4d37-007.json: 9c13a15e5397402790d9b57c95895cb3bce1236216151d02adde9ea1b81d7b72
- inputs_sha256.judge_labels.judge-6c0d4d37-008.json: d1b59f2fbc696321a5aa71824a1ededa012513e992ea138d378afef58a65534f
- inputs_sha256.judge_labels.judge-6c0d4d37-009.json: 562769bbd2b4ae4964925ef586016a3bc47a0eeadfcbaeed4f3bff5bd12ff419
- inputs_sha256.judge_labels.judge-6c0d4d37-010.json: c78fabfa8756689e561129d257d6b9ac14eb87b638ca8e160607400b8293eb77
- inputs_sha256.judge_labels.judge-6c0d4d37-011.json: a99f68fb0a0faeb3f7936fb74fca44bbb1ae1f19e269d7837dbfa160025eccf4
- inputs_sha256.judge_labels.judge-6c0d4d37-012.json: a9e04d405fca024121c00da4f07054fcd6b122cf4cca137a13af1a922b552102
- inputs_sha256.judge_labels.judge-6c0d4d37-013.json: 5049fb6254a0f9cc37c250e61775933215da57373cca4cc21a35acc2fe39e115
- inputs_sha256.judge_labels.judge-6c0d4d37-014.json: 70c3fda76880f17364c026d8da329c34fd95acd6ce4ca4ff83f84d7844e9b162
- inputs_sha256.judge_labels.judge-6c0d4d37-015.json: 9e10a2c7219426aaa948c0c749b0d0775be216387c86d3cbedfa7ab830632020
- inputs_sha256.judge_labels.judge-6c0d4d37-016.json: d822f563a36624f767344caf8c32cb0fca0d1cdd8f548f1f970be312b9fad0f7
- inputs_sha256.judge_labels.judge-6c0d4d37-017.json: 294320d23f97814b559dffdc163781a94a0d65cc2f6663103b792730539b9438
- inputs_sha256.judge_labels.judge-6c0d4d37-018.json: a68569b57c2855a26323f5655d7cfa738345b793feeb23a653606ae04fcfc2cc
- inputs_sha256.judge_labels.judge-6c0d4d37-019.json: 0e0ebcc2777530e42173d793be5e92ffbc49140a3734510a2a6d85246b29cfa4
- inputs_sha256.judge_labels.judge-6c0d4d37-020.json: de44fcbd09a1f829a057a63d5eca798755375c91441697d4190a65dd9b9b7dac
- inputs_sha256.judge_labels.judge-6c0d4d37-021.json: 6a5fa96157dd94f95160d86fa1fa3e5d121f342d71564e43f39a2ccafbf086f0
- inputs_sha256.judge_labels.judge-6c0d4d37-022.json: de549a9fc1393be9d6406c35e51385aafe8bce940ef5b6c9ee3a36335aa18b92
- inputs_sha256.judge_labels.judge-6c0d4d37-023.json: 050e0ff105243782d58b8fdba873d8e8e940db0b38c9b7bc3100dd8d12cf739d
- inputs_sha256.judge_labels.judge-6c0d4d37-024.json: 38bfbe96021cf4ffd377d42a1597ce0d59a2994c81a17f8e59790085f3bd89fb
- inputs_sha256.judge_labels.judge-6c0d4d37-025.json: 555c4853d320115144c3dbbe57a01c435006bd31d2b4776a298ddc714cfb8dfe
- inputs_sha256.judge_labels.judge-6c0d4d37-026.json: ebacfb06a25cf3a0ce62bf0c298253a63af2b906348f5c3febacb0be8f95bb77
- inputs_sha256.judge_labels.judge-6c0d4d37-027.json: 90bbde71265e728c40e4a9594d1cd26f6a497e8127585130386b922bcdd9afd9
- inputs_sha256.judge_labels.judge-6c0d4d37-028.json: 537c518baa3e20c8d20432f057edd5de1db13de401a46d06103778a5ca36ce18
- inputs_sha256.judge_labels.judge-6c0d4d37-029.json: ad1cdf141222063aea24b79f0a20cb866418467057755e1dee63ca0aa52f593d
- inputs_sha256.judge_labels.judge-6c0d4d37-030.json: 66240aa639c975474783e2d3a3abba62f9e92a87e2f186962cdc09f3867d4f29
- inputs_sha256.judge_labels.judge-6c0d4d37-031.json: 5518d5bd408f46e37b08c16cb8b2a7cb56da1a4ae4d77611227d690fb9dab7fb
- inputs_sha256.judge_labels.judge-6c0d4d37-032.json: 0cead9d75be5808de9e88038d084c40768703e37fa7bbc78a2412eb2d3ac9677
- inputs_sha256.judge_labels.judge-6c0d4d37-033.json: 386c328f393aad94f8d62e087e9c43e6184fea4b516e475374ac4df05bec4ea6
- inputs_sha256.judge_labels.judge-6c0d4d37-034.json: 3409280aeacf5b84f3324b22887d69ae16500d05c0fd0be036c88b1937b9b142
- inputs_sha256.judge_rubric_sha256: 38e858bb40ca275e0b05a9555e74c26c5084d76b6fa88ac596928812f9b48b88
- inputs_sha256.rows.teamrouter:deepseek-flash@low: 343988b27310257b69c4f6d2749f4a595c704ec4a92e1cefd0c73d783cd12fe7
- inputs_sha256.rows.teamrouter:gemini-3.8-flash@low: c5c79ba61a840817328a7ad06269f703e020929e80f0fe45c9e7376f8cfdbdc1
- inputs_sha256.rows.teamrouter:glm-5.3-flash@low: de1c26cfc29453837c7ad62194c9add87764cb486e2383850c68a659bd284f59
- incumbent: teamrouter:gemini-3.8-flash@low
- primary: Ear cc_accuracy

A `-` cell is null: a rate with no denominator (n = 0), a count not seen, `cost_usd` when the report is made without `--prices`, and `undeclared_reveals`, which the rows do not carry.

## ear: recorded

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| cc_accuracy | 0.8728 [0.8391, 0.9003] (398/456) | 0.8289 [0.7917, 0.8607] (378/456) | 0.7895 [0.7497, 0.8244] (360/456) |
| arguments.facts | 1.0 [0.9417, 1.0] (62/62) | 1.0 [0.9465, 1.0] (68/68) | 0.9688 [0.8426, 0.9945] (31/32) |
| arguments.offer_ref | 1.0 [0.9577, 1.0] (87/87) | 0.9615 [0.8702, 0.9894] (50/52) | 0.9884 [0.937, 0.9979] (85/86) |
| arguments.price_usd | - | - | - |
| block_size_first_attempt | 1.0 [0.9011, 1.0] (35/35) | 0.7714 [0.6098, 0.8793] (27/35) | 1.0 [0.9011, 1.0] (35/35) |
| exact_accuracy | 0.8399 [0.8034, 0.8707] (383/456) | 0.8026 [0.7636, 0.8366] (366/456) | 0.7259 [0.6832, 0.7648] (331/456) |
| excluded | 0 | 0 | 0 |
| exhausted | 1 | 8 | 35 |
| first_attempt_valid | 0.9826 [0.9645, 0.9915] (395/402) | 0.7488 [0.7041, 0.7887] (301/402) | 0.8582 [0.8207, 0.8889] (345/402) |
| harm.accept.fn | 0 | 0 | 0 |
| harm.accept.fp | 0 | 0 | 0 |
| harm.cancel_intent.fn | 0 | 0 | 0 |
| harm.cancel_intent.fp | 0 | 0 | 3 |
| harm.cite_competitor.fn | 0 | 0 | 0 |
| harm.cite_competitor.fp | 0 | 0 | 0 |
| items | 402 | 402 | 402 |
| per_class.accept.precision | - | - | - |
| per_class.accept.recall | - | - | - |
| per_class.ask_discount.precision | 0.7865 [0.6905, 0.8589] (70/89) | 0.8851 [0.8012, 0.9364] (77/87) | 0.6667 [0.5676, 0.7529] (64/96) |
| per_class.ask_discount.recall | 0.7955 [0.6997, 0.8665] (70/88) | 0.875 [0.7899, 0.9287] (77/88) | 0.7273 [0.6262, 0.8093] (64/88) |
| per_class.ask_readback.precision | 0.7909 [0.7057, 0.8564] (87/110) | 0.8525 [0.7428, 0.9204] (52/61) | 0.8113 [0.7265, 0.8744] (86/106) |
| per_class.ask_readback.recall | 0.9255 [0.8542, 0.9635] (87/94) | 0.5532 [0.4526, 0.6496] (52/94) | 0.9149 [0.841, 0.9562] (86/94) |
| per_class.ask_supervisor.precision | - | - | - |
| per_class.ask_supervisor.recall | - | - | - |
| per_class.cancel_intent.precision | - | - | 0.0 [0.0, 0.5615] (0/3) |
| per_class.cancel_intent.recall | - | - | - |
| per_class.cite_competitor.precision | - | - | - |
| per_class.cite_competitor.recall | - | - | - |
| per_class.decline.precision | 0.0 [0.0, 0.4345] (0/5) | 0.0 [0.0, 0.2775] (0/10) | 0.0 [0.0, 0.6576] (0/2) |
| per_class.decline.recall | - | - | - |
| per_class.hold_request.precision | 0.9138 [0.8136, 0.9626] (53/58) | 0.9623 [0.8725, 0.9896] (51/53) | 1.0 [0.9324, 1.0] (53/53) |
| per_class.hold_request.recall | 0.9815 [0.9023, 0.9967] (53/54) | 0.9444 [0.8489, 0.9809] (51/54) | 0.9815 [0.9023, 0.9967] (53/54) |
| per_class.injection.precision | 0.0 [0.0, 0.4899] (0/4) | 0.0 [0.0, 0.4899] (0/4) | 0.0 [0.0, 0.1936] (0/16) |
| per_class.injection.recall | - | - | - |
| per_class.other.precision | 0.8182 [0.6148, 0.9269] (18/22) | 0.5581 [0.4111, 0.6957] (24/43) | 0.65 [0.4951, 0.7787] (26/40) |
| per_class.other.recall | 0.4 [0.2702, 0.5455] (18/45) | 0.5333 [0.3908, 0.6706] (24/45) | 0.5778 [0.433, 0.7103] (26/45) |
| per_class.provide_fact.precision | 0.9688 [0.893, 0.9914] (62/64) | 0.9714 [0.9017, 0.9921] (68/70) | 0.9697 [0.8468, 0.9946] (32/33) |
| per_class.provide_fact.recall | 0.8857 [0.7904, 0.9409] (62/70) | 0.9714 [0.9017, 0.9921] (68/70) | 0.4571 [0.3457, 0.573] (32/70) |
| per_class.refuse_fact.precision | 0.9747 [0.9123, 0.993] (77/79) | 0.9529 [0.8852, 0.9815] (81/85) | 0.9855 [0.9224, 0.9974] (68/69) |
| per_class.refuse_fact.recall | 0.8851 [0.8012, 0.9364] (77/87) | 0.931 [0.8576, 0.968] (81/87) | 0.7816 [0.6839, 0.8555] (68/87) |
| per_class.smalltalk.precision | 0.6667 [0.4671, 0.8203] (16/24) | 0.65 [0.4329, 0.8188] (13/20) | 1.0 [0.3424, 1.0] (2/2) |
| per_class.smalltalk.recall | 0.8889 [0.672, 0.969] (16/18) | 0.7222 [0.4913, 0.875] (13/18) | 0.1111 [0.031, 0.328] (2/18) |
| per_class.tenure.precision | - | - | - |
| per_class.tenure.recall | - | - | - |
| stability | 0.9375 [0.7985, 0.9827] (30/32) | 0.9062 [0.7578, 0.9676] (29/32) | 0.9688 [0.8426, 0.9945] (31/32) |
| timeout | 0 | 9 | 0 |
| utterances | 456 | 456 | 456 |
| weighted.cc_accuracy | 0.9061 | 0.8482 | 0.8091 |
| weighted.exact | 0.8654 | 0.8294 | 0.6761 |

## ear: constructed

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| cc_accuracy | 0.9143 [0.8562, 0.9503] (128/140) | 0.9071 [0.8476, 0.9449] (127/140) | 0.8429 [0.7735, 0.8939] (118/140) |
| arguments.facts | 1.0 [0.8454, 1.0] (21/21) | 1.0 [0.8454, 1.0] (21/21) | 1.0 [0.8241, 1.0] (18/18) |
| arguments.offer_ref | 1.0 [0.7719, 1.0] (13/13) | 0.9286 [0.6853, 0.9873] (13/14) | 0.9231 [0.6669, 0.9863] (12/13) |
| arguments.price_usd | 1.0 [0.8928, 1.0] (32/32) | 1.0 [0.8897, 1.0] (31/31) | 1.0 [0.8865, 1.0] (30/30) |
| block_size_first_attempt | 1.0 [0.6457, 1.0] (7/7) | 0.8571 [0.4869, 0.9743] (6/7) | 0.8571 [0.4869, 0.9743] (6/7) |
| exact_accuracy | 0.9071 [0.8476, 0.9449] (127/140) | 0.9 [0.8391, 0.9395] (126/140) | 0.8286 [0.7576, 0.882] (116/140) |
| excluded | 3 | 3 | 3 |
| exhausted | 3 | 5 | 11 |
| first_attempt_valid | 0.9778 [0.9367, 0.9924] (132/135) | 0.7704 [0.6925, 0.8332] (104/135) | 0.8593 [0.7906, 0.908] (116/135) |
| harm.accept.fn | 0 | 0 | 1 |
| harm.accept.fp | 4 | 1 | 1 |
| harm.cancel_intent.fn | 2 | 0 | 2 |
| harm.cancel_intent.fp | 1 | 3 | 2 |
| harm.cite_competitor.fn | 0 | 1 | 1 |
| harm.cite_competitor.fp | 0 | 1 | 1 |
| items | 135 | 135 | 135 |
| per_class.accept.precision | 0.75 [0.505, 0.8982] (12/16) | 0.9231 [0.6669, 0.9863] (12/13) | 0.9167 [0.6461, 0.9851] (11/12) |
| per_class.accept.recall | 1.0 [0.7575, 1.0] (12/12) | 1.0 [0.7575, 1.0] (12/12) | 0.9167 [0.6461, 0.9851] (11/12) |
| per_class.ask_discount.precision | 1.0 [0.7009, 1.0] (9/9) | 1.0 [0.7009, 1.0] (9/9) | 1.0 [0.6097, 1.0] (6/6) |
| per_class.ask_discount.recall | 0.9 [0.5958, 0.9821] (9/10) | 0.9 [0.5958, 0.9821] (9/10) | 0.6 [0.3127, 0.8318] (6/10) |
| per_class.ask_readback.precision | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) |
| per_class.ask_readback.recall | 0.5 [0.0945, 0.9055] (1/2) | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) |
| per_class.ask_supervisor.precision | 0.8947 [0.6861, 0.9706] (17/19) | 0.9412 [0.7302, 0.9895] (16/17) | 0.8947 [0.6861, 0.9706] (17/19) |
| per_class.ask_supervisor.recall | 0.9444 [0.7424, 0.9901] (17/18) | 0.8889 [0.672, 0.969] (16/18) | 0.9444 [0.7424, 0.9901] (17/18) |
| per_class.cancel_intent.precision | 0.9412 [0.7302, 0.9895] (16/17) | 0.8571 [0.6536, 0.9502] (18/21) | 0.8889 [0.672, 0.969] (16/18) |
| per_class.cancel_intent.recall | 0.8889 [0.672, 0.969] (16/18) | 1.0 [0.8241, 1.0] (18/18) | 0.8889 [0.672, 0.969] (16/18) |
| per_class.cite_competitor.precision | 1.0 [0.8389, 1.0] (20/20) | 0.95 [0.7639, 0.9911] (19/20) | 0.95 [0.7639, 0.9911] (19/20) |
| per_class.cite_competitor.recall | 1.0 [0.8389, 1.0] (20/20) | 0.95 [0.7639, 0.9911] (19/20) | 0.95 [0.7639, 0.9911] (19/20) |
| per_class.decline.precision | 1.0 [0.4385, 1.0] (3/3) | 1.0 [0.4385, 1.0] (3/3) | 0.5 [0.0945, 0.9055] (1/2) |
| per_class.decline.recall | 1.0 [0.4385, 1.0] (3/3) | 1.0 [0.4385, 1.0] (3/3) | 0.3333 [0.0615, 0.7923] (1/3) |
| per_class.hold_request.precision | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.3424, 1.0] (2/2) | - |
| per_class.hold_request.recall | 0.5 [0.0945, 0.9055] (1/2) | 1.0 [0.3424, 1.0] (2/2) | 0.0 [0.0, 0.6576] (0/2) |
| per_class.injection.precision | - | 0.0 [0.0, 0.7935] (0/1) | 0.0 [0.0, 0.4899] (0/4) |
| per_class.injection.recall | - | - | - |
| per_class.other.precision | 0.8571 [0.4869, 0.9743] (6/7) | 0.8333 [0.4365, 0.9699] (5/6) | 0.8889 [0.565, 0.9801] (8/9) |
| per_class.other.recall | 0.5455 [0.2801, 0.7873] (6/11) | 0.4545 [0.2127, 0.7199] (5/11) | 0.7273 [0.4344, 0.9025] (8/11) |
| per_class.provide_fact.precision | 0.913 [0.732, 0.9758] (21/23) | 0.9545 [0.782, 0.9919] (21/22) | 1.0 [0.8241, 1.0] (18/18) |
| per_class.provide_fact.recall | 1.0 [0.8454, 1.0] (21/21) | 1.0 [0.8454, 1.0] (21/21) | 0.8571 [0.6536, 0.9502] (18/21) |
| per_class.refuse_fact.precision | 0.5 [0.15, 0.85] (2/4) | 0.6667 [0.2077, 0.9385] (2/3) | 0.5 [0.15, 0.85] (2/4) |
| per_class.refuse_fact.recall | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) |
| per_class.smalltalk.precision | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) | - |
| per_class.smalltalk.recall | 0.6667 [0.2077, 0.9385] (2/3) | 0.6667 [0.2077, 0.9385] (2/3) | 0.0 [0.0, 0.5615] (0/3) |
| per_class.tenure.precision | 0.9444 [0.7424, 0.9901] (17/18) | 0.9375 [0.7167, 0.9889] (15/16) | 1.0 [0.8064, 1.0] (16/16) |
| per_class.tenure.recall | 0.9444 [0.7424, 0.9901] (17/18) | 0.8333 [0.6078, 0.9416] (15/18) | 0.8889 [0.672, 0.969] (16/18) |
| stability | 0.8 [0.4902, 0.9433] (8/10) | 0.8 [0.4902, 0.9433] (8/10) | 0.7 [0.3968, 0.8922] (7/10) |
| timeout | 0 | 1 | 1 |
| utterances | 140 | 140 | 140 |
| weighted.cc_accuracy | 0.9143 | 0.9071 | 0.8429 |
| weighted.exact | 0.9071 | 0.9 | 0.8286 |

## ear: off_distribution

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| cc_accuracy | 0.9167 [0.7817, 0.9713] (33/36) | 0.9722 [0.8583, 0.9951] (35/36) | 0.4722 [0.3199, 0.6299] (17/36) |
| arguments.facts | - | - | - |
| arguments.offer_ref | 1.0 [0.8389, 1.0] (20/20) | 1.0 [0.8389, 1.0] (20/20) | 1.0 [0.7009, 1.0] (9/9) |
| arguments.price_usd | 1.0 [0.7719, 1.0] (13/13) | 1.0 [0.7719, 1.0] (13/13) | 1.0 [0.5655, 1.0] (5/5) |
| block_size_first_attempt | 1.0 [0.6097, 1.0] (6/6) | 0.8333 [0.4365, 0.9699] (5/6) | 1.0 [0.6097, 1.0] (6/6) |
| exact_accuracy | 0.9167 [0.7817, 0.9713] (33/36) | 0.9722 [0.8583, 0.9951] (35/36) | 0.4444 [0.2954, 0.6042] (16/36) |
| excluded | 0 | 0 | 0 |
| exhausted | 0 | 0 | 9 |
| first_attempt_valid | 1.0 [0.883, 1.0] (29/29) | 0.8966 [0.7361, 0.9642] (26/29) | 0.6552 [0.4735, 0.8006] (19/29) |
| harm.accept.fn | 0 | 0 | 8 |
| harm.accept.fp | 1 | 0 | 0 |
| harm.cancel_intent.fn | 0 | 0 | 0 |
| harm.cancel_intent.fp | 0 | 0 | 0 |
| harm.cite_competitor.fn | 0 | 0 | 0 |
| harm.cite_competitor.fp | 0 | 0 | 1 |
| items | 29 | 29 | 29 |
| per_class.accept.precision | 0.9286 [0.6853, 0.9873] (13/14) | 1.0 [0.7719, 1.0] (13/13) | 1.0 [0.5655, 1.0] (5/5) |
| per_class.accept.recall | 1.0 [0.7719, 1.0] (13/13) | 1.0 [0.7719, 1.0] (13/13) | 0.3846 [0.1771, 0.6448] (5/13) |
| per_class.ask_discount.precision | 1.0 [0.4385, 1.0] (3/3) | 0.75 [0.3006, 0.9544] (3/4) | 1.0 [0.3424, 1.0] (2/2) |
| per_class.ask_discount.recall | 1.0 [0.4385, 1.0] (3/3) | 1.0 [0.4385, 1.0] (3/3) | 0.6667 [0.2077, 0.9385] (2/3) |
| per_class.ask_readback.precision | 0.875 [0.5291, 0.9776] (7/8) | 1.0 [0.6457, 1.0] (7/7) | 0.5714 [0.2505, 0.8418] (4/7) |
| per_class.ask_readback.recall | 1.0 [0.6457, 1.0] (7/7) | 1.0 [0.6457, 1.0] (7/7) | 0.5714 [0.2505, 0.8418] (4/7) |
| per_class.ask_supervisor.precision | 0.0 [0.0, 0.7935] (0/1) | - | 0.0 [0.0, 0.6576] (0/2) |
| per_class.ask_supervisor.recall | - | - | - |
| per_class.cancel_intent.precision | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.2065, 1.0] (1/1) |
| per_class.cancel_intent.recall | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.2065, 1.0] (1/1) | 1.0 [0.2065, 1.0] (1/1) |
| per_class.cite_competitor.precision | - | - | 0.0 [0.0, 0.7935] (0/1) |
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
| stability | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) | 1.0 [0.3424, 1.0] (2/2) |
| timeout | 0 | 0 | 1 |
| utterances | 36 | 36 | 36 |
| weighted.cc_accuracy | 0.9167 | 0.9722 | 0.4722 |
| weighted.exact | 0.9167 | 0.9722 | 0.4444 |

## mouth: recorded

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| exhausted | 0 | 0 | 0 |
| fallback | 0.0378 [0.02, 0.0703] (9/238) | 0.0042 [0.0007, 0.0234] (1/238) | 0.063 [0.0386, 0.1014] (15/238) |
| fallback_with_length_call | 7 | 0 | 0 |
| fidelity_ok | 0.9622 [0.9297, 0.98] (229/238) | 0.9874 [0.9636, 0.9957] (235/238) | 0.937 [0.8986, 0.9614] (223/238) |
| items | 238 | 238 | 238 |
| judged.M1 | 1.0 [0.9835, 1.0] (229/229) | 1.0 [0.9839, 1.0] (235/235) | 0.9103 [0.8655, 0.9412] (203/223) |
| judged.M2 | 1.0 [0.9835, 1.0] (229/229) | 1.0 [0.9839, 1.0] (235/235) | 0.9955 [0.975, 0.9992] (222/223) |
| judged.M3 | 1.0 [0.9835, 1.0] (229/229) | 1.0 [0.9839, 1.0] (235/235) | 0.8655 [0.8144, 0.9041] (193/223) |
| judged.M4 | 1.0 [0.9835, 1.0] (229/229) | 1.0 [0.9839, 1.0] (235/235) | 0.9552 [0.9194, 0.9755] (213/223) |
| judged.M5 | 1.0 [0.9835, 1.0] (229/229) | 1.0 [0.9839, 1.0] (235/235) | 1.0 [0.9831, 1.0] (223/223) |
| judged.no_violation | 1.0 [0.9835, 1.0] (229/229) | 1.0 [0.9839, 1.0] (235/235) | 0.8072 [0.7504, 0.8536] (180/223) |
| judged_final_call_length | 0 | 0 | 0 |
| n_excluded_fallback | 9 | 1 | 15 |
| timeout | 0 | 2 | 0 |

Judged M1-M5 cover non-fallback outputs only; `n_excluded_fallback` counts the fallbacks left out (ADR-0024 §5). `fallback_with_length_call`: fallbacks with a call that stopped at `length`; `judged_final_call_length`: judged outputs whose final call stopped at `length` (their text may be truncated).

## mouth: constructed

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| exhausted | 0 | 0 | 0 |
| fallback | 0.0545 [0.0187, 0.1485] (3/55) | 0.0364 [0.01, 0.1232] (2/55) | 0.0727 [0.0286, 0.1726] (4/55) |
| fallback_with_length_call | 1 | 0 | 0 |
| fidelity_ok | 0.9455 [0.8515, 0.9813] (52/55) | 0.9636 [0.8768, 0.99] (53/55) | 0.9273 [0.8274, 0.9714] (51/55) |
| items | 55 | 55 | 55 |
| judged.M1 | 1.0 [0.9312, 1.0] (52/52) | 1.0 [0.9324, 1.0] (53/53) | 1.0 [0.93, 1.0] (51/51) |
| judged.M2 | 1.0 [0.9312, 1.0] (52/52) | 1.0 [0.9324, 1.0] (53/53) | 1.0 [0.93, 1.0] (51/51) |
| judged.M3 | 1.0 [0.9312, 1.0] (52/52) | 1.0 [0.9324, 1.0] (53/53) | 1.0 [0.93, 1.0] (51/51) |
| judged.M4 | 1.0 [0.9312, 1.0] (52/52) | 1.0 [0.9324, 1.0] (53/53) | 1.0 [0.93, 1.0] (51/51) |
| judged.M5 | 1.0 [0.9312, 1.0] (52/52) | 1.0 [0.9324, 1.0] (53/53) | 1.0 [0.93, 1.0] (51/51) |
| judged.no_violation | 1.0 [0.9312, 1.0] (52/52) | 1.0 [0.9324, 1.0] (53/53) | 1.0 [0.93, 1.0] (51/51) |
| judged_final_call_length | 0 | 0 | 0 |
| n_excluded_fallback | 3 | 2 | 4 |
| timeout | 0 | 0 | 0 |

Judged M1-M5 cover non-fallback outputs only; `n_excluded_fallback` counts the fallbacks left out (ADR-0024 §5). `fallback_with_length_call`: fallbacks with a call that stopped at `length`; `judged_final_call_length`: judged outputs whose final call stopped at `length` (their text may be truncated).

## paired: X - incumbent, 95 % CI (no decision rule)

| metric | teamrouter:deepseek-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|
| ear_cc_accuracy.constructed | 0.0071 [-0.0435, 0.0584] (132 clusters) | -0.0643 [-0.1324, 0.0] (132 clusters) |
| ear_cc_accuracy.off_distribution | -0.0556 [-0.1765, 0.05] (29 clusters) | -0.5 [-0.6944, -0.3056] (29 clusters) |
| ear_cc_accuracy.recorded | 0.0439 [-0.0378, 0.1462] (42 clusters) | -0.0395 [-0.1651, 0.0986] (42 clusters) |
| mouth_fidelity_ok.constructed | -0.0182 [-0.0909, 0.0364] (55 clusters) | -0.0364 [-0.1091, 0.0364] (55 clusters) |
| mouth_fidelity_ok.recorded | -0.0252 [-0.0675, 0.0078] (35 clusters) | -0.0504 [-0.0862, -0.0152] (35 clusters) |

## calls: latency, tokens, cost, finish reasons, timeouts, served echoes

| metric | teamrouter:deepseek-flash@low | teamrouter:gemini-3.8-flash@low | teamrouter:glm-5.3-flash@low |
|---|---|---|---|
| cost_usd | - | - | - |
| echoes | deepseek-v4-1-flash-260910 | gemini-3.8-flash | glm-5.3-flash |
| finish_reason.ear.calls | 624 | 778 | 765 |
| finish_reason.ear.length | 3 | 1 | 0 |
| finish_reason.ear.null | - | 11 | 2 |
| finish_reason.ear.stop | - | 174 | - |
| finish_reason.ear.tool_calls | 621 | 592 | 763 |
| finish_reason.mouth.calls | 343 | 302 | 363 |
| finish_reason.mouth.length | 23 | 0 | 0 |
| finish_reason.mouth.null | - | 2 | - |
| finish_reason.mouth.stop | 320 | 300 | 363 |
| latency_ms.ear.n | 624 | 767 | 763 |
| latency_ms.ear.p50 | 2166 | 3465 | 4984 |
| latency_ms.ear.p95 | 5340 | 13552 | 9447 |
| latency_ms.mouth.n | 343 | 300 | 363 |
| latency_ms.mouth.p50 | 3681 | 4494 | 2177 |
| latency_ms.mouth.p95 | 13764 | 13651 | 4490 |
| not_final_rows.capped | 0 | 0 | 0 |
| not_final_rows.unavailable | 0 | 0 | 0 |
| timeout_all_repeats.ear | 0 | 11 | 2 |
| timeout_all_repeats.mouth | 0 | 2 | 0 |
| tokens.ear.completion_tokens | 138807 | 462209 | 29528 |
| tokens.ear.prompt_tokens | 498415 | 417864 | 497862 |
| tokens.ear.reasoning_tokens | 105168 | 441585 | 6836 |
| tokens.mouth.completion_tokens | 218983 | 265529 | 14215 |
| tokens.mouth.prompt_tokens | 56150 | 55597 | 53253 |
| tokens.mouth.reasoning_tokens | 213053 | 259528 | 4843 |
| torn_lines | 0 | 0 | 0 |

`finish_reason`, `timeout_all_repeats` and tokens cover every call of every attempt and repeat of the final rows (superseded `not_final_rows` left out); latency, those calls without an error. `null`: no finish reason (e.g. cancelled). `length`: stopped at max_tokens, world.MAX_TOKENS = 2048 for every arm at the generation commit; the rows do not record the cap, so it is the run's only if world.py did not change since the run. A segment's `timeout` is repeat 1 only.
