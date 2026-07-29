import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { listRulesOptions, putRulesMutation } from "@/api/@tanstack/react-query.gen";
import type { RuleInput } from "@/api/types.gen";
import { Button, Field, FormError, Input } from "@/components/Form";
import { ErrorState, Loading } from "@/components/States";
import { useBudget } from "./useBudget";

/**
 * Rules decide how an entry is split when nobody specifies one.
 *
 * Order is the whole semantics — first match wins — so the list is edited and saved as a
 * list, with explicit move controls, rather than as independently editable rows.
 */
export function RulesScreen() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { budget, isPending: budgetPending } = useBudget();

  const rules = useQuery({
    ...listRulesOptions({ path: { budget: budget?.slug ?? "" } }),
    enabled: Boolean(budget),
  });
  const [draft, setDraft] = useState<RuleInput[] | null>(null);

  const save = useMutation({
    ...putRulesMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      setDraft(null);
    },
  });

  if (budgetPending || rules.isPending) return <Loading />;
  if (rules.isError || !budget) return <ErrorState onRetry={() => void rules.refetch()} />;

  const rows: RuleInput[] = draft ?? rules.data;
  const members = budget.members;

  const update = (index: number, patch: Partial<RuleInput>) =>
    setDraft(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= rows.length) return;
    const next = [...rows];
    const [row] = next.splice(index, 1);
    if (row) next.splice(target, 0, row);
    setDraft(next);
  };

  return (
    <section>
      <h1 className="text-lg font-semibold">{t("rules.title")}</h1>
      <p className="mb-4 text-sm text-ink-muted">{t("rules.hint")}</p>

      {rows.length === 0 && <p className="mb-4 text-ink-muted">{t("rules.none")}</p>}

      <ol className="space-y-3">
        {rows.map((rule, index) => (
          <li key={index} className="rounded-lg bg-surface-raised p-3 ring-1 ring-line">
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label={t("rules.id")}>
                <Input
                  dir="ltr"
                  value={rule.id}
                  onChange={(event) => update(index, { id: event.target.value })}
                />
              </Field>
              <Field label={t("rules.payeeContains")}>
                <Input
                  value={rule.when?.payee_contains ?? ""}
                  onChange={(event) =>
                    update(index, {
                      when: { ...rule.when, payee_contains: event.target.value || null },
                    })
                  }
                />
              </Field>
              <Field label={t("rules.tag")}>
                <Input
                  value={rule.when?.tag ?? ""}
                  onChange={(event) =>
                    update(index, { when: { ...rule.when, tag: event.target.value || null } })
                  }
                />
              </Field>
            </div>

            <div className="mt-2 flex flex-wrap items-end gap-3">
              <span className="text-xs text-ink-muted">{t("rules.split")}</span>
              {members.map((member) => (
                <label key={member.person} className="text-xs">
                  <span className="me-1">{member.name}</span>
                  <Input
                    className="numeric inline-block w-20"
                    inputMode="decimal"
                    value={String(rule.split?.[member.person] ?? "")}
                    onChange={(event) => {
                      const split = { ...rule.split };
                      if (event.target.value === "") delete split[member.person];
                      else split[member.person] = event.target.value;
                      update(index, { split });
                    }}
                    placeholder="0.5"
                  />
                </label>
              ))}
            </div>

            <div className="mt-2 flex gap-2">
              <Button type="button" variant="quiet" onClick={() => move(index, -1)}>
                ↑
              </Button>
              <Button type="button" variant="quiet" onClick={() => move(index, 1)}>
                ↓
              </Button>
              <Button
                type="button"
                variant="quiet"
                onClick={() => setDraft(rows.filter((_, i) => i !== index))}
              >
                {t("entries.delete")}
              </Button>
            </div>
          </li>
        ))}
      </ol>

      {budget.can_write && (
        <div className="mt-4 flex gap-2">
          <Button
            type="button"
            variant="quiet"
            onClick={() =>
              setDraft([
                ...rows,
                {
                  id: `rule-${rows.length + 1}`,
                  when: {},
                  split: Object.fromEntries(members.map((m) => [m.person, "1"])),
                  bucket: {},
                },
              ])
            }
          >
            {t("rules.add")}
          </Button>
          <Button
            type="button"
            disabled={draft === null || save.isPending}
            onClick={() => draft && save.mutate({ path: { budget: budget.slug }, body: draft })}
          >
            {t("rules.save")}
          </Button>
        </div>
      )}

      <FormError error={save.error} />
    </section>
  );
}
