import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { getHistoryOptions } from "@/api/@tanstack/react-query.gen";
import { Card } from "@/components/Form";
import { Icon } from "@/components/Icon";
import { ErrorState, Loading } from "@/components/States";
import { useBudget } from "./useBudget";

/**
 * Every change, newest first.
 *
 * One feed regardless of which file a change touched, so assignments appear next to entries —
 * they are the same kind of event to someone asking what happened, even though one lives in a
 * ledger file and the other in a map.
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
  const { t, i18n } = useTranslation();
  const { budget, isPending } = useBudget();

  const history = useQuery({
    ...getHistoryOptions({ path: { budget: budget?.slug ?? "" }, query: { limit: 100 } }),
    enabled: Boolean(budget),
  });

  if (isPending || history.isPending) return <Loading />;
  if (history.isError || !budget) return <ErrorState onRetry={() => void history.refetch()} />;

  return (
    <section className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">{t("history.title")}</h1>
        <p className="text-sm text-ink-muted">{t("history.hint")}</p>
      </div>

      <Card className="divide-y divide-line">
        {history.data.events.map((event) => (
          <div key={event.sha} className="flex items-center gap-3 p-3 sm:px-4">
            <Icon
              name={KIND_ICONS[event.kind as keyof typeof KIND_ICONS] ?? "clock"}
              className="size-4 text-ink-muted"
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm">{event.subject}</span>
              <span className="mt-0.5 block text-xs text-ink-muted">
                {new Intl.DateTimeFormat(i18n.language, {
                  dateStyle: "medium",
                  timeStyle: "short",
                }).format(new Date(event.date))}
                {" · "}
                {event.author}
                {event.mine && ` · ${t("common.you")}`}
              </span>
            </span>
            <code className="numeric shrink-0 text-[11px] text-ink-muted">
              {event.sha.slice(0, 7)}
            </code>
          </div>
        ))}
      </Card>
    </section>
  );
}
