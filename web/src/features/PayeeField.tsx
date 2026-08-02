import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { suggestPayeesOptions } from "@/api/@tanstack/react-query.gen";
import type { PayeeSuggestion } from "@/api/types.gen";
import { Icon } from "@/components/Icon";
import { Input } from "@/components/Form";
import { Money } from "@/components/Money";

/**
 * A payee field that completes from this budget's own history.
 *
 * Typing a shop's name in full every time is the slowest part of logging an expense, and the
 * answer is already in the ledger. Picking a suggestion also fills the amount and bucket,
 * which is where most of the time actually goes.
 */
export function PayeeField({
  budget,
  currency,
  value,
  onChange,
  onPick,
}: {
  budget: string;
  currency: string;
  value: string;
  onChange: (payee: string) => void;
  onPick: (suggestion: PayeeSuggestion) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [debounced, setDebounced] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value.trim()), 180);
    return () => clearTimeout(timer);
  }, [value]);

  // Clicking anywhere else closes the list. Without this it stays open behind other fields.
  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const suggestions = useQuery({
    ...suggestPayeesOptions({ path: { budget }, query: { q: debounced } }),
    enabled: open,
  });
  const items = suggestions.data ?? [];

  const choose = (suggestion: PayeeSuggestion) => {
    onPick(suggestion);
    setOpen(false);
  };

  return (
    <div ref={box} className="relative">
      <Input
        value={value}
        autoComplete="off"
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
          setHighlighted(0);
        }}
        onKeyDown={(event) => {
          if (!open || items.length === 0) return;
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setHighlighted((index) => (index + 1) % items.length);
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setHighlighted((index) => (index - 1 + items.length) % items.length);
          } else if (event.key === "Enter" && items[highlighted]) {
            // Enter picks the highlighted suggestion rather than submitting the form, which
            // would otherwise save a half-filled entry from under the open list.
            event.preventDefault();
            choose(items[highlighted]);
          } else if (event.key === "Escape") {
            setOpen(false);
          }
        }}
      />

      {open && items.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-line bg-card shadow-lg">
          {items.map((suggestion, index) => (
            <li key={suggestion.payee}>
              <button
                type="button"
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => choose(suggestion)}
                className={`flex w-full items-center gap-2 px-3 py-2 text-start text-sm ${
                  index === highlighted ? "bg-brand-soft" : ""
                }`}
              >
                <span className="min-w-0 flex-1 truncate">{suggestion.payee}</span>
                {suggestion.amount && (
                  <Money
                    amount={String(suggestion.amount)}
                    currency={currency}
                    colour={false}
                    className="text-xs text-ink-muted"
                  />
                )}
                {/* Says where the number came from, so a suggestion is never mysterious. */}
                <span
                  className="flex items-center gap-1 text-[11px] text-ink-muted"
                  title={t(`payees.basis.${suggestion.basis}`, { count: suggestion.count })}
                >
                  <Icon name="sparkle" className="size-3.5" />
                  {suggestion.count}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
