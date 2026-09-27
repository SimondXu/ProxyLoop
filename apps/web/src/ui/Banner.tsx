import type { ReactNode } from "react";
import "./Banner.css";

/** A one-line message; `role` is the caller's (alert for errors, note for facts). */
export function Banner({ tone, role, children }: { tone: "danger" | "guard" | "attn"; role: "alert" | "note"; children: ReactNode }) {
  return (
    <p role={role} className={`pl-banner pl-banner-${tone}`}>
      {children}
    </p>
  );
}
