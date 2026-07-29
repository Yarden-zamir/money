import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  assignToBucketMutation,
  closeMonthMutation,
  getMonthCloseOptions,
  getMonthOptions,
  listBucketsOptions,
  putBucketMutation,
  reopenMonthMutation,
} from "@/api/@tanstack/react-query.gen";
import type { BucketState } from "@/api/types.gen";
import { Button, Card, Field, FormActions, FormError, Input } from "@/components/Form";
import { Money } from "@/components/Money";
import { ErrorState, Loading } from "@/components/States";
import { currentMonth, formatMonth, shiftMonth } from "@/lib/format";
import { useBudget } from "./useBudget";

export function MonthScreen() {
  const { t, i18n } = useTranslation();
  const { budget, isPending: budgetPending } = useBudget();
  const [month, setMonth] = useState(currentMonth);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);

  const query = useQuery({
    ...getMonthOptions({ path: { budget: budget?.slug ?? "", month } }),
    enabled: Boolean(budget),
  });

  if (budgetPending || query.isPending) return <Loading />;
  if (query.isError || !budget) return <ErrorState onRetry={() => void query.refetch()} />;

  const view = query.data;
  const ready = Number(view.ready_to_assign);

  // Buckets are grouped the way a person thinks about them — essentials, lifestyle, goals —
  // rather than as one long list. Ungrouped buckets fall into a single trailing section.
  const groups = new Map<string, BucketState[]>();
  for (const bucket of view.buckets) {
    const key = bucket.group ?? "";
    groups.set(key, [...(groups.get(key) ?? []), bucket]);
  }

  return (
    <section className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-1">
          {/* ‹ and › are Bidi-Mirrored: the text engine flips them in RTL, so they must not
              also get .icon-directional. Flex order puts "previous" at the inline start. */}
          <Step label={t("month.previous")} onClick={() => setMonth(shiftMonth(month, -1))}>
            ‹
          </Step>
          <h1 className="min-w-36 text-center text-base font-semibold sm:min-w-44 sm:text-lg">
            {formatMonth(month, i18n.language)}
          </h1>
          <Step label={t("month.next")} onClick={() => setMonth(shiftMonth(month, 1))}>
            ›
          </Step>
        </div>

        <div className="flex items-center gap-1">
          {month !== currentMonth() && (
            <Button variant="ghost" onClick={() => setMonth(currentMonth())}>
              {t("month.today")}
            </Button>
          )}
          {budget.can_write && <CloseMonth budget={budget.slug} month={month} />}
        </div>
      </div>

      {/* Ready to assign is the number that drives every decision on this screen, so it is
          the only thing given hero treatment. */}
      <Card
        className={`p-4 ${
          ready < 0
            ? "border-negative/40 bg-negative/5"
            : ready > 0
              ? "border-brand/40 bg-brand-soft/60"
              : ""
        }`}
      >
        <div className="text-xs font-medium text-ink-muted">{t("month.readyToAssign")}</div>
        <Money
          amount={view.ready_to_assign}
          currency={view.currency}
          className="text-2xl font-semibold sm:text-3xl"
        />
      </Card>

      {view.buckets.length === 0 ? (
        <Card className="p-6 text-center text-ink-muted">{t("month.empty")}</Card>
      ) : (
        [...groups.entries()].map(([group, buckets]) => (
          <div key={group}>
            {group && (
              <h2 className="mb-2 px-1 text-xs font-semibold tracking-wide text-ink-muted uppercase">
                {group}
              </h2>
            )}
            <Card className="divide-y divide-line overflow-hidden">
              {buckets.map((bucket) => (
                <BucketRow
                  key={bucket.bucket}
                  bucket={bucket}
                  currency={view.currency}
                  budget={budget.slug}
                  month={month}
                  canWrite={budget.can_write}
                  onEdit={() => setEditing(bucket.bucket)}
                />
              ))}
            </Card>
          </div>
        ))
      )}

      {editing && (
        <EditBucket budget={budget.slug} bucketId={editing} onDone={() => setEditing(null)} />
      )}

      {budget.can_write &&
        (creating ? (
          <NewBucket budget={budget.slug} onDone={() => setCreating(false)} />
        ) : (
          <Button variant="quiet" className="w-full" onClick={() => setCreating(true)}>
            + {t("month.newBucket")}
          </Button>
        ))}
    </section>
  );
}

function BucketRow({
  bucket,
  currency,
  budget,
  month,
  canWrite,
  onEdit,
}: {
  bucket: BucketState;
  currency: string;
  budget: string;
  month: string;
  canWrite: boolean;
  onEdit: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const assign = useMutation({
    ...assignToBucketMutation(),
    onSuccess: () => void queryClient.invalidateQueries(),
  });

  const available = Number(bucket.available);
  const target = bucket.target === null ? null : Number(bucket.target);
  const assigned = Number(bucket.assigned);

  // Progress runs against the target when there is one, otherwise against what was assigned.
  // Either way the question is "how much of this envelope is gone".
  const basis = target ?? assigned;
  const spent = Math.abs(Number(bucket.activity));
  const percent = basis > 0 ? Math.min(100, Math.round((spent / basis) * 100)) : 0;
  const tone = available < 0 ? "bg-negative" : percent >= 90 ? "bg-warning" : "bg-positive";

  const shortfall = target !== null && assigned < target;

  return (
    <div className="p-3 sm:px-4">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <button
            type="button"
            className="truncate text-start text-sm font-medium hover:text-brand"
            onClick={onEdit}
            disabled={!canWrite}
          >
            {bucket.name}
          </button>
          {/* "spent / target" is a fraction: its two halves have a fixed reading order. Each
              amount is individually isolated, so without an LTR run around the pair the
              sequence itself flips in Hebrew and the target appears to come first. */}
          <div dir="ltr" className="numeric mt-0.5 flex items-center gap-1.5 text-xs text-ink-muted">
            <Money amount={bucket.activity} currency={currency} colour={false} />
            {target !== null && (
              <>
                <span aria-hidden>/</span>
                <Money amount={bucket.target ?? "0"} currency={currency} colour={false} />
              </>
            )}
          </div>
        </div>

        <div className="text-end">
          <div className="text-[11px] text-ink-muted">{t("month.available")}</div>
          <Money amount={bucket.available} currency={currency} className="text-sm font-semibold" />
        </div>

        {canWrite && (
          <AssignField
            assigned={bucket.assigned}
            pending={assign.isPending}
            onAssign={(amount) =>
              assign.mutate({ path: { budget, month }, body: { bucket: bucket.bucket, amount } })
            }
          />
        )}
      </div>

      <div className="mt-2 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
          <div className={`h-full rounded-full ${tone}`} style={{ width: `${percent}%` }} />
        </div>
        {canWrite && shortfall && (
          <button
            type="button"
            className="shrink-0 text-[11px] text-brand hover:underline"
            onClick={() =>
              assign.mutate({
                path: { budget, month },
                body: { bucket: bucket.bucket, amount: (target ?? 0).toFixed(2) },
              })
            }
          >
            {t("month.fillToTarget")}
          </button>
        )}
      </div>
    </div>
  );
}

/** Editing assigned amounts is the most repeated action here, so it happens in place. */
function AssignField({
  assigned,
  pending,
  onAssign,
}: {
  assigned: string;
  pending: boolean;
  onAssign: (amount: string) => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<string | null>(null);

  const commit = () => {
    if (draft === null) return;
    const next = draft.trim();
    if (next !== "" && Number(next) !== Number(assigned)) onAssign(Number(next).toFixed(2));
    setDraft(null);
  };

  return (
    <Input
      fullWidth={false}
      aria-label={t("month.assign")}
      className="numeric ltr-field w-24 shrink-0 text-end"
      inputMode="decimal"
      value={draft ?? Number(assigned).toFixed(2)}
      disabled={pending}
      onFocus={(event) => {
        setDraft(Number(assigned).toFixed(2));
        event.currentTarget.select();
      }}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
        if (event.key === "Escape") setDraft(null);
      }}
    />
  );
}

function NewBucket({ budget, onDone }: { budget: string; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [group, setGroup] = useState("");
  const [target, setTarget] = useState("");

  const create = useMutation({
    ...putBucketMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      onDone();
    },
  });

  // The id is derived rather than asked for. It is what the YAML and CLI use, but nobody
  // naming a bucket "Eating out" also wants to invent "eating-out".
  const id = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 39);

  return (
    <Card className="sheet-in p-4">
      <form
        className="grid gap-3 sm:grid-cols-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!id) return;
          create.mutate({
            path: { budget, bucket_id: id },
            body: {
              id,
              name: name.trim(),
              group: group.trim() || null,
              target: target ? { kind: "monthly", amount: Number(target).toFixed(2) } : null,
            },
          });
        }}
      >
        <Field label={t("month.bucketName")}>
          <Input value={name} onChange={(event) => setName(event.target.value)} autoFocus />
        </Field>
        <Field label={t("month.group")}>
          <Input value={group} onChange={(event) => setGroup(event.target.value)} />
        </Field>
        <Field label={t("month.target")}>
          <Input
            className="numeric ltr-field"
            inputMode="decimal"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            placeholder="0.00"
          />
        </Field>

        <div className="sm:col-span-3">
          <FormActions
            primary={
              <Button type="submit" disabled={!id || create.isPending}>
                {t("month.create")}
              </Button>
            }
            secondary={
              <Button type="button" variant="ghost" onClick={onDone}>
                {t("common.cancel")}
              </Button>
            }
          />
        </div>
      </form>
      <FormError error={create.error} />
    </Card>
  );
}

function Step({
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
      className="flex size-9 items-center justify-center rounded-lg text-lg text-ink-muted hover:bg-card"
    >
      {children}
    </button>
  );
}


/** Rename a bucket, change its group or target, or archive it. */
function EditBucket({
  budget,
  bucketId,
  onDone,
}: {
  budget: string;
  bucketId: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const buckets = useQuery(listBucketsOptions({ path: { budget } }));
  const existing = (buckets.data ?? []).find((item) => item.id === bucketId);

  const [name, setName] = useState("");
  const [group, setGroup] = useState("");
  const [target, setTarget] = useState("");
  const [loaded, setLoaded] = useState(false);

  if (existing && !loaded) {
    setName(existing.name);
    setGroup(existing.group ?? "");
    setTarget(existing.target?.amount != null ? String(existing.target.amount) : "");
    setLoaded(true);
  }

  const save = useMutation({
    ...putBucketMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      onDone();
    },
  });

  const submit = (archived: boolean) =>
    save.mutate({
      path: { budget, bucket_id: bucketId },
      body: {
        id: bucketId,
        name: name.trim() || bucketId,
        group: group.trim() || null,
        target: target ? { kind: "monthly", amount: Number(target).toFixed(2) } : null,
        archived,
      },
    });

  return (
    <Card className="sheet-in p-4">
      <form
        className="grid gap-3 sm:grid-cols-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit(existing?.archived ?? false);
        }}
      >
        <Field label={t("month.bucketName")}>
          <Input value={name} onChange={(event) => setName(event.target.value)} autoFocus />
        </Field>
        <Field label={t("month.group")}>
          <Input value={group} onChange={(event) => setGroup(event.target.value)} />
        </Field>
        <Field label={t("month.target")}>
          <Input
            className="numeric ltr-field"
            inputMode="decimal"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            placeholder="0.00"
          />
        </Field>

        <div className="sm:col-span-3">
          <FormActions
            primary={
              <Button type="submit" disabled={save.isPending}>
                {t("common.save")}
              </Button>
            }
            secondary={
              <Button type="button" variant="ghost" onClick={onDone}>
                {t("common.cancel")}
              </Button>
            }
            /* Archive, not delete: entries already reference this bucket and their history
               must keep resolving to a name. */
            destructive={
              <Button type="button" variant="danger" disabled={save.isPending} onClick={() => submit(true)}>
                {t("month.archive")}
              </Button>
            }
          />
        </div>
      </form>
      <FormError error={save.error} />
    </Card>
  );
}

/**
 * Closing a month tags the commit it ended on, so it can be checked out exactly as it stood.
 * It is a bookmark, not a lock — later edits to that month are still allowed.
 */
function CloseMonth({ budget, month }: { budget: string; month: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const state = useQuery(getMonthCloseOptions({ path: { budget, month } }));

  const invalidate = () => void queryClient.invalidateQueries();
  const close = useMutation({ ...closeMonthMutation(), onSuccess: invalidate });
  const reopen = useMutation({ ...reopenMonthMutation(), onSuccess: invalidate });

  if (state.isPending || state.isError) return null;
  const closed = state.data.closed;

  return (
    <Button
      variant="ghost"
      disabled={close.isPending || reopen.isPending}
      onClick={() =>
        closed
          ? reopen.mutate({ path: { budget, month } })
          : close.mutate({ path: { budget, month } })
      }
    >
      {closed ? t("month.reopen") : t("month.close")}
    </Button>
  );
}
