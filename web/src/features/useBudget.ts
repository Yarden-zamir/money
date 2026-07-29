import { useQuery } from "@tanstack/react-query";

import { listBudgetsOptions } from "@/api/@tanstack/react-query.gen";
import type { BudgetSummary } from "@/api/types.gen";

const STORAGE_KEY = "money.budget";

/**
 * The budget the user is looking at.
 *
 * Most people have one or two, so this picks the stored choice, else the first one they can
 * write to, else the first one at all — rather than making them choose before seeing anything.
 */
export function useBudget(): {
  budget: BudgetSummary | undefined;
  budgets: BudgetSummary[];
  isPending: boolean;
  isError: boolean;
  select: (slug: string) => void;
} {
  const query = useQuery(listBudgetsOptions());
  const budgets = query.data ?? [];

  const stored = localStorage.getItem(STORAGE_KEY);
  const budget =
    budgets.find((candidate) => candidate.slug === stored) ??
    budgets.find((candidate) => candidate.can_write) ??
    budgets[0];

  return {
    budget,
    budgets,
    isPending: query.isPending,
    isError: query.isError,
    select: (slug: string) => {
      localStorage.setItem(STORAGE_KEY, slug);
      window.location.reload();
    },
  };
}
