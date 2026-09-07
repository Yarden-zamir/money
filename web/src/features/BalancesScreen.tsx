import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getBalancesOptions, settleUpMutation } from "@/api/@tanstack/react-query.gen";
import type { BudgetSummary } from "@/api/types.gen";
import { ForeignChips } from "@/components/Foreign";
import { Button, Card, FormError } from "@/components/Form";
import { Money } from "@/components/Money";
import { ListSkeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/States";
import { useBudget } from "./useBudget";

export function BalancesScreen() {
  const { t } = useTranslation();
  const { budget, isPending: budgetPending } = useBudget();

  const query = useQuery({
    ...getBalancesOptions({ path: { budget: budget?.slug ?? "" } }),
    enabled: Boolean(budget),
  });

  if (query.isError || !budget) return <ErrorState onRetry={() => void query.refetch()} />;
  if (budgetPending || query.isPending) return <ListSkeleton rows={3} />;

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
                  <Money amount={payment.amount} currency={payment.currency} colour={false} />
                  {budget.can_write && (payment.payer === budget.me || payment.payee === budget.me) && (
                    <SettleButton
                      budget={budget}
                      payment={payment}
                      nameOf={nameOf}
                    />
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
              <span className="ms-auto flex flex-wrap items-center justify-end gap-2">
                <ForeignChips foreign={balance.foreign} />
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
 * Records a settlement, from either side.
 *
 * Only the payer can record a payment through the API, because a settlement is authored by
 * whoever made it. But the person who is *owed* is usually the one holding the phone when
 * the money arrives, and if their partner does not use the app nobody could ever record it.
 * So this offers the matching wording on both rows and states plainly which way it moves.
 */
function SettleButton({
  budget,
  payment,
  nameOf,
}: {
  budget: BudgetSummary;
  payment: { payer: string; payee: string; amount: string; currency: string };
  nameOf: (person: string) => string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const iOwe = payment.payer === budget.me;

  const settle = useMutation({
    ...settleUpMutation(),
    onSuccess: () => void queryClient.invalidateQueries(),
  });

  const label = iOwe
    ? t("balances.iPaid", { person: nameOf(payment.payee) })
    : t("balances.theyPaid", { person: nameOf(payment.payer) });

  return (
    <>
      <Button
        className="min-h-9 px-3"
        disabled={settle.isPending}
        title={label}
        onClick={() => {
          if (!window.confirm(label)) return;
          // The payer is stated explicitly. Without it the API would assume the caller
          // paid, which records the payment backwards when the person owed presses this.
          settle.mutate({
            path: { budget: budget.slug },
            body: {
              payer: payment.payer,
              to: payment.payee,
              amount: payment.amount,
              currency: payment.currency,
            },
          });
        }}
      >
        {settle.isPending ? t("balances.settling") : t("balances.settleNow")}
      </Button>
      <FormError error={settle.error} />
    </>
  );
}
