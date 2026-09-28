import type { HTMLAttributes } from "react";
import "./Chip.css";

type Props = HTMLAttributes<HTMLSpanElement> & { tone?: "neutral" | "you" | "ok" | "over" | "honest" | "sim" };

export function Chip({ tone = "neutral", className = "", ...rest }: Props) {
  return <span className={`pl-chip pl-chip-${tone} ${className}`.trim()} {...rest} />;
}
