import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useQuery } from "@tanstack/react-query";

import { getMonthOptions } from "@/api/@tanstack/react-query.gen";
import { Money } from "@/components/Money";
import { Empty, ErrorState, Loading } from "@/components/States";
import { currentMonth, formatMonth, shiftMonth } from "@/lib/format";
import { useBudget } from "./useBudget";

export function MonthScreen() {
  const { t, i18n } = useTranslation();
  const { budget, isPending: budgetPending } = useBudget();
  const [month, setMonth] = useState(currentMonth);

  const query = useQuery({
    ...getMonthOptions({ path: { budget: budget?.slug ?? "", month } }),
    enabled: Boolean(budget),
  });

  if (budgetPending || query.isPending) return <Loading />;
  if (query.isError || !budget) return <ErrorState onRetry={() => void query.refetch()} />;

  const view = query.data;

  return (
    <section>
      <header className="mb-6 flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-1">
          {/* U+2039/U+203A are Bidi-Mirrored: the text engine already flips them in RTL, so
              they must NOT also get .icon-directional or they would flip back. Flex order
              puts "previous" at the inline start in both directions. */}
          <MonthStep label={t("month.previous")} onClick={() => setMonth(shiftMonth(month, -1))}>
            ‹
          </MonthStep>
          <span className="min-w-44 text-center text-lg font-semibold">
            {formatMonth(month, i18n.language)}
          </span>
          <MonthStep label={t("month.next")} onClick={() => setMonth(shiftMonth(month, 1))}>
            ›
          </MonthStep>
        </div>

        <div className="ms-auto rounded-lg bg-surface-raised px-4 py-2 ring-1 ring-line">
          <div className="text-xs text-ink-muted">{t("month.readyToAssign")}</div>
          <Money amount={view.ready_to_assign} currency={view.currency} className="text-xl" />
        </div>
      </header>

      {view.buckets.length === 0 ? (
        <Empty message={t("month.empty")} />
      ) : (
        <div className="overflow-x-auto rounded-lg ring-1 ring-line">
          <table className="w-full text-sm">
            <thead className="bg-surface-raised text-ink-muted">
              <tr>
                <th className="p-3 text-start font-medium">{t("month.bucket")}</th>
                <th className="p-3 text-end font-medium">{t("month.assigned")}</th>
                <th className="p-3 text-end font-medium">{t("month.activity")}</th>
                <th className="p-3 text-end font-medium">{t("month.available")}</th>
              </tr>
            </thead>
            <tbody>
              {view.buckets.map((bucket) => (
                <tr key={bucket.bucket} className="border-t border-line">
                  <td className="p-3">
                    {bucket.name}
                    {bucket.group && (
                      <span className="ms-2 text-xs text-ink-muted">{bucket.group}</span>
                    )}
                  </td>
                  <td className="p-3 text-end">
                    <Money amount={bucket.assigned} currency={view.currency} colour={false} />
                  </td>
                  <td className="p-3 text-end">
                    <Money amount={bucket.activity} currency={view.currency} />
                  </td>
                  <td className="p-3 text-end font-medium">
                    <Money amount={bucket.available} currency={view.currency} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function MonthStep({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="rounded-md px-2 py-1 text-lg text-ink-muted hover:bg-surface-raised"
    >
      {children}
    </button>
  );
}
