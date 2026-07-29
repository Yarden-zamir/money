import type { ReactNode } from "react";

/**
 * Small form primitives.
 *
 * They exist so every input in the app gets the same logical padding and border, and so no
 * screen hand-rolls a label that then sits on the wrong side in Hebrew.
 */

const FIELD =
  "w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm " +
  "focus:border-brand focus:outline-none";

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-ink-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-ink-muted">{hint}</span>}
    </label>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const { className = "", ...rest } = props;
  return <input {...rest} className={`${FIELD} ${className}`} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const { className = "", ...rest } = props;
  return <select {...rest} className={`${FIELD} ${className}`} />;
}

export function Button({
  variant = "primary",
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "quiet" }) {
  const style =
    variant === "primary"
      ? "bg-brand text-white"
      : "border border-line text-ink hover:bg-surface-raised";
  return (
    <button
      {...rest}
      className={`rounded-md px-3 py-1.5 text-sm disabled:opacity-50 ${style} ${className}`}
    />
  );
}

/** Renders an API error in the shape the backend always returns. */
export function FormError({ error }: { error: unknown }) {
  if (!error) return null;

  const body = (error as { error?: { message?: string } } | undefined)?.error;
  const message = body?.message ?? (error instanceof Error ? error.message : String(error));

  return <p className="mt-2 text-sm text-negative">{message}</p>;
}
