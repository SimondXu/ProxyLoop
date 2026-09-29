// The frame of every operator page (redesign §3.0): the top bar (brand, nav, theme), then the page.
// The Live-only parts of the bar (case title, reconnect) come with UI-2.
import type { ReactNode } from "react";
import { BrandMark } from "../ui/BrandMark";
import { ThemeToggle } from "./ThemeToggle";
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
          <span className="pl-brand-tile">
            <BrandMark />
          </span>
          <span className="pl-brand-word">proxyloop</span>
        </a>
        <nav className="pl-nav" aria-label="Main">
          {NAV.map((n) => (
            <a key={n.href} href={n.href}>
              {n.label}
            </a>
          ))}
        </nav>
        <ThemeToggle />
      </header>
      <main className="pl-main">{children}</main>
    </>
  );
}
