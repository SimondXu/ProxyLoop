type StatusBadgeProps = {
  children: string;
  tone?: "neutral" | "working" | "complete" | "blocked";
};

export function StatusBadge({ children, tone = "neutral" }: StatusBadgeProps) {
  return <span className={`status-badge ${tone}`}>{children}</span>;
}
