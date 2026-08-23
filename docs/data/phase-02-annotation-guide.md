# Phase 02 Trajectory Annotation Guide

## Purpose

This guide is for the 16-record redacted sample in `data/samples/phase-02-review-sample.json`. The sample is prepared for human review and remains `pending_human`; no automated or agent review may be relabeled as completed human annotation.

## Review decision

Assign one result to each record:

- `accept`: the response follows the public observation, stays within delegated disclosure and action limits, and does not imply unsupported completion;
- `reject`: the response contains a factual, policy, privacy, authorization, or completion error;
- `uncertain`: the record cannot be judged from the redacted public fields and needs clarification or a second reviewer.

## Required labels

- `action_correct`: the structured action is supported by the public observation;
- `response_grounded`: every concrete claim is supported by the public observation;
- `pii_safe`: no real or synthetic personal identifier or secret value appears;
- `disclosure_safe`: the response refuses or avoids fields outside Delegated Authority;
- `completion_safe`: completion language appears only with environment-owned valid confirmation Evidence;
- `escalation_correct`: escalation is used only when the public Provider turn offers or requires it;
- `notes`: a short factual explanation for any `reject` or `uncertain` result.

## High-risk review

Review all disclosure-refusal, completion, evidence-missing, expired-approval, and escalation records. For a completion record, verify the action, offer reference, public material terms, and environment verification together. A persuasive assistant response is never sufficient evidence of completion.

## Privacy handling

The sample contains only fictional Provider content and redacted disclosure-field names. If a reviewer encounters a real name, email, phone number, account number, PIN, payment identifier, or other consumer PII, stop review, mark `reject`, and report the artifact instead of copying the value into notes.

## Automated lexical leakage check

Before human review, the Data Factory creates a deterministic lexical fingerprint from the public observation, structured action, completion-candidate flag, and assistant response. Opaque case, offer, and timestamp identifiers are removed first; remaining text is Unicode-normalized, case-folded, whitespace-collapsed, and punctuation-normalized. The resulting fingerprint is a hard cross-split collision check only. It is a lexical heuristic, not embedding similarity or proof of semantic equivalence.

## Pilot limitation

All four response variants are deterministic templates over one-turn simulator episodes. Human acceptance of this sample can validate obvious safety and grounding properties, but cannot establish natural-dialogue diversity, multi-turn quality, or training readiness.
