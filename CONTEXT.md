# ProxyLoop Domain Context

This glossary defines the words used at ProxyLoop's product and model boundaries. It is intentionally implementation-free so contracts, simulator behavior, evaluation, and UI use the same language.

## Language

**Consumer**:
The person whose goal, constraints, delegated authority, and interests define a Case.
_Avoid_: Customer, client, account holder

**Case**:
The durable lifecycle of one delegated consumer objective, including its versioned state, approvals, evidence, and completion status.
_Avoid_: Session, chat, job, run

**Consumer Goal**:
The outcome the Consumer asks ProxyLoop to pursue within a Case.
_Avoid_: Prompt, request, task description

**Constraint**:
A hard prohibition or soft preference that bounds acceptable actions and outcomes for a Case.
_Avoid_: Rule, setting

**Delegated Authority**:
The explicit, bounded permission a Consumer grants ProxyLoop to act for a Case.
_Avoid_: Autonomy, blanket consent

**Provider**:
The counterparty offering or managing a consumer service; all research-MVP Providers are fictional.
_Avoid_: Vendor, carrier when used generically

**Bill Snapshot**:
An evidence-linked representation of the Consumer's current service and charges at a specific version.
_Avoid_: Bill, account state

**Offer**:
A Provider proposal with explicit terms, validity, and provenance that has not been accepted merely by being recorded.
_Avoid_: Deal, plan, completion

**Fact Ledger**:
The versioned set of supported Case facts, with provenance and conflict status, available to decision components.
_Avoid_: Memory, context blob, notes

**Strategy Packet**:
A versioned, structured plan produced by the Slow Reasoner for bounded downstream use; it is not raw chain-of-thought.
_Avoid_: Reasoning trace, prompt dump

**Fast Turn Decision**:
A structured proposal for the next dialogue act, fact delta, escalation, or completion candidate during a bounded interaction.
_Avoid_: Agent action, autonomous decision

**Action Intent**:
A typed request to perform a side effect that remains inert until deterministic policy and approval checks authorize it.
_Avoid_: Tool call, command

**Approval Request**:
A request for Consumer authorization tied to a specific action, terms, Case version, and expiry.
_Avoid_: Confirmation, consent dialog

**Evidence**:
An immutable reference to a simulator or controlled external artifact used to support facts or completion.
_Avoid_: Claim, model output, log line

**Completion Candidate**:
A proposal that the Consumer Goal may have been satisfied, pending deterministic verification.
_Avoid_: Completion, success

**Completion Decision**:
The deterministic verifier result that accepts or rejects a Completion Candidate against current constraints and evidence.
_Avoid_: Model verdict, reward score

**Model Trace**:
The versioned operational record of a model invocation, its structured inputs and outputs, and reproducibility metadata, excluding hidden chain-of-thought.
_Avoid_: Chain-of-thought, reasoning log

**Simulator Episode**:
One isolated, reproducible Case interaction against a versioned fictional Provider scenario.
_Avoid_: Conversation, test chat
