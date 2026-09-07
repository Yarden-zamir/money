import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addAttachmentMutation,
  deleteAttachmentMutation,
  listAttachmentsOptions,
} from "@/api/@tanstack/react-query.gen";
import type { AttachmentResponse } from "@/api/types.gen";
import { Button, FormError } from "@/components/Form";
import { Icon } from "@/components/Icon";

/**
 * Receipt photos and PDFs kept beside an entry, in the budget repo.
 *
 * Nothing is parsed out of them yet — a photo is a photo. It answers "what was this 284
 * shekel charge" six weeks later, which is the question a ledger line cannot.
 *
 * Mirrors the server's limits so a phone finds out before the upload, not after it. Both
 * numbers exist in one place server-side; keep these in step with `ATTACHMENT_TYPES` and
 * `ATTACHMENT_MAX_BYTES` in `money.store.store`.
 */
const ACCEPT = ["image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"];
const MAX_BYTES = 8 * 1024 * 1024;

/** The translation key of what is wrong with a file, or null when it can be attached. */
export function acceptableAttachment(file: File): string | null {
  if (!ACCEPT.includes(file.type)) return "attachments.unsupported";
  if (file.size > MAX_BYTES) return "attachments.tooLarge";
  return null;
}

/** The URL a browser can load an attachment from directly, with the session cookie. */
export function attachmentUrl(budget: string, entryId: string, name: string): string {
  return `/api/v1/budgets/${encodeURIComponent(budget)}/entries/${encodeURIComponent(entryId)}/attachments/${encodeURIComponent(name)}`;
}

/**
 * A file chosen on the add form, before there is an entry to attach it to.
 *
 * `capture` hints the phone to open the camera: at a till, the receipt is in your hand, and
 * scrolling the gallery for it is the wrong first screen.
 */
export function AttachmentPicker({
  file,
  onPick,
  onClear,
}: {
  file: File | null;
  onPick: (file: File) => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);

  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
      <input
        ref={input}
        type="file"
        accept={ACCEPT.join(",")}
        capture="environment"
        className="hidden"
        onChange={(event) => {
          const chosen = event.target.files?.[0];
          if (chosen) onPick(chosen);
          event.target.value = "";
        }}
      />
      {file ? (
        <>
          <Icon name="paperclip" className="size-3.5" />
          <span className="truncate">{file.name}</span>
          <span>· {t("attachments.pending")}</span>
          <button
            type="button"
            aria-label={t("attachments.remove")}
            className="hover:text-negative"
            onClick={onClear}
          >
            <Icon name="close" className="size-3" />
          </button>
        </>
      ) : (
        <button
          type="button"
          className="inline-flex items-center gap-1.5 text-brand underline underline-offset-2"
          onClick={() => input.current?.click()}
        >
          <Icon name="camera" className="size-3.5" />
          {t("attachments.add")}
        </button>
      )}
    </div>
  );
}

/** The files on an existing entry: thumbnails, open in a new tab, add, remove. */
export function Attachments({
  budget,
  entryId,
  canWrite,
}: {
  budget: string;
  entryId: string;
  canWrite: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);

  const list = useQuery(listAttachmentsOptions({ path: { budget, entry_id: entryId } }));
  const refresh = () => {
    void queryClient.invalidateQueries();
  };
  const add = useMutation({ ...addAttachmentMutation(), onSuccess: refresh });
  const remove = useMutation({ ...deleteAttachmentMutation(), onSuccess: refresh });

  const files = list.data?.attachments ?? [];

  return (
    <div>
      <div className="mb-1 flex items-center gap-2 font-medium text-ink-muted">
        {t("attachments.title")}
        {files.length > 0 && (
          <span className="text-[11px] font-normal">
            {t("attachments.count", { count: files.length })}
          </span>
        )}
      </div>

      {files.length > 0 && (
        <ul className="mb-2 flex flex-wrap gap-2">
          {files.map((file) => (
            <Thumbnail
              key={file.name}
              file={file}
              url={attachmentUrl(budget, entryId, file.name)}
              onRemove={
                canWrite
                  ? () => {
                      if (window.confirm(t("attachments.confirmRemove"))) {
                        remove.mutate({ path: { budget, entry_id: entryId, name: file.name } });
                      }
                    }
                  : undefined
              }
            />
          ))}
        </ul>
      )}

      {canWrite && (
        <>
          <input
            ref={input}
            type="file"
            accept={ACCEPT.join(",")}
            capture="environment"
            className="hidden"
            onChange={(event) => {
              const chosen = event.target.files?.[0];
              event.target.value = "";
              if (!chosen) return;
              const problem = acceptableAttachment(chosen);
              if (problem) {
                window.alert(t(problem));
                return;
              }
              add.mutate({
                path: { budget, entry_id: entryId },
                body: chosen,
                headers: { "content-type": chosen.type },
              });
            }}
          />
          <Button
            type="button"
            variant="quiet"
            className="min-h-9 px-3"
            disabled={add.isPending}
            onClick={() => input.current?.click()}
          >
            <Icon name="camera" className="size-4" />
            {add.isPending ? t("attachments.uploading") : t("attachments.add")}
          </Button>
          <p className="mt-1 text-[11px] text-ink-muted">{t("attachments.addHint")}</p>
        </>
      )}

      <FormError error={add.error ?? remove.error} />
    </div>
  );
}

function Thumbnail({
  file,
  url,
  onRemove,
}: {
  file: AttachmentResponse;
  url: string;
  onRemove?: () => void;
}) {
  const { t } = useTranslation();
  const isImage = file.content_type.startsWith("image/");

  return (
    <li className="relative">
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        title={t("attachments.open")}
        className="flex size-24 items-center justify-center overflow-hidden rounded-lg border border-line bg-sunken"
      >
        {isImage ? (
          <img src={url} alt="" className="size-full object-cover" loading="lazy" />
        ) : (
          <span className="flex flex-col items-center gap-1 text-[11px] text-ink-muted">
            <Icon name="paperclip" className="size-5" />
            {file.content_type === "application/pdf" ? "PDF" : file.name}
          </span>
        )}
      </a>
      {onRemove && (
        <button
          type="button"
          aria-label={t("attachments.remove")}
          onClick={onRemove}
          className="absolute end-1 top-1 flex size-7 items-center justify-center rounded-full bg-card/90 text-ink-muted shadow hover:text-negative"
        >
          <Icon name="close" className="size-3.5" />
        </button>
      )}
    </li>
  );
}
