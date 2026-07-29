import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getBalancesOptions, settleUpMutation } from "@/api/@tanstack/react-query.gen";
import type { BudgetSummary } from "@/api/types.gen";
import { Button, Card, FormError } from "@/components/Form";
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
  const mine = balances.find((balance) => balance.person === budget.me);
  const net = Number(mine?.net ?? 0);

  const nameOf = (person: string) =>
    budget.members.find((member) => member.person === person)?.name ?? person;

  return (
    <section className="space-y-5">
      <h1 className="text-lg font-semibold">{t("balances.title")}</h1>

      {/* "Am I owed, or do I owe?" is the only question this screen exists to answer, so it
          gets stated in words before any table of numbers. */}
      {mine && (
        <Card
          className={`p-5 text-center ${
            net > 0 ? "border-positive/40 bg-positive/5" : net < 0 ? "border-negative/40 bg-negative/5" : ""
          }`}
        >
          <div className="text-xs font-medium text-ink-muted">
            {net > 0
              ? t("balances.youAreOwed")
              : net < 0
                ? t("balances.youOwe")
                : t("balances.allSquare")}
          </div>
          {net !== 0 && (
            <Money
              amount={Math.abs(net).toFixed(2)}
              currency={currency}
              colour={false}
              className={`text-3xl font-semibold ${net > 0 ? "text-positive" : "text-negative"}`}
            />
          )}
        </Card>
      )}

      {settlements.length > 0 && (
        <div>
          <h2 className="mb-2 px-1 text-xs font-semibold tracking-wide text-ink-muted uppercase">
            {t("balances.settleUp")}
          </h2>
          <Card className="divide-y divide-line">
            {settlements.map((payment) => (
              <div
                key={`${payment.payer}-${payment.payee}`}
                className="flex flex-wrap items-center gap-3 p-3 sm:px-4"
              >
                <span className="text-sm">
                  {t("balances.owes", {
                    payer: nameOf(payment.payer),
                    payee: nameOf(payment.payee),
                  })}
                </span>
                <span className="ms-auto flex items-center gap-3">
                  <Money amount={payment.amount} currency={currency} colour={false} />
                  {budget.can_write && payment.payer === budget.me && (
                    <SettleButton budget={budget} payee={payment.payee} amount={payment.amount} />
                  )}
                </span>
              </div>
            ))}
          </Card>
        </div>
      )}

      <div>
        <h2 className="mb-2 px-1 text-xs font-semibold tracking-wide text-ink-muted uppercase">
          {t("balances.net")}
        </h2>
        <Card className="divide-y divide-line">
          {balances.map((balance) => (
            <div key={balance.person} className="flex items-center gap-3 p-3 sm:px-4">
              <span className="text-sm font-medium">{nameOf(balance.person)}</span>
              {balance.person === budget.me && (
                <span className="rounded-full bg-brand-soft px-2 py-0.5 text-[11px] text-brand">
                  {t("common.you")}
                </span>
              )}
              <span className="ms-auto">
                <Money amount={balance.net} currency={currency} />
              </span>
            </div>
          ))}
        </Card>
      </div>
    </section>
  );
}

/**
 * Records a settlement. Offered only on the row where the signed-in person is the one who
 * owes: the API records whatever it is asked to, so a button on the other row would make it
 * one tap to move a balance the wrong way.
 */
function SettleButton({
  budget,
  payee,
  amount,
}: {
  budget: BudgetSummary;
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
    <>
      <Button
        className="min-h-9 px-3"
        disabled={settle.isPending}
        onClick={() => settle.mutate({ path: { budget: budget.slug }, body: { to: payee, amount } })}
      >
        {settle.isPending ? t("balances.settling") : t("balances.settleNow")}
      </Button>
      <FormError error={settle.error} />
    </>
  );
}
