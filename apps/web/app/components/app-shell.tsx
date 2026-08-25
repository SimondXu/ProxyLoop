import type { ReactNode } from "react";
import Link from "next/link";

type AppShellProps = { children: ReactNode };

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <Link className="brand" href="/" aria-label="ProxyLoop home">
          <span aria-hidden="true" className="brand-mark" />
          ProxyLoop
        </Link>
        <span className="prototype-chip">
          <span aria-hidden="true" className="chip-dot" />
          Local demo
        </span>
      </header>
      <main id="main-content" tabIndex={-1}>
        {children}
      </main>
      <footer className="site-footer">
        <p>
          Fictional Provider only. Nothing here connects to an account, payment,
          phone, or external model.
        </p>
        <Link href="/">Restart demo <span aria-hidden="true">→</span></Link>
      </footer>
    </div>
  );
}
