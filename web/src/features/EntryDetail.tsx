import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getEntryHistoryOptions,
  getEntryNoteOptions,
  putEntryNoteMutation,
  updateEntryMutation,
} from "@/api/@tanstack/react-query.gen";
import type { BudgetSummary, Entry, EntryExtras } from "@/api/types.gen";
import { Button, Field, FormError, Input } from "@/components/Form";
import { Money } from "@/components/Money";
import { Attachments } from "./Attachments";
import { Comments } from "./Comments";

/**
 * Everything about one entry that does not belong on a scannable row: the full split, the
 * long-form note, the edit form, and who changed what.
 *
 * History comes straight from `git log` filtered by the entry's `Entry-Id` trailer. It is
 * the clearest place the git-backed storage becomes visible rather than merely true.
 */
export function EntryDetail({
  entry,
  budget,
  bucketNames,
  extras,
  onDeleted,
}: {
  entry: Entry;
  budget: BudgetSummary;
  bucketNames: Map<string, string>;
  extras?: EntryExtras;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<"split" | "comments" | "note" | "history">("split");

  return (
    <div className="sheet-in border-t border-line bg-surface/60 px-3 py-3 sm:px-4">
      <div className="mb-3 flex flex-wrap gap-1">
        {(["split", "comments", "note", "history"] as const).map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => setTab(name)}
            className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs transition ${
              tab === name ? "bg-brand-soft font-medium text-brand" : "text-ink-muted"
            }`}
          >
            {t(`entries.tabs.${name}`)}
            {name === "comments" && extras?.comments ? (
              <span className="numeric rounded-full bg-line px-1.5 text-[10px]">
                {extras.comments}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      {tab === "split" && (
        <SplitTab entry={entry} budget={budget} bucketNames={bucketNames} onDeleted={onDeleted} />
      )}
      {tab === "comments" && <Comments entryId={entry.id} budget={budget} />}
      {tab === "note" && <NoteTab entry={entry} budget={budget} />}
      {tab === "history" && <HistoryTab entry={entry} budget={budget} />}
    </div>
  );
}

function SplitTab({
  entry,
  budget,
  bucketNames,
  onDeleted,
}: {
  entry: Entry;
  budget: BudgetSummary;
  bucketNames: Map<string, string>;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);

  const nameOf = (person: string) =>
    budget.members.find((member) => member.person === person)?.name ?? person;

  if (editing) {
    return <EditEntry entry={entry} budget={budget} onDone={() => setEditing(false)} />;
  }

  return (
    <div className="space-y-2 text-xs">
      <div>
        <div className="mb-1 font-medium text-ink-muted">{t("entries.paidBy")}</div>
        {Object.entries(entry.paid_by).map(([person, amount]) => (
          <div key={person} className="flex gap-2">
            <span>{nameOf(person)}</span>
            <Money amount={String(amount)} currency={entry.currency} colour={false} />
          </div>
        ))}
      </div>

      <div>
        <div className="mb-1 font-medium text-ink-muted">{t("entries.bears")}</div>
        {entry.shares.map((share, index) => (
          <div key={index} className="flex gap-2">
            <span>{nameOf(share.person)}</span>
            <Money amount={share.amount} currency={entry.currency} colour={false} />
            {share.bucket && (
              <span className="text-ink-muted">
                · {bucketNames.get(share.bucket) ?? share.bucket}
              </span>
            )}
          </div>
        ))}
      </div>

      {(entry.items?.length ?? 0) > 0 && (
        <div>
          <div className="mb-1 font-medium text-ink-muted">{t("entries.receipt")}</div>
          {(entry.items ?? []).map((item, index) => (
            <div key={index} className="flex gap-2">
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              <Money amount={String(item.amount)} currency={entry.currency} colour={false} />
            </div>
          ))}
        </div>
      )}

      {entry.place?.name && (
        <div className="text-ink-muted">{t("entries.at", { place: entry.place.name })}</div>
      )}

      {entry.at && (
        <div className="text-ink-muted">
          {new Intl.DateTimeFormat(undefined, { timeStyle: "short" }).format(new Date(entry.at))}
        </div>
      )}

      {entry.rule && (
        <div className="text-ink-muted">{t("entries.splitBy", { rule: entry.rule })}</div>
      )}

      <Attachments budget={budget.slug} entryId={entry.id} canWrite={budget.can_write} />

      {budget.can_write && (
        <div className="flex gap-2 pt-1">
          <Button variant="quiet" className="min-h-9 px-3" onClick={() => setEditing(true)}>
            {t("entries.edit")}
          </Button>
          <Button variant="danger" className="min-h-9 px-3" onClick={onDeleted}>
            {t("entries.delete")}
          </Button>
        </div>
      )}
    </div>
  );
}

/** Edits the fields that are safe to change without re-deriving the split. */
function EditEntry({
  entry,
  budget,
  onDone,
}: {
  entry: Entry;
  budget: BudgetSummary;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [payee, setPayee] = useState(entry.payee);
  const [date, setDate] = useState(entry.date);

  const update = useMutation({
    ...updateEntryMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      onDone();
    },
  });

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        update.mutate({
          path: { budget: budget.slug, entry_id: entry.id },
          body: { payee, date },
        });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("entries.payee")}>
          <Input value={payee} onChange={(event) => setPayee(event.target.value)} />
        </Field>
        <Field label={t("entries.date")}>
          <Input
            type="date"
            className="numeric ltr-field"
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </Field>
      </div>

      {/* Amount and split are not editable here on purpose: changing either has to keep
          paid_by and shares summing to the total, which is the split editor's job. Deleting
          and re-adding is clearer than a half-editor that can leave an entry unbalanced. */}
      <p className="text-xs text-ink-muted">{t("entries.editHint")}</p>

      <div className="flex gap-2">
        <Button type="submit" className="min-h-9 px-3" disabled={update.isPending}>
          {t("entries.save")}
        </Button>
        <Button type="button" variant="ghost" className="min-h-9 px-3" onClick={onDone}>
          {t("common.cancel")}
        </Button>
      </div>
      <FormError error={update.error} />
    </form>
  );
}

function NoteTab({ entry, budget }: { entry: Entry; budget: BudgetSummary }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const note = useQuery(
    getEntryNoteOptions({ path: { budget: budget.slug, entry_id: entry.id } }),
  );
  const [draft, setDraft] = useState<string | null>(null);

  const save = useMutation({
    ...putEntryNoteMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      setDraft(null);
    },
  });

  const text = draft ?? note.data?.text ?? "";

  return (
    <div className="space-y-2">
      <textarea
        className="control min-h-24 w-full py-2 leading-relaxed"
        value={text}
        placeholder={t("entries.notePlaceholder")}
        onChange={(event) => setDraft(event.target.value)}
        disabled={!budget.can_write}
      />
      {budget.can_write && draft !== null && (
        <div className="flex gap-2">
          <Button
            className="min-h-9 px-3"
            disabled={save.isPending}
            onClick={() =>
              save.mutate({
                path: { budget: budget.slug, entry_id: entry.id },
                body: { text: draft },
              })
            }
          >
            {t("entries.save")}
          </Button>
          <Button
            variant="ghost"
            className="min-h-9 px-3"
            onClick={() => setDraft(null)}
          >
            {t("common.cancel")}
          </Button>
        </div>
      )}
      <FormError error={save.error} />
    </div>
  );
}

function HistoryTab({ entry, budget }: { entry: Entry; budget: BudgetSummary }) {
  const { t, i18n } = useTranslation();
  const history = useQuery(
    getEntryHistoryOptions({ path: { budget: budget.slug, entry_id: entry.id } }),
  );

  if (history.isPending) return <p className="text-xs text-ink-muted">{t("common.loading")}</p>;
  if (history.isError || history.data.commits.length === 0) {
    return <p className="text-xs text-ink-muted">{t("entries.noHistory")}</p>;
  }

  return (
    <ol className="space-y-2 text-xs">
      {history.data.commits.map((commit) => (
        <li key={commit.sha} className="flex flex-wrap items-baseline gap-x-2">
          <span className="numeric text-ink-muted">
            {new Intl.DateTimeFormat(i18n.language, {
              dateStyle: "short",
              timeStyle: "short",
            }).format(new Date(commit.date))}
          </span>
          <span>{commit.subject}</span>
          <span className="text-ink-muted">{commit.author_name}</span>
          <code className="numeric ms-auto text-[10px] text-ink-muted">
            {commit.sha.slice(0, 7)}
          </code>
        </li>
      ))}
    </ol>
  );
}
