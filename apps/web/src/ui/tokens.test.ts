import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// One vocabulary (S1-SYS-76): the v4 tokens replaced the redesign's; no alias layer, and both themes name the same set.
const SRC = new URL("../", import.meta.url);
const read = (rel: string) => readFileSync(new URL(rel, SRC), "utf8");
// src's own files: never the dependency caches a tool may leave under it (src/node_modules/.vite).
const files = (readdirSync(SRC, { recursive: true }) as string[]).filter((f) => !f.split(/[\\/]/).includes("node_modules")).sort();
const sheets = files.filter((f) => f.endsWith(".css"));
const scripts = files.filter((f) => /\.tsx?$/.test(f) && !f.endsWith(".test.ts"));
const tokens = read("ui/tokens.css");

/** The custom properties a rule defines, by its selector. */
function blocks(css: string): { selector: string; names: string[]; body: string }[] {
  const out = [];
  for (const m of css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/(:root[^{]*)\{([^{}]*)\}/g)) {
    const body = m[2] ?? "";
    out.push({ selector: (m[1] ?? "").trim(), body, names: [...body.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((n) => n[1] ?? "").sort() });
  }
  return out;
}

const REMOVED = [
  "canvas", "surface", "sunken", "line-strong", "line-input", "user-bubble",
  "agent", "agent-hover", "agent-soft", "agent-tint", "on-agent", "rep", "rep-soft", "guard", "guard-soft",
  "attn", "attn-ring", "attn-soft", "attn-tint", "danger", "danger-soft",
  "font-display", "r-xs", "r-md", "r-lg", "e1", "e2", "e3",
].map((n) => `--${n}`);

describe("tokens.css", () => {
  const all = blocks(tokens);
  const light = all.filter((b) => b.selector === ":root" && /color-scheme:\s*light/.test(b.body));
  const dark = all.filter((b) => b.selector === ':root[data-theme="dark"]');
  const shared = all.filter((b) => b.selector === ":root" && !/color-scheme/.test(b.body));

  it("has one light, one dark and one shared block, and nothing else", () => {
    expect([light.length, dark.length, shared.length, all.length]).toEqual([1, 1, 1, 3]);
  });
  it("defines the same token set under light and dark, and no themed token in the shared block", () => {
    expect(dark[0]?.names).toEqual(light[0]?.names);
    expect(dark[0]?.body).toMatch(/color-scheme:\s*dark/);
    expect(shared[0]?.names.filter((n) => light[0]?.names.includes(n))).toEqual([]);
  });
  it("defines no removed name", () => {
    expect(all.flatMap((b) => b.names).filter((n) => REMOVED.includes(n))).toEqual([]);
  });
});

const defined = new Set(blocks(tokens).flatMap((b) => b.names));
/** `file: --name` for each var(--name) in `text` that is removed or that tokens.css does not define. */
const badRefs = (file: string, text: string) =>
  [...text.matchAll(/var\((--[a-z0-9-]+)/g)].map((m) => m[1] ?? "").filter((n) => REMOVED.includes(n) || !defined.has(n)).map((n) => `${file}: ${n}`);

describe("the stylesheets under src", () => {
  it("finds the sheets", () => {
    expect(sheets).toContain("ui/base.css");
    expect(sheets.length).toBeGreaterThan(15);
  });
  it("reference no removed token name, and only tokens that tokens.css defines", () => {
    expect(sheets.flatMap((f) => badRefs(f, read(f)))).toEqual([]);
  });
  it("keep raw colours in tokens.css only", () => {
    const raw = sheets
      .filter((f) => f !== "ui/tokens.css")
      .flatMap((f) => [...read(f).replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/g)].map((m) => `${f}: ${m[0]}`));
    expect(raw).toEqual([]);
  });
});

describe("the scripts under src and index.html", () => {
  it("find the scripts, and skip node_modules", () => {
    expect(scripts).toContain("main.tsx");
    expect(files.filter((f) => f.includes("node_modules"))).toEqual([]);
  });
  it("reference no removed token name, and only tokens that tokens.css defines", () => {
    const bad = [...scripts.flatMap((f) => badRefs(f, read(f))), ...badRefs("index.html", read("../index.html"))];
    expect(bad).toEqual([]);
  });
});

describe("the font tokens", () => {
  const faces = new Set([...read("ui/fonts.css").matchAll(/font-family:\s*"([^"]+)"/g)].map((m) => m[1]));
  it.each(["--font-ui", "--font-serif", "--font-mono"])("%s's first family is an @font-face in fonts.css", (token) => {
    const first = new RegExp(`${token}:\\s*"([^"]+)"`).exec(tokens)?.[1];
    expect(first).toBeDefined();
    expect(faces).toContain(first);
  });
});
