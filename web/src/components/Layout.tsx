import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";

import { LANGUAGES, type Language } from "@/lib/i18n";

const NAV = [
  { to: "/", key: "nav.month" },
  { to: "/entries", key: "nav.entries" },
  { to: "/balances", key: "nav.balances" },
  { to: "/rules", key: "nav.rules" },
  { to: "/settings", key: "nav.settings" },
] as const;

export function Layout({ children }: { children: ReactNode }) {
  const { t, i18n } = useTranslation();

  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-surface-raised">
        <div className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3">
          <span className="text-lg font-semibold">{t("app.name")}</span>

          <nav className="flex gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm ${
                    isActive ? "bg-brand/12 text-brand font-medium" : "text-ink-muted hover:text-ink"
                  }`
                }
              >
                {t(item.key)}
              </NavLink>
            ))}
          </nav>

          {/* Logical margin: this must sit at the inline end in both directions. */}
          <select
            className="ms-auto rounded-md border border-line bg-surface px-2 py-1 text-sm"
            value={i18n.language}
            onChange={(event) => void i18n.changeLanguage(event.target.value)}
            aria-label={t("settings.language")}
          >
            {Object.entries(LANGUAGES).map(([code, meta]) => (
              <option key={code} value={code}>
                {meta.name}
              </option>
            ))}
          </select>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
    </div>
  );
}

export type { Language };
