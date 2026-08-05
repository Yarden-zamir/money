import type { Member } from "@/api/types.gen";

/**
 * A colour per person, used for every bar, segment and pill that names them.
 *
 * Assigned by **position in the member list**, not by hashing the person id. A hash is
 * tempting because it needs no ordering, but two people in a four-person budget would collide
 * often enough to matter, and two members sharing a colour makes a stacked bar unreadable.
 * Position gives no collisions at all up to the size of the palette.
 *
 * The cost is that removing a member re-colours everyone after them. That is rare, and it is
 * a moment where the colours are being re-learned anyway.
 */
export const MEMBER_COLOURS = 8;

export function colourFor(person: string, members: Member[]): string {
  const index = members.findIndex((member) => member.person === person);
  // Unknown people — a share naming someone since removed — get the muted ink colour rather
  // than colour 1, so they never masquerade as the first member.
  if (index < 0) return "var(--color-ink-muted)";
  return `var(--color-member-${(index % MEMBER_COLOURS) + 1})`;
}

export function nameFor(person: string, members: Member[]): string {
  return members.find((member) => member.person === person)?.name ?? person;
}

/**
 * The effective split for a bucket: what is set, or an even split among members.
 *
 * Mirrors `Bucket.split_for` on the server. An unset split is resolved against the *current*
 * members rather than stored, so adding somebody to the budget does not leave every
 * unconfigured bucket quietly attributing their spending to everyone else.
 */
export function splitFor(
  split: Record<string, string> | null | undefined,
  members: Member[],
): Record<string, number> {
  const entries = Object.entries(split ?? {});
  if (entries.length > 0) {
    return Object.fromEntries(entries.map(([person, share]) => [person, Number(share)]));
  }
  if (members.length === 0) return {};
  const even = 1 / members.length;
  return Object.fromEntries(members.map((member) => [member.person, even]));
}
