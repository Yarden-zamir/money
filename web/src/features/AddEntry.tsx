import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createEntryMutation,
  listBucketsOptions,
  listRulesOptions,
  previewSplitMutation,
} from "@/api/@tanstack/react-query.gen";
import { Guessed } from "@/components/Guessed";
import { Icon } from "@/components/Icon";
import { PayeeField } from "./PayeeField";
import { ReceiptEditor, type ReceiptLine } from "./ReceiptEditor";
import { useCoords, useNearbyPlaces, useSuggestion } from "./useSuggestion";
import type { PickedPlace } from "./LocationPicker";

// Leaflet and its stylesheet are the app's one genuinely heavy dependency, and most entries
// never open the map. Split out so it is downloaded when someone asks for it.
const LocationPicker = lazy(() =>
  import("./LocationPicker").then((m) => ({ default: m.LocationPicker })),
);
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

  // Which fields the app filled, so a marker can disappear the moment one is edited: once it
  // is your number, saying the app guessed it would be a lie.
  const [guessed, setGuessed] = useState<Set<string>>(new Set());
  const forget = (field: string) =>
    setGuessed((current) => {
      if (!current.has(field)) return current;
      const next = new Set(current);
      next.delete(field);
      return next;
    });

  const [items, setItems] = useState<ReceiptLine[]>([]);
  const [place, setPlace] = useState<PickedPlace | null>(null);
  const [picking, setPicking] = useState(false);

  const { coords } = useCoords(true);
  const nearby = useNearbyPlaces(coords);
  const suggestion = useSuggestion({ budget: budget.slug, enabled: true, payee, coords });

  // Applied once per distinct suggestion and only into untouched fields. Overwriting what
  // someone typed would make the guess worse than useless.
  const applied = useRef<string | null>(null);
  useEffect(() => {
    const guess = suggestion.data;
    if (!guess || guess.basis === "none") return;

    const signature = `${guess.basis}:${guess.payee}:${String(guess.amount)}`;
    if (applied.current === signature) return;
    applied.current = signature;

    const filled = new Set<string>();
    if (!payee && guess.payee) {
      setPayee(guess.payee);
      filled.add("payee");
    }
    if (!amount && guess.amount != null) {
      setAmount(Math.abs(Number(guess.amount)).toFixed(2));
      filled.add("amount");
    }
    if (!bucket && guess.bucket) {
      setBucket(guess.bucket);
      filled.add("bucket");
    }
    if (items.length === 0 && guess.items.length > 0) {
      setItems(
        guess.items.map((item) => ({
          label: item.label,
          amount: Math.abs(Number(item.amount)).toFixed(2),
        })),
      );
      filled.add("items");
    }
    if (filled.size) setGuessed(filled);
  }, [suggestion.data, payee, amount, bucket, items.length]);

  // The nearest venue names the place on a first visit, when history has nothing to offer.
  useEffect(() => {
    if (place || !nearby.data?.length) return;
    const closest = nearby.data[0];
    if (closest) {
      setPlace({
        lat: closest.lat,
        lon: closest.lon,
        name: closest.name,
        provider_id: closest.id,
      });
    }
  }, [nearby.data, place]);

  const buckets = useQuery({
    ...listBucketsOptions({ path: { budget: budget.slug } }),
    enabled: Boolean(budget.slug),
  });

  // Rules can supply the bucket an expense is missing, so whether one must be picked here
  // depends on whether any rule exists at all.
  const rules = useQuery({
    ...listRulesOptions({ path: { budget: budget.slug } }),
    enabled: Boolean(budget.slug),
  });

  // The form takes a magnitude and the kind decides the sign. Asking someone to type a
  // leading minus for every purchase is a paper cut, and getting it wrong is silent.
  const signed = (value: string): string => {
    const magnitude = Math.abs(Number(value));
    if (!Number.isFinite(magnitude) || magnitude === 0) return "";
    return (kind === "income" ? magnitude : -magnitude).toFixed(2);
  };

  const lineTotal = items.reduce((total, item) => total + (Number(item.amount) || 0), 0);

  const body = () => ({
    amount: signed(amount),
    // The place's own coordinates, not the device's. Picking "the café across the road"
    // used to record the pavement this phone was standing on.
    ...(place
      ? {
          place: {
            lat: place.lat,
            lon: place.lon,
            name: place.name,
            provider_id: place.provider_id ?? null,
          },
        }
      : {}),
    ...(items.filter((item) => item.label.trim() && item.amount).length
      ? {
          items: items
            .filter((item) => item.label.trim() && item.amount)
            .map((item) => ({
              label: item.label.trim(),
              amount: (
                (kind === "income" ? 1 : -1) * Math.abs(Number(item.amount))
              ).toFixed(2),
            })),
        }
      : {}),
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

  // An expense has to land in some envelope. The bucket can come from this field or from a
  // rule, but if neither can supply one the entry is rejected by the domain — so the form
  // says which of the two is missing instead of letting someone submit into a 422.
  const noBuckets = usesBucket(kind) && buckets.isSuccess && buckets.data.length === 0;
  const bucketMissing =
    usesBucket(kind) && !custom && !bucket && rules.isSuccess && rules.data.length === 0;

  const ready =
    signed(amount) !== "" && payee.trim() !== "" && !noBuckets && !bucketMissing;

  return (
    <form
      className={bare ? "" : "sheet-in mb-4 rounded-card border border-line bg-card p-4"}
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) create.mutate({ path: { budget: budget.slug }, body: body() });
      }}
    >
      {/* With no buckets an expense cannot be recorded at all, and every other field here is
          wasted typing — so this comes first and names the fix.

          Told, not linked: this form also renders inside the quick-add dialog, where
          navigating away would leave the dialog open over the screen it moved to. */}
      {noBuckets && (
        <p className="mb-3 rounded-lg bg-warning/15 p-2.5 text-xs text-ink">
          {t("entries.noBucketsYet")}
        </p>
      )}

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

        <Field
          label={t("entries.amount")}
          hint={t("entries.amountHint")}
          suffix={
            guessed.has("amount") && suggestion.data ? (
              <Guessed
                reason={suggestion.data.reason}
                confidence={suggestion.data.confidence}
                sampleSize={suggestion.data.sample_size}
              />
            ) : null
          }
        >
          <Input
            className="numeric ltr-field"
            inputMode="decimal"
            value={amount}
            onChange={(event) => {
              setAmount(event.target.value);
              forget("amount");
            }}
            placeholder="50.00"
            autoFocus
          />
        </Field>

        <Field
          label={t("entries.payee")}
          suffix={
            guessed.has("payee") && suggestion.data ? (
              <Guessed
                reason={suggestion.data.reason}
                confidence={suggestion.data.confidence}
                sampleSize={suggestion.data.sample_size}
              />
            ) : null
          }
        >
          <PayeeField
            budget={budget.slug}
            currency={budget.currency}
            value={payee}
            onChange={(next) => {
              setPayee(next);
              forget("payee");
            }}
            onPick={(suggestion) => {
              // Filling only what is still empty: someone who already typed an amount meant
              // it, and having a suggestion overwrite it would be worse than no suggestion.
              setPayee(suggestion.payee);
              if (!amount && suggestion.amount != null) {
                setAmount(Math.abs(Number(suggestion.amount)).toFixed(2));
              }
              if (!bucket && suggestion.bucket) setBucket(suggestion.bucket);
            }}
          />
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
          <Field
            label={t("entries.bucket")}
            hint={bucketMissing ? t("entries.bucketRequired") : undefined}
          >
            <Select value={bucket} onChange={(event) => setBucket(event.target.value)}>
              {/* An empty bucket only works when a rule can fill it in. With no rules it is
                  a choice that cannot succeed, so it becomes a prompt rather than a trap —
                  still the selected value, so the field never shows a bucket nobody picked. */}
              {bucketMissing ? (
                <option value="" disabled>
                  {t("entries.chooseBucket")}
                </option>
              ) : (
                <option value="">{t("entries.byRule")}</option>
              )}
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

      {/* Location is opt-in detail, so it sits below the fields rather than among them. The
          map only loads when asked for — it is the one screen with a heavy dependency. */}
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
        {place ? (
          <>
            <Icon name="target" className="size-3.5" />
            <span>{place.name ?? t("place.aPoint")}</span>
            <button
              type="button"
              className="text-brand underline underline-offset-2"
              onClick={() => setPicking(true)}
            >
              {t("place.change")}
            </button>
            <button
              type="button"
              aria-label={t("common.cancel")}
              className="hover:text-negative"
              onClick={() => setPlace(null)}
            >
              <Icon name="close" className="size-3" />
            </button>
          </>
        ) : (
          <button
            type="button"
            className="inline-flex items-center gap-1.5 text-brand underline underline-offset-2"
            onClick={() => setPicking(true)}
          >
            <Icon name="target" className="size-3.5" />
            {t("place.set")}
          </button>
        )}
      </div>

      {picking && (
        <div className="mt-3">
          <Suspense fallback={<p className="text-xs text-ink-muted">{t("common.loading")}</p>}>
            <LocationPicker
              coords={coords}
              initial={place}
              onPick={(picked) => {
                setPlace(picked);
                setPicking(false);
              }}
              onCancel={() => setPicking(false)}
            />
          </Suspense>
        </div>
      )}

      <ReceiptEditor
        items={items}
        currency={budget.currency}
        total={Math.abs(Number(amount)) || 0}
        lineTotal={lineTotal}
        onChange={(next) => {
          setItems(next);
          forget("items");
        }}
      />

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
