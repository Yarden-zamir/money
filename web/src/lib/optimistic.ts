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
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  };
}
