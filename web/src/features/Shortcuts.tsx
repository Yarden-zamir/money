import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { redoChangeMutation, undoChangeMutation } from "@/api/@tanstack/react-query.gen";
import { Card } from "@/components/Form";
import { shortcutLabel, useShortcuts, type Shortcut } from "@/lib/useShortcuts";
import { useBudget } from "./useBudget";

/**
 * App-wide shortcuts, plus the sheet that lists them.
 *
 * `?` opens the list, which is the convention people already try — a shortcut nobody can
 * discover is a shortcut nobody uses.
 */
export function Shortcuts({ onQuickAdd }: { onQuickAdd: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { budget } = useBudget();
  const [showing, setShowing] = useState(false);

  const undo = useMutation({
    ...undoChangeMutation(),
    onSuccess: () => void queryClient.invalidateQueries(),
  });
  const redo = useMutation({
    ...redoChangeMutation(),
    onSuccess: () => void queryClient.invalidateQueries(),
  });

  const shortcuts: Shortcut[] = [
    { key: "n", label: t("shortcuts.newEntry"), run: onQuickAdd },
    { key: "z", meta: true, label: t("shortcuts.undo"), run: () => {
      if (budget?.can_write) undo.mutate({ path: { budget: budget.slug } });
    } },
    { key: "z", meta: true, shift: true, label: t("shortcuts.redo"), run: () => {
      if (budget?.can_write) redo.mutate({ path: { budget: budget.slug } });
    } },
    { key: "1", label: t("nav.month"), run: () => navigate("/") },
    { key: "2", label: t("nav.entries"), run: () => navigate("/entries") },
    { key: "3", label: t("nav.balances"), run: () => navigate("/balances") },
    { key: "4", label: t("nav.scheduled"), run: () => navigate("/scheduled") },
    { key: "5", label: t("nav.settings"), run: () => navigate("/settings") },
    { key: "?", shift: true, label: t("shortcuts.help"), run: () => setShowing((open) => !open) },
  ];

  useShortcuts(shortcuts);

  if (!showing) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={t("shortcuts.help")}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) setShowing(false);
      }}
    >
      <Card className="sheet-in w-full max-w-sm p-4">
        <h2 className="mb-3 text-base font-semibold">{t("shortcuts.help")}</h2>
        <ul className="space-y-2">
          {shortcuts.map((shortcut) => (
            <li key={shortcut.label} className="flex items-center gap-3 text-sm">
              <span className="flex-1">{shortcut.label}</span>
              <kbd className="numeric rounded border border-line bg-sunken px-2 py-0.5 text-xs">
                {shortcutLabel(shortcut)}
              </kbd>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-ink-muted">{t("shortcuts.note")}</p>
      </Card>
    </div>
  );
}
