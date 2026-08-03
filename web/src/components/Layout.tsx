import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";

import { Icon } from "@/components/Icon";
import { Select } from "@/components/Form";
import { useBudget } from "@/features/useBudget";
import { UndoButton } from "@/features/UndoButton";
import { LANGUAGES, type Language } from "@/lib/i18n";
import { prefetchRoute } from "@/lib/prefetch";

/**
 * Two navigations, one source of truth.
 *
 * The previous single top bar overflowed at phone width — the tabs ran off the edge and the
 * language picker was clipped. Phones get a bottom tab bar instead, which is both reachable
 * one-handed and the convention for an app you open at a checkout.
 */
const NAV = [
  { to: "/", key: "nav.month", icon: "wallet" },
  { to: "/entries", key: "nav.entries", icon: "list" },
  { to: "/balances", key: "nav.balances", icon: "swap" },
  { to: "/scheduled", key: "nav.scheduled", icon: "repeat" },
  { to: "/rules", key: "nav.rules", icon: "sliders" },
  { to: "/settings", key: "nav.settings", icon: "gear" },
] as const;

/**
 * `navigation` is off before there is a budget to navigate. Every tab would lead back to
 * the same "create a budget" screen, so six of them on a first run are noise pretending to
 * be an app that already has data in it — and one of them renders as the active tab.
 *
 * The header stays: switching language is exactly the thing a first-time reader may need
 * before they can read anything else.
 */
export function Layout({
  children,
  navigation = true,
}: {
  children: ReactNode;
  navigation?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { budget } = useBudget();

  // Warms whatever the tab is about to need, using time that is already being spent: the
  // pointer travelling to the tab, or a finger resting on it before the click registers.
  const warm = (path: string) => ({
    onMouseEnter: () => prefetchRoute(queryClient, path, budget?.slug ?? ""),
    onFocus: () => prefetchRoute(queryClient, path, budget?.slug ?? ""),
    onPointerDown: () => prefetchRoute(queryClient, path, budget?.slug ?? ""),
  });

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-20 border-b border-line bg-card/85 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center gap-2 px-4 py-2.5">
          <span className="text-base font-bold tracking-tight">{t("app.name")}</span>

          {navigation && (
          <nav className="ms-4 hidden gap-1 sm:flex">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                {...warm(item.to)}
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
          )}

          <span className="ms-auto flex items-center gap-1">
            <UndoButton />
            <NavLink
              to="/history"
              title={t("history.title")}
              aria-label={t("history.title")}
              className={({ isActive }) =>
                `flex size-9 items-center justify-center rounded-lg transition ${
                  isActive ? "bg-brand-soft text-brand" : "text-ink-muted hover:bg-sunken hover:text-ink"
                }`
              }
            >
              <Icon name="clock" className="size-4" />
            </NavLink>
            <Select
              fullWidth={false}
              className="h-9 min-h-0 py-0 text-xs"
              value={i18n.language}
              onChange={(event) => void i18n.changeLanguage(event.target.value)}
              aria-label={t("settings.language")}
            >
              {Object.entries(LANGUAGES).map(([code, meta]) => (
                <option key={code} value={code}>
                  {meta.name}
                </option>
              ))}
            </Select>
          </span>
        </div>
      </header>

      {/* Bottom padding clears the tab bar and the iOS home indicator. */}
      <main className="mx-auto max-w-4xl px-4 pt-4 pb-[calc(5.5rem+env(safe-area-inset-bottom))] sm:pb-10">
        {children}
      </main>

      {navigation && (
      <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur sm:hidden">
        <div className="flex">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              {...warm(item.to)}
              className={({ isActive }) =>
                `flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] transition ${
                  isActive ? "text-brand" : "text-ink-muted"
                }`
              }
            >
              <Icon name={item.icon} className="size-5" />
              {t(item.key)}
            </NavLink>
          ))}
        </div>
      </nav>
      )}
    </div>
  );
}

export type { Language };
