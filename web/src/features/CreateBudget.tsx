import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createBudgetMutation, getMeOptions } from "@/api/@tanstack/react-query.gen";
import { Button, Field, FormActions, FormError, Input, Select } from "@/components/Form";

/** Currencies offered up front. Anything else is reachable by editing budget.yaml. */
const CURRENCIES = ["ILS", "USD", "EUR", "GBP"];

/**
 * Starting a budget from nothing.
 *
 * Until this existed the only way in was to hand-write `budget.yaml` in a GitHub repo,
 * which meant the app could not be started by anyone who had not already been told how it
 * stores data. Everything here except the name is derived and collapsed behind "advanced",
 * because the repo name, the slug and your person id are all implementation the person
 * should not have to have an opinion about on their first screen.
 */
export function CreateBudget({ onCreated }: { onCreated?: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const me = useQuery({ ...getMeOptions(), retry: false });

  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("ILS");
  const [advanced, setAdvanced] = useState(false);
  const [repo, setRepo] = useState("");
  const [slug, setSlug] = useState("");
  const [person, setPerson] = useState("");

  const create = useMutation({
    ...createBudgetMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      onCreated?.();
    },
  });

  /** Lower-case, dashes for runs of anything else, trimmed to what the API accepts. */
  const idFrom = (text: string, fallback: string) =>
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 39) || fallback;

  // Derived unless the person opened advanced and typed over them, so the common path is
  // one field. `budget-` prefixes the repo because it lands among all their other repos —
  // unless the name already starts that way, which would produce `budget-budget`.
  const login = me.data?.login ?? "";
  const finalSlug = slug.trim() || idFrom(name, "budget");
  const finalRepo =
    repo.trim() || (finalSlug.startsWith("budget") ? finalSlug : `budget-${finalSlug}`);
  const finalPerson = person.trim() || idFrom(me.data?.name ?? login, "me");
  const ready = name.trim() !== "" && login !== "";

  return (
    <form
      className="rounded-card border border-line bg-card p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready || create.isPending) return;
        create.mutate({
          body: {
            name: name.trim(),
            currency,
            slug: finalSlug,
            repo: finalRepo,
            person: finalPerson,
            display_name: me.data?.name || login,
          },
        });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("budgets.name")} hint={t("budgets.nameHint")}>
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("budgets.namePlaceholder")}
            autoFocus
          />
        </Field>
        <Field label={t("budgets.currency")}>
          <Select value={currency} onChange={(event) => setCurrency(event.target.value)}>
            {CURRENCIES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      {advanced && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Field label={t("budgets.repo")} hint={t("budgets.repoCreateHint")}>
            <Input
              className="ltr-field"
              value={repo}
              onChange={(event) => setRepo(event.target.value)}
              placeholder={finalRepo}
            />
          </Field>
          <Field label={t("budgets.slug")} hint={t("budgets.slugHint")}>
            <Input
              className="ltr-field"
              value={slug}
              onChange={(event) => setSlug(event.target.value)}
              placeholder={finalSlug}
            />
          </Field>
          <Field label={t("budgets.person")} hint={t("budgets.personHint")}>
            <Input
              className="ltr-field"
              value={person}
              onChange={(event) => setPerson(event.target.value)}
              placeholder={finalPerson}
            />
          </Field>
        </div>
      )}

      {/* Says what pressing the button will actually do to their GitHub account. Creating a
          repo is a visible, external side effect and should not be a surprise.

          Held back until there is a name, because the repo is derived from it: on an empty
          form this would name a repo that has nothing to do with what they end up creating. */}
      {name.trim() !== "" && (
        <p className="mt-3 text-xs text-ink-muted">
          {t("budgets.createSummary", { repo: `${login || "you"}/${finalRepo}` })}
        </p>
      )}

      <div className="mt-3">
        <FormActions
          primary={
            <Button type="submit" disabled={!ready || create.isPending}>
              {create.isPending ? t("budgets.creating") : t("budgets.create")}
            </Button>
          }
          secondary={
            <Button type="button" variant="ghost" onClick={() => setAdvanced(!advanced)}>
              {advanced ? t("budgets.hideAdvanced") : t("budgets.showAdvanced")}
            </Button>
          }
        />
      </div>

      <FormError error={create.error} />
    </form>
  );
}
