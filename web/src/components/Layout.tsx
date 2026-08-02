import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";

import { LANGUAGES, type Language } from "@/lib/i18n";

/**
 * Two navigations, one source of truth.
 *
 * The previous single top bar overflowed at phone width — the tabs ran off the edge and the
 * language picker was clipped. Phones get a bottom tab bar instead, which is both reachable
 * one-handed and the convention for an app you open at a checkout.
 */
const NAV = [
  { to: "/", key: "nav.month", icon: "◍" },
  { to: "/entries", key: "nav.entries", icon: "≡" },
  { to: "/balances", key: "nav.balances", icon: "⇄" },
  { to: "/scheduled", key: "nav.scheduled", icon: "↻" },
  { to: "/rules", key: "nav.rules", icon: "⌥" },
  { to: "/settings", key: "nav.settings", icon: "⚙" },
] as const;

export function Layout({ children }: { children: ReactNode }) {
  const { t, i18n } = useTranslation();

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-20 border-b border-line bg-card/85 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center gap-2 px-4 py-2.5">
          <span className="text-base font-bold tracking-tight">{t("app.name")}</span>

          <nav className="ms-4 hidden gap-1 sm:flex">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-1.5 text-sm transition ${
                    isActive
                      ? "bg-brand-soft font-medium text-brand"
                      : "text-ink-muted hover:text-ink"
                  }`
                }
              >
                {t(item.key)}
              </NavLink>
            ))}
          </nav>

          <select
            className="control ms-auto h-9 min-h-0 py-0 text-xs"
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

      {/* Bottom padding clears the tab bar and the iOS home indicator. */}
      <main className="mx-auto max-w-4xl px-4 pt-4 pb-[calc(5.5rem+env(safe-area-inset-bottom))] sm:pb-10">
        {children}
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur sm:hidden">
        <div className="flex">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] transition ${
                  isActive ? "text-brand" : "text-ink-muted"
                }`
              }
            >
              <span aria-hidden className="text-lg leading-none">
                {item.icon}
              </span>
              {t(item.key)}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}

export type { Language };
