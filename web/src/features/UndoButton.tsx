import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getHistoryOptions,
  redoChangeMutation,
  undoChangeMutation,
} from "@/api/@tanstack/react-query.gen";
import { Icon } from "@/components/Icon";
import { describeError } from "@/components/Form";
import { useBudget } from "./useBudget";

/**
 * Undo and redo, as an editor has them.
 *
 * Both are scoped to your own commits: in a shared budget, silently reversing your partner's
 * work is the failure worth designing against. Each names what it acted on in the
 * confirmation — "undo" that does not say what it undid is not a reversible action, it is a
 * gamble.
 *
 * Redo appears only while your last change was an undo. Doing anything else makes it vanish,
 * exactly as a new edit clears an editor's redo stack.
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

  const announce = (message: string, ms = 6000) => {
    setToast(message);
    setTimeout(() => setToast(null), ms);
  };

  const undo = useMutation({
    ...undoChangeMutation(),
    onSuccess: (result) => {
      void queryClient.invalidateQueries();
      announce(t("history.undone", { what: result.undone_subject }));
    },
    onError: (error) => announce(describeError(error) ?? t("common.error"), 8000),
  });

  const redo = useMutation({
    ...redoChangeMutation(),
    onSuccess: (result) => {
      void queryClient.invalidateQueries();
      announce(t("history.redone", { what: result.undone_subject }));
    },
    onError: (error) => announce(describeError(error) ?? t("common.error"), 8000),
  });

  const canUndo = Boolean(budget?.can_write && history.data?.undoable);
  const canRedo = Boolean(budget?.can_write && history.data?.redoable);
  if (!budget || (!canUndo && !canRedo)) return null;

  return (
    <>
      {canUndo && (
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
      )}
      {canRedo && (
        <button
          type="button"
          title={`${t("history.redo")} (⇧⌘Z)`}
          aria-label={t("history.redo")}
          disabled={redo.isPending}
          onClick={() => redo.mutate({ path: { budget: budget.slug } })}
          className="flex size-9 items-center justify-center rounded-lg text-ink-muted hover:bg-sunken hover:text-ink disabled:opacity-40"
        >
          <Icon name="redo" className="size-4" directional />
        </button>
      )}

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
