import { useEffect } from "react";

export type Shortcut = {
  key: string;
  /** Requires the platform's command key: ⌘ on a Mac, Ctrl elsewhere. */
  meta?: boolean;
  shift?: boolean;
  label: string;
  run: () => void;
};

/**
 * Keyboard shortcuts that stay out of the way.
 *
 * Nothing fires while a field is focused. A budgeting app is mostly typing — payee names,
 * amounts — and a bare letter that triggers an action mid-word is worse than having no
 * shortcut at all. Combinations with the command key still work while typing, because those
 * cannot be produced by accident.
 */
export function useShortcuts(shortcuts: Shortcut[], enabled = true): void {
  useEffect(() => {
    if (!enabled) return;

    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target?.isContentEditable ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName ?? "");

      const meta = event.metaKey || event.ctrlKey;

      for (const shortcut of shortcuts) {
        if (shortcut.key.toLowerCase() !== event.key.toLowerCase()) continue;
        if (Boolean(shortcut.meta) !== meta) continue;
        if (Boolean(shortcut.shift) !== event.shiftKey) continue;
        // A bare letter never fires mid-word; a chorded one always may.
        if (typing && !shortcut.meta) continue;

        event.preventDefault();
        shortcut.run();
        return;
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shortcuts, enabled]);
}

/** How a shortcut reads on this platform, for tooltips and the help sheet. */
export function shortcutLabel(shortcut: Shortcut): string {
  const mac = navigator.platform.toLowerCase().includes("mac");
  const parts = [
    shortcut.meta ? (mac ? "⌘" : "Ctrl") : "",
    shortcut.shift ? "⇧" : "",
    shortcut.key.toUpperCase(),
  ];
  return parts.filter(Boolean).join(mac ? "" : "+");
}
