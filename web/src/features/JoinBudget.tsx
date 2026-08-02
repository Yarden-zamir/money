import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getMeOptions, joinBudgetMutation } from "@/api/@tanstack/react-query.gen";
import type { BudgetSummary } from "@/api/types.gen";
import { Button, Field, FormError, Input } from "@/components/Form";

/**
 * Shown when you can push to a budget's repo but are not named in `budget.yaml`.
 *
 * That combination is ordinary, not exceptional: it is exactly what someone sees the first
 * time a partner shares a budget with them. Before this, every screen answered with a 403
 * telling them to go and edit YAML — including the member editor that would have fixed it.
 *
 * Only ever adds the signed-in person. Changing anyone else stays in settings, where
 * removing a member is checked against the entries that still reference them.
 */
export function JoinBudget({ budget }: { budget: BudgetSummary }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const me = useQuery({ ...getMeOptions(), retry: false });

  const [person, setPerson] = useState("");
  const taken = new Set(budget.members.map((member) => member.person));

  const suggested = (() => {
    const base =
      (me.data?.name ?? me.data?.login ?? "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 39) || "me";
    if (!taken.has(base)) return base;
    // The obvious id is already someone else's; offer a free one rather than a 409.
    for (let suffix = 2; suffix < 100; suffix += 1) {
      if (!taken.has(`${base}-${suffix}`)) return `${base}-${suffix}`;
    }
    return base;
  })();

  const join = useMutation({
    ...joinBudgetMutation(),
    onSuccess: () => void queryClient.invalidateQueries(),
  });

  const finalPerson = person.trim() || suggested;
  const conflict = taken.has(finalPerson);

  return (
    <section className="mx-auto max-w-xl">
      <h1 className="mb-1 text-lg font-semibold">{t("budgets.notMember", { name: budget.name })}</h1>
      <p className="mb-4 text-sm text-ink-muted">{t("budgets.notMemberHelp")}</p>

      <form
        className="rounded-card border border-line bg-card p-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (conflict || join.isPending || !me.data) return;
          join.mutate({
            path: { budget: budget.slug },
            body: {
              person: finalPerson,
              display_name: me.data.name || me.data.login,
            },
          });
        }}
      >
        <Field label={t("budgets.person")} hint={t("budgets.personHint")}>
          <Input
            className="ltr-field"
            value={person}
            onChange={(event) => setPerson(event.target.value)}
            placeholder={suggested}
          />
        </Field>

        {conflict && <p className="mt-2 text-xs text-negative">{t("budgets.personTaken")}</p>}

        <p className="mt-3 text-xs text-ink-muted">
          {t("budgets.membersAlready", {
            names: budget.members.map((member) => member.name).join(", "),
          })}
        </p>

        <div className="mt-3">
          <Button type="submit" disabled={conflict || join.isPending || !me.data}>
            {join.isPending ? t("budgets.joining") : t("budgets.join")}
          </Button>
        </div>

        <FormError error={join.error} />
      </form>
    </section>
  );
}
