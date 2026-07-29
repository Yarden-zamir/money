import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteEntryMutation, listEntriesOptions } from "@/api/@tanstack/react-query.gen";
import { Button } from "@/components/Form";
import { AddEntry } from "./AddEntry";
import type { BudgetSummary, Entry } from "@/api/types.gen";
import { Money } from "@/components/Money";
import { Empty, ErrorState, Loading } from "@/components/States";
import { currentMonth, formatDate, formatMonth, shiftMonth } from "@/lib/format";
import { useBudget } from "./useBudget";

const RECENT_MONTHS = 12;

export function EntriesScreen() {
  const { t, i18n } = useTranslation();
  const { budget, isPending: budgetPending } = useBudget();
  const [month, setMonth] = useState<string>(currentMonth);
  const [adding, setAdding] = useState(false);

  const query = useQuery({
    ...listEntriesOptions({
      path: { budget: budget?.slug ?? "" },
      query: month ? { month } : {},
    }),
    enabled: Boolean(budget),
  });

  if (budgetPending || query.isPending) return <Loading />;
  if (query.isError || !budget) return <ErrorState onRetry={() => void query.refetch()} />;

  const months = Array.from({ length: RECENT_MONTHS }, (_, index) =>
    shiftMonth(currentMonth(), -index),
  );

  return (
    <section>
      <header className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">{t("entries.title")}</h1>
        {budget.can_write && !adding && (
          <Button onClick={() => setAdding(true)}>{t("entries.add")}</Button>
        )}
        <select
          className="ms-auto rounded-md border border-line bg-surface px-2 py-1 text-sm"
          value={month}
          onChange={(event) => setMonth(event.target.value)}
          aria-label={t("entries.filterMonth")}
        >
          <option value="">{t("entries.filterAll")}</option>
          {months.map((candidate) => (
            <option key={candidate} value={candidate}>
              {formatMonth(candidate, i18n.language)}
            </option>
          ))}
        </select>
      </header>

      {adding && <AddEntry budget={budget} onDone={() => setAdding(false)} />}

      {query.data.entries.length === 0 ? (
        <Empty message={t("entries.empty")} />
      ) : (
        <ul className="divide-y divide-line rounded-lg ring-1 ring-line">
          {query.data.entries.map((entry) => (
            <EntryRow key={entry.id} entry={entry} budget={budget} />
          ))}
        </ul>
      )}
    </section>
  );
}

function EntryRow({ entry, budget }: { entry: Entry; budget: BudgetSummary }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const me = budget.me;

  const remove = useMutation({
    ...deleteEntryMutation(),
    onSuccess: () => void queryClient.invalidateQueries(),
  });

  // The split is the interesting part of this app, so a row shows both dimensions: what the
  // whole thing cost, and what it cost *you*.
  const yourShare = entry.shares
    .filter((share) => share.person === me)
    .reduce((total, share) => total + Number(share.amount), 0);
  const buckets = [...new Set(entry.shares.map((s) => s.bucket).filter(Boolean))];
  const payers = Object.keys(entry.paid_by);

  return (
    <li className="flex flex-wrap items-baseline gap-x-4 gap-y-1 p-3">
      <span className="w-16 shrink-0 text-sm text-ink-muted numeric">
        {formatDate(entry.date, i18n.language)}
      </span>

      <span className="font-medium">{entry.payee}</span>

      <span className="text-xs text-ink-muted">
        {buckets.join(", ")}
        {buckets.length > 0 && payers.length > 0 && " · "}
        {payers.length > 0 && `${t("entries.paidBy")} ${payers.join(", ")}`}
      </span>

      <span className="ms-auto flex items-baseline gap-3">
        {me && yourShare !== 0 && (
          <span className="text-xs text-ink-muted">
            {t("entries.yourShare")}{" "}
            <Money amount={yourShare.toFixed(2)} currency={entry.currency} colour={false} />
          </span>
        )}
        <Money amount={entry.amount} currency={entry.currency} className="font-medium" />
        {budget.can_write && (
          <button
            type="button"
            className="text-xs text-ink-muted hover:text-negative"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(t("entries.confirmDelete"))) {
                remove.mutate({
                  path: { budget: budget.slug, entry_id: entry.id },
                });
              }
            }}
          >
            {t("entries.delete")}
          </button>
        )}
      </span>
    </li>
  );
}
