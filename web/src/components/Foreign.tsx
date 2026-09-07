import { useTranslation } from "react-i18next";

import { Money } from "@/components/Money";

/**
 * What is not yet in the budget currency, one chip per currency.
 *
 * A chip rather than a number in the column, because these are never added to the figure
 * beside them: five unconverted dollars are five dollars, not "about eighteen shekels", and
 * the shape has to say so. Pressing a chip is the way into converting, where a caller
 * offers that. See specs/currency.md.
 */
export function ForeignChips({
  foreign,
  onConvert,
  className = "",
}: {
  foreign: Record<string, string> | null | undefined;
  onConvert?: (currency: string) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const codes = Object.keys(foreign ?? {}).sort();
  if (codes.length === 0) return null;

  return (
    <span className={`inline-flex flex-wrap items-center gap-1 ${className}`}>
      {codes.map((code) => {
        const label = (
          <>
            <Money amount={foreign?.[code] ?? "0.00"} currency={code} colour={false} className="text-[11px]" />
            <span className="text-[10px] text-ink-muted">{t("currency.unconverted")}</span>
          </>
        );
        const classes =
          "inline-flex items-center gap-1 rounded-full border border-dashed border-line-strong px-1.5 py-0.5";
        return onConvert ? (
          <button
            key={code}
            type="button"
            onClick={() => onConvert(code)}
            title={t("currency.convertThese", { currency: code })}
            aria-label={t("currency.convertThese", { currency: code })}
            className={`${classes} hover:border-brand hover:text-brand`}
          >
            {label}
          </button>
        ) : (
          <span key={code} className={classes}>
            {label}
          </span>
        );
      })}
    </span>
  );
}
