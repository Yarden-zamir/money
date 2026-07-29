import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createApiKeyMutation,
  deleteApiKeyMutation,
  listApiKeysOptions,
  listApiKeysQueryKey,
  listMembersOptions,
  putMembersMutation,
} from "@/api/@tanstack/react-query.gen";
import type { BudgetSummary, Member } from "@/api/types.gen";
import { Button, FormError, Input } from "@/components/Form";
import { ErrorState, Loading } from "@/components/States";
import { ConnectBudget } from "./ConnectBudget";
import { useBudget } from "./useBudget";

export function SettingsScreen() {
  const { t } = useTranslation();
  const { budget, budgets, select } = useBudget();

  return (
    <section className="space-y-8">
      <h1 className="text-lg font-semibold">{t("settings.title")}</h1>

      <div>
        <h2 className="mb-2 text-sm font-medium text-ink-muted">{t("settings.budgets")}</h2>
        <div className="mb-3">
          <ConnectBudget />
        </div>
        <ul className="divide-y divide-line rounded-card border border-line bg-card">
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

      {budget && <Members budget={budget} />}
      <ApiKeys />
    </section>
  );
}

/**
 * Who can hold a share of an entry.
 *
 * Separate from who can *reach* the budget, which is GitHub repo access — the hint says so,
 * because the two being different is surprising until it is stated.
 */
function Members({ budget }: { budget: BudgetSummary }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const members = useQuery(listMembersOptions({ path: { budget: budget.slug } }));
  const [draft, setDraft] = useState<Member[] | null>(null);

  const save = useMutation({
    ...putMembersMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      setDraft(null);
    },
  });

  if (members.isPending) return <Loading />;
  if (members.isError) return <ErrorState onRetry={() => void members.refetch()} />;

  const rows = draft ?? members.data;
  const update = (index: number, patch: Partial<Member>) =>
    setDraft(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  return (
    <div>
      <h2 className="mb-1 text-sm font-medium text-ink-muted">{t("members.title")}</h2>
      <p className="mb-2 text-xs text-ink-muted">{t("members.hint")}</p>

      <div className="space-y-2">
        {rows.map((member, index) => (
          <div key={index} className="flex flex-wrap gap-2">
            <Input
              fullWidth={false}
              className="ltr-field w-full sm:w-32"
              dir="ltr"
              placeholder={t("members.person")}
              value={member.person}
              onChange={(event) => update(index, { person: event.target.value })}
            />
            <Input
              fullWidth={false}
              className="w-full sm:w-40"
              placeholder={t("members.name")}
              value={member.name}
              onChange={(event) => update(index, { name: event.target.value })}
            />
            <Input
              fullWidth={false}
              className="ltr-field w-full sm:w-48"
              dir="ltr"
              placeholder={t("members.github")}
              value={member.github ?? ""}
              onChange={(event) => update(index, { github: event.target.value || null })}
            />
            {rows.length > 1 && (
              <Button
                type="button"
                variant="quiet"
                onClick={() => setDraft(rows.filter((_, i) => i !== index))}
              >
                ×
              </Button>
            )}
          </div>
        ))}
      </div>

      {budget.can_write && (
        <div className="mt-2 flex gap-2">
          <Button
            type="button"
            variant="quiet"
            onClick={() => setDraft([...rows, { person: "", name: "", github: null }])}
          >
            {t("members.add")}
          </Button>
          <Button
            type="button"
            disabled={draft === null || save.isPending}
            onClick={() => draft && save.mutate({ path: { budget: budget.slug }, body: draft })}
          >
            {t("members.save")}
          </Button>
        </div>
      )}

      <FormError error={save.error} />
    </div>
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
        <ul className="divide-y divide-line rounded-card border border-line bg-card">
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
