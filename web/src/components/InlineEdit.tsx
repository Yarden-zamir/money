import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * Edit a value where it is displayed.
 *
 * Opening a separate form to change one field costs the context of the row you were looking
 * at — the whole reason you wanted to change it. This shows the value as text until it is
 * clicked, then becomes an input in the same place, the same size.
 *
 * Enter commits, Escape reverts, blur commits. Committing on blur rather than discarding is
 * deliberate: on a phone, tapping elsewhere is how people finish, and losing the edit there
 * would be the surprising outcome.
 */
export function InlineEdit({
  value,
  onCommit,
  render,
  className = "",
  inputClassName = "",
  placeholder,
  label,
  inputMode,
  disabled,
}: {
  value: string;
  onCommit: (next: string) => void;
  /** How the value looks when not being edited. Defaults to the raw text. */
  render?: (value: string) => React.ReactNode;
  className?: string;
  inputClassName?: string;
  placeholder?: string;
  label: string;
  inputMode?: "text" | "decimal" | "numeric";
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      input.current?.focus();
      input.current?.select();
    }
  }, [editing]);

  // A value changed elsewhere — by an undo, or by the other person — must not be overwritten
  // by a stale draft sitting in a field nobody is looking at.
  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  const commit = () => {
    setEditing(false);
    if (draft !== value) onCommit(draft);
  };

  if (disabled) {
    return <span className={className}>{render ? render(value) : value}</span>;
  }

  if (!editing) {
    return (
      <button
        type="button"
        aria-label={t("common.edit", { field: label })}
        onClick={() => setEditing(true)}
        className={`rounded px-1 -mx-1 text-start hover:bg-sunken focus-visible:bg-sunken ${className}`}
      >
        {render ? render(value) : value || <span className="text-ink-muted">{placeholder}</span>}
      </button>
    );
  }

  return (
    <input
      ref={input}
      aria-label={label}
      inputMode={inputMode}
      value={draft}
      placeholder={placeholder}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commit();
        } else if (event.key === "Escape") {
          setDraft(value);
          setEditing(false);
        }
      }}
      className={`w-full rounded border border-brand bg-card px-1 -mx-1 outline-none ${inputClassName}`}
    />
  );
}
