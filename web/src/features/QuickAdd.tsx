import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Icon } from "@/components/Icon";
import { AddEntry } from "./AddEntry";
import { useBudget } from "./useBudget";

/**
 * A single add-entry action, available from every screen.
 *
 * Logging an expense is what people open this app to do, and it should never depend on being
 * on the right tab first. The button is fixed at the inline end, clear of the mobile tab bar,
 * and opens the form in a dialog rather than inline so it works the same everywhere.
 */
export function QuickAdd() {
  const { t } = useTranslation();
  const { budget } = useBudget();
  const [open, setOpen] = useState(false);

  // `n` opens it from anywhere, but never while someone is typing — otherwise it fires in
  // the middle of a payee name.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") return setOpen(false);

      const target = event.target as HTMLElement | null;
      const typing =
        target?.isContentEditable ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName ?? "");
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return;

      if (event.key === "n") {
        event.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Keep the page behind the dialog from scrolling on touch.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  if (!budget?.can_write) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={t("entries.add")}
        title={`${t("entries.add")} (n)`}
        className={
          "fixed end-4 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-30 flex size-14 " +
          "items-center justify-center rounded-full bg-brand text-on-brand " +
          "shadow-lg transition hover:opacity-90 active:scale-95 sm:end-6 sm:bottom-6"
        }
      >
        {/* An SVG is centred by construction; the glyph it replaced sat on a text baseline
            and could only ever be nudged into approximate alignment. A plus encodes no
            direction, so it never mirrors. */}
        <Icon name="plus" className="size-7" />
      </button>

      {open && (
        <div
          className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-0 backdrop-blur-sm sm:items-center sm:p-4"
          role="dialog"
          aria-modal="true"
          aria-label={t("entries.add")}
          onMouseDown={(event) => {
            // Only a click on the backdrop itself closes; dragging inside the form must not.
            if (event.target === event.currentTarget) setOpen(false);
          }}
        >
          <div className="sheet-in max-h-[92dvh] w-full overflow-y-auto rounded-t-2xl bg-card p-4 shadow-xl sm:max-w-2xl sm:rounded-2xl">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold">{t("entries.add")}</h2>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label={t("common.cancel")}
                className="flex size-9 items-center justify-center rounded-lg text-ink-muted hover:bg-surface"
              >
                <Icon name="close" className="size-4" />
              </button>
            </div>

            <AddEntry bare budget={budget} onDone={() => setOpen(false)} />
          </div>
        </div>
      )}
    </>
  );
}
