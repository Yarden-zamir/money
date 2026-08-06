import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listBucketsOptions,
  listRulesOptions,
  putRulesMutation,
} from "@/api/@tanstack/react-query.gen";
import type { BucketOutput, RuleInput } from "@/api/types.gen";
import { Button, Card, Field, FormActions, FormError, Input, Select } from "@/components/Form";
import { ListSkeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/States";
import { useBudget } from "./useBudget";

/**
 * Rules decide how an entry is split when nobody specifies one.
 *
 * Order is the whole semantics — first match wins — so rules are numbered, moved explicitly,
 * and saved as a list rather than edited as independent rows.
 */
export function RulesScreen() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { budget, isPending: budgetPending } = useBudget();

  const rules = useQuery({
    ...listRulesOptions({ path: { budget: budget?.slug ?? "" } }),
    enabled: Boolean(budget),
  });
  const buckets = useQuery({
    ...listBucketsOptions({ path: { budget: budget?.slug ?? "" } }),
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

  if (budgetPending || rules.isPending) return <ListSkeleton rows={4} />;
  if (rules.isError || !budget) return <ErrorState onRetry={() => void rules.refetch()} />;

  const rows: RuleInput[] = draft ?? rules.data;
  const dirty = draft !== null;

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
    <section className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">{t("rules.title")}</h1>
        <p className="text-sm text-ink-muted">{t("rules.hint")}</p>
      </div>

      {rows.length === 0 && (
        <Card className="p-6 text-center text-ink-muted">{t("rules.none")}</Card>
      )}

      <ol className="space-y-3">
        {rows.map((rule, index) => (
          <RuleCard
            key={index}
            rule={rule}
            index={index}
            total={rows.length}
            buckets={buckets.data ?? []}
            canWrite={budget.can_write}
            onChange={(patch) => update(index, patch)}
            onMove={(delta) => move(index, delta)}
            onRemove={() => setDraft(rows.filter((_, i) => i !== index))}
          />
        ))}
      </ol>

      {budget.can_write && (
        <FormActions
          primary={
            <Button
              disabled={!dirty || save.isPending}
              onClick={() => draft && save.mutate({ path: { budget: budget.slug }, body: draft })}
            >
              {dirty ? t("rules.save") : t("rules.saved")}
            </Button>
          }
          secondary={
            <>
              <Button
                variant="quiet"
                onClick={() =>
                  setDraft([
                    ...rows,
                    { id: `rule-${rows.length + 1}`, when: {}, bucket: buckets.data?.[0]?.id ?? "" },
                  ])
                }
              >
                + {t("rules.add")}
              </Button>
              {dirty && (
                <Button variant="ghost" onClick={() => setDraft(null)}>
                  {t("common.cancel")}
                </Button>
              )}
            </>
          }
        />
      )}

      <FormError error={save.error} />
    </section>
  );
}

function RuleCard({
  rule,
  index,
  total,
  buckets,
  canWrite,
  onChange,
  onMove,
  onRemove,
}: {
  rule: RuleInput;
  index: number;
  total: number;
  buckets: BucketOutput[];
  canWrite: boolean;
  onChange: (patch: Partial<RuleInput>) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();

  const catchAll = !rule.when?.payee_contains && !rule.when?.tag;

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand">
          {index + 1}
        </span>
        {catchAll && (
          <span className="rounded-full bg-line px-2 py-0.5 text-[11px] text-ink-muted">
            {t("rules.catchAll")}
          </span>
        )}

        {canWrite && (
          <div className="ms-auto flex gap-1">
            {/* Vertical arrows encode list order, not reading direction, so they never flip. */}
            <IconButton label={t("rules.moveUp")} disabled={index === 0} onClick={() => onMove(-1)}>
              ↑
            </IconButton>
            <IconButton
              label={t("rules.moveDown")}
              disabled={index === total - 1}
              onClick={() => onMove(1)}
            >
              ↓
            </IconButton>
            <IconButton label={t("entries.delete")} onClick={onRemove} danger>
              ×
            </IconButton>
          </div>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Field label={t("rules.id")}>
          <Input
            className="ltr-field"
            value={rule.id}
            onChange={(event) => onChange({ id: event.target.value })}
          />
        </Field>
        <Field label={t("rules.payeeContains")}>
          <Input
            value={rule.when?.payee_contains ?? ""}
            placeholder={t("rules.anyPayee")}
            onChange={(event) =>
              onChange({ when: { ...rule.when, payee_contains: event.target.value || null } })
            }
          />
        </Field>
        <Field label={t("rules.tag")}>
          <Input
            value={rule.when?.tag ?? ""}
            placeholder={t("rules.anyTag")}
            onChange={(event) =>
              onChange({ when: { ...rule.when, tag: event.target.value || null } })
            }
          />
        </Field>
      </div>

      {/* A rule picks a bucket and nothing else. Who bears the spending is the bucket's
          split, because it is a property of the category rather than of the payee — and a
          rule that carried its own had to be kept in step with one that nothing enforced. */}
      <div className="mt-4">
        <Field label={t("entries.bucket")} hint={t("rules.bucketHint")}>
          <Select
            value={rule.bucket ?? ""}
            onChange={(event) => onChange({ bucket: event.target.value })}
          >
            {buckets.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
    </Card>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={`flex size-9 items-center justify-center rounded-lg text-base transition disabled:opacity-30 ${
        danger ? "text-negative hover:bg-negative/10" : "text-ink-muted hover:bg-surface"
      }`}
    >
      {children}
    </button>
  );
}
