import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getHistoryDetailOptions,
  getHistoryOptions,
  undoChangeMutation,
} from "@/api/@tanstack/react-query.gen";
import type { BudgetSummary, HistoryEvent } from "@/api/types.gen";
import { Bidi } from "@/components/Bidi";
import { Button, Card, FormError } from "@/components/Form";
import { Icon } from "@/components/Icon";
import { ListSkeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/States";
import { lastWriteWins } from "@/lib/optimistic";
import { useBudget } from "./useBudget";

/**
 * Every change, newest first.
 *
 * One feed regardless of which file a change touched, so assignments appear next to entries —
 * they are the same kind of event to someone asking what happened, even though one lives in a
 * ledger file and the other in a map.
 *
 * A subject line says what someone meant to do. Opening a row says what actually happened,
 * which for YAML-shaped data is readable enough to be the answer rather than a debugging
 * aid: an assignment is one number changing on one line.
 */
const KIND_ICONS = {
  entry: "list",
  assignment: "wallet",
  bucket: "target",
  rules: "sliders",
  members: "swap",
  note: "list",
  scheduled: "repeat",
  undo: "undo",
  other: "clock",
} as const;

export function HistoryScreen() {
  const { t } = useTranslation();
  const { budget, isPending } = useBudget();
  const [open, setOpen] = useState<string | null>(null);

  const history = useQuery({
    ...getHistoryOptions({ path: { budget: budget?.slug ?? "" }, query: { limit: 100 } }),
    enabled: Boolean(budget),
  });

  if (history.isError || !budget) return <ErrorState onRetry={() => void history.refetch()} />;
  if (isPending || history.isPending) {
    return (
      <section className="space-y-4">
        <div>
          <h1 className="text-lg font-semibold">{t("history.title")}</h1>
          <p className="text-sm text-ink-muted">{t("history.openHint")}</p>
        </div>
        <ListSkeleton rows={8} />
      </section>
    );
  }

  // Which changes are no longer applied. Derived from the feed rather than fetched, because
  // a revert names what it undid — so the list already contains the answer for every row.
  const undone = new Set(
    history.data.events.map((event) => event.reverts).filter((sha): sha is string => Boolean(sha)),
  );

  return (
    <section className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">{t("history.title")}</h1>
        <p className="text-sm text-ink-muted">{t("history.openHint")}</p>
      </div>

      <Card className="divide-y divide-line">
        {history.data.events.map((event) => (
          <Row
            key={event.sha}
            event={event}
            budget={budget}
            // Prefix match: the store writes a full sha into the Reverts trailer, but a
            // revert made by hand with `git revert` records an abbreviated one.
            undone={[...undone].some((sha) => event.sha.startsWith(sha))}
            open={open === event.sha}
            onToggle={() => setOpen(open === event.sha ? null : event.sha)}
          />
        ))}
      </Card>
    </section>
  );
}

function Row({
  event,
  budget,
  undone,
  open,
  onToggle,
}: {
  event: HistoryEvent;
  budget: BudgetSummary;
  undone: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  const { t, i18n } = useTranslation();

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 p-3 text-start transition hover:bg-surface sm:px-4"
      >
        <Icon
          name={KIND_ICONS[event.kind as keyof typeof KIND_ICONS] ?? "clock"}
          className={`size-4 shrink-0 ${undone ? "text-ink-muted/50" : "text-ink-muted"}`}
        />
        <span className="min-w-0 flex-1">
          {/* A subject mixes a template with a name someone chose, so it can mix scripts.
              Without isolating the right-to-left runs the numbers around them lay out
              backwards — "מכולת 0.00 → 2000.00" renders as "2000.00 → 0.00 מכולת". */}
          {/* Clamped rather than truncated. A subject is an English-shaped string, so in a
              right-to-left page a single-line ellipsis eats its *beginning* — "assign: מכולת"
              disappears and "0 → 2000.00 for 2026-08" is what survives, which is the half
              that says nothing. Two lines fit almost every subject whole. */}
          <Bidi
            text={event.subject}
            className={`block line-clamp-2 text-sm ${undone ? "text-ink-muted line-through" : ""}`}
          />
          <span className="mt-0.5 block text-xs text-ink-muted">
            {new Intl.DateTimeFormat(i18n.language, {
              dateStyle: "medium",
              timeStyle: "short",
            }).format(new Date(event.date))}
            {" · "}
            {event.author}
            {event.mine && ` · ${t("common.you")}`}
            {undone && ` · ${t("history.undone")}`}
          </span>
        </span>
        <code className="numeric shrink-0 text-[11px] text-ink-muted">{event.sha.slice(0, 7)}</code>
        <Icon
          name="chevronDown"
          className={`size-4 shrink-0 text-ink-muted transition ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && <Detail sha={event.sha} budget={budget} />}
    </div>
  );
}

/** The patch, plus what can still be done about it. */
function Detail({ sha, budget }: { sha: string; budget: BudgetSummary }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [copied, setCopied] = useState(false);

  const detail = useQuery({
    ...getHistoryDetailOptions({ path: { budget: budget.slug, sha } }),
    // A commit is immutable, so its diff never needs re-fetching — and this screen polls.
    staleTime: Infinity,
    refetchInterval: false,
  });

  const undo = useMutation({
    ...undoChangeMutation(),
    onSettled: lastWriteWins(queryClient),
  });

  if (detail.isPending) return <p className="px-3 pb-3 text-xs text-ink-muted sm:px-4">…</p>;
  if (detail.isError) {
    return (
      <div className="px-3 pb-3 sm:px-4">
        <FormError error={detail.error} />
      </div>
    );
  }

  const data = detail.data;

  return (
    <div className="sheet-in border-t border-line bg-surface/60 px-3 py-3 sm:px-4">
      <ul className="mb-2 space-y-1 text-xs">
        {data.files.map((file) => (
          <li key={file.path} className="flex flex-wrap items-baseline gap-2">
            <span className="rounded bg-line px-1.5 py-0.5 text-[10px] text-ink-muted">
              {t(`history.status.${file.status}`)}
            </span>
            <code className="ltr-field min-w-0 flex-1 truncate">{file.path}</code>
            <span className="numeric text-positive">+{file.added}</span>
            <span className="numeric text-negative">−{file.removed}</span>
          </li>
        ))}
      </ul>

      {/* A patch is code: always left-to-right and never reflowed, whatever the page
          direction. Scrolls in its own box so the page itself never moves sideways. */}
      <pre
        dir="ltr"
        className="max-h-72 overflow-auto rounded-lg border border-line bg-card p-2.5 text-[11px] leading-relaxed"
      >
        {data.diff.split("\n").map((line, index) => (
          <div
            key={index}
            className={
              line.startsWith("+") && !line.startsWith("+++")
                ? "text-positive"
                : line.startsWith("-") && !line.startsWith("---")
                  ? "text-negative"
                  : line.startsWith("@@")
                    ? "text-brand"
                    : "text-ink-muted"
            }
          >
            {line || " "}
          </div>
        ))}
      </pre>

      {data.diff_truncated && (
        <p className="mt-1 text-[11px] text-ink-muted">{t("history.truncated")}</p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {data.can_undo ? (
          <Button
            variant="quiet"
            className="min-h-9 px-3 text-xs"
            disabled={undo.isPending}
            onClick={() => undo.mutate({ path: { budget: budget.slug }, query: { sha } })}
          >
            <Icon name="undo" className="size-3.5" />
            {t("history.undoThis")}
          </Button>
        ) : (
          <span className="text-xs text-ink-muted">
            {data.reverted_by ? t("history.alreadyUndone") : t("history.cannotUndo")}
          </span>
        )}

        {/* The data really is a git repo, so the commit really does have a page. */}
        <a
          href={`https://github.com/${budget.repo}/commit/${data.sha}`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex min-h-9 items-center gap-1.5 rounded-lg px-3 text-xs text-ink-muted hover:bg-line hover:text-ink"
        >
          <Icon name="external" className="size-3.5" />
          {t("history.onGitHub")}
        </a>

        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(data.sha);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          className="inline-flex min-h-9 items-center gap-1.5 rounded-lg px-3 text-xs text-ink-muted hover:bg-line hover:text-ink"
        >
          <Icon name={copied ? "check" : "copy"} className="size-3.5" />
          {copied ? t("history.copied") : t("history.copySha")}
        </button>
      </div>

      <FormError error={undo.error} />
    </div>
  );
}
