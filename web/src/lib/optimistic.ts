import type { QueryClient } from "@tanstack/react-query";

/**
 * Apply a change to the cache immediately, and put it back if the server disagrees.
 *
 * Every write here goes to git — a commit, a rebase, a push — which is fast but never
 * instant. Waiting for that round trip before moving a number makes the app feel broken on
 * a phone, so the number moves first and the request confirms it.
 *
 * Correctness comes from the rollback: on failure the previous snapshot is restored, and on
 * settle the queries are invalidated so whatever the server actually has wins. An optimistic
 * value is never allowed to become the truth.
 */
export function optimistic<TData>(
  client: QueryClient,
  key: readonly unknown[],
  patch: (current: TData) => TData,
) {
  return {
    onMutate: async () => {
      // Stop an in-flight refetch from landing after the patch and reverting it on screen.
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<TData>(key);
      if (previous !== undefined) client.setQueryData<TData>(key, patch(previous));
      return { previous };
    },
    onError: (_error: unknown, _variables: unknown, context?: { previous?: TData }) => {
      if (context?.previous !== undefined) client.setQueryData<TData>(key, context.previous);
    },
    onSettled: lastWriteWins(client, key),
  };
}

/**
 * Invalidate only once every write has finished — not once per write.
 *
 * Invalidating on settle is what stops an optimistic value becoming the truth, and with one
 * write at a time it is correct. But a drag between groups fires one write per bucket whose
 * position changed, and they run concurrently. The first to finish would invalidate while
 * its siblings were still in flight; the refetch then returns a server state containing only
 * that one write and overwrites the rest — a reorder visibly undoing itself.
 *
 * `isMutating()` still counts the mutation that is currently settling, so `1` means "no
 * others left". Whichever write finishes last does the invalidating, and it sees them all.
 */
export function lastWriteWins(client: QueryClient, key?: readonly unknown[]) {
  return () => {
    if (client.isMutating() > 1) return;
    void client.invalidateQueries(key ? { queryKey: key } : undefined);
  };
}
