import { useState } from "react";
import { useTranslation } from "react-i18next";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Bar, LedgerSkeleton, SummarySkeleton } from "@/components/Skeleton";
import { FunderBreakdown, FundingBar, MemberDot } from "@/components/FunderBars";
import { splitFor } from "@/lib/members";
import { lastWriteWins } from "@/lib/optimistic";

import {
  assignToBucketMutation,
  autoAssignMutation,
  moveMoneyMutation,
  getMonthOptions,
  getMonthQueryKey,
  listBucketsOptions,
  putBucketMutation,
  reorderBucketsMutation,
} from "@/api/@tanstack/react-query.gen";
import type { BucketState, Member, MonthResponse } from "@/api/types.gen";
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
  const reorder = useMutation({
    ...reorderBucketsMutation(),
    onSettled: lastWriteWins(queryClient),
  });

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

    // One request for the whole gesture. Sending a bucket at a time meant N writes to the
    // same file, each with its own round trip, and a failure partway left a half-applied
    // order. The server takes position from the sequence rather than from an index this
    // client computes, so the only thing sent is the order actually on screen.
    reorder.mutate({
      path: { budget: budget.slug },
      body: {
        order: order
          .filter(({ id }) => byId.has(id))
          .map(({ id, group: name }) => ({ bucket: id, group: name || null })),
      },
    });
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
      {/* Who each colour is, and how to read the bars. Without it the segments are pretty
          and meaningless. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {budget.members.map((member) => (
          <span key={member.person} className="flex items-center gap-1.5 text-xs text-ink-muted">
            <MemberDot person={member.person} members={budget.members} />
            {member.name}
          </span>
        ))}
      </div>

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
        </div>
      </header>

      {/* A summary strip, not a hero number. "Ready to assign" alone cannot answer whether
          anything is overspent, or how much of the month's income is already committed. */}
      <Card className="grid grid-cols-2 divide-line sm:grid-cols-4 sm:divide-x rtl:sm:divide-x-reverse">
        <Stat label={t("month.yourIncome")} amount={view.income} currency={view.currency} />
        <Stat label={t("month.yourFunding")} amount={view.assigned} currency={view.currency} muted />
        <Stat
          label={t("month.yourReadyToAssign")}
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
            <span className="eyebrow w-24 text-end">{t("month.yourFunding")}</span>
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
                  members={budget.members}
                  me={view.person}
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
        <EditBucket
          budget={budget.slug}
          bucketId={editing}
          members={budget.members}
          onDone={() => setEditing(null)}
        />
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
      {/* Wraps rather than scrolls sideways. As a scroll strip, the last button — Move money,
          the one story 4b is about — sat past the edge of a phone with nothing to say so. */}
      <div className="flex flex-wrap items-center gap-2">
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

/** Patch one bucket's figures in the cached month, so the row moves before the server does.

 * The amount being written is the acting person's funding, so the delta is measured against
 * THEIR previous slice — the household totals then move by the same delta, because their
 * contribution is part of the totals. Measuring against the household figure (as this once
 * did) made the optimistic row jump by the wrong amount whenever anyone else had funded.
 */
function patchMonth(
  view: MonthResponse,
  bucketId: string,
  me: string,
  assigned: number,
): MonthResponse {
  const bucket = view.buckets.find((candidate) => candidate.bucket === bucketId);
  const mine = bucket?.funders?.find((funder) => funder.person === me);
  const delta = assigned - Number(mine?.assigned ?? 0);

  return {
    ...view,
    buckets: view.buckets.map((candidate) => {
      if (candidate.bucket !== bucketId) return candidate;
      return {
        ...candidate,
        assigned: (Number(candidate.assigned) + delta).toFixed(2),
        // Available shifts by the same delta as assigned: the money came from somewhere.
        available: (Number(candidate.available) + delta).toFixed(2),
        funders: candidate.funders?.map((funder) =>
          funder.person === me
            ? {
                ...funder,
                assigned: assigned.toFixed(2),
                available: (Number(funder.available) + delta).toFixed(2),
              }
            : funder,
        ),
      };
    }),
    assigned: (Number(view.assigned) + delta).toFixed(2),
    ready_to_assign: (Number(view.ready_to_assign) - delta).toFixed(2),
  };
}

function BucketRow({
  bucket,
  members,
  me,
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
  members: Member[];
  me: string;
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
  const [breakdown, setBreakdown] = useState(false);

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
          patchMonth(previous, bucket.bucket, me, Number(variables.body.amount)),
        );
      }
      return { previous };
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(monthKey, context.previous);
    },
    onSettled: lastWriteWins(queryClient),
  });

  // Scoped to this bucket. Writing `target` into the assign field instead (as this once
  // did) set ONE person's funding to the whole household target — the fill has to share
  // the shortfall across funders in the split ratio, which is the server's job.
  const fill = useMutation({
    ...autoAssignMutation(),
    onSettled: lastWriteWins(queryClient),
  });

  const available = Number(bucket.available);
  const target = bucket.target === null ? null : Number(bucket.target);
  const assigned = Number(bucket.assigned);
  // The figures on the row are the household's; the editable one is YOURS. Showing the
  // household total in an editable field meant pressing Enter replaced your funding with
  // everybody's combined figure.
  const myAssigned = bucket.funders?.find((funder) => funder.person === me)?.assigned ?? "0.00";

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
            {/* The way into group, split and archive. A 14px glyph is not a touch target,
                so the hit area is padded out to thumb size without moving the icon. */}
            <button
              type="button"
              className="-my-2 ms-0.5 flex size-8 items-center justify-center rounded-md hover:bg-sunken hover:text-brand"
              onClick={onEdit}
              title={t("month.moreOptions")}
              aria-label={t("month.moreOptions")}
            >
              <Icon name="sliders" className="size-3.5" />
            </button>
          </span>
        </span>

        <span className="hidden w-28 shrink-0 text-end text-sm sm:block">
          <Money amount={bucket.activity} currency={currency} colour={false} />
        </span>
        {/* shrink-0, because a shrinking cell with unshrinkable digits overflows onto its
            neighbour — which is exactly what happened at 320px. The name is the only cell
            allowed to give way. */}
        <span className="w-24 shrink-0 text-end text-sm font-semibold sm:w-28">
          <Money amount={bucket.available} currency={currency} />
        </span>

        {canWrite ? (
          <AssignField
            assigned={myAssigned}
            pending={assign.isPending}
            onAssign={(amount) =>
              assign.mutate({ path: { budget, month }, body: { bucket: bucket.bucket, amount } })
            }
          />
        ) : (
          <span className="w-20 shrink-0 text-end text-sm text-ink-muted sm:w-24">
            <Money amount={myAssigned} currency={currency} colour={false} />
          </span>
        )}
      </div>

      <div className="mt-2 flex items-center gap-3">
        {/* The bar is also the way into the per-funder numbers: it names who funded, so it
            is the natural thing to press when asking "and where does that leave each of us". */}
        <button
          type="button"
          onClick={() => setBreakdown(!breakdown)}
          aria-expanded={breakdown}
          title={t("month.showBreakdown")}
          className="min-w-0 flex-1 cursor-pointer py-1"
        >
          <FundingBar funders={bucket.funders ?? []} members={members} target={target} />
        </button>
        {/* Only shown when acting on it would change something. */}
        {canWrite && target !== null && assigned < target && (
          <button
            type="button"
            disabled={fill.isPending}
            className="shrink-0 text-[11px] text-brand hover:underline disabled:opacity-50"
            onClick={() =>
              fill.mutate({
                path: { budget, month },
                body: { strategy: "underfunded", buckets: [bucket.bucket] },
              })
            }
          >
            {fill.isPending ? t("month.assigning") : t("month.fillToTarget")}
          </button>
        )}
      </div>

      {breakdown && (
        <FunderBreakdown funders={bucket.funders ?? []} members={members} currency={currency} />
      )}
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
      className="numeric ltr-field min-h-9 w-[5.5rem] shrink-0 border-transparent bg-transparent px-2 text-end hover:border-line focus:bg-card sm:w-24"
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
  members,
  onDone,
}: {
  budget: string;
  bucketId: string;
  members: Member[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const buckets = useQuery(listBucketsOptions({ path: { budget } }));
  const existing = (buckets.data ?? []).find((item) => item.id === bucketId);

  const [name, setName] = useState("");
  const [group, setGroup] = useState("");
  const [target, setTarget] = useState("");
  const [split, setSplit] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState(false);

  if (existing && !loaded) {
    setName(existing.name);
    setGroup(existing.group ?? "");
    setTarget(existing.target?.amount != null ? String(existing.target.amount) : "");
    // An unset split shows as the even one it already behaves as, rather than as blanks that
    // look like nobody bears anything.
    setSplit(
      Object.fromEntries(
        Object.entries(splitFor(existing.split as Record<string, string>, members)).map(
          ([person, share]) => [person, String(Number(share.toFixed(4)))],
        ),
      ),
    );
    setLoaded(true);
  }

  const shares = members.map((member) => Number(split[member.person] ?? 0) || 0);
  const total = shares.reduce((sum, value) => sum + value, 0);
  // The API refuses a split that does not sum to 1, and a partial one is a typo rather than
  // an instruction to normalise. Saying so while typing beats finding out on save.
  const balanced = Math.abs(total - 1) < 0.0001;

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
        split: Object.fromEntries(
          Object.entries(split).filter(([, share]) => Number(share) > 0),
        ),
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

        {/* Who bears spending here. Independent of who funds it, which is what lets an
            envelope be in the red for one person and in the black for another. */}
        <div className="sm:col-span-3">
          <div className="mb-2 flex items-baseline gap-2">
            <span className="text-xs font-medium text-ink-muted">{t("month.split")}</span>
            <span className={`numeric text-xs ${balanced ? "text-ink-muted" : "text-negative"}`}>
              {total.toFixed(2)} / 1.00
            </span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {members.map((member) => (
              <div key={member.person} className="flex items-center gap-2">
                <MemberDot person={member.person} members={members} />
                <span className="min-w-0 flex-1 truncate text-sm">{member.name}</span>
                <Input
                  fullWidth={false}
                  aria-label={`${member.name} ${t("month.split")}`}
                  className="numeric ltr-field w-20 text-end"
                  inputMode="decimal"
                  placeholder="0.5"
                  value={split[member.person] ?? ""}
                  onChange={(event) =>
                    setSplit({ ...split, [member.person]: event.target.value })
                  }
                />
              </div>
            ))}
          </div>
          <button
            type="button"
            className="mt-2 text-xs text-brand hover:underline"
            onClick={() =>
              setSplit(
                Object.fromEntries(
                  members.map((member) => [
                    member.person,
                    String(Number((1 / members.length).toFixed(4))),
                  ]),
                ),
              )
            }
          >
            {t("month.splitEvenly")}
          </button>
        </div>

        <div className="sm:col-span-3">
          <FormActions
            primary={
              <Button type="submit" disabled={save.isPending || !balanced}>
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
