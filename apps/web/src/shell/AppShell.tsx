// The frame of every operator page (redesign §3.0): the top bar, then the page.
// The Live-only parts of the bar (case title, stepper, reconnect) come with UI-2.
import type { ReactNode } from "react";
import "./AppShell.css";

// "New case" is the server route: it sets the operator cookie, then 303s to ?start.
const NAV = [
  { href: "/start", label: "New case" },
  { href: "/", label: "Replays" },
];

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <>
      <header className="pl-topbar">
        <a className="pl-brand" href="/" aria-label="ProxyLoop home">
          <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
            <circle cx="12" cy="16" r="7.5" />
            <circle cx="20" cy="16" r="7.5" />
            <circle cx="16" cy="16" r="2.4" className="pl-brand-dot" />
          </svg>
          ProxyLoop
        </a>
        <nav className="pl-nav" aria-label="Main">
          {NAV.map((n) => (
            <a key={n.href} href={n.href}>
              {n.label}
            </a>
          ))}
        </nav>
      </header>
      <main className="pl-main">{children}</main>
    </>
  );
}
