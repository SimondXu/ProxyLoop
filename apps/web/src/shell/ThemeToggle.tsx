// Light / Dark / System (S1-SYS-76): a radiogroup with a roving tab stop. It only shows the choice and changes it:
// the one controller (main.tsx, theme.ts) applies the theme and follows the OS on every page, the Rep page included.
import { createContext, useContext, useRef, useSyncExternalStore, type KeyboardEvent } from "react";
import type { ThemeChoice, ThemeController } from "../theme";
import { Icon } from "../ui/Icon";

const CHOICES: { value: ThemeChoice; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];
const STEP: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

export const ThemeContext = createContext<ThemeController | null>(null);

export function ThemeToggle() {
  const theme = useContext(ThemeContext);
  if (!theme) throw new Error("ThemeToggle needs main.tsx's ThemeContext");
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const choice = useSyncExternalStore(theme.subscribe, theme.choice);
  const choose = (c: ThemeChoice) => theme.choose(c);
  const onKey = (e: KeyboardEvent, i: number) => {
    const step = STEP[e.key];
    if (step === undefined) return;
    e.preventDefault();
    const n = (i + step + CHOICES.length) % CHOICES.length;
    const next = CHOICES[n];
    if (!next) return;
    choose(next.value);
    buttons.current[n]?.focus();
  };
  return (
    <div className="pl-theme" role="radiogroup" aria-label="Theme">
      {CHOICES.map((c, i) => (
        <button
          key={c.value}
          ref={(el) => {
            buttons.current[i] = el;
          }}
          type="button"
          role="radio"
          aria-checked={choice === c.value}
          tabIndex={choice === c.value ? 0 : -1}
          onClick={() => choose(c.value)}
          onKeyDown={(e) => onKey(e, i)}
        >
          <Icon name={c.value} size="sm" />
          <span className="pl-theme-word">{c.label}</span>
        </button>
      ))}
    </div>
  );
}
