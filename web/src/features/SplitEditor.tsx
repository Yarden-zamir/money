import { useTranslation } from "react-i18next";

import type { BucketOutput, Member } from "@/api/types.gen";
import { MemberDot } from "@/components/FunderBars";
import { Field, Input, Select } from "@/components/Form";
import { Money } from "@/components/Money";

/**
 * Who bears an entry — edited as a *decision*, not as a list of numbers, and always on the
 * form rather than behind a button.
 *
 * The first version hid the split and let the bucket's default apply silently, which is how
 * a meal eaten alone came out split in half. Now the panel is always there, pre-filled from
 * the bucket, so the default is visible and one press away from being wrong-proofed: *Just
 * me* for the meal alone, *By item* for the receipt where one line was one person's.
 *
 * The same modes, minus the money-shaped ones, edit a bucket's default split — see
 * `RatioEditor`. Arithmetic is in whole agorot or basis points, never floating point.
 */

export type SplitMode = "me" | "equal" | "percent" | "shares" | "exact" | "adjust" | "items";

/** Modes that make sense for a ratio with no amount attached. */
export const RATIO_MODES: SplitMode[] = ["me", "equal", "percent", "shares"];
const AMOUNT_MODES: SplitMode[] = ["exact", "adjust"];

export type SplitDraft = {
  mode: SplitMode;
  /** Equal mode: who is in. Everyone, by default. */
  included: Record<string, boolean>;
  percent: Record<string, string>;
  weights: Record<string, string>;
  exact: Record<string, string>;
  /** Adjust mode: a fixed extra for a person, on top of an equal share of the rest. */
  adjust: Record<string, string>;
  /** By item: for each receipt line (by index), who shares it equally. */
  lines: Record<number, Record<string, boolean>>;
  /** One bucket for every share. Per-line buckets are what receipt lines are for. */
  bucket: string;
};

export type ShareRow = { person: string; amount: string; bucket: string };
export type PaidRow = { person: string; amount: string };
export type Line = { label: string; amount: string };

export function emptyDraft(members: Member[], bucket: string): SplitDraft {
  return {
    mode: "equal",
    included: Object.fromEntries(members.map((member) => [member.person, true])),
    percent: {},
    weights: Object.fromEntries(members.map((member) => [member.person, "1"])),
    exact: {},
    adjust: {},
    lines: {},
    bucket,
  };
}

/**
 * A draft that expresses a bucket's stored split, so the panel opens showing the default
 * rather than a blank. An even split is *equal, everyone*; anything else is *percent*.
 */
export function draftFromRatio(
  ratio: Record<string, number>,
  members: Member[],
  bucket: string,
): SplitDraft {
  const base = emptyDraft(members, bucket);
  const values = members.map((member) => ratio[member.person] ?? 0);
  const present = values.filter((value) => value > 0);
  const even = present.length > 0 && present.every((value) => Math.abs(value - present[0]!) < 0.0005);
  if (even) {
    return {
      ...base,
      mode: "equal",
      included: Object.fromEntries(members.map((m) => [m.person, (ratio[m.person] ?? 0) > 0])),
    };
  }
  return {
    ...base,
    mode: "percent",
    percent: Object.fromEntries(
      members.map((m) => [m.person, String(Math.round((ratio[m.person] ?? 0) * 10000) / 100)]),
    ),
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
 * Distribute `total` across weights so the parts sum exactly to the total.
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

export type Problem = "percent" | "exact" | "nobody" | "adjust" | "items" | "line" | null;

/** The weights a ratio-shaped mode describes, or null when it describes nobody. */
function weightsFor(draft: SplitDraft, people: string[], me: string): Record<string, number> | null {
  switch (draft.mode) {
    case "me":
      return me ? { [me]: 1 } : null;
    case "equal": {
      const included = people.filter((person) => draft.included[person] !== false);
      return included.length ? Object.fromEntries(included.map((p) => [p, 1])) : null;
    }
    case "percent": {
      const percents = Object.fromEntries(
        people.map((person) => [person, Math.max(0, Number(draft.percent[person]) || 0)]),
      );
      return Object.values(percents).some((value) => value > 0) ? percents : null;
    }
    case "shares": {
      const weights = Object.fromEntries(
        people.map((person) => [person, Math.max(0, Number(draft.weights[person]) || 0)]),
      );
      return Object.values(weights).some((value) => value > 0) ? weights : null;
    }
    default:
      return null;
  }
}

/** Percent mode has one extra constraint the others lack: the numbers must be a hundred. */
function percentOff(draft: SplitDraft, people: string[]): number {
  const sum = people.reduce((total, p) => total + Math.max(0, Number(draft.percent[p]) || 0), 0);
  return Math.round((sum - 100) * 100) / 100;
}

export type Computed = {
  shares: ShareRow[];
  /** By-item mode: the shares of each line, in line order, for the request body. */
  lineShares: ShareRow[][];
  problem: Problem;
  /** How far off the constraint is: agorot, or percent points for percent mode. */
  off: number;
};

/** The shares a draft describes for a signed `total`, or the reason it describes none. */
export function computeShares(
  draft: SplitDraft,
  members: Member[],
  total: string,
  me: string,
  lines: Line[] = [],
): Computed {
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
  const none = (problem: Problem, off = 0): Computed => ({ shares: [], lineShares: [], problem, off });

  switch (draft.mode) {
    case "me":
    case "equal":
    case "shares": {
      const weights = weightsFor(draft, people, me);
      if (!weights) return none("nobody");
      return { shares: toRows(allocate(magnitude, weights)), lineShares: [], problem: null, off: 0 };
    }
    case "percent": {
      const off = percentOff(draft, people);
      if (Math.abs(off) > 0.001) return none("percent", off);
      const weights = weightsFor(draft, people, me);
      if (!weights) return none("nobody");
      return { shares: toRows(allocate(magnitude, weights)), lineShares: [], problem: null, off: 0 };
    }
    case "exact": {
      const parts = Object.fromEntries(
        people.map((person) => [person, Math.abs(cents(draft.exact[person]))]),
      );
      const sum = Object.values(parts).reduce((a, b) => a + b, 0);
      if (sum !== magnitude) return none("exact", sum - magnitude);
      return { shares: toRows(parts), lineShares: [], problem: null, off: 0 };
    }
    case "adjust": {
      const extras = Object.fromEntries(
        people.map((person) => [person, Math.abs(cents(draft.adjust[person]))]),
      );
      const extraTotal = Object.values(extras).reduce((a, b) => a + b, 0);
      if (extraTotal > magnitude) return none("adjust", extraTotal - magnitude);
      const rest = allocate(magnitude - extraTotal, Object.fromEntries(people.map((p) => [p, 1])));
      const parts = Object.fromEntries(
        people.map((person) => [person, (rest[person] ?? 0) + (extras[person] ?? 0)]),
      );
      return { shares: toRows(parts), lineShares: [], problem: null, off: 0 };
    }
    case "items": {
      // Every line is shared equally by whoever is ticked on it; the entry's shares are the
      // per-person sums. Lines must add up to the entry first, or nothing here is true.
      const lineTotal = lines.reduce((sum, line) => sum + Math.abs(cents(line.amount)), 0);
      if (lines.length === 0 || lineTotal !== magnitude) return none("items", lineTotal - magnitude);
      const totals: Record<string, number> = {};
      const lineShares: ShareRow[][] = [];
      for (const [index, line] of lines.entries()) {
        const who = people.filter((p) => (draft.lines[index] ?? {})[p] !== false);
        if (who.length === 0) return none("line", index);
        const parts = allocate(Math.abs(cents(line.amount)), Object.fromEntries(who.map((p) => [p, 1])));
        lineShares.push(toRows(parts));
        for (const [person, part] of Object.entries(parts)) {
          totals[person] = (totals[person] ?? 0) + part;
        }
      }
      return { shares: toRows(totals), lineShares, problem: null, off: 0 };
    }
  }
}

/**
 * A bucket's default split as fractions summing to exactly 1, from a ratio-shaped draft.
 * Basis points, so four decimals and an exact sum — the server refuses a split off by more.
 */
export function computeRatio(
  draft: SplitDraft,
  members: Member[],
  me: string,
): { ratio: Record<string, number>; problem: Problem; off: number } {
  const people = members.map((member) => member.person);
  if (draft.mode === "percent") {
    const off = percentOff(draft, people);
    if (Math.abs(off) > 0.001) return { ratio: {}, problem: "percent", off };
  }
  const weights = weightsFor(draft, people, me);
  if (!weights) return { ratio: {}, problem: "nobody", off: 0 };
  const points = allocate(10000, weights);
  return {
    ratio: Object.fromEntries(
      Object.entries(points)
        .filter(([, value]) => value > 0)
        .map(([person, value]) => [person, value / 10000]),
    ),
    problem: null,
    off: 0,
  };
}

function ModeTabs({
  modes,
  mode,
  onMode,
}: {
  modes: SplitMode[];
  mode: SplitMode;
  onMode: (mode: SplitMode) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="mb-2 flex flex-wrap items-center gap-1" role="tablist">
      {modes.map((candidate) => (
        <button
          key={candidate}
          type="button"
          role="tab"
          aria-selected={mode === candidate}
          onClick={() => onMode(candidate)}
          className={`min-h-9 rounded-lg px-3 text-xs transition ${
            mode === candidate
              ? "bg-brand-soft font-medium text-brand"
              : "text-ink-muted hover:bg-surface hover:text-ink"
          }`}
        >
          {t(`split.modes.${candidate}`)}
        </button>
      ))}
    </div>
  );
}

/** One row per member: name, the mode's input, and the derived figure on the end. */
function PersonRows({
  members,
  draft,
  onChange,
  me,
  figure,
}: {
  members: Member[];
  draft: SplitDraft;
  onChange: (patch: Partial<SplitDraft>) => void;
  me: string;
  /** What to show at the end of the row for a person, if anything. */
  figure: (person: string) => React.ReactNode;
}) {
  const { t } = useTranslation();
  const visible = draft.mode === "me" ? members.filter((m) => m.person === me) : members;

  return (
    <div className="space-y-1.5">
      {visible.map((member) => (
        <div key={member.person} className="flex items-center gap-2">
          {draft.mode === "equal" ? (
            <label className="flex min-h-9 min-w-0 flex-1 cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 accent-[var(--color-brand)]"
                checked={draft.included[member.person] !== false}
                onChange={(event) =>
                  onChange({ included: { ...draft.included, [member.person]: event.target.checked } })
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
                {draft.mode === "me" && (
                  <span className="text-xs text-ink-muted">{t("split.bearsAll")}</span>
                )}
              </span>
              <ModeInput member={member} draft={draft} onChange={onChange} />
            </>
          )}
          <span className="numeric w-24 shrink-0 text-end text-sm">{figure(member.person)}</span>
        </div>
      ))}
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
  const field = (key: "percent" | "weights" | "exact" | "adjust", placeholder: string, suffix?: string) => (
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
function ProblemLine({
  problem,
  off,
  currency,
}: {
  problem: Problem;
  off: number;
  currency?: string;
}) {
  const { t } = useTranslation();
  if (problem === null) return null;

  let text: React.ReactNode;
  if (problem === "percent") text = t("split.percentTotal", { total: 100 + off });
  else if (problem === "nobody") text = t("split.modeHint.equal");
  else if (problem === "items") text = t("split.itemsMustSum");
  else if (problem === "line") text = t("split.lineNeedsSomeone", { line: off + 1 });
  else
    text = (
      <>
        {off < 0 ? t("split.remaining") : t("split.over")}{" "}
        <Money amount={fromCents(Math.abs(off))} currency={currency ?? "ILS"} colour={false} />
      </>
    );
  return (
    <p role="alert" className="mt-2 text-xs text-negative">
      {text}
    </p>
  );
}

export function SplitEditor({
  members,
  buckets,
  total,
  currency,
  me,
  lines,
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
  /** The acting person: who "Just me" means. */
  me: string;
  /** Receipt lines, which unlock *By item*. */
  lines: Line[];
  draft: SplitDraft;
  onDraftChange: (draft: SplitDraft) => void;
  paidBy: PaidRow[];
  onPaidByChange: (rows: PaidRow[]) => void;
  showBuckets: boolean;
}) {
  const { t } = useTranslation();
  const computed = computeShares(draft, members, total, me, lines);
  const amounts = new Map(computed.shares.map((share) => [share.person, share.amount]));
  const set = (patch: Partial<SplitDraft>) => onDraftChange({ ...draft, ...patch });
  const modes = [...RATIO_MODES, ...AMOUNT_MODES, ...(lines.length ? (["items"] as SplitMode[]) : [])];

  const paidTotal = paidBy.reduce((sum, row) => sum + cents(row.amount), 0);
  const paidOff = paidTotal - cents(total);

  return (
    <div className="mt-3 space-y-4 rounded-lg border border-line p-3">
      <section>
        <div className="mb-1 text-xs font-medium text-ink-muted">{t("split.title")}</div>
        <ModeTabs modes={modes} mode={draft.mode} onMode={(mode) => set({ mode })} />
        <p className="mb-2 text-xs text-ink-muted">{t(`split.modeHint.${draft.mode}`)}</p>

        {draft.mode === "items" ? (
          <ItemRows members={members} lines={lines} draft={draft} onChange={set} currency={currency} computed={computed} />
        ) : (
          <PersonRows
            members={members}
            draft={draft}
            onChange={set}
            me={me}
            figure={(person) =>
              amounts.has(person) ? (
                <Money amount={amounts.get(person) ?? "0.00"} currency={currency} colour={false} />
              ) : (
                <span className="text-ink-muted">—</span>
              )
            }
          />
        )}

        <ProblemLine problem={computed.problem} off={computed.off} currency={currency} />

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
                  ? [{ person: paidBy[0]?.person ?? me, amount: total }]
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
            value={paidBy[0]?.person ?? me}
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

/** By item: one row per receipt line, a tick per person, the line's amount on the end. */
function ItemRows({
  members,
  lines,
  draft,
  onChange,
  currency,
  computed,
}: {
  members: Member[];
  lines: Line[];
  draft: SplitDraft;
  onChange: (patch: Partial<SplitDraft>) => void;
  currency: string;
  computed: Computed;
}) {
  const { t } = useTranslation();
  const amounts = new Map(computed.shares.map((share) => [share.person, share.amount]));

  return (
    <div className="space-y-2">
      {lines.map((line, index) => (
        <div key={index} className="rounded-lg bg-sunken p-2">
          <div className="mb-1 flex items-center gap-2 text-sm">
            <span className="min-w-0 flex-1 truncate">{line.label || t("entries.lineLabel")}</span>
            <Money amount={line.amount || "0.00"} currency={currency} colour={false} className="text-xs" />
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {members.map((member) => (
              <label key={member.person} className="flex min-h-8 cursor-pointer items-center gap-1.5 text-xs">
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--color-brand)]"
                  checked={(draft.lines[index] ?? {})[member.person] !== false}
                  onChange={(event) =>
                    onChange({
                      lines: {
                        ...draft.lines,
                        [index]: { ...(draft.lines[index] ?? {}), [member.person]: event.target.checked },
                      },
                    })
                  }
                />
                <MemberDot person={member.person} members={members} />
                {member.name}
              </label>
            ))}
          </div>
        </div>
      ))}
      {/* The per-person totals the lines add up to — what will actually be recorded. */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-1 text-xs text-ink-muted">
        {members.map((member) => (
          <span key={member.person} className="flex items-center gap-1">
            <MemberDot person={member.person} members={members} />
            {member.name}{" "}
            {amounts.has(member.person) ? (
              <Money amount={amounts.get(member.person) ?? "0.00"} currency={currency} colour={false} />
            ) : (
              "—"
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * A bucket's default split: the same panel with the ratio modes only, no amounts. The
 * figure at the end of each row is the percentage the mode works out to.
 */
export function RatioEditor({
  members,
  me,
  draft,
  onDraftChange,
}: {
  members: Member[];
  me: string;
  draft: SplitDraft;
  onDraftChange: (draft: SplitDraft) => void;
}) {
  const { t } = useTranslation();
  const result = computeRatio(draft, members, me);
  const set = (patch: Partial<SplitDraft>) => onDraftChange({ ...draft, ...patch });

  return (
    <div>
      <ModeTabs modes={RATIO_MODES} mode={draft.mode} onMode={(mode) => set({ mode })} />
      <p className="mb-2 text-xs text-ink-muted">{t(`split.modeHint.${draft.mode}`)}</p>
      <PersonRows
        members={members}
        draft={draft}
        onChange={set}
        me={me}
        figure={(person) =>
          result.ratio[person] !== undefined ? (
            <span>{Math.round(result.ratio[person]! * 1000) / 10}%</span>
          ) : (
            <span className="text-ink-muted">—</span>
          )
        }
      />
      <ProblemLine problem={result.problem} off={result.off} />
    </div>
  );
}
