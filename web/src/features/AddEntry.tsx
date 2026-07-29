import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createEntryMutation,
  listBucketsOptions,
  previewSplitMutation,
} from "@/api/@tanstack/react-query.gen";
import { SplitEditor, evenSplit, type PaidRow, type ShareRow } from "./SplitEditor";
import type { BudgetSummary } from "@/api/types.gen";
import { Button, Field, FormError, Input, Select } from "@/components/Form";
import { Money } from "@/components/Money";

const KINDS = ["expense", "income", "transfer", "settlement"] as const;
type Kind = (typeof KINDS)[number];

/** Only an expense books against an envelope; the other kinds move money without one. */
function usesBucket(kind: Kind): boolean {
  return kind === "expense";
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function AddEntry({
  budget,
  onDone,
  bare = false,
}: {
  budget: BudgetSummary;
  onDone: () => void;
  /** Drop the card chrome when the form is already inside a dialog. */
  bare?: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [kind, setKind] = useState<Kind>("expense");
  const [amount, setAmount] = useState("");
  const [payee, setPayee] = useState("");
  const [date, setDate] = useState(today);
  const [bucket, setBucket] = useState("");
  const [note, setNote] = useState("");

  // Off by default: most entries are handled by the rules, and showing eight inputs for a
  // coffee would bury the common case. On, it exposes both halves of the split.
  const [custom, setCustom] = useState(false);
  const [shares, setShares] = useState<ShareRow[]>([]);
  const [paidBy, setPaidBy] = useState<PaidRow[]>([]);

  const buckets = useQuery({
    ...listBucketsOptions({ path: { budget: budget.slug } }),
    enabled: Boolean(budget.slug),
  });

  // The form takes a magnitude and the kind decides the sign. Asking someone to type a
  // leading minus for every purchase is a paper cut, and getting it wrong is silent.
  const signed = (value: string): string => {
    const magnitude = Math.abs(Number(value));
    if (!Number.isFinite(magnitude) || magnitude === 0) return "";
    return (kind === "income" ? magnitude : -magnitude).toFixed(2);
  };

  const body = () => ({
    amount: signed(amount),
    payee,
    date,
    kind,
    ...(usesBucket(kind) && bucket && !custom ? { bucket } : {}),
    ...(note ? { note } : {}),
    ...(custom
      ? {
          shares: shares
            .filter((row) => row.amount !== "")
            .map((row) => ({
              person: row.person,
              amount: row.amount,
              bucket: usesBucket(kind) && row.bucket ? row.bucket : null,
            })),
          paid_by: Object.fromEntries(
            paidBy.filter((row) => row.amount !== "").map((row) => [row.person, row.amount]),
          ),
        }
      : {}),
  });

  /** Seed the editor from the current form so it opens with something sensible, not blanks. */
  const openCustom = () => {
    const total = signed(amount);
    setShares(evenSplit(budget.members, total, usesBucket(kind) ? bucket : ""));
    setPaidBy([{ person: budget.me ?? budget.members[0]?.person ?? "", amount: total }]);
    setCustom(true);
  };

  // Shows what the rules will do before anything is written, which is the whole point of
  // having rules you cannot see from the form.
  const preview = useMutation(previewSplitMutation());

  const create = useMutation({
    ...createEntryMutation(),
    onSuccess: () => {
      // Balances, the month view and the ledger all derive from entries, so refresh
      // everything rather than trying to name each affected query.
      void queryClient.invalidateQueries();
      onDone();
    },
  });

  const ready = signed(amount) !== "" && payee.trim() !== "";

  return (
    <form
      className={bare ? "" : "sheet-in mb-4 rounded-card border border-line bg-card p-4"}
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) create.mutate({ path: { budget: budget.slug }, body: body() });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Field label={t("entries.kind")}>
          <Select value={kind} onChange={(event) => setKind(event.target.value as Kind)}>
            {KINDS.map((option) => (
              <option key={option} value={option}>
                {t(`entries.kinds.${option}`)}
              </option>
            ))}
          </Select>
        </Field>

        <Field label={t("entries.amount")} hint={t("entries.amountHint")}>
          <Input
            className="numeric ltr-field"
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            placeholder="50.00"
            autoFocus
          />
        </Field>

        <Field label={t("entries.payee")}>
          <Input value={payee} onChange={(event) => setPayee(event.target.value)} />
        </Field>

        <Field label={t("entries.date")}>
          <Input
            type="date"
            className="numeric"
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </Field>

        {usesBucket(kind) && (
          <Field label={t("entries.bucket")}>
            <Select value={bucket} onChange={(event) => setBucket(event.target.value)}>
              <option value="">—</option>
              {(buckets.data ?? []).map((option) => (
                <option key={option.id} value={option.id}>
                  {option.name}
                </option>
              ))}
            </Select>
          </Field>
        )}

        <Field label={t("entries.note")}>
          <Input value={note} onChange={(event) => setNote(event.target.value)} />
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={!ready || create.isPending}>
          {t("entries.save")}
        </Button>
        <Button
          type="button"
          variant="quiet"
          disabled={!ready || preview.isPending}
          onClick={() => preview.mutate({ path: { budget: budget.slug }, body: body() })}
        >
          {t("entries.splitPreview")}
        </Button>
        {custom ? (
          <>
            <Button type="button" variant="quiet" onClick={() => setCustom(false)}>
              {t("entries.useRules")}
            </Button>
            <Button
              type="button"
              variant="quiet"
              onClick={() =>
                setShares(
                  evenSplit(budget.members, signed(amount), usesBucket(kind) ? bucket : ""),
                )
              }
            >
              {t("entries.splitEven")}
            </Button>
          </>
        ) : (
          <Button type="button" variant="quiet" onClick={openCustom} disabled={!ready}>
            {t("entries.customSplit")}
          </Button>
        )}
        <Button type="button" variant="quiet" onClick={onDone}>
          {t("common.cancel")}
        </Button>

        {preview.data && (
          <span className="text-xs text-ink-muted">
            {preview.data.rule && <>{t("entries.splitBy", { rule: preview.data.rule })} · </>}
            {preview.data.shares.map((share) => (
              <span key={`${share.person}-${share.bucket}`} className="ms-2">
                {share.person}{" "}
                <Money amount={String(share.amount)} currency={budget.currency} colour={false} />
                {share.bucket && ` (${share.bucket})`}
              </span>
            ))}
          </span>
        )}
      </div>

      {custom && (
        <SplitEditor
          members={budget.members}
          buckets={buckets.data ?? []}
          total={signed(amount)}
          shares={shares}
          paidBy={paidBy}
          onSharesChange={setShares}
          onPaidByChange={setPaidBy}
          showBuckets={usesBucket(kind)}
        />
      )}

      <FormError error={create.error ?? preview.error} />
    </form>
  );
}
