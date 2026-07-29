import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getBalancesOptions, settleUpMutation } from "@/api/@tanstack/react-query.gen";
import { Button } from "@/components/Form";
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
                <span className="ms-auto flex items-center gap-3">
                  <Money amount={payment.amount} currency={currency} colour={false} />
                  {budget.can_write && payment.payer === budget.me && (
                    <SettleButton
                      budget={budget.slug}
                      payee={payment.payee}
                      amount={payment.amount}
                    />
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

/**
 * Records a settlement. Only offered to the person who owes: the API records whatever it is
 * asked to, so putting the button on the wrong row would make it easy to move a balance the
 * wrong way.
 */
function SettleButton({
  budget,
  payee,
  amount,
}: {
  budget: string;
  payee: string;
  amount: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const settle = useMutation({
    ...settleUpMutation(),
    onSuccess: () => void queryClient.invalidateQueries(),
  });

  return (
    <Button
      type="button"
      disabled={settle.isPending}
      onClick={() => settle.mutate({ path: { budget }, body: { to: payee, amount } })}
    >
      {settle.isPending ? t("balances.settling") : t("balances.settleNow")}
    </Button>
  );
}
