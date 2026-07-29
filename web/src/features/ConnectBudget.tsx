import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { connectBudgetMutation } from "@/api/@tanstack/react-query.gen";
import { Button, Field, FormError, Input } from "@/components/Form";

/**
 * Points the app at the private GitHub repo holding a budget's data.
 *
 * This is the first thing anyone has to do — until a repo is connected there is nothing for
 * any other screen to show.
 */
export function ConnectBudget({ onConnected }: { onConnected?: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [slug, setSlug] = useState("");
  const [repo, setRepo] = useState("");

  const connect = useMutation({
    ...connectBudgetMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      setSlug("");
      setRepo("");
      onConnected?.();
    },
  });

  const ready = slug.trim() !== "" && repo.includes("/");

  return (
    <form
      className="rounded-card border border-line bg-card p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) connect.mutate({ body: { slug: slug.trim(), repo: repo.trim() } });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("budgets.slug")} hint={t("budgets.slugHint")}>
          <Input
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
            placeholder="joint"
          />
        </Field>
        <Field label={t("budgets.repo")} hint={t("budgets.repoHint")}>
          <Input
            dir="ltr"
            value={repo}
            onChange={(event) => setRepo(event.target.value)}
            placeholder="Yarden-zamir/budget-joint"
          />
        </Field>
      </div>

      <Button type="submit" className="mt-3" disabled={!ready || connect.isPending}>
        {connect.isPending ? t("budgets.connecting") : t("budgets.connect")}
      </Button>

      <FormError error={connect.error} />
    </form>
  );
}
