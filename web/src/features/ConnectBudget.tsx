import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  connectBudgetMutation,
  listGithubReposOptions,
} from "@/api/@tanstack/react-query.gen";
import { Button, Field, FormActions, FormError, Input } from "@/components/Form";

/**
 * Points the app at the private GitHub repo holding a budget's data.
 *
 * Typing `owner/repo` from memory was the only way to do this, which meant a typo produced a
 * 404 with no clue whether the repo was wrong or the access was. The list shows what the
 * signed-in user can actually push to, marks which already contain a `budget.yaml`, and
 * still accepts a hand-typed name for anything not listed.
 */
export function ConnectBudget({ onConnected }: { onConnected?: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [slug, setSlug] = useState("");
  const [repo, setRepo] = useState("");
  const [manual, setManual] = useState(false);

  const repos = useQuery({ ...listGithubReposOptions(), retry: false });

  const connect = useMutation({
    ...connectBudgetMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      setSlug("");
      setRepo("");
      onConnected?.();
    },
  });

  // The slug is derived from the repo name, so the common case is one choice, not two fields.
  const suggestedSlug = (fullName: string) =>
    (fullName.split("/")[1] ?? "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .replace(/^budget-/, "")
      .slice(0, 39) || "budget";

  const choose = (fullName: string) => {
    setRepo(fullName);
    if (!slug) setSlug(suggestedSlug(fullName));
  };

  const options = repos.data ?? [];
  const ready = slug.trim() !== "" && repo.includes("/");

  return (
    <form
      className="rounded-card border border-line bg-card p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) connect.mutate({ body: { slug: slug.trim(), repo: repo.trim() } });
      }}
    >
      {!manual && (
        <div className="mb-3">
          <span className="mb-1.5 block text-xs font-medium text-ink-muted">
            {t("budgets.chooseRepo")}
          </span>

          {repos.isPending ? (
            <p className="text-sm text-ink-muted">{t("common.loading")}</p>
          ) : options.length === 0 ? (
            <p className="text-sm text-ink-muted">{t("budgets.noRepos")}</p>
          ) : (
            <ul className="max-h-64 divide-y divide-line overflow-y-auto rounded-xl border border-line">
              {options.map((option) => (
                <li key={option.full_name}>
                  <button
                    type="button"
                    disabled={option.connected}
                    onClick={() => choose(option.full_name)}
                    className={`flex w-full items-center gap-2 p-2.5 text-start text-sm transition ${
                      repo === option.full_name ? "bg-brand-soft" : "hover:bg-surface"
                    } disabled:opacity-40`}
                  >
                    <span className="ltr-field min-w-0 flex-1 truncate">{option.full_name}</span>
                    {option.is_budget && (
                      <span className="shrink-0 rounded-full bg-positive/15 px-2 py-0.5 text-[11px] text-positive">
                        {t("budgets.hasBudgetFile")}
                      </span>
                    )}
                    {option.connected && (
                      <span className="shrink-0 rounded-full bg-line px-2 py-0.5 text-[11px] text-ink-muted">
                        {t("budgets.alreadyConnected")}
                      </span>
                    )}
                    {option.private && (
                      <span className="shrink-0 text-[11px] text-ink-muted">
                        {t("budgets.private")}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}

          <FormError error={repos.error} />
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {manual && (
          <Field label={t("budgets.repo")} hint={t("budgets.repoHint")}>
            <Input
              className="ltr-field"
              value={repo}
              onChange={(event) => setRepo(event.target.value)}
              placeholder="Yarden-zamir/budget-joint"
            />
          </Field>
        )}
        <Field label={t("budgets.slug")} hint={t("budgets.slugHint")}>
          <Input
            className="ltr-field"
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
            placeholder="joint"
          />
        </Field>
      </div>

      <div className="mt-3">
        <FormActions
          primary={
            <Button type="submit" disabled={!ready || connect.isPending}>
              {connect.isPending ? t("budgets.connecting") : t("budgets.connect")}
            </Button>
          }
          secondary={
            <Button type="button" variant="ghost" onClick={() => setManual(!manual)}>
              {manual ? t("budgets.chooseFromList") : t("budgets.enterManually")}
            </Button>
          }
        />
      </div>

      <FormError error={connect.error} />
    </form>
  );
}
