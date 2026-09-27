// The honesty band and the provenance chip (redesign §3.0, I8, I11): who is
// simulated and which kind of model ran, from the first kernel session.started
// only. The replay passes its full log, never the time-filtered view, so every
// frame is labelled, also before session.started's t_ms.
import { parties, simLabels } from "./conversation";
import type { Ev } from "./replay";

export const HUMAN_PRINCIPAL = "Only your clicks can authorize a deal";
export const LIVE = "Live models";
export const SCRIPTED = "Scripted test run · no models called";
export const RECORDED = "Recorded replay";
export const BASELINE = "Baseline (scripted policy)";
export const LIVE_AND_BASELINE = "Live models + baseline (scripted policy)";

// The adapter kinds (AGENTS rule 5), per role in the chip's details; any other kind is shown raw.
const KIND: Record<string, string> = {
  real_http: "Live model",
  test_fake: "Scripted test fake",
  recorded_replay: RECORDED,
  baseline: BASELINE,
};

export type Chip = { label: string; scripted: boolean; roles: { role: string; label: string }[] };
export type Honesty = { sim: string[]; principal: string | null; chip: Chip | null };

const kindOf = (m: unknown): string => {
  const kind = (m as { ref?: { kind?: unknown } } | null)?.ref?.kind;
  return typeof kind === "string" ? kind : "unknown";
};

function chip(models: Record<string, unknown>): Chip {
  const kinds = Object.entries(models).map(([role, m]) => ({ role, kind: kindOf(m) }));
  if (kinds.length === 0) return { label: "Model kind: unknown", scripted: false, roles: [] }; // never "no provenance"
  const has = (k: string) => kinds.some((r) => r.kind === k);
  const unknown = [...new Set(kinds.map((r) => r.kind).filter((k) => !Object.hasOwn(KIND, k)))];
  const label = has("test_fake")
    ? SCRIPTED
    : has("recorded_replay")
      ? RECORDED
      : unknown.length > 0
        ? `Model kind: ${unknown.join(", ")}`
        : !has("real_http")
          ? BASELINE
          : has("baseline")
            ? LIVE_AND_BASELINE
            : LIVE;
  return { label, scripted: label === SCRIPTED, roles: kinds.map(({ role, kind }) => ({ role, label: (Object.hasOwn(KIND, kind) ? KIND[kind] : undefined) ?? kind })) };
}

export function honesty(events: Ev[]): Honesty {
  const p = parties(events);
  const start = events.find((e) => e.type === "session.started" && e.actor === "kernel");
  const models = start?.payload.models;
  const known = typeof models === "object" && models !== null && !Array.isArray(models);
  return {
    sim: simLabels(p),
    principal: p.known && !p.simUser ? HUMAN_PRINCIPAL : null,
    chip: start === undefined ? null : chip(known ? (models as Record<string, unknown>) : {}),
  };
}
