/**
 * Formatting helpers.
 *
 * Amounts arrive from the API as decimal strings and are never parsed into a JS number for
 * arithmetic — `Number("0.1") + Number("0.2")` is exactly the drift the backend's Decimal
 * type exists to prevent. They are parsed only at the last moment, to hand to Intl for
 * display, and every total shown comes from the API.
 */

// Unicode isolates. Without them the bidi algorithm can move a minus sign or currency symbol
// to the wrong end of a number sitting inside Hebrew text, so "-50.00" reads as "50.00-".
const LRI = "⁦";
const PDI = "⁩";

export function formatMoney(amount: string, currency: string, locale: string): string {
  const value = Number(amount);
  if (!Number.isFinite(value)) return amount; // never invent a number we cannot show

  const formatted = new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(value);

  return `${LRI}${formatted}${PDI}`;
}

export function formatDate(iso: string, locale: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(parsed);
}

export function formatMonth(month: string, locale: string): string {
  const [year, monthNumber] = month.split("-");
  if (!year || !monthNumber) return month;
  const parsed = new Date(Number(year), Number(monthNumber) - 1, 1);
  return new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }).format(parsed);
}

export function isNegative(amount: string): boolean {
  return amount.trimStart().startsWith("-");
}

/** Today's month as `YYYY-MM`, in local time. */
export function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function shiftMonth(month: string, delta: number): string {
  const [year, monthNumber] = month.split("-").map(Number);
  if (!year || !monthNumber) return month;
  const shifted = new Date(year, monthNumber - 1 + delta, 1);
  return `${shifted.getFullYear()}-${String(shifted.getMonth() + 1).padStart(2, "0")}`;
}
