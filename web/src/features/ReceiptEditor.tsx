import { useTranslation } from "react-i18next";

import { Button, Input } from "@/components/Form";
import { Icon } from "@/components/Icon";
import { Money } from "@/components/Money";

export type ReceiptLine = { label: string; amount: string };

/**
 * The lines of a receipt.
 *
 * One payment, several things bought — and they do not always belong in the same envelope.
 * Lines are optional: most entries never need them, so this stays collapsed until asked for.
 *
 * The running total is shown against the entry amount and turns red when they disagree,
 * because the backend refuses an unbalanced receipt and finding that out on save is worse
 * than seeing it while typing.
 */
export function ReceiptEditor({
  items,
  currency,
  total,
  lineTotal,
  onChange,
}: {
  items: ReceiptLine[];
  currency: string;
  total: number;
  lineTotal: number;
  onChange: (items: ReceiptLine[]) => void;
}) {
  const { t } = useTranslation();
  const balanced = Math.abs(lineTotal - total) < 0.005;

  if (items.length === 0) {
    return (
      <Button
        type="button"
        variant="ghost"
        className="mt-2 min-h-9 px-2 text-xs"
        onClick={() => onChange([{ label: "", amount: "" }])}
      >
        <Icon name="plus" className="size-3.5" />
        {t("entries.receipt")}
      </Button>
    );
  }

  return (
    <div className="mt-3 rounded-lg border border-line p-3">
      <div className="mb-2 flex items-baseline gap-2">
        <span className="eyebrow">{t("entries.receipt")}</span>
        <span className={`numeric text-xs ${balanced ? "text-ink-muted" : "text-negative"}`}>
          <Money amount={lineTotal.toFixed(2)} currency={currency} colour={false} />
          {" / "}
          <Money amount={total.toFixed(2)} currency={currency} colour={false} />
        </span>
      </div>

      <div className="space-y-2">
        {items.map((item, index) => (
          <div key={index} className="flex gap-2">
            <Input
              aria-label={t("entries.lineLabel")}
              placeholder={t("entries.lineLabel")}
              value={item.label}
              onChange={(event) =>
                onChange(
                  items.map((row, i) =>
                    i === index ? { ...row, label: event.target.value } : row,
                  ),
                )
              }
            />
            <Input
              fullWidth={false}
              aria-label={t("entries.amount")}
              className="numeric ltr-field w-24 text-end"
              inputMode="decimal"
              placeholder="0.00"
              value={item.amount}
              onChange={(event) =>
                onChange(
                  items.map((row, i) =>
                    i === index ? { ...row, amount: event.target.value } : row,
                  ),
                )
              }
            />
            <button
              type="button"
              aria-label={t("entries.delete")}
              onClick={() => onChange(items.filter((_, i) => i !== index))}
              className="flex size-11 shrink-0 items-center justify-center rounded-lg text-ink-muted hover:bg-negative/10 hover:text-negative"
            >
              <Icon name="close" className="size-4" />
            </button>
          </div>
        ))}
      </div>

      <Button
        type="button"
        variant="ghost"
        className="mt-2 min-h-9 px-2 text-xs"
        onClick={() => onChange([...items, { label: "", amount: "" }])}
      >
        <Icon name="plus" className="size-3.5" />
        {t("entries.addLine")}
      </Button>
    </div>
  );
}
