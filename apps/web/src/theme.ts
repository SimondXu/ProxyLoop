// The Light / Dark / System choice (S1-SYS-76). index.html's inline script applies the same rule before first paint;
// this module keeps the toggle and the OS in step afterwards. Storage may be missing or throw (private modes, blocked
// cookies): then the choice is "system" and a new one lasts for this page only; the page renders either way.
export type ThemeChoice = "light" | "dark" | "system";
export type Theme = "light" | "dark";
export const THEME_KEY = "proxyloop.theme";

type Store = Pick<Storage, "getItem" | "setItem">;
type Media = { readonly matches: boolean; addEventListener(t: "change", f: () => void): void; removeEventListener(t: "change", f: () => void): void };

const isChoice = (v: unknown): v is ThemeChoice => v === "light" || v === "dark" || v === "system";

/** The stored choice; "system" when none is stored, or when storage (or reaching it) throws. */
export function storedChoice(store: () => Store): ThemeChoice {
  try {
    const v = store().getItem(THEME_KEY);
    return isChoice(v) ? v : "system";
  } catch {
    return "system";
  }
}

export const resolveTheme = (c: ThemeChoice, osDark: boolean): Theme => (c === "system" ? (osDark ? "dark" : "light") : c);

/** Applies the stored choice now, re-applies it when the OS scheme changes while on "system", and saves new choices. */
export function themeController({ store, media, setTheme }: { store: () => Store; media: Media; setTheme: (t: Theme) => void }) {
  let choice = storedChoice(store);
  const apply = () => setTheme(resolveTheme(choice, media.matches));
  const onOs = () => {
    if (choice === "system") apply();
  };
  media.addEventListener("change", onOs);
  apply();
  return {
    choice: () => choice,
    choose(c: ThemeChoice) {
      choice = c;
      try {
        store().setItem(THEME_KEY, c);
      } catch {
        // Storage refused the write: the choice still applies, for this page only.
      }
      apply();
    },
    dispose: () => media.removeEventListener("change", onOs),
  };
}
