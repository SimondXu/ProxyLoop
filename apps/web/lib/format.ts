// Money as the Web shows it: one formatter for the conversation artifacts and
// the Agent Status Bar.

function field(value: unknown, key: string): unknown {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)[key]
    : undefined;
}

// null when the value is not a projected Money (integer minor units + currency).
export function formatMoneyOrNull(value: unknown): string | null {
  const amountMinor = field(value, "amount_minor");
  const currency = field(value, "currency");
  if (typeof amountMinor !== "number" || !Number.isInteger(amountMinor)) return null;
  if (typeof currency !== "string" || !currency.trim()) return null;
  try {
    return new Intl.NumberFormat("en-US", {
      currency,
      maximumFractionDigits: 2,
      style: "currency",
    }).format(amountMinor / 100);
  } catch {
    return `${currency} ${(amountMinor / 100).toFixed(2)}`;
  }
}

export function formatMoney(value: unknown): string {
  return formatMoneyOrNull(value) ?? "Unavailable";
}
