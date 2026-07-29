import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createApiKeyMutation,
  deleteApiKeyMutation,
  listApiKeysOptions,
  listApiKeysQueryKey,
} from "@/api/@tanstack/react-query.gen";
import { ErrorState, Loading } from "@/components/States";
import { useBudget } from "./useBudget";

export function SettingsScreen() {
  const { t } = useTranslation();
  const { budget, budgets, select } = useBudget();

  return (
    <section className="space-y-8">
      <h1 className="text-lg font-semibold">{t("settings.title")}</h1>

      <div>
        <h2 className="mb-2 text-sm font-medium text-ink-muted">{t("settings.budgets")}</h2>
        <ul className="divide-y divide-line rounded-lg ring-1 ring-line">
          {budgets.map((candidate) => (
            <li key={candidate.slug} className="flex flex-wrap items-baseline gap-3 p-3">
              <button
                type="button"
                onClick={() => select(candidate.slug)}
                className={`font-medium ${candidate.slug === budget?.slug ? "text-brand" : ""}`}
              >
                {candidate.name}
              </button>
              <span className="text-xs text-ink-muted">
                {t("settings.dataRepo")}: {candidate.repo} · {t("settings.branch")}:{" "}
                {candidate.branch}
              </span>
              <span className="ms-auto text-xs text-ink-muted">
                {candidate.can_write ? "read/write" : "read"}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <ApiKeys />
    </section>
  );
}

function ApiKeys() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [freshToken, setFreshToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const keys = useQuery(listApiKeysOptions());
  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: listApiKeysQueryKey() });

  const create = useMutation({
    ...createApiKeyMutation(),
    onSuccess: (created) => {
      // Shown once, here and nowhere else: the server only ever stored the hash.
      setFreshToken(created.token);
      setName("");
      invalidate();
    },
  });
  const revoke = useMutation({ ...deleteApiKeyMutation(), onSuccess: invalidate });

  if (keys.isPending) return <Loading />;
  if (keys.isError) return <ErrorState onRetry={() => void keys.refetch()} />;

  return (
    <div>
      <h2 className="mb-2 text-sm font-medium text-ink-muted">{t("settings.apiKeys")}</h2>

      {freshToken && (
        <div className="mb-3 rounded-lg border border-brand/40 bg-brand/8 p-3">
          <p className="mb-2 text-sm">{t("settings.keyShownOnce")}</p>
          <div className="flex items-center gap-2">
            <code className="numeric grow overflow-x-auto rounded bg-surface px-2 py-1 text-xs">
              {freshToken}
            </code>
            <button
              type="button"
              className="shrink-0 rounded-md border border-line px-3 py-1 text-sm"
              onClick={() => {
                void navigator.clipboard.writeText(freshToken);
                setCopied(true);
              }}
            >
              {copied ? t("settings.copied") : t("settings.copy")}
            </button>
          </div>
        </div>
      )}

      <form
        className="mb-3 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) create.mutate({ body: { name: name.trim(), scopes: ["read", "write"] } });
        }}
      >
        <input
          className="grow rounded-md border border-line bg-surface px-3 py-1.5 text-sm"
          placeholder={t("settings.keyName")}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <button
          type="submit"
          disabled={!name.trim() || create.isPending}
          className="rounded-md bg-brand px-3 py-1.5 text-sm text-white disabled:opacity-50"
        >
          {t("settings.createKey")}
        </button>
      </form>

      {keys.data.length === 0 ? (
        <p className="text-ink-muted">{t("settings.noKeys")}</p>
      ) : (
        <ul className="divide-y divide-line rounded-lg ring-1 ring-line">
          {keys.data.map((key) => (
            <li key={key.id} className="flex flex-wrap items-baseline gap-3 p-3">
              <span className="font-medium">{key.name}</span>
              <span className="text-xs text-ink-muted">{key.scopes.join(", ")}</span>
              <span className="text-xs text-ink-muted">
                {t("settings.lastUsed")}:{" "}
                {key.last_used_at ? key.last_used_at.slice(0, 10) : t("settings.never")}
              </span>
              <button
                type="button"
                onClick={() => revoke.mutate({ path: { key_id: key.id } })}
                className="ms-auto text-sm text-negative"
              >
                {t("settings.revoke")}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
