import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listBucketsOptions,
  listDueOptions,
  listScheduledOptions,
  postScheduledMutation,
  putScheduledMutation,
} from "@/api/@tanstack/react-query.gen";
import type { BudgetSummary, ScheduledInput } from "@/api/types.gen";
import { Button, Card, Field, FormActions, FormError, Input, Select } from "@/components/Form";
import { Money } from "@/components/Money";
import { ListSkeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/States";
import { formatDate } from "@/lib/format";
import { useBudget } from "./useBudget";

const CADENCES = ["monthly", "weekly", "yearly"] as const;

/**
 * Recurring entries.
 *
 * A recurrence never posts by itself. It produces a list of charges that are *due*, and a
 * person confirms each one — so every commit in the data repo still has an author, and money
 * never appears in a budget while nobody is looking.
 */
export function ScheduledScreen() {
  const { budget, isPending } = useBudget();

  if (isPending) return <ListSkeleton rows={4} />;
  if (!budget) return <ErrorState />;

  return (
    <section className="space-y-6">
      <Due budget={budget} />
      <Templates budget={budget} />
    </section>
  );
}

function Due({ budget }: { budget: BudgetSummary }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();

  const due = useQuery(listDueOptions({ path: { budget: budget.slug } }));
  const post = useMutation({
    ...postScheduledMutation(),
    onSuccess: () => void queryClient.invalidateQueries(),
  });

  if (due.isPending) return <ListSkeleton rows={4} />;
  if (due.isError) return <ErrorState onRetry={() => void due.refetch()} />;

  const items = due.data.due;

  return (
    <div>
      <div className="mb-2 flex items-baseline gap-2">
        <h1 className="text-lg font-semibold">{t("scheduled.due")}</h1>
        {items.length > 0 && (
          <span className="numeric rounded-full bg-brand-soft px-2 py-0.5 text-xs text-brand">
            {items.length}
          </span>
        )}
      </div>

      {items.length === 0 ? (
        <Card className="p-6 text-center text-sm text-ink-muted">{t("scheduled.nothingDue")}</Card>
      ) : (
        <Card className="divide-y divide-line">
          {items.map((item) => (
            <div
              key={`${item.scheduled_id}-${item.date}`}
              className="flex flex-wrap items-center gap-3 p-3 sm:px-4"
            >
              {/* Overdue is stated in form as well as in the date — a chip reads at a glance
                  where a date only reads on inspection. */}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{item.name}</span>
                <span className="mt-0.5 flex items-center gap-2 text-xs text-ink-muted">
                  <span className="numeric">{formatDate(item.date, i18n.language)}</span>
                  {item.overdue && (
                    <span className="rounded-full bg-warning/15 px-2 py-0.5 text-[11px] text-warning">
                      {t("scheduled.overdue")}
                    </span>
                  )}
                </span>
              </span>

              <Money amount={item.amount} currency={item.currency} className="text-sm font-semibold" />

              {budget.can_write && (
                <Button
                  className="min-h-9 px-3"
                  disabled={post.isPending}
                  onClick={() =>
                    post.mutate({
                      path: { budget: budget.slug, scheduled_id: item.scheduled_id },
                      body: { date: item.date },
                    })
                  }
                >
                  {t("scheduled.post")}
                </Button>
              )}
            </div>
          ))}
        </Card>
      )}

      <FormError error={post.error} />
    </div>
  );
}

function Templates({ budget }: { budget: BudgetSummary }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const scheduled = useQuery(listScheduledOptions({ path: { budget: budget.slug } }));
  const buckets = useQuery(listBucketsOptions({ path: { budget: budget.slug } }));
  const [draft, setDraft] = useState<ScheduledInput[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  const save = useMutation({
    ...putScheduledMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      setDraft(null);
    },
  });

  if (scheduled.isPending) return <ListSkeleton rows={4} />;
  if (scheduled.isError) return <ErrorState onRetry={() => void scheduled.refetch()} />;

  const rows: ScheduledInput[] = draft ?? scheduled.data;
  const dirty = draft !== null;

  const update = (index: number, patch: Partial<ScheduledInput>) =>
    setDraft(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  return (
    <div>
      <h2 className="eyebrow mb-2">{t("scheduled.templates")}</h2>

      {rows.length === 0 && (
        <Card className="p-6 text-center text-sm text-ink-muted">{t("scheduled.none")}</Card>
      )}

      <div className="space-y-3">
        {rows.map((item, index) => (
          <Card key={index}>
            {/* A summary row, expanding to the editor. A screen of fully-expanded forms is
                unreadable on a phone, and most visits here are to check, not to edit. */}
            <button
              type="button"
              className="flex w-full items-center gap-3 p-3 text-start hover:bg-sunken sm:px-4"
              onClick={() => setOpen(open === index ? null : index)}
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {item.name || t("scheduled.untitled")}
                </span>
                <span className="mt-0.5 block truncate text-xs text-ink-muted">
                  {t(`scheduled.cadences.${item.recurrence.cadence}`)}
                  {item.paused && ` · ${t("scheduled.paused")}`}
                </span>
              </span>
              <Money
                amount={String(item.amount)}
                currency={String(item.currency)}
                className="text-sm font-semibold"
              />
            </button>

            <div
              className={`grid gap-3 border-t border-line p-4 sm:grid-cols-2 lg:grid-cols-4 ${
                open === index ? "sheet-in" : "hidden"
              }`}
            >
              <Field label={t("scheduled.name")}>
                <Input
                  value={item.name}
                  onChange={(event) => update(index, { name: event.target.value })}
                />
              </Field>
              <Field label={t("entries.payee")}>
                <Input
                  value={item.payee}
                  onChange={(event) => update(index, { payee: event.target.value })}
                />
              </Field>
              <Field label={t("entries.amount")}>
                <Input
                  className="numeric ltr-field"
                  inputMode="decimal"
                  value={String(item.amount)}
                  onChange={(event) => update(index, { amount: event.target.value })}
                />
              </Field>
              <Field label={t("entries.bucket")}>
                <Select
                  value={String(item.bucket ?? "")}
                  onChange={(event) => update(index, { bucket: event.target.value || null })}
                >
                  <option value="">—</option>
                  {(buckets.data ?? []).map((bucket) => (
                    <option key={bucket.id} value={bucket.id}>
                      {bucket.name}
                    </option>
                  ))}
                </Select>
              </Field>

              <Field label={t("scheduled.cadence")}>
                <Select
                  value={item.recurrence.cadence}
                  onChange={(event) =>
                    update(index, {
                      recurrence: {
                        ...item.recurrence,
                        cadence: event.target.value as (typeof CADENCES)[number],
                      },
                    })
                  }
                >
                  {CADENCES.map((cadence) => (
                    <option key={cadence} value={cadence}>
                      {t(`scheduled.cadences.${cadence}`)}
                    </option>
                  ))}
                </Select>
              </Field>

              {item.recurrence.cadence === "weekly" ? (
                <Field label={t("scheduled.weekday")}>
                  <Select
                    value={String(item.recurrence.weekday ?? 0)}
                    onChange={(event) =>
                      update(index, {
                        recurrence: { ...item.recurrence, weekday: Number(event.target.value) },
                      })
                    }
                  >
                    {[0, 1, 2, 3, 4, 5, 6].map((day) => (
                      <option key={day} value={day}>
                        {t(`scheduled.weekdays.${day}`)}
                      </option>
                    ))}
                  </Select>
                </Field>
              ) : (
                <Field label={t("scheduled.dayOfMonth")} hint={t("scheduled.dayHint")}>
                  <Input
                    className="numeric ltr-field"
                    inputMode="numeric"
                    value={String(item.recurrence.day ?? "")}
                    onChange={(event) =>
                      update(index, {
                        recurrence: { ...item.recurrence, day: Number(event.target.value) || null },
                      })
                    }
                  />
                </Field>
              )}

              <Field label={t("scheduled.starts")}>
                <Input
                  type="date"
                  className="numeric ltr-field"
                  value={String(item.starts)}
                  onChange={(event) => update(index, { starts: event.target.value })}
                />
              </Field>

              <div className="flex items-end gap-2">
                <label className="flex min-h-11 items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 accent-[var(--color-brand)]"
                    checked={Boolean(item.paused)}
                    onChange={(event) => update(index, { paused: event.target.checked })}
                  />
                  {t("scheduled.paused")}
                </label>
                {budget.can_write && (
                  <button
                    type="button"
                    aria-label={t("entries.delete")}
                    title={t("entries.delete")}
                    onClick={() => setDraft(rows.filter((_, i) => i !== index))}
                    className="ms-auto flex size-9 items-center justify-center rounded-lg text-negative hover:bg-negative/10"
                  >
                    ×
                  </button>
                )}
              </div>
            </div>

            {item.last_posted && (
              <p className="mt-2 text-xs text-ink-muted">
                {t("scheduled.lastPosted", { date: String(item.last_posted) })}
              </p>
            )}
          </Card>
        ))}
      </div>

      {budget.can_write && (
        <div className="mt-3">
          <FormActions
            primary={
              <Button
                disabled={!dirty || save.isPending}
                onClick={() => draft && save.mutate({ path: { budget: budget.slug }, body: draft })}
              >
                {dirty ? t("common.save") : t("rules.saved")}
              </Button>
            }
            secondary={
              <>
                <Button variant="quiet" onClick={() => setDraft([...rows, blank(rows.length)])}>
                  + {t("scheduled.add")}
                </Button>
                {dirty && (
                  <Button variant="ghost" onClick={() => setDraft(null)}>
                    {t("common.cancel")}
                  </Button>
                )}
              </>
            }
          />
        </div>
      )}

      <FormError error={save.error} />
    </div>
  );
}

function blank(count: number): ScheduledInput {
  const today = new Date().toISOString().slice(0, 10);
  return {
    id: `scheduled-${count + 1}`,
    name: "",
    payee: "",
    amount: "0.00",
    currency: "ILS",
    kind: "expense",
    recurrence: { cadence: "monthly", day: 1, interval: 1 },
    starts: today,
    shares: [],
    paid_by: {},
    tags: [],
    paused: false,
  };
}
