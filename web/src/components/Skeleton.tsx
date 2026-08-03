/**
 * Placeholders shaped like the thing that is coming.
 *
 * The whole app used to collapse to the word "Loading…" while any query was in flight. That
 * reads as slower than it is: the screen is destroyed and rebuilt, so every wait looks like a
 * navigation even when the data arrives in 80ms. A block that already has the right number of
 * rows in the right places reads as the same screen, filling in.
 *
 * Deliberately not animated with a sweeping shimmer. A shimmer is another moving thing to
 * look at, and this screen already animates the ready-to-assign figure on arrival; a quiet
 * pulse says "not yet" without competing with it. It respects reduced-motion via the
 * `animate-pulse` utility, which Tailwind already gates.
 */

/** One grey block. `w`/`h` are Tailwind classes so callers control the shape. */
export function Bar({ className = "" }: { className?: string }) {
  return <span className={`block rounded bg-line ${className}`} />;
}

/** Rows of a ledger: a name, a couple of figures, and a bar underneath. */
export function LedgerSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="animate-pulse rounded-card border border-line bg-card" aria-hidden>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="border-b border-line p-3 last:border-b-0 sm:px-4">
          <div className="flex items-center gap-3">
            <Bar className="h-3.5 w-32" />
            <span className="flex-1" />
            <Bar className="h-3.5 w-20" />
            <Bar className="h-9 w-24" />
          </div>
          <Bar className="mt-2.5 h-1" />
        </div>
      ))}
    </div>
  );
}

/** A plain list: one line per row, no figures. */
export function ListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="animate-pulse rounded-card border border-line bg-card" aria-hidden>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex items-center gap-3 border-b border-line p-3 last:border-b-0 sm:px-4">
          <Bar className="h-4 w-4 shrink-0 rounded-full" />
          <span className="min-w-0 flex-1">
            <Bar className="h-3.5 w-48 max-w-full" />
            <Bar className="mt-1.5 h-2.5 w-28" />
          </span>
          <Bar className="h-3.5 w-16 shrink-0" />
        </div>
      ))}
    </div>
  );
}

/** The four figures above the month ledger. */
export function SummarySkeleton() {
  return (
    <div
      className="grid animate-pulse grid-cols-2 rounded-card border border-line bg-card sm:grid-cols-4"
      aria-hidden
    >
      {Array.from({ length: 4 }, (_, index) => (
        <div key={index} className="border-b border-line p-3 last:border-b-0 sm:border-b-0 sm:px-4">
          <Bar className="h-2.5 w-20" />
          <Bar className="mt-2 h-5 w-28" />
        </div>
      ))}
    </div>
  );
}
