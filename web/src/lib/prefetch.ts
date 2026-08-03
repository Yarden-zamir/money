import type { QueryClient } from "@tanstack/react-query";

import {
  getBalancesOptions,
  getHistoryOptions,
  getMonthCloseOptions,
  getMonthOptions,
  listBucketsOptions,
  listEntriesOptions,
  listRulesOptions,
  listScheduledOptions,
} from "@/api/@tanstack/react-query.gen";
import { currentMonth } from "@/lib/format";

/**
 * What each tab is about to need, fetched while the pointer is still on its way there.
 *
 * A tab change costs a round trip to git-backed data. The gap between deciding to click and
 * clicking is dead time that already exists, and it is usually longer than the request —
 * spending it on the fetch means the screen is often complete before it is asked for.
 *
 * Triggered on hover *and* on pointer-down, which is what covers touch: there is no hover on
 * a phone, but a finger rests on a tab for a few tens of milliseconds before the click fires,
 * and pointer-down happens at the start of that.
 *
 * Nothing here is a mutation, so a prefetch that turns out to be unwanted costs one cached
 * GET. `prefetchQuery` is a no-op while the data is still fresh, so running along a row of
 * tabs does not produce a request per tab.
 *
 * Each case calls `prefetchQuery` itself rather than returning options to a shared loop:
 * every query has a different result type, and collecting them into one array only type
 * checks by erasing exactly the types that make the call safe.
 */
export function prefetchRoute(client: QueryClient, path: string, budget: string): void {
  if (!budget) return;

  switch (path) {
    case "/":
      void client.prefetchQuery(getMonthOptions({ path: { budget, month: currentMonth() } }));
      void client.prefetchQuery(listBucketsOptions({ path: { budget } }));
      // The close-month state is asked for by a component that only mounts once the month has
      // arrived, so leaving it out kept a second round trip behind the first.
      void client.prefetchQuery(
        getMonthCloseOptions({ path: { budget, month: currentMonth() } }),
      );
      return;
    case "/entries":
      void client.prefetchQuery(
        listEntriesOptions({ path: { budget }, query: { month: currentMonth() } }),
      );
      void client.prefetchQuery(listBucketsOptions({ path: { budget } }));
      return;
    case "/balances":
      void client.prefetchQuery(getBalancesOptions({ path: { budget } }));
      return;
    case "/scheduled":
      void client.prefetchQuery(listScheduledOptions({ path: { budget } }));
      return;
    case "/rules":
      void client.prefetchQuery(listRulesOptions({ path: { budget } }));
      return;
    case "/history":
      void client.prefetchQuery(getHistoryOptions({ path: { budget }, query: { limit: 100 } }));
      return;
    default:
      // Settings has no single dominant query worth guessing at.
      return;
  }
}
