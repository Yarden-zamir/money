import type { ReactNode } from "react";

/**
 * Form primitives.
 *
 * Width is *not* baked into the base style. It used to be, which meant a caller passing
 * `w-24` was fighting a `w-full` of equal specificity and the winner depended on stylesheet
 * order — the assign field ended up full-width. Callers now opt into a width, and `Field`
 * supplies the common full-width case.
 */

export function Field({
  label,
  hint,
  children,
  className = "",
}: {
  label?: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      {label && <span className="mb-1.5 block text-xs font-medium text-ink-muted">{label}</span>}
      {children}
      {hint && <span className="mt-1 block text-xs text-ink-muted">{hint}</span>}
    </label>
  );
}

export function Input({
  className = "",
  fullWidth = true,
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement> & { fullWidth?: boolean }) {
  return <input {...rest} className={`control ${fullWidth ? "w-full" : ""} ${className}`} />;
}

export function Select({
  className = "",
  fullWidth = true,
  ...rest
}: React.SelectHTMLAttributes<HTMLSelectElement> & { fullWidth?: boolean }) {
  return <select {...rest} className={`control ${fullWidth ? "w-full" : ""} ${className}`} />;
}

const VARIANTS = {
  primary: "bg-brand text-white hover:opacity-90",
  quiet: "border border-line bg-card text-ink hover:bg-surface",
  ghost: "text-ink-muted hover:bg-surface hover:text-ink",
  danger: "text-negative hover:bg-negative/10",
} as const;

export function Button({
  variant = "primary",
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof VARIANTS }) {
  return (
    <button
      {...rest}
      className={
        "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl px-4 text-sm " +
        `font-medium transition disabled:opacity-40 ${VARIANTS[variant]} ${className}`
      }
    />
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-card border border-line bg-card ${className}`}>{children}</div>
  );
}

/**
 * Form actions in a fixed order: primary first at the inline start, then secondary, then
 * anything destructive pushed to the inline end.
 *
 * Every form used to arrange its own buttons, and they drifted — some screens led with the
 * secondary action, so the blue button landed on a different side depending on the screen.
 * Going through here means the order cannot vary.
 */
export function FormActions({
  primary,
  secondary,
  destructive,
}: {
  primary?: ReactNode;
  secondary?: ReactNode;
  destructive?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {primary}
      {secondary}
      {destructive && <div className="ms-auto">{destructive}</div>}
    </div>
  );
}

/** Renders an API error in the envelope the backend always returns. */
export function FormError({ error }: { error: unknown }) {
  if (!error) return null;

  const body = (error as { error?: { message?: string } } | undefined)?.error;
  const message = body?.message ?? (error instanceof Error ? error.message : String(error));

  return (
    <p className="mt-3 rounded-lg bg-negative/10 px-3 py-2 text-sm text-negative">{message}</p>
  );
}
