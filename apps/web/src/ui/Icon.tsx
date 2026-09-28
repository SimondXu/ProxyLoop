// The icon set (redesign §2.4): one fixed meaning per icon, named per-icon imports only.
import { Compass, FlaskConical, Hand, Lock, Mic, Monitor, Moon, Pause, Phone, ShieldCheck, Sun, type LucideIcon } from "lucide-react";

export const ICONS = {
  guard: ShieldCheck,
  planner: Compass,
  voice: Mic,
  call: Phone,
  you: Hand,
  hold: Pause,
  private: Lock,
  simulated: FlaskConical,
  light: Sun,
  dark: Moon,
  system: Monitor,
} satisfies Record<string, LucideIcon>;

const SIZE = { md: 18, sm: 15, xs: 13 } as const;

/** Decorative: the text next to it carries the meaning. */
export function Icon({ name, size = "md" }: { name: keyof typeof ICONS; size?: keyof typeof SIZE }) {
  const Svg = ICONS[name];
  return <Svg className="pl-icon" size={SIZE[size]} strokeWidth={1.75} aria-hidden="true" focusable="false" />;
}
