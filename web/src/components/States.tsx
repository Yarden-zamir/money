import { useTranslation } from "react-i18next";

export function Loading() {
  const { t } = useTranslation();
  return <p className="p-6 text-ink-muted">{t("common.loading")}</p>;
}

export function ErrorState({ onRetry }: { onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="p-6">
      <p className="text-negative">{t("common.error")}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 min-h-11 rounded-xl border border-line bg-card px-4 text-sm hover:bg-surface"
        >
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

export function Empty({ message }: { message: string }) {
  return <p className="p-6 text-ink-muted">{message}</p>;
}
