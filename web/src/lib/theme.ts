/**
 * Light, dark, or whatever the system says.
 *
 * The tokens already respond to `prefers-color-scheme`, so "system" is simply the absence of
 * an override. An explicit choice stamps `data-theme` on the root element, and the CSS for
 * that attribute restates the full palette — not just the differences — because someone who
 * picks light while their OS is dark must actually get light.
 */

export const THEMES = ["system", "light", "dark"] as const;
export type Theme = (typeof THEMES)[number];

const STORAGE_KEY = "money.theme";

export function storedTheme(): Theme {
  const saved = localStorage.getItem(STORAGE_KEY);
  return THEMES.includes(saved as Theme) ? (saved as Theme) : "system";
}

export function applyTheme(theme: Theme): void {
  localStorage.setItem(STORAGE_KEY, theme);
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

// Applied before React mounts, so the first paint is already the right colour rather than
// flashing the wrong one.
applyTheme(storedTheme());
