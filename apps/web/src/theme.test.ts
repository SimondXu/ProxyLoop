import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { resolveTheme, storedChoice, THEME_KEY, themeController, type Theme } from "./theme";

type Store = { getItem(k: string): string | null; setItem(k: string, v: string): void };

function memory(init: Record<string, string> = {}): Store & { data: Record<string, string> } {
  const data = { ...init };
  return { data, getItem: (k) => data[k] ?? null, setItem: (k, v) => void (data[k] = v) };
}
const throwing: Store = {
  getItem: () => {
    throw new Error("SecurityError");
  },
  setItem: () => {
    throw new Error("QuotaExceededError");
  },
};

/** A prefers-color-scheme media query whose OS answer the test flips. */
function media(dark: boolean) {
  const ls = new Set<() => void>();
  return {
    matches: dark,
    addEventListener: (_: "change", f: () => void) => void ls.add(f),
    removeEventListener: (_: "change", f: () => void) => void ls.delete(f),
    flip(d: boolean) {
      this.matches = d;
      ls.forEach((f) => f());
    },
    listeners: ls,
  };
}

function env(store: () => Store, os: ReturnType<typeof media>) {
  const set: Theme[] = [];
  return { set, c: themeController({ store, media: os, setTheme: (t) => set.push(t) }) };
}

describe("storedChoice", () => {
  it("reads light, dark and system", () => {
    for (const c of ["light", "dark", "system"] as const) expect(storedChoice(() => memory({ [THEME_KEY]: c }))).toBe(c);
  });
  it("is system when nothing or junk is stored", () => {
    expect(storedChoice(() => memory())).toBe("system");
    expect(storedChoice(() => memory({ [THEME_KEY]: "sepia" }))).toBe("system");
  });
  it("is system when storage throws, or when reaching it throws", () => {
    expect(storedChoice(() => throwing)).toBe("system");
    expect(
      storedChoice(() => {
        throw new Error("SecurityError: localStorage is not available");
      }),
    ).toBe("system");
  });
});

describe("resolveTheme", () => {
  it("follows a fixed choice, and the OS only on system", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });
});

describe("themeController", () => {
  it("applies the stored choice at once, and saves a new one", () => {
    const store = memory({ [THEME_KEY]: "dark" });
    const { set, c } = env(() => store, media(false));
    expect(c.choice()).toBe("dark");
    expect(set).toEqual(["dark"]);
    c.choose("light");
    expect(set.at(-1)).toBe("light");
    expect(store.data[THEME_KEY]).toBe("light");
  });

  it("with no storage at all, starts on system and still switches for this page", () => {
    const { set, c } = env(() => throwing, media(true));
    expect(c.choice()).toBe("system");
    expect(set).toEqual(["dark"]);
    c.choose("light");
    expect(c.choice()).toBe("light");
    expect(set.at(-1)).toBe("light");
  });

  it("follows an OS change while on system, and ignores it otherwise", () => {
    const os = media(false);
    const { set, c } = env(() => memory(), os);
    expect(set).toEqual(["light"]);
    os.flip(true);
    expect(set.at(-1)).toBe("dark");
    c.choose("light");
    os.flip(false);
    os.flip(true);
    expect(set.at(-1)).toBe("light");
    c.choose("system");
    expect(set.at(-1)).toBe("dark");
    c.dispose();
    expect(os.listeners.size).toBe(0);
  });
});

describe("index.html's first-paint script", () => {
  // The same rule before React loads: run the inline script against a stored choice, an OS answer and a storage
  // that may throw, and read the data-theme it sets.
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const script = /<script>([\s\S]*?)<\/script>/.exec(html)?.[1] ?? "";
  function firstPaint(store: Store | null, osDark: boolean): string | undefined {
    const attrs: Record<string, string> = {};
    const document = { documentElement: { setAttribute: (k: string, v: string) => void (attrs[k] = v) } };
    const window = {
      get localStorage() {
        if (!store) throw new Error("SecurityError");
        return store;
      },
      matchMedia: (q: string) => ({ matches: q === "(prefers-color-scheme: dark)" && osDark }),
    };
    new Function("window", "document", script)(window, document);
    return attrs["data-theme"];
  }

  it("uses the module's storage key", () => {
    expect(script).toContain(JSON.stringify(THEME_KEY));
  });
  it("sets the stored theme, else the OS's, and survives a throwing storage", () => {
    expect(firstPaint(memory({ [THEME_KEY]: "dark" }), false)).toBe("dark");
    expect(firstPaint(memory({ [THEME_KEY]: "light" }), true)).toBe("light");
    expect(firstPaint(memory({ [THEME_KEY]: "system" }), true)).toBe("dark");
    expect(firstPaint(memory(), false)).toBe("light");
    expect(firstPaint(null, true)).toBe("dark");
    expect(firstPaint(throwing, false)).toBe("light");
  });
});
