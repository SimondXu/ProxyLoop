// Light / Dark / System (S1-SYS-76): a radiogroup with a roving tab stop; the rule is theme.ts's.
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { storedChoice, themeController, type ThemeChoice } from "../theme";
import { Icon } from "../ui/Icon";

const CHOICES: { value: ThemeChoice; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];
const STEP: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

export function ThemeToggle() {
  const ctl = useRef<ReturnType<typeof themeController> | null>(null);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const [choice, setChoice] = useState<ThemeChoice>(() => storedChoice(() => window.localStorage));
  useEffect(() => {
    const c = themeController({
      store: () => window.localStorage,
      media: window.matchMedia("(prefers-color-scheme: dark)"),
      setTheme: (t) => document.documentElement.setAttribute("data-theme", t),
    });
    ctl.current = c;
    return c.dispose;
  }, []);
  const choose = (c: ThemeChoice) => {
    ctl.current?.choose(c);
    setChoice(c);
  };
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
