import type { FunderState, Member } from "@/api/types.gen";
import { bucketBar } from "@/lib/bucket";
import { colourFor, nameFor } from "@/lib/members";

/**
 * How full a shared envelope is, per person who funds it.
 *
 * Two shapes for two questions, which is why it toggles rather than picking one:
 *
 * - **Separate** — one bar per funder, each measured against *their own* contribution. Answers
 *   "is each of us within our own share", and is the only shape where somebody being over
 *   while everybody else is under is visible at a glance.
 * - **Stacked** — one bar, segments sized by what each person has spent against the household
 *   total. Answers "how much of this envelope is gone, and who spent it".
 *
 * Colour names the person, so it can no longer name the state — the figure beside the bar and
 * the row's severity edge carry that. A funder in the red gets a hatched overlay instead,
 * which reads without relying on hue at all.
 */
export function FunderBars({
  funders,
  members,
  stacked,
}: {
  funders: FunderState[];
  members: Member[];
  stacked: boolean;
}) {
  // Somebody with no split and nothing funded is not part of this envelope and would
  // otherwise contribute an empty row to every bucket they are not in.
  const involved = funders.filter(
    (funder) =>
      Number(funder.split) > 0 || Number(funder.assigned) !== 0 || Number(funder.available) !== 0,
  );
  if (involved.length === 0) return <div className="h-1 rounded-full bg-line" />;

  if (stacked) return <Stacked funders={involved} members={members} />;

  return (
    <div className="flex flex-col gap-0.5">
      {involved.map((funder) => (
        <Single key={funder.person} funder={funder} members={members} />
      ))}
    </div>
  );
}

function Single({ funder, members }: { funder: FunderState; members: Member[] }) {
  const { percent } = bucketBar(Number(funder.available), Number(funder.activity));
  const overspent = Number(funder.available) < 0;

  return (
    <div
      className="h-1 overflow-hidden rounded-full bg-line"
      title={`${nameFor(funder.person, members)} · ${funder.available}`}
    >
      <div
        className={`h-full ${overspent ? "bar-overspent" : ""}`}
        style={{ width: `${percent}%`, background: colourFor(funder.person, members) }}
      />
    </div>
  );
}

function Stacked({ funders, members }: { funders: FunderState[]; members: Member[] }) {
  const spent = funders.map((funder) => Math.abs(Number(funder.activity)));
  const held = funders.reduce(
    (total, funder, index) => total + Number(funder.available) + spent[index]!,
    0,
  );

  // Nothing was ever in it, so any spending is entirely overspend and fills the bar — the
  // alternative is segments of zero width nobody can see.
  const total = held > 0 ? held : spent.reduce((sum, value) => sum + value, 0);

  return (
    <div className="flex h-1 overflow-hidden rounded-full bg-line">
      {funders.map((funder, index) => {
        const share = total > 0 ? (spent[index]! / total) * 100 : 0;
        if (share <= 0) return null;
        return (
          <div
            key={funder.person}
            title={`${nameFor(funder.person, members)} · ${funder.activity}`}
            className={Number(funder.available) < 0 ? "bar-overspent" : ""}
            style={{ width: `${share}%`, background: colourFor(funder.person, members) }}
          />
        );
      })}
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
