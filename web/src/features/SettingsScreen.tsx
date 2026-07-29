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
import { Button, Card, Field, FormActions, FormError, Input } from "@/components/Form";
import { ErrorState, Loading } from "@/components/States";
import { ConnectBudget } from "./ConnectBudget";
import { InvitePerson } from "./InvitePerson";
import { useBudget } from "./useBudget";

export function SettingsScreen() {
  const { t } = useTranslation();
  const { budget, budgets, select } = useBudget();
  const [connecting, setConnecting] = useState(false);

  return (
    <section className="space-y-8">
      <h1 className="text-lg font-semibold">{t("settings.title")}</h1>

      <div>
        <h2 className="mb-2 text-sm font-medium text-ink-muted">{t("settings.budgets")}</h2>

        <ul className="divide-y divide-line rounded-card border border-line bg-card">
          {budgets.map((candidate) => {
            const active = candidate.slug === budget?.slug;
            return (
              <li key={candidate.slug}>
                <button
                  type="button"
                  onClick={() => select(candidate.slug)}
                  className="flex w-full items-center gap-3 p-3 text-start hover:bg-surface sm:px-4"
                >
                  {/* A check, not just colour: "which budget am I looking at" should not
                      depend on noticing a shade of blue. */}
                  <span
                    aria-hidden
                    className={`flex size-5 shrink-0 items-center justify-center rounded-full text-xs ${
                      active ? "bg-brand text-white" : "border border-line text-transparent"
                    }`}
                  >
                    ✓
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{candidate.name}</span>
                    <span className="block truncate text-xs text-ink-muted">
                      {candidate.repo} · {t("settings.branch")}: {candidate.branch}
                    </span>
                  </span>
                  <span className="shrink-0 rounded-full bg-line px-2 py-0.5 text-[11px] text-ink-muted">
                    {candidate.can_write ? t("settings.readWrite") : t("settings.readOnly")}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        {connecting ? (
          <div className="mt-3">
            <ConnectBudget onConnected={() => setConnecting(false)} />
            <Button variant="ghost" className="mt-2" onClick={() => setConnecting(false)}>
              {t("common.cancel")}
            </Button>
          </div>
        ) : (
          <Button variant="quiet" className="mt-3" onClick={() => setConnecting(true)}>
            + {t("budgets.connect")}
          </Button>
        )}
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

      {/* One card per person, with a label on every field.
          A header row only works while the columns line up, and at phone width they stack —
          leaving three anonymous boxes whose placeholders vanish as soon as they are filled. */}
      <div className="space-y-3">
        {rows.map((member, index) => (
          <Card key={index} className="p-3 sm:px-4">
            <div className="grid gap-3 sm:grid-cols-[8rem_1fr_1fr_auto]">
              <Field label={t("members.person")}>
                <Input
                  className="ltr-field"
                  value={member.person}
                  onChange={(event) => update(index, { person: event.target.value })}
                />
              </Field>
              <Field label={t("members.name")}>
                <Input
                  value={member.name}
                  onChange={(event) => update(index, { name: event.target.value })}
                />
              </Field>
              <Field label={t("members.github")}>
                <Input
                  className="ltr-field"
                  placeholder={t("members.githubHint")}
                  value={member.github ?? ""}
                  onChange={(event) => update(index, { github: event.target.value || null })}
                />
              </Field>

              {rows.length > 1 && (
                <button
                  type="button"
                  aria-label={`${t("entries.delete")} ${member.name || member.person}`}
                  title={t("entries.delete")}
                  onClick={() => setDraft(rows.filter((_, i) => i !== index))}
                  className="flex size-11 items-center justify-center self-end justify-self-end rounded-xl text-negative hover:bg-negative/10"
                >
                  ×
                </button>
              )}
            </div>
          </Card>
        ))}
      </div>

      {budget.can_write && (
        <div className="mt-3">
          <FormActions
            primary={
              <Button
                type="button"
                disabled={draft === null || save.isPending}
                onClick={() => draft && save.mutate({ path: { budget: budget.slug }, body: draft })}
              >
                {t("members.save")}
              </Button>
            }
            secondary={
              <Button
                type="button"
                variant="quiet"
                onClick={() => setDraft([...rows, { person: "", name: "", github: null }])}
              >
                + {t("members.add")}
              </Button>
            }
          />
        </div>
      )}

      <FormError error={save.error} />

      {/* Invitations belong with the people they concern, not in a section of their own. */}
      <div className="mt-6">
        <InvitePerson budget={budget} />
      </div>
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
        className="mb-3 space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) create.mutate({ body: { name: name.trim(), scopes: ["read", "write"] } });
        }}
      >
        <Field label={t("settings.keyName")} className="sm:max-w-sm">
          <Input
            placeholder={t("settings.keyNameHint")}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <FormActions
          primary={
            <Button type="submit" disabled={!name.trim() || create.isPending}>
              {t("settings.createKey")}
            </Button>
          }
        />
      </form>

      {keys.data.length === 0 ? (
        <Card className="p-6 text-center text-ink-muted">{t("settings.noKeys")}</Card>
      ) : (
        <ul className="divide-y divide-line rounded-card border border-line bg-card">
          {keys.data.map((key) => (
            <li key={key.id} className="flex flex-wrap items-baseline gap-3 p-3 sm:px-4">
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
