/** The brand mark (redesign §2.4): two linked rings, the two lanes, and the planner's dot. Decorative. */
export function BrandMark() {
  return (
    <svg className="pl-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <circle cx="12" cy="16" r="7.5" />
      <circle cx="20" cy="16" r="7.5" />
      <circle cx="16" cy="16" r="2.4" className="pl-mark-dot" />
    </svg>
  );
}
