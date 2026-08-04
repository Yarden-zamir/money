import { useState } from "react";
import { useTranslation } from "react-i18next";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Bar, LedgerSkeleton, SummarySkeleton } from "@/components/Skeleton";
import { BAR_TONES, bucketBar } from "@/lib/bucket";
import { lastWriteWins } from "@/lib/optimistic";

import {
  assignToBucketMutation,
  autoAssignMutation,
  moveMoneyMutation,
  closeMonthMutation,
  getMonthCloseOptions,
  getMonthOptions,
  getMonthQueryKey,
  listBucketsOptions,
  putBucketMutation,
  reopenMonthMutation,
} from "@/api/@tanstack/react-query.gen";
import type { BucketState, MonthResponse } from "@/api/types.gen";
import { Button, Card, Field, FormActions, FormError, Input, Select } from "@/components/Form";
import { Icon } from "@/components/Icon";
import { useCountUp } from "@/lib/useCountUp";
import { Money } from "@/components/Money";
import { ErrorState } from "@/components/States";
import { currentMonth, formatMonth, shiftMonth } from "@/lib/format";
import { InlineEdit } from "@/components/InlineEdit";
import { useBudget } from "./useBudget";

/**
 * The envelope view.
 *
 * Laid out as a ledger, not as a list of cards: one set of column headers, amounts in a
 * monospace column, and the row itself carrying no repeated labels. The previous version
 * printed "Available" on every single row, which is noise once there is more than one.
 */
export function MonthScreen() {
  const { t, i18n } = useTranslation();
  const { budget, isPending: budgetPending } = useBudget();
  const [month, setMonth] = useState(currentMonth);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);

  const query = useQuery({
    ...getMonthOptions({ path: { budget: budget?.slug ?? "", month } }),
    enabled: Boolean(budget),
    // Stepping to another month keeps the one on screen until the new one arrives. Blanking
    // the whole ledger to the word "Loading…" made a 100ms fetch feel like a page load, and
    // it destroys the scroll position on the way back.
    placeholderData: keepPreviousData,
  });
  const buckets = useQuery({
    ...listBucketsOptions({ path: { budget: budget?.slug ?? "" } }),
    enabled: Boolean(budget),
  });

  const queryClient = useQueryClient();
  const put = useMutation({
    ...putBucketMutation(),
    // A drag fires this once per bucket whose position changed, all at once. Invalidating
    // per write let the first one to land wipe out the others while they were still in
    // flight, which is a reorder undoing itself on screen.
    onSettled: lastWriteWins(queryClient),
  });

  /**
   * Move a bucket, possibly into a different group.
   *
   * Order is stored per bucket rather than as a list, so this writes only the buckets whose
   * position or group actually changed — two people rearranging different groups at once do
   * not overwrite each other.
   *
   * Dropping onto a row puts the bucket at that row's position *and* adopts that row's
   * group, which is what makes dragging between groups work without a separate gesture.
   */
  const applyMove = (draggedId: string, targetGroup: string, beforeId: string | null) => {
    if (!budget || draggedId === beforeId) return;

    const byId = new Map((buckets.data ?? []).map((item) => [item.id, item]));
    const byGroup = new Map<string, string[]>();
    for (const bucket of view.buckets) {
      const key = bucket.group ?? "";
      byGroup.set(key, [...(byGroup.get(key) ?? []), bucket.bucket]);
    }

    // Lift the dragged bucket out of wherever it currently sits before re-inserting it, so
    // a move within its own group does not leave a duplicate behind.
    for (const [name, ids] of byGroup) {
      byGroup.set(
        name,
        ids.filter((id) => id !== draggedId),
      );
    }

    const target = byGroup.get(targetGroup) ?? [];
    const at = beforeId ? target.indexOf(beforeId) : target.length;
    target.splice(at < 0 ? target.length : at, 0, draggedId);
    byGroup.set(targetGroup, target);

    // Reorder the cached month first so the row lands where it was dropped, rather than
    // snapping back until several writes have made the round trip.
    const order = [...byGroup.entries()].flatMap(([name, ids]) =>
      ids.map((id) => ({ id, group: name })),
    );
    const monthKey = getMonthQueryKey({ path: { budget: budget.slug, month } });
    const cached = queryClient.getQueryData<MonthResponse>(monthKey);
    if (cached) {
      const byBucket = new Map(cached.buckets.map((bucket) => [bucket.bucket, bucket]));
      queryClient.setQueryData<MonthResponse>(monthKey, {
        ...cached,
        buckets: order
          .map(({ id, group: name }) => {
            const existing = byBucket.get(id);
            return existing ? { ...existing, group: name || null } : null;
          })
          .filter((bucket): bucket is BucketState => bucket !== null),
      });
    }

    for (const [name, ids] of byGroup) {
      void name;
      ids.forEach((id, index) => {
        const existing = byId.get(id);
        if (!existing) return;

        const nextGroup = id === draggedId ? targetGroup || null : existing.group;
        if (existing.order === index && existing.group === nextGroup) return;

        put.mutate({
          path: { budget: budget.slug, bucket_id: id },
          body: { ...existing, group: nextGroup, order: index },
        });
      });
    }
  };

  /** The keyboard equivalent: nudge one place within the same group. */
  const nudge = (group: string, id: string, delta: number) => {
    const ids = view.buckets
      .filter((bucket) => (bucket.group ?? "") === group)
      .map((bucket) => bucket.bucket);
    const from = ids.indexOf(id);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= ids.length) return;

    const without = ids.filter((each) => each !== id);
    applyMove(id, group, without[to] ?? null);
  };

  // putBucket replaces the whole bucket, so an inline edit of one field has to merge into
  // the current one — sending a partial would silently clear the group and the target.
  const patchBucket = (id: string, patch: { name?: string; target?: string }) => {
    const existing = (buckets.data ?? []).find((item) => item.id === id);
    if (!existing || !budget) return;

    const target =
      patch.target === undefined
        ? existing.target
        : patch.target.trim() === ""
          ? null
          : { kind: "monthly", amount: Number(patch.target).toFixed(2) };

    put.mutate({
      path: { budget: budget.slug, bucket_id: id },
      body: {
        id,
        name: patch.name ?? existing.name,
        group: existing.group,
        archived: existing.archived,
        order: existing.order,
        target,
      },
    });
  };

  if (query.isError || !budget) return <ErrorState onRetry={() => void query.refetch()} />;
  if (budgetPending || query.isPending) {
    return (
      <section className="space-y-4" aria-busy>
        <header className="flex items-center gap-0.5">
          <Bar className="h-9 w-9 rounded-lg" />
          <Bar className="h-5 w-40" />
          <Bar className="h-9 w-9 rounded-lg" />
        </header>
        <SummarySkeleton />
        <LedgerSkeleton />
      </section>
    );
  }

  const view = query.data;
  const overspent = view.buckets.filter((bucket) => Number(bucket.available) < 0);

  const groups = new Map<string, BucketState[]>();
  for (const bucket of view.buckets) {
    const key = bucket.group ?? "";
    groups.set(key, [...(groups.get(key) ?? []), bucket]);
  }

  return (
    // While the next month is loading the previous one stays on screen. Dimmed, because the
    // figures below no longer match the month named above them, and a stale number presented
    // as current is worse than a wait.
    <section
      className={`space-y-4 transition-opacity ${query.isPlaceholderData ? "opacity-60" : ""}`}
      aria-busy={query.isPlaceholderData}
    >
      <header className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-0.5">
          {/* ‹ and › are Bidi-Mirrored: the text engine flips them in RTL, so they must not
              also get .icon-directional. Flex order puts "previous" at the inline start. */}
          <Step label={t("month.previous")} onClick={() => setMonth(shiftMonth(month, -1))}>
            ‹
          </Step>
          <h1 className="min-w-32 text-center text-base font-semibold sm:min-w-40">
            {formatMonth(month, i18n.language)}
          </h1>
          <Step label={t("month.next")} onClick={() => setMonth(shiftMonth(month, 1))}>
            ›
          </Step>
        </div>

        <div className="ms-auto flex items-center gap-1">
          {month !== currentMonth() && (
            <Button variant="ghost" className="min-h-9 px-3" onClick={() => setMonth(currentMonth())}>
              {t("month.today")}
            </Button>
          )}
          {budget.can_write && <CloseMonth budget={budget.slug} month={month} />}
        </div>
      </header>

      {/* A summary strip, not a hero number. "Ready to assign" alone cannot answer whether
          anything is overspent, or how much of the month's income is already committed. */}
      <Card className="grid grid-cols-2 divide-line sm:grid-cols-4 sm:divide-x rtl:sm:divide-x-reverse">
        <Stat label={t("month.income")} amount={view.income} currency={view.currency} />
        <Stat label={t("month.assigned")} amount={view.assigned} currency={view.currency} muted />
        <Stat
          label={t("month.readyToAssign")}
          amount={view.ready_to_assign}
          currency={view.currency}
          emphasis
          animate
        />
        <div className="border-t border-line p-3 sm:border-t-0">
          <div className="eyebrow">{t("month.overspent")}</div>
          <div
            className={`numeric mt-0.5 text-lg font-semibold ${
              overspent.length ? "text-negative" : "text-ink-muted"
            }`}
          >
            {overspent.length}
          </div>
        </div>
      </Card>

      {budget.can_write && view.buckets.length > 0 && (
        <MonthActions budget={budget.slug} month={month} buckets={view.buckets} />
      )}

      {view.buckets.length === 0 ? (
        <Card className="p-8 text-center text-sm text-ink-muted">{t("month.empty")}</Card>
      ) : (
        <Card className="overflow-hidden">
          {/* Column headers once, at the top — not repeated as a label on every row. */}
          <div className="hidden items-center gap-3 border-b border-line px-4 py-2 sm:flex">
            <span className="eyebrow flex-1">{t("month.bucket")}</span>
            <span className="eyebrow w-28 text-end">{t("month.activity")}</span>
            <span className="eyebrow w-28 text-end">{t("month.available")}</span>
            <span className="eyebrow w-24 text-end">{t("month.assigned")}</span>
          </div>

          {[...groups.entries()].map(([group, buckets_]) => (
            <div key={group}>
              {group && (
                <div
                  onDragOver={(event) => {
                    if (dragging) event.preventDefault();
                  }}
                  onDrop={() => {
                    if (dragging) applyMove(dragging, group, null);
                    setDragging(null);
                    setDropTarget(null);
                  }}
                  className={`flex items-baseline gap-2 bg-sunken px-4 py-1.5 ${
                    dragging ? "outline-1 outline-dashed outline-brand/40" : ""
                  }`}
                >
                  <span className="eyebrow">{group}</span>
                  {/* A group subtotal: the question "can this category cover the rest of the
                      month" is about the group, not any single envelope in it. */}
                  <span className="ms-auto text-xs text-ink-muted">
                    <Money
                      amount={buckets_
                        .reduce((total, bucket) => total + Number(bucket.available), 0)
                        .toFixed(2)}
                      currency={view.currency}
                      colour={false}
                    />
                  </span>
                </div>
              )}
              {buckets_.map((bucket) => (
                <BucketRow
                  key={bucket.bucket}
                  bucket={bucket}
                  currency={view.currency}
                  budget={budget.slug}
                  month={month}
                  canWrite={budget.can_write}
                  onEdit={() => setEditing(bucket.bucket)}
                  onRename={(name) => patchBucket(bucket.bucket, { name })}
                  onRetarget={(value) => patchBucket(bucket.bucket, { target: value })}
                  dragging={dragging === bucket.bucket}
                  dropBefore={dropTarget === bucket.bucket && dragging !== bucket.bucket}
                  onDragStart={() => setDragging(bucket.bucket)}
                  onDragEnd={() => {
                    setDragging(null);
                    setDropTarget(null);
                  }}
                  onDragOverRow={() => setDropTarget(bucket.bucket)}
                  onDropOn={() => {
                    if (dragging) applyMove(dragging, group, bucket.bucket);
                    setDragging(null);
                    setDropTarget(null);
                  }}
                  onMove={(delta) => nudge(group, bucket.bucket, delta)}
                />
              ))}
            </div>
          ))}
        </Card>
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

/**
 * Bulk assignment and moving money.
 *
 * Funding envelopes one at a time is the most repeated chore in envelope budgeting, and
 * covering an overspend by editing two figures means doing the arithmetic yourself and
 * leaving the budget briefly wrong between the two saves.
 */
function MonthActions({
  budget,
  month,
  buckets,
}: {
  budget: string;
  month: string;
  buckets: BucketState[];
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [moving, setMoving] = useState(false);

  const auto = useMutation({
    ...autoAssignMutation(),
    onSettled: lastWriteWins(queryClient),
  });

  const STRATEGIES = [
    ["underfunded", t("month.underfunded")],
    ["assigned_last_month", t("month.assignedLastMonth")],
    ["spent_last_month", t("month.spentLastMonth")],
  ] as const;

  return (
    <div className="space-y-3">
      <div className="-mx-4 flex items-center gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0">
        <span className="eyebrow shrink-0">{t("month.autoAssign")}</span>
        {STRATEGIES.map(([strategy, label]) => (
          <Button
            key={strategy}
            variant="quiet"
            className="min-h-9 shrink-0 px-3 text-xs"
            disabled={auto.isPending}
            onClick={() => auto.mutate({ path: { budget, month }, body: { strategy } })}
          >
            {/* Named, not just disabled. This writes to git, so it is never instant, and a
                greyed-out button with nothing else moving reads as a broken one. */}
            {auto.isPending && auto.variables?.body.strategy === strategy
              ? t("month.assigning")
              : label}
          </Button>
        ))}
        <Button
          variant="quiet"
          className="min-h-9 shrink-0 px-3 text-xs sm:ms-auto"
          onClick={() => setMoving(!moving)}
        >
          <Icon name="swap" className="size-4" />
          {t("month.move")}
        </Button>
      </div>

      {moving && <MoveMoney budget={budget} month={month} buckets={buckets} onDone={() => setMoving(false)} />}
      <FormError error={auto.error} />
    </div>
  );
}

function MoveMoney({
  budget,
  month,
  buckets,
  onDone,
}: {
  budget: string;
  month: string;
  buckets: BucketState[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [source, setSource] = useState(buckets[0]?.bucket ?? "");
  const [target, setTarget] = useState(buckets[1]?.bucket ?? "");
  const [amount, setAmount] = useState("");

  const move = useMutation({
    ...moveMoneyMutation(),
    onSettled: lastWriteWins(queryClient),
    onSuccess: () => {
      onDone();
    },
  });

  return (
    <Card className="sheet-in p-4">
      <form
        className="grid gap-3 sm:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!amount) return;
          move.mutate({
            path: { budget, month },
            body: { source, target, amount: Math.abs(Number(amount)).toFixed(2) },
          });
        }}
      >
        <Field label={t("month.moveFrom")}>
          <Select value={source} onChange={(event) => setSource(event.target.value)}>
            {buckets.map((bucket) => (
              <option key={bucket.bucket} value={bucket.bucket}>
                {bucket.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("month.moveTo")}>
          <Select value={target} onChange={(event) => setTarget(event.target.value)}>
            {buckets.map((bucket) => (
              <option key={bucket.bucket} value={bucket.bucket}>
                {bucket.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("entries.amount")}>
          <Input
            className="numeric ltr-field"
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            placeholder="0.00"
            autoFocus
          />
        </Field>
        <div className="flex items-end">
          <FormActions
            primary={
              <Button type="submit" disabled={!amount || move.isPending}>
                {t("month.move")}
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
      <FormError error={move.error} />
    </Card>
  );
}

function Stat({
  label,
  amount,
  currency,
  emphasis,
  muted,
  animate,
}: {
  label: string;
  amount: string;
  currency: string;
  emphasis?: boolean;
  muted?: boolean;
  animate?: boolean;
}) {
  // Only the headline figure counts up. A row of numbers all animating at once is noise, and
  // a figure still in motion cannot be compared against the one beside it.
  const counted = useCountUp(animate ? Number(amount) : Number.NaN);
  const shown = animate && Number.isFinite(counted) ? counted.toFixed(2) : amount;

  return (
    <div className="p-3">
      <div className="eyebrow">{label}</div>
      <Money
        amount={shown}
        currency={currency}
        colour={Boolean(emphasis)}
        className={`mt-0.5 block ${emphasis ? "text-lg font-semibold" : "text-lg"} ${
          muted ? "text-ink-muted" : ""
        }`}
      />
    </div>
  );
}

/** Patch one bucket's figures in the cached month, so the row moves before the server does. */
function patchMonth(view: MonthResponse, bucketId: string, assigned: number): MonthResponse {
  return {
    ...view,
    buckets: view.buckets.map((bucket) => {
      if (bucket.bucket !== bucketId) return bucket;
      // Available shifts by the same delta as assigned: the money came from somewhere.
      const delta = assigned - Number(bucket.assigned);
      return {
        ...bucket,
        assigned: assigned.toFixed(2),
        available: (Number(bucket.available) + delta).toFixed(2),
      };
    }),
    assigned: (
      Number(view.assigned) +
      (assigned -
        Number(view.buckets.find((bucket) => bucket.bucket === bucketId)?.assigned ?? 0))
    ).toFixed(2),
    ready_to_assign: (
      Number(view.ready_to_assign) -
      (assigned -
        Number(view.buckets.find((bucket) => bucket.bucket === bucketId)?.assigned ?? 0))
    ).toFixed(2),
  };
}

function BucketRow({
  bucket,
  currency,
  budget,
  month,
  canWrite,
  onEdit,
  onRename,
  onRetarget,
  dragging,
  dropBefore,
  onDragStart,
  onDragEnd,
  onDragOverRow,
  onDropOn,
  onMove,
}: {
  bucket: BucketState;
  currency: string;
  budget: string;
  month: string;
  canWrite: boolean;
  onEdit: () => void;
  onRename: (name: string) => void;
  onRetarget: (target: string) => void;
  dragging: boolean;
  dropBefore: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDragOverRow: () => void;
  onDropOn: () => void;
  onMove: (delta: number) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [armed, setArmed] = useState(false);

  const monthKey = getMonthQueryKey({ path: { budget, month } });
  const assign = useMutation({
    ...assignToBucketMutation(),
    // The figure moves on keypress; the request confirms it and the rollback undoes it if
    // the server disagrees, so an optimistic value never becomes the truth.
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: monthKey });
      const previous = queryClient.getQueryData<MonthResponse>(monthKey);
      if (previous) {
        queryClient.setQueryData<MonthResponse>(
          monthKey,
          patchMonth(previous, bucket.bucket, Number(variables.body.amount)),
        );
      }
      return { previous };
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(monthKey, context.previous);
    },
    onSettled: lastWriteWins(queryClient),
  });

  const available = Number(bucket.available);
  const target = bucket.target === null ? null : Number(bucket.target);
  const assigned = Number(bucket.assigned);

  const { percent, tone } = bucketBar(available, Number(bucket.activity));

  return (
    // The severity edge marks the one state that needs acting on. It is not decoration —
    // rows that are fine carry no edge at all.
    <div
      // Names the row for tests. Reordering is the part of this screen that has regressed
      // most often, and asserting it needs the DOM order of buckets to be readable without
      // depending on a translated label.
      data-bucket={bucket.bucket}
      // Draggable only once the handle is pressed. A permanently draggable row containing an
      // input cannot be clicked into or selected in — the browser starts a drag instead.
      draggable={canWrite && armed}
      onDragStart={(event) => {
        // Firefox refuses to start a drag without payload, and without an explicit effect
        // the cursor never shows a move affordance.
        event.dataTransfer.setData("text/plain", bucket.bucket);
        event.dataTransfer.effectAllowed = "move";
        onDragStart();
      }}
      onDragEnd={() => {
        setArmed(false);
        onDragEnd();
      }}
      onDragOver={(event) => {
        if (!canWrite) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        onDragOverRow();
      }}
      onDrop={(event) => {
        event.preventDefault();
        onDropOn();
      }}
      className={`border-b border-line px-4 py-2.5 last:border-b-0 ${
        available < 0 ? "border-s-2 border-s-negative" : ""
      } ${dragging ? "opacity-40" : ""} ${
        dropBefore ? "border-t-2 border-t-brand" : ""
      }`}
    >
      <div className="flex items-center gap-3">
        {canWrite && (
          <span className="flex items-center">
            {/* Dragging is a mouse gesture, so the handle is also a pair of keyboard
                controls — reordering must not be reachable by pointer only. */}
            <span
              aria-hidden
              onMouseDown={() => setArmed(true)}
              onMouseUp={() => setArmed(false)}
              className="drag-handle cursor-grab touch-none text-ink-muted active:cursor-grabbing"
              title={t("month.reorder")}
            >
              <Icon name="drag" className="size-4" />
            </span>
            <span className="sr-only-controls flex flex-col">
              <button
                type="button"
                aria-label={t("rules.moveUp")}
                onClick={() => onMove(-1)}
                className="text-[9px] leading-none text-ink-muted hover:text-brand"
              >
                ▲
              </button>
              <button
                type="button"
                aria-label={t("rules.moveDown")}
                onClick={() => onMove(1)}
                className="text-[9px] leading-none text-ink-muted hover:text-brand"
              >
                ▼
              </button>
            </span>
          </span>
        )}
        <span className="min-w-0 flex-1">
          <InlineEdit
            label={t("month.bucketName")}
            value={bucket.name}
            disabled={!canWrite}
            className="block truncate text-sm font-medium"
            inputClassName="text-sm font-medium"
            onCommit={(name) => onRename(name)}
          />
          {/* The monthly target belongs on the row: "how much was this meant to be" is the
              question the assigned figure is answered against. */}
          <span className="mt-0.5 flex items-center gap-1.5 text-[11px] whitespace-nowrap text-ink-muted">
            <Icon name="target" className="size-3" />
            <InlineEdit
              label={t("month.target")}
              value={target === null ? "" : target.toFixed(2)}
              disabled={!canWrite}
              inputMode="decimal"
              placeholder={t("month.noTarget")}
              className="numeric"
              inputClassName="numeric w-20"
              onCommit={(next) => onRetarget(next)}
            />
            <button
              type="button"
              className="ms-1 hover:text-brand"
              onClick={onEdit}
              title={t("month.moreOptions")}
            >
              <Icon name="sliders" className="size-3.5" />
            </button>
          </span>
        </span>

        <span className="hidden w-28 text-end text-sm sm:block">
          <Money amount={bucket.activity} currency={currency} colour={false} />
        </span>
        <span className="w-28 text-end text-sm font-semibold">
          <Money amount={bucket.available} currency={currency} />
        </span>

        {canWrite ? (
          <AssignField
            assigned={bucket.assigned}
            pending={assign.isPending}
            onAssign={(amount) =>
              assign.mutate({ path: { budget, month }, body: { bucket: bucket.bucket, amount } })
            }
          />
        ) : (
          <span className="w-24 text-end text-sm text-ink-muted">
            <Money amount={bucket.assigned} currency={currency} colour={false} />
          </span>
        )}
      </div>

      <div className="mt-2 flex items-center gap-3">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-line">
          <div className={`h-full ${BAR_TONES[tone]}`} style={{ width: `${percent}%` }} />
        </div>
        {/* Only shown when acting on it would change something. */}
        {canWrite && target !== null && assigned < target && (
          <button
            type="button"
            className="shrink-0 text-[11px] text-brand hover:underline"
            onClick={() =>
              assign.mutate({
                path: { budget, month },
                body: { bucket: bucket.bucket, amount: target.toFixed(2) },
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
      // Quiet until touched, so a column of them does not read as a wall of boxes — but it
      // still has to look editable, hence the border on hover and focus.
      className="numeric ltr-field min-h-9 w-24 border-transparent bg-transparent px-2 text-end hover:border-line focus:bg-card"
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
    onSettled: lastWriteWins(queryClient),
    onSuccess: () => {
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
    onSettled: lastWriteWins(queryClient),
    onSuccess: () => {
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
              <Button
                type="button"
                variant="danger"
                disabled={save.isPending}
                onClick={() => submit(true)}
              >
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

  const invalidate = lastWriteWins(queryClient);
  const close = useMutation({ ...closeMonthMutation(), onSettled: invalidate });
  const reopen = useMutation({ ...reopenMonthMutation(), onSettled: invalidate });

  if (state.isPending || state.isError) return null;
  const closed = state.data.closed;

  return (
    <Button
      variant={closed ? "quiet" : "ghost"}
      className="min-h-9 px-3"
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
