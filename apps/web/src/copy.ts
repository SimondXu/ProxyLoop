// The rail's fixed words (redesign §2.5, §3.2): the status line's rungs, the
// step texts, GUIDE moves and reasons in plain words. Nothing here is model
// output; an unknown move or reason is shown raw by its caller, never hidden.

/** contract/messages.py GuideMove, as the step the planner handed the phone voice. */
export const MOVE: Record<string, string> = {
  open_call: "Open the call",
  identify: "Verify your identity",
  ask_discount: "Ask for a lower price",
  cite_competitor: "Mention the competitor's price you shared",
  mention_tenure: "Mention how long you've been a customer",
  cancel_lever: "Say you may cancel (you allowed this)",
  ask_readback: "Ask the rep to read back every term",
  hold_for_decision: "Ask the rep to hold while you decide",
  decline_offer: "Decline the offer",
  ask_final_offer: "Ask for their best and final offer",
  deflect_fact_request: "Politely decline to share a private detail",
  close_call: "Wrap up the call",
  hold_for_fact: "Ask the rep to hold while it checks with you",
  defer_callback: "Arrange a call back",
};

export const GROUP = { before: "Before the call", call: "On the call", after: "After" } as const;
export const callGroup = (n: number) => (n > 1 ? `Call ${n}` : GROUP.call);

export const WHO = {
  planner: "Planner",
  toVoice: "Planner → phone voice",
  you: "You",
  sim: "Simulated approver",
  call: "Call",
  guard: "Guard",
  phone: "Phone voice",
  offer: "Offer heard",
} as const;

export const STEP = {
  asked: "Asked you a question",
  told: "Updated you in the chat",
  proposed: "Proposed your limits",
  called: "Called the company",
  calledBack: "Called back",
  callEnded: "Call ended",
  disclosure: "Opened with the AI disclosure",
  hold: "Asked the rep to hold",
  askedApproval: "Asked for your approval",
  outsideLimits: ": outside your limits",
  paused: "Your message paused commitments",
  pausedRead: "Your message paused commitments; the agent read it",
  saidYes: "Said yes on the call",
  saidYesCut: "Said yes on the call (cut off)",
  kept: "Kept a private detail from being said",
  verified: "Verified against the company's records",
  notVerified: "Couldn't verify: re-planning",
} as const;

export const said = (lane: string) => (lane === "cp" ? "✓ Said on the call" : "✓ Said in the chat");
export const PASSED = "Passed to the voice";

export const limitsDecided = (granted: boolean) => (granted ? "Confirmed your limits" : "Declined your limits");
export const approvalDecided = (granted: boolean) => (granted ? "Approved" : "Declined");
export const confirmation = (id: string) => `Got confirmation ${id}`;

/** An offer's step: "$78.00/mo · 24 months", its revision when past the first. */
export function offerText(price: string | null, months: string | null, revision: number): string {
  const terms = [price && `${price}/mo`, months && `${months} months`].filter(Boolean).join(" · ") || "Terms recorded";
  return revision > 1 ? `${terms} (revision ${revision})` : terms;
}

export const readbackText = (confirmed: number, total: number) =>
  total > 0 && confirmed === total ? `All ${total} terms read back and confirmed` : `Read-back: ${confirmed} of ${total} confirmed`;

// acceptedBy (conversation.ts) → whose grant cleared the yes.
const CLEARED: Record<string, string> = {
  "approved by you": "your approval",
  "approved by the simulated approver": "the simulated approver's approval",
  "fixed wording": "within the confirmed limits",
};
export const cleared = (by: string) => `Cleared to say yes (${CLEARED[by] ?? by})`;

// speak.revoked reasons (guard/capability.py revalidate, kernel/speaker.py).
const REVOKED: Record<string, string> = {
  fence: "you sent a message",
  expired: "the offer expired",
  epoch: "your instructions changed",
  offer_closed: "the offer closed",
  terms_changed: "the terms changed",
  consumed: "it was already used",
};
export const stoppedYes = (reason: string) => `Stopped the yes before it was said: ${REVOKED[reason] ?? reason}`;

// authority.epoch reasons (contract EpochBump); mandate_decided has its own step ("Confirmed your limits").
export const EPOCH: Record<string, { who: string; text: string }> = {
  f2s_revoke: { who: WHO.you, text: "Your instructions changed; earlier approvals no longer count" },
  slow_revoke: { who: WHO.planner, text: "Withdrew earlier approvals; they no longer count" },
  tighten_mandate: { who: WHO.planner, text: "Tightened your limits; earlier approvals no longer count" },
};
export const epochText = (reason: string) => EPOCH[reason] ?? { who: WHO.guard, text: `Earlier approvals no longer count (${reason})` };

// Guard's action.denied intents shown in the main view (slow/authority.py, slow/tools.py); others are engineer-only.
export const DENIED: Record<string, string> = {
  request_approval: "asking for your approval",
  accept_offer: "saying yes",
  decline_offer: "declining the offer",
  propose_mandate: "proposing limits",
  tighten_mandate: "changing your limits",
  share_fact: "sharing a detail",
};
export const blocked = (intent: string, reason: string) => `Blocked: ${DENIED[intent] ?? intent} (${reason})`;

/** The status line's rungs (redesign §3.2 NowCard), highest priority first. */
export const NOW = {
  approve: (terms: string | null) => `Waiting for you: approve or decline ${terms ?? "the offer"}`,
  limits: "Waiting for you: confirm your limits",
  reply: "Waiting for your reply in the chat",
  fence: "Reading your message before doing anything binding",
  hold: "Rep on hold while the agent checks something",
  inCall: "On the call with the company",
  intake: "Getting the details before calling",
} as const;

export const PLANNER = { thinking: "Planner is thinking…", listening: "Planner is listening" } as const;
export const LIMITS_NOTE = "Only your click can set or loosen these.";
export const NO_LIMITS = "No limits confirmed yet.";
