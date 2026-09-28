# Mouth judge rubric v1 (world-model selection, S1-MOD-09, ADR-0024)

The judge sees one simulated customer-service rep line ("the output"), together with what the rep was asked to say:
- `intent`: the policy's speech act for this turn (e.g. offer, readback, ask_identity, ok_hold, no_better, confirmed, hang_up);
- `say`: the terms the rep must state, with their values (absence terms such as "no fee" or "no change" included);
- `ask`: the one thing the rep may ask the caller for, if any;
- `heard`: what the caller said this turn (context only).

The judge never sees which model wrote the output. Judge each criterion independently and answer true (satisfied) or false (violated). If the criterion does not apply (e.g. `say` is empty for M2), answer true.

- **M1 (speech act):** the output performs the same speech act as `intent` (an offer is an offer, a read-back reads back, a hold acknowledgement acknowledges the hold, a hang-up ends the call).
- **M2 (terms stated):** every `say` term is stated with its value, including absence terms ("no activation fee", "no service changes"). A value may be phrased naturally (e.g. "seventy-five dollars a month" for monthly_price 75.00) but must be the same value.
- **M3 (nothing invented):** the output states no term, price, fee, perk, date or commitment that is not in `say`, and contradicts none that is.
- **M4 (no extra request):** the output asks the caller for nothing beyond `ask` (no extra questions, no requests for other information).
- **M5 (form):** at most two spoken sentences, and no meta-text (no "As a rep…", stage directions, quotation marks around the whole line, or explanations of the task).

Output per record: {"record": <id>, "M1": bool, "M2": bool, "M3": bool, "M4": bool, "M5": bool, "note": "≤ 20 words, only when any is false"}.
A line is "no-violation" when all five are true.
