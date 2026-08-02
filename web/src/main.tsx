import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

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
      refetchInterval: 10_000,
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
