import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Icon } from "./Icon";

/**
 * Marks a field the app filled in, and explains why.
 *
 * A value that appears without being typed is only acceptable if the person can find out
 * where it came from — otherwise a wrong guess is indistinguishable from a bug, and a right
 * one is still unsettling. Hovering or focusing the marker states the reasoning in a
 * sentence, including how many past purchases it drew on.
 *
 * The marker disappears the moment the field is edited: once it is your number, saying the
 * app guessed it would be a lie.
 */
export function Guessed({
  reason,
  confidence,
  sampleSize,
}: {
  reason: string;
  confidence: number;
  sampleSize: number;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-label={t("suggest.explain")}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen(!open)}
        className="flex size-5 items-center justify-center rounded text-brand"
      >
        <Icon name="sparkle" className="size-3.5" />
      </button>

      {open && (
        <span
          role="tooltip"
          className="absolute bottom-full z-30 mb-1.5 w-60 rounded-lg border border-line bg-card p-2.5 text-xs leading-relaxed font-normal text-ink shadow-lg end-0"
        >
          <span className="block">{reason}</span>
          <span className="mt-1.5 block text-ink-muted">
            {t("suggest.confidence", {
              percent: Math.round(confidence * 100),
              count: sampleSize,
            })}
          </span>
        </span>
      )}
    </span>
  );
}
