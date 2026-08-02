import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";

import { getAuthConfigOptions, getMeOptions } from "@/api/@tanstack/react-query.gen";
import { Layout } from "@/components/Layout";
import { Loading } from "@/components/States";
import { ConnectBudget } from "@/features/ConnectBudget";
import { CreateBudget } from "@/features/CreateBudget";
import { JoinBudget } from "@/features/JoinBudget";
import { useBudget } from "@/features/useBudget";
import { BalancesScreen } from "@/features/BalancesScreen";
import { EntriesScreen } from "@/features/EntriesScreen";
import { MonthScreen } from "@/features/MonthScreen";
import { QuickAdd } from "@/features/QuickAdd";
import { Shortcuts } from "@/features/Shortcuts";
import { HistoryScreen } from "@/features/HistoryScreen";
import { RulesScreen } from "@/features/RulesScreen";
import { ScheduledScreen } from "@/features/ScheduledScreen";
import { SettingsScreen } from "@/features/SettingsScreen";

export default function App() {
  const { t } = useTranslation();
  const [quickAdd, setQuickAdd] = useState(0);
  // /me is the auth probe: a 401 here means "not signed in", and no retry would help.
  const me = useQuery({ ...getMeOptions(), retry: false });

  if (me.isPending) return <Loading />;
  if (me.isError) return <SignIn message={t("auth.required")} label={t("auth.signIn")} />;


  // The gate is outside the layout because it decides whether there is anything to navigate.
  return (
    <BudgetGate>
      <Layout>
        <Routes>
          <Route path="/" element={<MonthScreen />} />
          <Route path="/entries" element={<EntriesScreen />} />
          <Route path="/balances" element={<BalancesScreen />} />
          <Route path="/scheduled" element={<ScheduledScreen />} />
          <Route path="/rules" element={<RulesScreen />} />
          <Route path="/history" element={<HistoryScreen />} />
          <Route path="/settings" element={<SettingsScreen />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <QuickAdd openSignal={quickAdd} />
        <Shortcuts onQuickAdd={() => setQuickAdd((count) => count + 1)} />
      </Layout>
    </BudgetGate>
  );
}

/**
 * Nothing in this app means anything until you are in a budget, and every screen would
 * otherwise sit on a query that never runs — or, worse, on one that 403s.
 *
 * Two different dead ends, so two different offers. No budget at all is the first-run case
 * and leads with *creating* one, because someone arriving with nothing has no repo to
 * connect and asking them for one was a wall, not a question. Being able to push to a
 * budget you are not listed in is the shared-with-me case, and leads with joining it.
 */
function BudgetGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { budget, budgets, isPending, isError } = useBudget();
  const [connecting, setConnecting] = useState(false);

  // Chrome without tabs while loading: which of the three outcomes below applies is not yet
  // known, and rendering tabs that may be about to disappear is worse than not having them.
  if (isPending)
    return (
      <Layout navigation={false}>
        <Loading />
      </Layout>
    );

  if (!isError && budgets.length === 0) {
    return (
      <Layout navigation={false}>
      <section className="mx-auto max-w-xl">
        <h1 className="mb-1 text-lg font-semibold">{t("budgets.none")}</h1>
        <p className="mb-4 text-sm text-ink-muted">
          {connecting ? t("budgets.noneHelp") : t("budgets.firstRunHelp")}
        </p>
        {connecting ? <ConnectBudget /> : <CreateBudget />}
        <button
          type="button"
          onClick={() => setConnecting(!connecting)}
          className="mt-3 text-sm text-brand underline underline-offset-2"
        >
          {connecting ? t("budgets.insteadCreate") : t("budgets.insteadConnect")}
        </button>
      </section>
      </Layout>
    );
  }

  // `me` is null when budget.yaml does not list the signed-in account. Read-only viewers
  // cannot fix that themselves, so they get told rather than shown a form that would 403.
  if (budget && budget.me === null) {
    return (
      <Layout navigation={false}>
        {budget.can_write ? (
          <JoinBudget budget={budget} />
        ) : (
          <section className="mx-auto max-w-xl">
            <h1 className="mb-1 text-lg font-semibold">
              {t("budgets.notMember", { name: budget.name })}
            </h1>
            <p className="text-sm text-ink-muted">{t("budgets.notMemberReadOnly")}</p>
          </section>
        )}
      </Layout>
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
