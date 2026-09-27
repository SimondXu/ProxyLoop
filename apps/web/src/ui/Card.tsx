import type { HTMLAttributes } from "react";
import "./Card.css";

/** A surface panel. A labelled card is a region (aria-label → role region). */
export function Card({ className = "", ...rest }: HTMLAttributes<HTMLElement>) {
  return <section className={`pl-card ${className}`.trim()} {...rest} />;
}
