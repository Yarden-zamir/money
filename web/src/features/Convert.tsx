import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  convertBucketMutation,
  convertEntryMutation,
  lookupRateOptions,
} from "@/api/@tanstack/react-query.gen";
import { Button, Field, FormActions, FormError, Input } from "@/components/Form";
import { Money } from "@/components/Money";

/**
 * Converting after the fact: one entry, or every unconverted entry in one currency with a
 * share in a bucket. Both default to the rate for *today*, because that is what "convert it
 * now" means, and both take a typed rate instead. See specs/currency.md, CUR-7 and CUR-8.
 *
 * The lookup commits nothing; the rate is written by the conversion that uses it.
 */
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function useRate(budget: string, currency: string | null, date: string) {
  return useQuery({
    ...lookupRateOptions({ path: { budget }, query: { currency: currency ?? "XXX", date } }),
    enabled: Boolean(currency),
    staleTime: 60_000,
  });
}

/** Rate input pre-filled from the lookup, plus the line that says what it will do. */
export function RateField({
  budget,
  currency,
  base,
  rate,
  onRate,
}: {
  budget: string;
  currency: string;
  base: string;
  rate: string;
  onRate: (rate: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const lookup = useRate(budget, currency, today());
  const suggested = lookup.data?.rate ?? null;

  return (
    <Field
      label={t("currency.rate")}
      hint={
        lookup.isPending
          ? t("currency.lookingUp")
          : suggested
            ? t("currency.rateFor", {
                rate: suggested,
                date: new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" }).format(
                  new Date(lookup.data?.date ?? today()),
                ),
              })
            : t("currency.noRate", { currency })
      }
    >
      <Input
        className="numeric ltr-field"
        inputMode="decimal"
        placeholder={suggested ?? "0.0000"}
        value={rate}
        onChange={(event) => onRate(event.target.value)}
        aria-label={t("currency.rateHint", { base, currency })}
      />
    </Field>
  );
}

export function ConvertEntry({
  budget,
  base,
  entryId,
  amount,
  currency,
  onDone,
}: {
  budget: string;
  base: string;
  entryId: string;
  amount: string;
  currency: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [rate, setRate] = useState("");
  const lookup = useRate(budget, currency, today());
  const effective = rate || lookup.data?.rate || "";

  const convert = useMutation({
    ...convertEntryMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      onDone();
    },
  });

  return (
    <form
      className="mt-2 space-y-2 rounded-lg border border-line p-3"
      onSubmit={(event) => {
        event.preventDefault();
        convert.mutate({
          path: { budget, entry_id: entryId },
          body: rate ? { rate } : {},
        });
      }}
    >
      <RateField budget={budget} currency={currency} base={base} rate={rate} onRate={setRate} />
      {effective && (
        <p className="text-xs text-ink-muted">
          <Money amount={amount} currency={currency} colour={false} /> →{" "}
          <Money amount={(Number(amount) * Number(effective)).toFixed(2)} currency={base} colour={false} />
        </p>
      )}
      <FormActions
        primary={
          <Button type="submit" disabled={convert.isPending || (!rate && !lookup.data?.rate)}>
            {convert.isPending ? t("currency.converting") : t("currency.convertEntry", { currency: base })}
          </Button>
        }
        secondary={
          <Button type="button" variant="ghost" onClick={onDone}>
            {t("common.cancel")}
          </Button>
        }
      />
      <FormError error={convert.error} />
    </form>
  );
}

export function ConvertBucket({
  budget,
  base,
  bucketId,
  bucketName,
  currency,
  amount,
  onDone,
}: {
  budget: string;
  base: string;
  bucketId: string;
  bucketName: string;
  currency: string;
  amount: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [rate, setRate] = useState("");
  const [spanning, setSpanning] = useState(0);
  const lookup = useRate(budget, currency, today());
  const effective = rate || lookup.data?.rate || "";

  const convert = useMutation({
    ...convertBucketMutation(),
    onSuccess: (result) => {
      void queryClient.invalidateQueries();
      const moved = result.spanning?.length ?? 0;
      if (moved) setSpanning(moved);
      else onDone();
    },
  });

  return (
    <form
      className="sheet-in mt-2 space-y-2 rounded-lg border border-line bg-card p-3"
      onSubmit={(event) => {
        event.preventDefault();
        convert.mutate({
          path: { budget, bucket_id: bucketId },
          body: rate ? { currency, rate } : { currency },
        });
      }}
    >
      <p className="text-sm font-medium">
        {t("currency.convertBucket", { currency, bucket: bucketName })}
      </p>
      <RateField budget={budget} currency={currency} base={base} rate={rate} onRate={setRate} />
      {effective && (
        <p className="text-xs text-ink-muted">
          <Money amount={amount} currency={currency} colour={false} /> →{" "}
          <Money amount={(Number(amount) * Number(effective)).toFixed(2)} currency={base} colour={false} />
        </p>
      )}
      {spanning > 0 ? (
        <>
          <p className="text-xs text-warning">{t("currency.spanning", { count: spanning })}</p>
          <Button type="button" variant="quiet" onClick={onDone}>
            {t("split.done")}
          </Button>
        </>
      ) : (
        <FormActions
          primary={
            <Button type="submit" disabled={convert.isPending || (!rate && !lookup.data?.rate)}>
              {convert.isPending ? t("currency.converting") : t("currency.convert")}
            </Button>
          }
          secondary={
            <Button type="button" variant="ghost" onClick={onDone}>
              {t("common.cancel")}
            </Button>
          }
        />
      )}
      <FormError error={convert.error} />
    </form>
  );
}
