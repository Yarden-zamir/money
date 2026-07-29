import { useTranslation } from "react-i18next";

import { formatMoney, isNegative } from "@/lib/format";

/**
 * Renders an amount. Always through this component: it is the one place that applies bidi
 * isolation and locale formatting, so no screen can accidentally show a reordered minus sign.
 */
export function Money({
  amount,
  currency,
  colour = true,
  className = "",
}: {
  amount: string;
  currency: string;
  colour?: boolean;
  className?: string;
}) {
  const { i18n } = useTranslation();
  const tone = !colour
    ? "text-ink"
    : isNegative(amount)
      ? "text-negative"
      : "text-positive";

  return (
    <span className={`numeric ${tone} ${className}`}>
      {formatMoney(amount, currency, i18n.language)}
    </span>
  );
}
