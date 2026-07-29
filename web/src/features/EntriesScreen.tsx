import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteEntryMutation,
  listBucketsOptions,
  listEntriesOptions,
} from "@/api/@tanstack/react-query.gen";
import type { BudgetSummary, Entry } from "@/api/types.gen";
import { Button, Card, Select } from "@/components/Form";
import { Money } from "@/components/Money";
import { ErrorState, Loading } from "@/components/States";
import { currentMonth, formatDate, formatMonth, shiftMonth } from "@/lib/format";
import { AddEntry } from "./AddEntry";
import { useBudget } from "./useBudget";

const RECENT_MONTHS = 12;

export function EntriesScreen() {
  const { t, i18n } = useTranslation();
  const { budget, isPending: budgetPending } = useBudget();
  const [month, setMonth] = useState<string>(currentMonth);
  const [bucket, setBucket] = useState("");
  const [adding, setAdding] = useState(false);

  const entries = useQuery({
    ...listEntriesOptions({
      path: { budget: budget?.slug ?? "" },
      query: { ...(month ? { month } : {}), ...(bucket ? { bucket } : {}) },
    }),
    enabled: Boolean(budget),
  });

  // Bucket ids are what an entry stores, but they are not what anyone calls them. The list
  // is fetched purely so a row can show "Eating out" instead of "eating-out".
  const buckets = useQuery({
    ...listBucketsOptions({ path: { budget: budget?.slug ?? "" } }),
    enabled: Boolean(budget),
  });

  if (budgetPending || entries.isPending) return <Loading />;
  if (entries.isError || !budget) return <ErrorState onRetry={() => void entries.refetch()} />;

  const names = new Map((buckets.data ?? []).map((item) => [item.id, item.name]));
  const months = Array.from({ length: RECENT_MONTHS }, (_, index) =>
    shiftMonth(currentMonth(), -index),
  );

  const total = entries.data.entries.reduce((sum, entry) => sum + Number(entry.amount), 0);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold">{t("entries.title")}</h1>
        <span className="text-sm text-ink-muted">
          <Money amount={total.toFixed(2)} currency={budget.currency} colour={false} />
        </span>

        <div className="ms-auto flex gap-2">
          <Select
            fullWidth={false}
            className="h-10 min-h-0 w-auto text-xs"
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
          </Select>

          <Select
            fullWidth={false}
            className="h-10 min-h-0 w-auto text-xs"
            value={bucket}
            onChange={(event) => setBucket(event.target.value)}
            aria-label={t("entries.bucket")}
          >
            <option value="">{t("entries.allBuckets")}</option>
            {(buckets.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {adding && <AddEntry budget={budget} onDone={() => setAdding(false)} />}

      {entries.data.entries.length === 0 ? (
        <Card className="p-6 text-center text-ink-muted">{t("entries.empty")}</Card>
      ) : (
        <Card className="divide-y divide-line overflow-hidden">
          {entries.data.entries.map((entry) => (
            <EntryRow key={entry.id} entry={entry} budget={budget} bucketNames={names} />
          ))}
        </Card>
      )}

      {/* A floating action on phones: adding an expense is the thing people open this for,
          and it should never be more than one thumb-reachable tap away. */}
      {budget.can_write && !adding && (
        <Button
          className="fixed end-4 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-10 shadow-lg sm:static sm:w-full sm:shadow-none"
          onClick={() => setAdding(true)}
        >
          + {t("entries.add")}
        </Button>
      )}
    </section>
  );
}

function EntryRow({
  entry,
  budget,
  bucketNames,
}: {
  entry: Entry;
  budget: BudgetSummary;
  bucketNames: Map<string, string>;
}) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  const remove = useMutation({
    ...deleteEntryMutation(),
    onSuccess: () => void queryClient.invalidateQueries(),
  });

  const mine = entry.shares
    .filter((share) => share.person === budget.me)
    .reduce((total, share) => total + Number(share.amount), 0);

  const shared = new Set(entry.shares.map((share) => share.person)).size > 1;
  const buckets = [
    ...new Set(
      entry.shares
        .map((share) => share.bucket)
        .filter((id): id is string => Boolean(id))
        .map((id) => bucketNames.get(id) ?? id),
    ),
  ];

  return (
    <div>
      <button
        type="button"
        className="flex w-full items-center gap-3 p-3 text-start hover:bg-surface sm:px-4"
        onClick={() => setOpen(!open)}
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{entry.payee}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-ink-muted">
            <span className="numeric">{formatDate(entry.date, i18n.language)}</span>
            {buckets.length > 0 && <span>· {buckets.join(", ")}</span>}
            {shared && <span>· {t("entries.shared")}</span>}
          </div>
        </div>

        <div className="text-end">
          <Money amount={entry.amount} currency={entry.currency} className="text-sm font-semibold" />
          {shared && mine !== 0 && (
            <div className="text-[11px] text-ink-muted">
              {t("entries.yourShare")}{" "}
              <Money amount={mine.toFixed(2)} currency={entry.currency} colour={false} />
            </div>
          )}
        </div>
      </button>

      {/* Details and the destructive action stay behind a tap: a delete button on every row
          is both visual noise and easy to hit by accident on a phone. */}
      {open && (
        <div className="sheet-in space-y-2 border-t border-line bg-surface/60 px-3 py-3 text-xs sm:px-4">
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {entry.shares.map((share, index) => (
              <span key={index}>
                {share.person}{" "}
                <Money amount={share.amount} currency={entry.currency} colour={false} />
                {share.bucket && ` · ${bucketNames.get(share.bucket) ?? share.bucket}`}
              </span>
            ))}
          </div>
          <div className="text-ink-muted">
            {t("entries.paidBy")}{" "}
            {Object.entries(entry.paid_by)
              .map(([person]) => person)
              .join(", ")}
            {entry.rule && ` · ${t("entries.splitBy", { rule: entry.rule })}`}
          </div>
          {entry.note && <div className="text-ink-muted">{entry.note}</div>}

          {budget.can_write && (
            <Button
              variant="danger"
              className="min-h-9 px-2"
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(t("entries.confirmDelete"))) {
                  remove.mutate({ path: { budget: budget.slug, entry_id: entry.id } });
                }
              }}
            >
              {t("entries.delete")}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
