import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteEntryMutation,
  listBucketsOptions,
  listEntriesOptions,
} from "@/api/@tanstack/react-query.gen";
import type { BudgetSummary, Entry, EntryExtras } from "@/api/types.gen";
import { Button, Card, Input, Select } from "@/components/Form";
import { Icon } from "@/components/Icon";
import { Money } from "@/components/Money";
import { ListSkeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/States";
import { currentMonth, formatDate, formatMonth, shiftMonth } from "@/lib/format";
import { EntryDetail } from "./EntryDetail";
import { useBudget } from "./useBudget";

const RECENT_MONTHS = 12;
const KINDS = ["expense", "income", "transfer", "settlement"] as const;

export function EntriesScreen() {
  const { t, i18n } = useTranslation();
  const { budget, isPending: budgetPending } = useBudget();
  const [month, setMonth] = useState<string>(currentMonth);
  const [bucket, setBucket] = useState("");
  const [person, setPerson] = useState("");
  const [kind, setKind] = useState("");
  const [unconverted, setUnconverted] = useState(false);
  const [search, setSearch] = useState("");
  // What actually goes to the server: the search box, a few hundred milliseconds after the
  // last keystroke. Every keystroke is a ledger read otherwise.
  const [query, setQuery] = useState("");
  useEffect(() => {
    const handle = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(handle);
  }, [search]);

  // Typing a search widens the month to "all": somebody searching is looking for something
  // they cannot place, and the one month on screen is the least likely place for it to be.
  // Only on the first character, so a month chosen afterwards stays chosen.
  useEffect(() => {
    if (search.length === 1) setMonth("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.length === 1]);

  const filtered = Boolean(
    query || bucket || person || kind || unconverted || month !== currentMonth(),
  );

  const entries = useQuery({
    ...listEntriesOptions({
      path: { budget: budget?.slug ?? "" },
      query: {
        ...(month ? { month } : {}),
        ...(bucket ? { bucket } : {}),
        ...(person ? { person } : {}),
        ...(kind ? { kind: kind as (typeof KINDS)[number] } : {}),
        ...(query ? { q: query } : {}),
        ...(unconverted ? { unconverted: true } : {}),
      },
    }),
    enabled: Boolean(budget),
    // Changing month or bucket filters the same list. Emptying the screen between the two
    // makes filtering feel like a fetch rather than a filter.
    placeholderData: keepPreviousData,
  });

  // Bucket ids are what an entry stores, but they are not what anyone calls them. The list
  // is fetched purely so a row can show "Eating out" instead of "eating-out".
  const buckets = useQuery({
    ...listBucketsOptions({ path: { budget: budget?.slug ?? "" } }),
    enabled: Boolean(budget),
  });

  if (entries.isError || !budget) return <ErrorState onRetry={() => void entries.refetch()} />;
  if (budgetPending || entries.isPending) return <ListSkeleton />;

  const names = new Map((buckets.data ?? []).map((item) => [item.id, item.name]));
  const months = Array.from({ length: RECENT_MONTHS }, (_, index) =>
    shiftMonth(currentMonth(), -index),
  );

  const total = entries.data.entries.reduce((sum, entry) => sum + Number(entry.amount), 0);

  const clear = () => {
    setSearch("");
    setQuery("");
    setBucket("");
    setPerson("");
    setKind("");
    setUnconverted(false);
    setMonth(currentMonth());
  };

  return (
    <section
      className={`space-y-4 transition-opacity ${entries.isPlaceholderData ? "opacity-60" : ""}`}
      aria-busy={entries.isPlaceholderData}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold">{t("entries.title")}</h1>
        <span className="text-sm text-ink-muted">
          <Money amount={total.toFixed(2)} currency={budget.currency} colour={false} />
        </span>
        {filtered && (
          <span className="text-xs text-ink-muted">
            · {t("entries.matches", { count: entries.data.total })}
          </span>
        )}
      </div>

      {/* Search first, then the narrowing filters. The box is full width on a phone because
          typing is the filter people reach for; the selects wrap under it. */}
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative min-w-0 flex-1 basis-56">
          <span className="sr-only">{t("entries.search")}</span>
          <Icon
            name="search"
            className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-ink-muted"
          />
          <Input
            type="search"
            className="h-10 min-h-0 ps-9"
            placeholder={t("entries.searchPlaceholder")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>

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

        {budget.members.length > 1 && (
          <Select
            fullWidth={false}
            className="h-10 min-h-0 w-auto text-xs"
            value={person}
            onChange={(event) => setPerson(event.target.value)}
            aria-label={t("entries.filterPerson")}
          >
            <option value="">{t("entries.anyone")}</option>
            {budget.members.map((member) => (
              <option key={member.person} value={member.person}>
                {member.name}
              </option>
            ))}
          </Select>
        )}

        <Select
          fullWidth={false}
          className="h-10 min-h-0 w-auto text-xs"
          value={kind}
          onChange={(event) => setKind(event.target.value)}
          aria-label={t("entries.filterKind")}
        >
          <option value="">{t("entries.anyKind")}</option>
          {KINDS.map((option) => (
            <option key={option} value={option}>
              {t(`entries.kinds.${option}`)}
            </option>
          ))}
        </Select>

        <label className="flex min-h-9 cursor-pointer items-center gap-1.5 text-xs text-ink-muted">
          <input
            type="checkbox"
            className="size-4 accent-[var(--color-brand)]"
            checked={unconverted}
            onChange={(event) => setUnconverted(event.target.checked)}
          />
          {t("currency.unconvertedOnly")}
        </label>

        {filtered && (
          <Button variant="ghost" className="min-h-9 px-3 text-xs" onClick={clear}>
            {t("entries.clearFilters")}
          </Button>
        )}
      </div>

      {entries.data.entries.length === 0 ? (
        <Card className="p-6 text-center text-ink-muted">
          {filtered ? t("entries.noMatches") : t("entries.empty")}
        </Card>
      ) : (
        <Card className="divide-y divide-line overflow-hidden">
          {entries.data.entries.map((entry) => (
            <EntryRow
              key={entry.id}
              entry={entry}
              budget={budget}
              bucketNames={names}
              extras={entries.data.extras?.[entry.id]}
            />
          ))}
        </Card>
      )}
    </section>
  );
}

function EntryRow({
  entry,
  budget,
  bucketNames,
  extras,
}: {
  entry: Entry;
  budget: BudgetSummary;
  bucketNames: Map<string, string>;
  extras: EntryExtras | undefined;
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
        aria-expanded={open}
        data-entry={entry.id}
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{entry.payee}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-ink-muted">
            <span className="numeric">{formatDate(entry.date, i18n.language)}</span>
            {buckets.length > 0 && <span>· {buckets.join(", ")}</span>}
            {shared && <span>· {t("entries.shared")}</span>}
            {/* What hangs off the entry, so a conversation or a receipt is findable from
                the list rather than only by opening every row. */}
            {extras?.comments ? (
              <span
                className="inline-flex items-center gap-0.5"
                title={t("comments.count", { count: extras.comments })}
              >
                <Icon name="message" className="size-3" />
                <span className="numeric">{extras.comments}</span>
              </span>
            ) : null}
            {extras?.attachments ? (
              <span
                className="inline-flex items-center gap-0.5"
                title={t("attachments.count", { count: extras.attachments })}
              >
                <Icon name="paperclip" className="size-3" />
                <span className="numeric">{extras.attachments}</span>
              </span>
            ) : null}
          </div>
        </div>

        <div className="text-end">
          {/* The budget figure first; the receipt figure and its rate beneath. Unconverted
              rows show their own currency and say so. */}
          <Money
            amount={entry.fx ? entry.fx.amount : entry.amount}
            currency={entry.fx ? budget.currency : entry.currency}
            className="text-sm font-semibold"
          />
          {entry.fx && (
            <div className="text-[11px] text-ink-muted">
              {t("currency.convertedAt", { original: "", rate: entry.fx.rate }).trim()}{" "}
              <Money amount={entry.amount} currency={entry.currency} colour={false} />
            </div>
          )}
          {!entry.fx && entry.currency !== budget.currency && (
            <div className="text-[11px] text-ink-muted">{t("currency.unconverted")}</div>
          )}
          {shared && mine !== 0 && (
            <div className="text-[11px] text-ink-muted">
              {t("entries.yourShare")}{" "}
              <Money amount={mine.toFixed(2)} currency={entry.currency} colour={false} />
            </div>
          )}
        </div>
      </button>

      {open && (
        <EntryDetail
          entry={entry}
          budget={budget}
          bucketNames={bucketNames}
          extras={extras}
          onDeleted={() => {
            if (window.confirm(t("entries.confirmDelete"))) {
              remove.mutate({ path: { budget: budget.slug, entry_id: entry.id } });
            }
          }}
        />
      )}
    </div>
  );
}
