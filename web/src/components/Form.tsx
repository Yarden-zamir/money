import type { ReactNode } from "react";

import { Icon } from "./Icon";

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
  suffix,
}: {
  label?: string;
  hint?: string;
  children: ReactNode;
  className?: string;
  /** Sits beside the label — used for the marker on a field the app filled in. */
  suffix?: ReactNode;
}) {
  return (
    <label className={`block ${className}`}>
      {label && (
        <span className="mb-1.5 flex items-center gap-1 text-xs font-medium text-ink-muted">
          {label}
          {suffix}
        </span>
      )}
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
  arrow = true,
  ...rest
}: React.SelectHTMLAttributes<HTMLSelectElement> & {
  fullWidth?: boolean;
  /** Off for controls whose purpose is obvious from their content, like the language picker. */
  arrow?: boolean;
}) {
  return (
    <span className={`relative inline-flex items-center ${fullWidth ? "w-full" : ""}`}>
      <select
        {...rest}
        // The native arrow ignores padding and sits flush against the edge of the control.
        // Suppressing it and drawing our own is the only way to give it a margin, and the
        // logical inset means it swaps sides in RTL instead of colliding with the text.
        //
        // Width is only forced when the caller asked for it: an auto-width select inside an
        // inline-flex wrapper sizes to its content, and `w-full` there resolves against a
        // shrink-to-fit parent, so the reserved space for the arrow is dropped and the
        // chevron lands on top of the label.
        className={`control appearance-none ${arrow ? "pe-9" : ""} ${
          fullWidth ? "w-full" : ""
        } ${className}`}
      />
      {arrow && (
        <Icon
          name="chevronDown"
          className="pointer-events-none absolute end-2.5 size-4 text-ink-muted"
        />
      )}
    </span>
  );
}

const VARIANTS = {
  primary: "bg-brand text-on-brand hover:opacity-90",
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

/**
 * Turns whatever the API or the network produced into one readable sentence.
 *
 * The envelope is the normal case, but not the only one: a proxy can return HTML, the
 * network can fail before any body exists, and a stray shape used to fall through to
 * `String(error)` and render the literal text "[object Object]". Nothing here may ever put
 * an object where a sentence belongs.
 */
export function describeError(error: unknown): string | null {
  if (!error) return null;

  if (typeof error === "string") return error;

  if (typeof error === "object") {
    const shape = error as {
      error?: { message?: unknown; code?: unknown };
      detail?: unknown;
      message?: unknown;
    };

    if (typeof shape.error?.message === "string") return shape.error.message;

    // FastAPI's own validation shape, in case one slips past the server-side handler.
    if (Array.isArray(shape.detail)) {
      const parts = shape.detail
        .map((item) => {
          const entry = item as { loc?: unknown[]; msg?: unknown };
          const field = Array.isArray(entry.loc)
            ? entry.loc.filter((part) => part !== "body").join(".")
            : "";
          return field ? `${field}: ${String(entry.msg)}` : String(entry.msg);
        })
        .filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
    if (typeof shape.detail === "string") return shape.detail;
    if (typeof shape.message === "string") return shape.message;
  }

  if (error instanceof Error) return error.message;

  // Last resort: show the shape rather than "[object Object]", which tells nobody anything.
  try {
    return JSON.stringify(error);
  } catch {
    return "Unknown error";
  }
}

export function FormError({ error }: { error: unknown }) {
  const message = describeError(error);
  if (!message) return null;

  return (
    <p role="alert" className="mt-3 rounded-lg bg-negative/10 px-3 py-2 text-sm text-negative">
      {message}
    </p>
  );
}
