import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  assignToBucketMutation,
  getMonthOptions,
  putBucketMutation,
} from "@/api/@tanstack/react-query.gen";
import { Button, Input } from "@/components/Form";
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

      {budget.can_write && <NewBucket budget={budget.slug} />}

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
                    {budget.can_write ? (
                      <AssignCell
                        budget={budget.slug}
                        month={month}
                        bucket={bucket.bucket}
                        assigned={bucket.assigned}
                      />
                    ) : (
                      <Money amount={bucket.assigned} currency={view.currency} colour={false} />
                    )}
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

/** Assigning is the most repeated action in envelope budgeting, so it is edited in place. */
function AssignCell({
  budget,
  month,
  bucket,
  assigned,
}: {
  budget: string;
  month: string;
  bucket: string;
  assigned: string;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);

  const assign = useMutation({
    ...assignToBucketMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      setDraft(null);
    },
  });

  const commit = () => {
    if (draft === null) return;
    if (draft.trim() === "" || Number(draft) === Number(assigned)) {
      setDraft(null);
      return;
    }
    assign.mutate({
      path: { budget, month },
      body: { bucket, amount: Number(draft).toFixed(2) },
    });
  };

  return (
    <Input
      className="numeric w-24 text-end"
      inputMode="decimal"
      value={draft ?? assigned}
      onFocus={() => setDraft(assigned)}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
        if (event.key === "Escape") setDraft(null);
      }}
      disabled={assign.isPending}
    />
  );
}

function NewBucket({ budget }: { budget: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [id, setId] = useState("");

  const create = useMutation({
    ...putBucketMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      setName("");
      setId("");
    },
  });

  // A readable id is derived from the name, but stays editable: it is what the CLI and the
  // YAML files use, so it should not be a slugified surprise.
  const suggested = id || name.trim().toLowerCase().replace(/\s+/g, "-").slice(0, 39);

  return (
    <form
      className="mb-4 flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (!name.trim() || !suggested) return;
        create.mutate({
          path: { budget, bucket_id: suggested },
          body: { id: suggested, name: name.trim() },
        });
      }}
    >
      <Input
        className="w-48"
        placeholder={t("month.bucketName")}
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <Input
        className="w-40"
        dir="ltr"
        placeholder={t("month.bucketId")}
        value={suggested}
        onChange={(event) => setId(event.target.value)}
      />
      <Button type="submit" disabled={!name.trim() || create.isPending}>
        {t("month.create")}
      </Button>
    </form>
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
