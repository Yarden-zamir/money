import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";

import { getMeOptions } from "@/api/@tanstack/react-query.gen";
import { Layout } from "@/components/Layout";
import { Loading } from "@/components/States";
import { LOGIN_URL } from "@/lib/client";
import { BalancesScreen } from "@/features/BalancesScreen";
import { EntriesScreen } from "@/features/EntriesScreen";
import { MonthScreen } from "@/features/MonthScreen";
import { SettingsScreen } from "@/features/SettingsScreen";

export default function App() {
  const { t } = useTranslation();
  // /me is the auth probe: a 401 here means "not signed in", and no retry would help.
  const me = useQuery({ ...getMeOptions(), retry: false });

  if (me.isPending) return <Loading />;
  if (me.isError) return <SignIn message={t("auth.required")} label={t("auth.signIn")} />;

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<MonthScreen />} />
        <Route path="/entries" element={<EntriesScreen />} />
        <Route path="/balances" element={<BalancesScreen />} />
        <Route path="/settings" element={<SettingsScreen />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}

function SignIn({ message, label }: { message: string; label: string }) {
  return (
    <div className="grid min-h-dvh place-items-center p-6 text-center">
      <div>
        <h1 className="mb-2 text-2xl font-semibold">money</h1>
        <p className="mb-6 text-ink-muted">{message}</p>
        <a
          href={LOGIN_URL}
          className="inline-block rounded-md bg-brand px-4 py-2 text-white"
        >
          {label}
        </a>
      </div>
    </div>
  );
}
