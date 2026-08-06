import { useTranslation } from "react-i18next";

import type { FunderState, Member } from "@/api/types.gen";
import { Money } from "@/components/Money";
import { colourFor, nameFor } from "@/lib/members";

/**
 * One bar, one meaning: how funded this envelope is, and by whom.
 *
 * The previous design drew a thin line per funder showing how much of *their own*
 * contribution *they* had consumed. Three failures at once: it answered a question nobody
 * asks, every line had a different denominator so equal lengths meant different amounts, and
 * with real data — where spending is often attributed to one person — most lines rendered
 * empty and the whole thing read as broken.
 *
 * Now the track is the target, the segments are what each person has put in this month, and
 * the empty remainder is the gap. No target: the segments fill the track, showing the
 * funding mix. That is the question an envelope app answers with a bar — "did we fill it" —
 * plus the one this app adds: "who filled it".
 *
 * What the bar deliberately no longer carries is spending state. Overspend lives in the
 * available figure, the row's severity edge, and the per-person breakdown below — where "Noa
 * is 10.58 in the red" is a number with a name on it, not an unlabelled hatched sliver.
 */
export function FundingBar({
  funders,
  members,
  target,
}: {
  funders: FunderState[];
  members: Member[];
  target: number | null;
}) {
  const { t } = useTranslation();
  const contributions = funders
    .map((funder) => ({ funder, amount: Number(funder.assigned) }))
    .filter(({ amount }) => amount > 0);
  const funded = contributions.reduce((sum, { amount }) => sum + amount, 0);

  // Overfunding rescales the whole bar rather than clipping whoever funded last: the
  // segments stay proportional to each other, and the numbers carry the "over" part.
  const track = target !== null ? Math.max(target, funded) : funded;

  if (track <= 0) {
    return <div className="h-1.5 rounded-full bg-line" aria-hidden />;
  }

  return (
    <div
      className="flex h-1.5 overflow-hidden rounded-full bg-line"
      role="img"
      aria-label={
        target !== null
          ? t("month.barLabel", { funded: funded.toFixed(2), target: target.toFixed(2) })
          : t("month.barLabelNoTarget", { funded: funded.toFixed(2) })
      }
    >
      {contributions.map(({ funder, amount }) => (
        <div
          key={funder.person}
          data-person={funder.person}
          title={`${nameFor(funder.person, members)} · ${amount.toFixed(2)}`}
          style={{
            width: `${(amount / track) * 100}%`,
            background: colourFor(funder.person, members),
          }}
        />
      ))}
    </div>
  );
}

/**
 * Each funder's standing, as numbers with names.
 *
 * This is where "a bucket can be in the red for one person and in the black for another"
 * actually shows. It was previously encoded as bar geometry, which nobody could read; here
 * it is a row per person: what they put in this month, what they bore, and where that
 * leaves them — red when negative, with their share of the split alongside so the *why* is
 * on the same line.
 */
export function FunderBreakdown({
  funders,
  members,
  currency,
}: {
  funders: FunderState[];
  members: Member[];
  currency: string;
}) {
  const { t } = useTranslation();
  const involved = funders.filter(
    (funder) =>
      Number(funder.split) > 0 || Number(funder.assigned) !== 0 || Number(funder.available) !== 0,
  );
  if (involved.length === 0) return null;

  return (
    <div className="sheet-in mt-2 overflow-x-auto rounded-lg border border-line bg-surface/60">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-ink-muted">
            <th className="p-2 text-start font-normal">{t("month.funder")}</th>
            <th className="p-2 text-end font-normal">{t("month.share")}</th>
            <th className="p-2 text-end font-normal">{t("month.putIn")}</th>
            <th className="p-2 text-end font-normal">{t("month.bore")}</th>
            <th className="p-2 text-end font-normal">{t("month.left")}</th>
          </tr>
        </thead>
        <tbody>
          {involved.map((funder) => (
            <tr key={funder.person} className="border-t border-line">
              <td className="flex items-center gap-1.5 p-2">
                <MemberDot person={funder.person} members={members} />
                <span className="truncate">{nameFor(funder.person, members)}</span>
              </td>
              <td className="numeric p-2 text-end text-ink-muted">
                {Math.round(Number(funder.split) * 100)}%
              </td>
              <td className="numeric p-2 text-end">
                <Money amount={funder.assigned} currency={currency} colour={false} />
              </td>
              <td className="numeric p-2 text-end">
                <Money
                  amount={Math.abs(Number(funder.activity)).toFixed(2)}
                  currency={currency}
                  colour={false}
                />
              </td>
              <td className="numeric p-2 text-end font-medium">
                <Money amount={funder.available} currency={currency} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A dot in someone's colour, for naming them beside a figure. */
export function MemberDot({ person, members }: { person: string; members: Member[] }) {
  return (
    <span
      aria-hidden
      className="inline-block size-2 shrink-0 rounded-full"
      style={{ background: colourFor(person, members) }}
    />
  );
}
