# UI research boundary and reuse audit

The interaction direction was informed by one observation of a private page
after a single login on 2026-08-25. That observation is a project reference,
not a public source and not a publicly reproducible inspection. No credentials,
session data, screenshot, account data, or private content is stored here.
The observation supports only the interaction direction: conversation as the
primary workspace, calm structured artifacts inline, and user confirmation at
consequential boundaries.

The implementation also reviewed the local legacy snapshot `b8d7ee5` without
merging or cherry-picking it.

Reusable from the snapshot:

- the calm trust-first three-column shell with a compact task sidebar,
  continuous conversation, and context rail;
- typography, spacing, responsive collapse, focus treatment, and the inline
  Task Brief / Progress / Offer / Approval / Evidence artifact language;
- readable status text alongside color and a conversation-first mobile layout.

Not reusable as product truth:

- `demo-case.ts` and any prebuilt `/cases/demo*` journey;
- click-local approval or receipt state that claims completion without a
  Runtime response;
- static bill, offer, revision, hash, approval, confirmation, or Evidence
  identifiers;
- copy that implies a Provider action is connected or that arbitrary chat
  corrections mutate an authoritative Case.

The current demo is therefore a local fictional-Provider journey only. The
reference observation does not establish a public pixel-perfect product clone,
authenticated route map, production transport, or Pine implementation.
