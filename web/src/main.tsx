import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import { getMeOptions, listBudgetsOptions } from "@/api/@tanstack/react-query.gen";
import { prefetchRoute } from "@/lib/prefetch";
import App from "./App";
import "./lib/client";
import "./lib/i18n";
import "./lib/theme";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A shared budget changes under you: the other person adds an entry from their phone
      // and this screen should show it without a reload. Polling is cheap because the server
      // caches every read against the commit sha — an unchanged budget is a Redis hit.
      //
      // Paused while anything is being written. A write goes to git — commit, rebase, push —
      // which takes long enough for a poll to start during it, read the state from *before*
      // the write, and land afterwards, overwriting what the person just did. Cancelling
      // in-flight refetches when a mutation starts does not cover this: the problem is the
      // poll that starts later and finishes first.
      // The return type is annotated because this closure reads `queryClient` while
      // `queryClient` is still being defined, and inference would otherwise be circular.
      refetchInterval: (): number | false => (queryClient.isMutating() > 0 ? false : 10_000),
      // Only while the tab is visible. Polling a backgrounded tab spends the other person's
      // rate limit for a screen nobody is looking at.
      refetchIntervalInBackground: false,
      refetchOnWindowFocus: true,
      // Short enough that returning to a screen shows current data, long enough that moving
      // between tabs does not refetch on every click.
      staleTime: 5_000,
      retry: 1,
    },
  },
});

/**
 * Start the first screen's requests before React has rendered anything.
 *
 * The app used to discover what to fetch in three serial steps: `/me` decided whether to
 * render at all, `/budgets` decided which budget, and only then did the month screen ask for
 * a month. Three round trips deep before the first number appears — and the middle one is
 * only needed to learn a slug this browser already knows, because choosing a budget writes it
 * to localStorage.
 *
 * So on any visit after the first, all three go out at once. `/me` and `/budgets` are
 * independent: firing `/budgets` while signed out costs one 401 that touches no git, which is
 * a much better trade than a round trip on every load. A stale slug costs one 404 and the app
 * falls back to whatever `/budgets` returns, exactly as it did before.
 */
function warmFirstScreen() {
  void queryClient.prefetchQuery(getMeOptions());
  void queryClient.prefetchQuery(listBudgetsOptions());

  const slug = localStorage.getItem("money.budget");
  if (slug) prefetchRoute(queryClient, window.location.pathname, slug);
}
warmFirstScreen();

const root = document.getElementById("root");
if (!root) throw new Error("missing #root element");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
