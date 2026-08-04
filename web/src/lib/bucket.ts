/**
 * How full a bucket's bar is, and what colour.
 *
 * The bar's length is the proportion of the envelope that has been spent. The only honest
 * denominator for that is what the envelope actually *held*, which is `available + spent` —
 * available is what is left after the spending, so adding the spending back gives the total.
 *
 * It used to divide by `target ?? assigned`, and both are wrong:
 *
 * - `assigned` is only *this month's* assignment, while `available` carries over. An envelope
 *   funded last month and spent from this month showed an empty bar, because nothing was
 *   assigned in the current month — the denominator was zero.
 * - `target` is what you meant to put in, not what is there. A bucket with a 1000 target
 *   holding 3000 and 2000 spent showed a full bar with 1000 still available.
 *
 * Both failures share a shape: an overspent envelope with nothing assigned this month got a
 * red bar of zero width, so the one state that needs acting on was invisible.
 */
export type BucketBar = {
  /** 0–100. Clamped, so a 300% overspend looks the same as a 101% one. */
  percent: number;
  tone: "overspent" | "emptied" | "low" | "healthy";
};

export function bucketBar(available: number, activity: number): BucketBar {
  const spent = Math.abs(activity);
  const held = available + spent;

  // Nothing was ever in it. Spending from an empty envelope is entirely overspend, so it
  // fills — the alternative is a red bar nobody can see.
  const percent =
    held > 0 ? Math.min(100, Math.round((spent / held) * 100)) : spent > 0 ? 100 : 0;

  // Four states: overspent, emptied exactly on plan (a paid bill — neither good nor bad),
  // running low, and healthy. "Low" is measured against what the envelope held, so a small
  // envelope is not permanently amber just for being small.
  const tone =
    available < 0
      ? "overspent"
      : available === 0
        ? "emptied"
        : held > 0 && available < held * 0.1
          ? "low"
          : "healthy";

  return { percent, tone };
}

export const BAR_TONES: Record<BucketBar["tone"], string> = {
  overspent: "bg-negative",
  emptied: "bg-ink-muted/40",
  low: "bg-warning",
  healthy: "bg-positive",
};
