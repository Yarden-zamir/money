import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getHistoryOptions, undoChangeMutation } from "@/api/@tanstack/react-query.gen";
import { Icon } from "@/components/Icon";
import { describeError } from "@/components/Form";
import { useBudget } from "./useBudget";

/**
 * Undo the last change you made.
 *
 * Scoped to your own commits: in a shared budget, silently reversing your partner's work is
 * the failure worth designing against. What was undone is named in the confirmation, because
 * "undo" with no statement of what it undid is not a reversible action, it is a gamble.
 */
export function UndoButton() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { budget } = useBudget();
  const [toast, setToast] = useState<string | null>(null);

  const history = useQuery({
    ...getHistoryOptions({ path: { budget: budget?.slug ?? "" }, query: { limit: 20 } }),
    enabled: Boolean(budget),
  });

  const undo = useMutation({
    ...undoChangeMutation(),
    onSuccess: (result) => {
      void queryClient.invalidateQueries();
      setToast(t("history.undone", { what: result.undone_subject }));
      setTimeout(() => setToast(null), 6000);
    },
    onError: (error) => {
      setToast(describeError(error) ?? t("common.error"));
      setTimeout(() => setToast(null), 8000);
    },
  });

  if (!budget?.can_write || !history.data?.undoable) return null;

  return (
    <>
      <button
        type="button"
        title={`${t("history.undo")} (⌘Z)`}
        aria-label={t("history.undo")}
        disabled={undo.isPending}
        onClick={() => undo.mutate({ path: { budget: budget.slug } })}
        className="flex size-9 items-center justify-center rounded-lg text-ink-muted hover:bg-sunken hover:text-ink disabled:opacity-40"
      >
        <Icon name="undo" className="size-4" directional />
      </button>

      {toast && (
        <div
          role="status"
          className="sheet-in fixed inset-x-4 bottom-24 z-40 mx-auto max-w-md rounded-xl border border-line bg-card p-3 text-sm shadow-lg sm:bottom-6"
        >
          {toast}
        </div>
      )}
    </>
  );
}
