import { useTranslation } from "react-i18next";

import type { BucketOutput, Member } from "@/api/types.gen";
import { MemberDot } from "@/components/FunderBars";
import { Field, Input, Select } from "@/components/Form";
import { Money } from "@/components/Money";

/**
 * Who bears an entry, and who paid for it — edited as a *decision*, not as a list of numbers.
 *
 * The first version asked for an amount per person and refused anything that did not add up.
 * That is the shape the ledger stores, and it is the wrong shape to type: "we split it in
 * thirds" or "she owes ten more for the wine" is what somebody knows at the till, and the
 * amounts follow from it. So the editor takes the decision in one of five modes and derives
 * the amounts, with the remainder allocated the way the backend does it — largest share
 * takes the rounding — so the shares always sum exactly and never trip validation.
 *
 * Arithmetic is done in whole agorot, never in floating point: 0.1 + 0.2 must not become
 * 0.30000000000000004 on its way to a ledger that stores decimals.
 */

export type SplitMode = "equal" | "percent" | "shares" | "exact" | "adjust";
export const SPLIT_MODES: SplitMode[] = ["equal", "percent", "shares", "exact", "adjust"];

export type SplitDraft = {
  mode: SplitMode;
  /** Equal mode: who is in. Everyone, by default. */
  included: Record<string, boolean>;
  percent: Record<string, string>;
  weights: Record<string, string>;
  exact: Record<string, string>;
  /** Adjust mode: a fixed extra for a person, on top of an equal share of the rest. */
  adjust: Record<string, string>;
  /** One bucket for every share. Per-line buckets are what receipt lines are for. */
  bucket: string;
};

export type ShareRow = { person: string; amount: string; bucket: string };
export type PaidRow = { person: string; amount: string };

export function emptyDraft(members: Member[], bucket: string): SplitDraft {
  return {
    mode: "equal",
    included: Object.fromEntries(members.map((member) => [member.person, true])),
    percent: {},
    weights: Object.fromEntries(members.map((member) => [member.person, "1"])),
    exact: {},
    adjust: {},
    bucket,
  };
}

/** Parse a typed number into agorot. Blank and junk are 0, which is what a blank row means. */
function cents(value: string | undefined): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed * 100) : 0;
}

function fromCents(value: number): string {
  return (value / 100).toFixed(2);
}

/**
 * Distribute `total` agorot across weights so the parts sum exactly to the total.
 * Mirrors `money.domain.amounts.allocate`: the largest weight absorbs the rounding.
 */
function allocate(total: number, weights: Record<string, number>): Record<string, number> {
  const sum = Object.values(weights).reduce((a, b) => a + b, 0);
  if (sum <= 0) return {};
  const parts: Record<string, number> = {};
  let handed = 0;
  for (const [person, weight] of Object.entries(weights)) {
    const part = Math.round((total * weight) / sum);
    parts[person] = part;
    handed += part;
  }
  const drift = total - handed;
  if (drift !== 0) {
    const largest = Object.entries(weights).sort((a, b) => b[1] - a[1])[0];
    if (largest) parts[largest[0]] = (parts[largest[0]] ?? 0) + drift;
  }
  return parts;
}

export type Computed = {
  shares: ShareRow[];
  /** Why the shares cannot be used yet, if they cannot. */
  problem: "percent" | "exact" | "nobody" | "adjust" | null;
  /** How far off the constraint is, in agorot or in percent points depending on the mode. */
  off: number;
};

/** The shares a draft describes for a signed `total`, or the reason it describes none. */
export function computeShares(draft: SplitDraft, members: Member[], total: string): Computed {
  const signed = cents(total);
  const magnitude = Math.abs(signed);
  const sign = signed < 0 ? -1 : 1;
  const people = members.map((member) => member.person);
  const toRows = (parts: Record<string, number>): ShareRow[] =>
    people
      .filter((person) => (parts[person] ?? 0) !== 0)
      .map((person) => ({
        person,
        amount: fromCents(sign * (parts[person] ?? 0)),
        bucket: draft.bucket,
      }));

  switch (draft.mode) {
    case "equal": {
      const included = people.filter((person) => draft.included[person] !== false);
      if (included.length === 0) return { shares: [], problem: "nobody", off: 0 };
      return {
        shares: toRows(allocate(magnitude, Object.fromEntries(included.map((p) => [p, 1])))),
        problem: null,
        off: 0,
      };
    }
    case "percent": {
      const percents = Object.fromEntries(
        people.map((person) => [person, Math.max(0, Number(draft.percent[person]) || 0)]),
      );
      const sum = Object.values(percents).reduce((a, b) => a + b, 0);
      if (Math.abs(sum - 100) > 0.001) {
        return { shares: [], problem: "percent", off: Math.round((sum - 100) * 100) / 100 };
      }
      return { shares: toRows(allocate(magnitude, percents)), problem: null, off: 0 };
    }
    case "shares": {
      const weights = Object.fromEntries(
        people.map((person) => [person, Math.max(0, Number(draft.weights[person]) || 0)]),
      );
      if (Object.values(weights).every((weight) => weight === 0)) {
        return { shares: [], problem: "nobody", off: 0 };
      }
      return { shares: toRows(allocate(magnitude, weights)), problem: null, off: 0 };
    }
    case "exact": {
      const parts = Object.fromEntries(
        people.map((person) => [person, Math.abs(cents(draft.exact[person]))]),
      );
      const sum = Object.values(parts).reduce((a, b) => a + b, 0);
      if (sum !== magnitude) return { shares: [], problem: "exact", off: sum - magnitude };
      return { shares: toRows(parts), problem: null, off: 0 };
    }
    case "adjust": {
      const extras = Object.fromEntries(
        people.map((person) => [person, Math.abs(cents(draft.adjust[person]))]),
      );
      const extraTotal = Object.values(extras).reduce((a, b) => a + b, 0);
      if (extraTotal > magnitude) {
        return { shares: [], problem: "adjust", off: extraTotal - magnitude };
      }
      const rest = allocate(magnitude - extraTotal, Object.fromEntries(people.map((p) => [p, 1])));
      const parts = Object.fromEntries(
        people.map((person) => [person, (rest[person] ?? 0) + (extras[person] ?? 0)]),
      );
      return { shares: toRows(parts), problem: null, off: 0 };
    }
  }
}

export function SplitEditor({
  members,
  buckets,
  total,
  currency,
  draft,
  onDraftChange,
  paidBy,
  onPaidByChange,
  showBuckets,
}: {
  members: Member[];
  buckets: BucketOutput[];
  total: string;
  currency: string;
  draft: SplitDraft;
  onDraftChange: (draft: SplitDraft) => void;
  paidBy: PaidRow[];
  onPaidByChange: (rows: PaidRow[]) => void;
  showBuckets: boolean;
}) {
  const { t } = useTranslation();
  const computed = computeShares(draft, members, total);
  const amounts = new Map(computed.shares.map((share) => [share.person, share.amount]));
  const set = (patch: Partial<SplitDraft>) => onDraftChange({ ...draft, ...patch });

  const paidTotal = paidBy.reduce((sum, row) => sum + cents(row.amount), 0);
  const paidOff = paidTotal - cents(total);

  return (
    <div className="mt-3 space-y-4 rounded-lg border border-line p-3">
      <section>
        <div className="mb-2 flex flex-wrap items-center gap-1" role="tablist">
          <span className="me-1 text-xs font-medium text-ink-muted">{t("split.title")}</span>
          {SPLIT_MODES.map((mode) => (
            <button
              key={mode}
              type="button"
              role="tab"
              aria-selected={draft.mode === mode}
              onClick={() => set({ mode })}
              className={`min-h-9 rounded-lg px-3 text-xs transition ${
                draft.mode === mode
                  ? "bg-brand-soft font-medium text-brand"
                  : "text-ink-muted hover:bg-surface hover:text-ink"
              }`}
            >
              {t(`split.modes.${mode}`)}
            </button>
          ))}
        </div>
        <p className="mb-2 text-xs text-ink-muted">{t(`split.modeHint.${draft.mode}`)}</p>

        <div className="space-y-1.5">
          {members.map((member) => (
            <div key={member.person} className="flex items-center gap-2">
              {draft.mode === "equal" ? (
                <label className="flex min-h-9 min-w-0 flex-1 cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 accent-[var(--color-brand)]"
                    checked={draft.included[member.person] !== false}
                    onChange={(event) =>
                      set({ included: { ...draft.included, [member.person]: event.target.checked } })
                    }
                  />
                  <MemberDot person={member.person} members={members} />
                  <span className="truncate">{member.name}</span>
                </label>
              ) : (
                <>
                  <span className="flex min-h-9 min-w-0 flex-1 items-center gap-2 text-sm">
                    <MemberDot person={member.person} members={members} />
                    <span className="truncate">{member.name}</span>
                  </span>
                  <ModeInput member={member} draft={draft} onChange={set} />
                </>
              )}
              {/* The derived figure, always visible, so a percentage or a weight reads as
                  money before anything is saved. */}
              <span className="numeric w-24 shrink-0 text-end text-sm">
                {amounts.has(member.person) ? (
                  <Money amount={amounts.get(member.person) ?? "0.00"} currency={currency} colour={false} />
                ) : (
                  <span className="text-ink-muted">—</span>
                )}
              </span>
            </div>
          ))}
        </div>

        <Problem computed={computed} currency={currency} />

        {showBuckets && (
          <div className="mt-3">
            <Field label={t("split.bucketForAll")}>
              <Select value={draft.bucket} onChange={(event) => set({ bucket: event.target.value })}>
                <option value="">—</option>
                {buckets.map((bucket) => (
                  <option key={bucket.id} value={bucket.id}>
                    {bucket.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-center gap-2">
          <span className="text-xs font-medium text-ink-muted">{t("split.paidSection")}</span>
          <button
            type="button"
            className="text-xs text-brand hover:underline"
            onClick={() =>
              onPaidByChange(
                paidBy.length > 1
                  ? [{ person: paidBy[0]?.person ?? members[0]?.person ?? "", amount: total }]
                  : [
                      ...paidBy,
                      { person: members.find((m) => m.person !== paidBy[0]?.person)?.person ?? "", amount: "" },
                    ],
              )
            }
          >
            {paidBy.length > 1 ? t("split.onePayer") : t("split.severalPayers")}
          </button>
        </div>

        {paidBy.length <= 1 ? (
          <Select
            value={paidBy[0]?.person ?? ""}
            onChange={(event) => onPaidByChange([{ person: event.target.value, amount: total }])}
          >
            {members.map((member) => (
              <option key={member.person} value={member.person}>
                {member.name}
              </option>
            ))}
          </Select>
        ) : (
          <div className="space-y-1.5">
            {paidBy.map((row, index) => (
              <div key={index} className="flex items-center gap-2">
                <Select
                  value={row.person}
                  onChange={(event) =>
                    onPaidByChange(paidBy.map((r, i) => (i === index ? { ...r, person: event.target.value } : r)))
                  }
                >
                  {members.map((member) => (
                    <option key={member.person} value={member.person}>
                      {member.name}
                    </option>
                  ))}
                </Select>
                <Input
                  fullWidth={false}
                  className="numeric ltr-field w-28 text-end"
                  inputMode="decimal"
                  placeholder="0.00"
                  aria-label={t("entries.amount")}
                  value={row.amount}
                  onChange={(event) =>
                    onPaidByChange(paidBy.map((r, i) => (i === index ? { ...r, amount: event.target.value } : r)))
                  }
                />
                <button
                  type="button"
                  aria-label={t("entries.delete")}
                  className="flex size-9 shrink-0 items-center justify-center rounded-lg text-ink-muted hover:bg-negative/10 hover:text-negative"
                  onClick={() => onPaidByChange(paidBy.filter((_, i) => i !== index))}
                >
                  ×
                </button>
              </div>
            ))}
            <button
              type="button"
              className="text-xs text-brand hover:underline"
              onClick={() => onPaidByChange([...paidBy, { person: members[0]?.person ?? "", amount: "" }])}
            >
              + {t("entries.addPayer")}
            </button>
            {paidOff !== 0 && (
              <p className="text-xs text-negative">
                {paidOff < 0 ? t("split.remaining") : t("split.over")}{" "}
                <Money amount={fromCents(Math.abs(paidOff))} currency={currency} colour={false} />
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function ModeInput({
  member,
  draft,
  onChange,
}: {
  member: Member;
  draft: SplitDraft;
  onChange: (patch: Partial<SplitDraft>) => void;
}) {
  const { t } = useTranslation();
  const field = (
    key: "percent" | "weights" | "exact" | "adjust",
    placeholder: string,
    suffix?: string,
  ) => (
    <span className="flex items-center gap-1">
      <Input
        fullWidth={false}
        className="numeric ltr-field w-20 text-end"
        inputMode="decimal"
        placeholder={placeholder}
        aria-label={`${member.name} ${t(`split.modes.${draft.mode}`)}`}
        value={draft[key][member.person] ?? ""}
        onChange={(event) => onChange({ [key]: { ...draft[key], [member.person]: event.target.value } })}
      />
      {suffix && <span className="w-3 text-xs text-ink-muted">{suffix}</span>}
    </span>
  );

  switch (draft.mode) {
    case "percent":
      return field("percent", "0", "%");
    case "shares":
      return field("weights", "1");
    case "exact":
      return field("exact", "0.00");
    case "adjust":
      return field("adjust", "+0.00");
    default:
      return null;
  }
}

/** The one line that says why the split is not usable yet, in the unit the mode thinks in. */
function Problem({ computed, currency }: { computed: Computed; currency: string }) {
  const { t } = useTranslation();
  if (computed.problem === null) return null;

  let text: React.ReactNode;
  if (computed.problem === "percent") {
    text = t("split.percentTotal", { total: 100 + computed.off });
  } else if (computed.problem === "nobody") {
    text = t("split.modeHint.equal");
  } else {
    text = (
      <>
        {computed.off < 0 ? t("split.remaining") : t("split.over")}{" "}
        <Money amount={fromCents(Math.abs(computed.off))} currency={currency} colour={false} />
      </>
    );
  }
  return (
    <p role="alert" className="mt-2 text-xs text-negative">
      {text}
    </p>
  );
}
