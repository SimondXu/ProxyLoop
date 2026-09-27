import "./Skeleton.css";

/** Placeholder bars while something loads; `label` is what a screen reader hears. */
export function Skeleton({ label, lines = 3 }: { label: string; lines?: number }) {
  return (
    <div className="pl-skeleton" aria-busy="true">
      <span className="pl-sr">{label}</span>
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="pl-skeleton-bar" aria-hidden="true" />
      ))}
    </div>
  );
}
