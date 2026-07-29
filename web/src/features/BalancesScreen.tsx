import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { getBalancesOptions } from "@/api/@tanstack/react-query.gen";
import { Money } from "@/components/Money";
import { ErrorState, Loading } from "@/components/States";
import { useBudget } from "./useBudget";

export function BalancesScreen() {
  const { t } = useTranslation();
  const { budget, isPending: budgetPending } = useBudget();

  const query = useQuery({
    ...getBalancesOptions({ path: { budget: budget?.slug ?? "" } }),
    enabled: Boolean(budget),
  });

  if (budgetPending || query.isPending) return <Loading />;
  if (query.isError || !budget) return <ErrorState onRetry={() => void query.refetch()} />;

  const { balances, settle_up: settlements, currency } = query.data;

  return (
    <section className="space-y-6">
      <h1 className="text-lg font-semibold">{t("balances.title")}</h1>

      <ul className="divide-y divide-line rounded-lg ring-1 ring-line">
        {balances.map((balance) => (
          <li key={balance.person} className="flex items-baseline gap-3 p-3">
            <span className="font-medium">{balance.person}</span>
            {balance.person === budget.me && (
              <span className="text-xs text-ink-muted">{t("common.you")}</span>
            )}
            <span className="ms-auto">
              <Money amount={balance.net} currency={currency} />
            </span>
          </li>
        ))}
      </ul>

      <div>
        <h2 className="mb-2 text-sm font-medium text-ink-muted">{t("balances.settleUp")}</h2>
        {settlements.length === 0 ? (
          <p className="text-ink-muted">{t("balances.allSquare")}</p>
        ) : (
          <ul className="space-y-2">
            {settlements.map((payment) => (
              <li
                key={`${payment.payer}-${payment.payee}`}
                className="flex items-baseline gap-3 rounded-lg bg-surface-raised p-3 ring-1 ring-line"
              >
                <span>
                  {t("balances.owes", { payer: payment.payer, payee: payment.payee })}
                </span>
                <span className="ms-auto">
                  <Money amount={payment.amount} currency={currency} colour={false} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
