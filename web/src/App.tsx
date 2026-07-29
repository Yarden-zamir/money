import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";

import { getAuthConfigOptions, getMeOptions } from "@/api/@tanstack/react-query.gen";
import { Layout } from "@/components/Layout";
import { Loading } from "@/components/States";
import { ConnectBudget } from "@/features/ConnectBudget";
import { useBudget } from "@/features/useBudget";
import { BalancesScreen } from "@/features/BalancesScreen";
import { EntriesScreen } from "@/features/EntriesScreen";
import { MonthScreen } from "@/features/MonthScreen";
import { QuickAdd } from "@/features/QuickAdd";
import { RulesScreen } from "@/features/RulesScreen";
import { SettingsScreen } from "@/features/SettingsScreen";

export default function App() {
  const { t } = useTranslation();
  // /me is the auth probe: a 401 here means "not signed in", and no retry would help.
  const me = useQuery({ ...getMeOptions(), retry: false });

  if (me.isPending) return <Loading />;
  if (me.isError) return <SignIn message={t("auth.required")} label={t("auth.signIn")} />;


  return (
    <Layout>
      <BudgetGate>
        <Routes>
          <Route path="/" element={<MonthScreen />} />
          <Route path="/entries" element={<EntriesScreen />} />
          <Route path="/balances" element={<BalancesScreen />} />
          <Route path="/rules" element={<RulesScreen />} />
          <Route path="/settings" element={<SettingsScreen />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <QuickAdd />
      </BudgetGate>
    </Layout>
  );
}

/**
 * Nothing in this app means anything until a budget repo is connected, and every screen
 * would otherwise sit on a query that never runs. Ask for the repo instead of rendering
 * four empty tables.
 */
function BudgetGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { budgets, isPending, isError } = useBudget();

  if (isPending) return <Loading />;
  if (!isError && budgets.length === 0) {
    return (
      <section className="mx-auto max-w-xl">
        <h1 className="mb-1 text-lg font-semibold">{t("budgets.none")}</h1>
        <p className="mb-4 text-sm text-ink-muted">{t("budgets.noneHelp")}</p>
        <ConnectBudget />
      </section>
    );
  }
  return <>{children}</>;
}

function SignIn({ message, label }: { message: string; label: string }) {
  // Where sign-in starts depends on whether this is production or a PR preview, and only the
  // server knows which. A preview sends the user to production and gets the session handed
  // back, because one OAuth app has one callback URL.
  const config = useQuery({ ...getAuthConfigOptions(), retry: false });

  return (
    <div className="grid min-h-dvh place-items-center p-6 text-center">
      <div>
        <h1 className="mb-2 text-2xl font-semibold">money</h1>
        <p className="mb-6 text-ink-muted">{message}</p>
        <a
          href={config.data?.login_url ?? "/api/v1/auth/github/start"}
          className="inline-block rounded-md bg-brand px-4 py-2 text-white"
        >
          {label}
        </a>
      </div>
    </div>
  );
}
