import type { ReactNode } from "react";
import "./EmptyState.css";

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="pl-empty">
      <p className="pl-empty-title">{title}</p>
      {children}
    </div>
  );
}
